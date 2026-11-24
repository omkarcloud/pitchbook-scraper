"""PitchBook transport: plain curl_cffi on pitchbook.com's public pages. No
browser, no login, no cookie and no token.

Every surface is a server-rendered page behind Cloudflare bot management:

    GET /profiles/search?q=<name>&page=<n>      15 profiles a page, 34 pages at most
    GET /profiles/company/<id>                  a company        (ids: 54782-29)
    GET /profiles/investor/<id>                 an investor
    GET /profiles/fund/<id>F                    a fund           (the id ends in F)
    GET /profiles/limited-partner/<id>          a limited partner
    GET /profiles/advisor/<id>                  an advisor or a lender
    GET /profiles/industry/<slug>               a vertical
    GET /profiles/screeners/<slug>              a curated list
    GET /sitemap.xml                            the index of the sitemap files
    GET /<kind>-profiles-sitemap-<n>.xml.gz     20,000 profile links a file (gzip)

How the site answers (measured 2026-11-21):

  * An unknown id: HTTP 404 "Profile not found". A removed one: HTTP 410
    "This profile was removed". Both are full pages of the site.
  * An id asked under the wrong kind (/profiles/investor/<a company's id>)
    is redirected to its own kind. Redirects are not followed here: the
    caller is told which endpoint the id belongs to.
  * A page past the end of a search answers 200 with no rows.
  * Cloudflare answers a "Just a moment..." challenge page in two cases.
    HTTP 403: it does not trust the address or the browser profile. HTTP
    429: the rate limit of /profiles/* is used up, about 15 requests a
    minute, and what it counts is the Cloudflare data centre the request
    arrived at together with the browser family, NOT the address: a fresh
    address at the same data centre is refused on its first request, for
    about ten minutes. The sitemap is outside that limit.

So the scraper spreads its /profiles requests over residential exits in
many countries (each lands at another data centre): config.PITCHBOOK_EXIT
and the countries of config.PITCHBOOK_EXIT_COUNTRIES. Process-wide it keeps
every country under config.PITCHBOOK_COUNTRY_PER_MINUTE requests a minute
and, after a 429, stays off that country for
config.PITCHBOOK_COUNTRY_REST_S seconds. A country whose data centre other
visitors have used up answers 429 on the first request (8 of 21 did on
2026-11-23), so the countries that just answered a real page are preferred
(_pick). A refused or failed request is tried again from another country,
config.PITCHBOOK_MAX_TRIES times in all.
When every country rests, nothing is sent and the caller is told to come
back later (PitchbookUnavailable, HTTP 503 with Retry-After).

The TLS profile is safari17_0: on residential exits it was let in on every
address whose data centre had budget left, where the chrome profile met a
challenge on a third to four fifths of the addresses. The request headers
are the ones the site's own page navigation sent, as the research replayed
them; the user-agent and Accept-Language are the session's own (the
language follows the exit).

Failure taxonomy (scraper_errors, mapped to HTTP by route_glue):
  PitchbookUpstreamError  transport failure / 5xx / an unexpected page   retryable
  PitchbookBlocked        a Cloudflare challenge (403 / 429)             retryable
  PitchbookUnavailable    every exit is resting or at its pace           not attempted
  PitchbookNotFound       404 / 410 / an id of another kind              never retried
"""
import gzip
import logging
import threading
import time
from collections import OrderedDict, deque
from types import SimpleNamespace
from urllib.parse import urlencode

import config
import egress
from pitchbook import refs
from scraper_errors import Blocked, NotFound, Unavailable, UpstreamError
from scraper_utils import retry, sessions
from scraper_utils.pages import is_challenged
from scraper_utils.pages import page_title as _page_title

log = logging.getLogger(__name__)

IMPERSONATE = "safari17_0"
PAGE_TIMEOUT = 20          # a profile page is 220 to 320 KB and answers in 1 to 7 s; a dead proxy should cost no more
SITEMAP_TIMEOUT = 60       # a sitemap file is about 120 KB packed, 4 MB unpacked
SESSIONS_PER_THREAD = 3    # keep-alive sessions (one per country) a request thread holds
PACE_WINDOW = 60.0         # seconds the per-country pace is counted over
PACE_MAX_WAIT = 12.0       # seconds a request waits for a free slot before it gives up
PROVEN_FOR = 1800.0        # seconds an exit counts as proven after a real page came back through it
PROVEN_FIRST = 2           # requests a minute a proven exit takes before a load is spread wider: at 5 each,
                           # 3 of 10 countries answered 429 after 3 to 4 pages in 20 s (2026-11-23)

# The headers of the site's own page navigation (samples/pages/*.request.json
# of the research, 2026-11-21). The session adds its user-agent and the
# Accept-Language of its exit.
PAGE_HEADERS = {
    "accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,image/jxl,image/avif,image/webp,"
               "image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7"),
    "priority": "u=0, i",
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "none",
    "sec-fetch-user": "?1",
    "upgrade-insecure-requests": "1",
}

NOT_FOUND_TITLE = "profile not found"
REMOVED_TITLE = "profile was removed"


class PitchbookUpstreamError(UpstreamError):
    """Transport failure, 5xx or a page that is not the one asked for — retryable."""


class PitchbookBlocked(PitchbookUpstreamError, Blocked):
    """A Cloudflare challenge page (HTTP 403 or 429) — retryable from another exit."""


class PitchbookUnavailable(PitchbookUpstreamError, Unavailable):
    """Every exit is resting after a rate limit, or at its pace: nothing was
    sent. Answered as 503 with Retry-After."""

    def __init__(self, message, retry_after=120):
        super().__init__(message)
        self.retry_after = max(1, int(retry_after))


class PitchbookNotFound(NotFound):
    """No such profile, industry, screener or sitemap file — never retried."""


class _Redirected(Exception):
    """The site answered a redirect (not followed): `location` is where to."""

    def __init__(self, location):
        super().__init__(location)
        self.location = location


# ---- exits: which country the next request rides ------------------------------------

# Process-wide, shared by every request thread: when each exit was last used
# and until when it rests. The site's limit is counted per data centre, so
# the pace has to be kept by the process, not by a thread.
_lock = threading.Lock()
_sent = {}            # exit -> deque of the times of its requests in the last PACE_WINDOW
_rest_until = {}      # exit -> the time its rest ends
_proven = {}          # exit -> the time of its last real /profiles answer
_local = threading.local()


def _exits():
    """The exits requests are spread over, the knob's own first."""
    first = config.PITCHBOOK_EXIT or "direct"
    return [first, *(exit_ for exit_ in config.PITCHBOOK_EXIT_COUNTRIES if exit_ and exit_ != first)]


def _recent(exit_, now):
    times = _sent.setdefault(exit_, deque())
    while times and now - times[0] > PACE_WINDOW:
        times.popleft()
    return times


def _pick(paced=True):
    """The exit for the next request, among the exits that are not resting.

    An exit is *proven* while its last /profiles answer was a real page
    (within PROVEN_FOR): its data centre has budget left. A fresh one may
    land at a data centre other visitors have used up (8 of 21 countries
    did on 2026-11-23). So the order is: a proven exit with fewer than
    PROVEN_FIRST requests in the last minute, then one not tried yet (which
    grows the set of proven exits under load), then a proven exit up to its
    full pace; after a refusal in this call the proven ones come before the
    untried ones. Within a group the least used in the last minute wins, so
    a load is spread evenly, and the knob's order breaks a tie. An exit this
    call already failed on (a 403, a timeout: it is not resting) is the last
    choice, so each try leaves from another exit while one is left.

    A paced request is charged to its exit, and waits for a slot when every
    exit is at its pace. An unpaced one (the sitemap, which the limit does
    not cover) rides the least used exit without being counted."""
    limit = config.PITCHBOOK_COUNTRY_PER_MINUTE
    refused = getattr(_local, "refused", ())        # the exits this call has failed on
    deadline = time.monotonic() + PACE_MAX_WAIT
    while True:
        with _lock:
            now = time.monotonic()
            awake = [exit_ for exit_ in _exits() if _rest_until.get(exit_, 0) <= now]
            if not awake:
                if not paced:
                    return _exits()[0]
                wait = min(_rest_until[exit_] for exit_ in _exits()) - now
                raise PitchbookUnavailable("PitchBook is rate-limiting every exit right now; try again later", wait)
            uses = {exit_: len(_recent(exit_, now)) for exit_ in awake}
            others = [exit_ for exit_ in awake if exit_ not in refused]
            if not paced:
                return min(others or awake, key=uses.get)
            proven = [exit_ for exit_ in others if now - _proven.get(exit_, -PROVEN_FOR) < PROVEN_FOR]
            fresh = [exit_ for exit_ in others if exit_ not in proven]
            cap = limit or float("inf")
            groups = [[e for e in proven if uses[e] < min(PROVEN_FIRST, cap)], [e for e in fresh if uses[e] < cap],
                      [e for e in proven if uses[e] < cap]]
            if refused:
                groups = [groups[0], groups[2], groups[1], [e for e in awake if e in refused and uses[e] < cap]]
            best = next((min(group, key=uses.get) for group in groups if group), None)
            if best is not None:
                _sent[best].append(now)
                return best
            wait = PACE_WINDOW - (now - min(_sent[exit_][0] for exit_ in awake))
        if time.monotonic() + wait > deadline:
            raise PitchbookUnavailable("PitchBook requests are at their pace; try again in a moment", wait)
        time.sleep(min(wait, 1.0))


def _answered(exit_):
    """A real page came back through this exit: its data centre has budget."""
    with _lock:
        _proven[exit_] = time.monotonic()


def _rest(exit_):
    """Keep every thread off an exit whose data centre answered 429."""
    with _lock:
        _rest_until[exit_] = time.monotonic() + config.PITCHBOOK_COUNTRY_REST_S
        _proven.pop(exit_, None)
    log.warning("pitchbook: exit %s answered 429 (rate limit), resting it for %s s",
                exit_, config.PITCHBOOK_COUNTRY_REST_S)


def resting():
    """The exits that rest right now -> seconds left (for logs and tests)."""
    with _lock:
        now = time.monotonic()
        return {exit_: round(until - now) for exit_, until in _rest_until.items() if until > now}


def reset_pacing():
    """Forget every pace count and rest (tests, a config reload)."""
    with _lock:
        _sent.clear()
        _rest_until.clear()
        _proven.clear()


# ---- sessions ------------------------------------------------------------------------

# One curl session per request thread and exit (a curl handle must not be
# shared across threads). The calls are stateless: nothing a session earned
# is needed by the next call, so a failed one is simply closed.

def _session(exit_):
    store = sessions.thread_store(_local)
    return sessions.keyed(store, exit_, lambda: egress.exit_session(exit_, impersonate=IMPERSONATE),
                          SESSIONS_PER_THREAD)


def _drop_session(exit_=None):
    """Close the thread's session on `exit_` (the one last used when not
    named), so the next try leaves from a fresh address."""
    exit_ = exit_ or getattr(_local, "last_exit", None)
    if exit_ is not None:
        sessions.drop_keyed(sessions.thread_store(_local), exit_)


def _retrying(fn):
    """fn() under the shared retry loop with the site's own count and pause:
    PitchbookUpstreamError (a challenge included) is retried, each try from
    another exit; NotFound and Unavailable surface at once."""
    policy = SimpleNamespace(MAX_RETRIES=config.PITCHBOOK_MAX_TRIES, RETRY_BACKOFF=config.PITCHBOOK_RETRY_PAUSE)

    def once():
        try:
            return fn()
        except PitchbookUnavailable as error:        # nothing was sent: retrying at once cannot help
            raise _GiveUp(error)

    def failed(error):
        # the next try leaves from another exit, a proven one first
        _local.refused = [*getattr(_local, "refused", ()), getattr(_local, "last_exit", None)]
        _drop_session()

    _local.refused = []
    try:
        return retry.run(once, policy, PitchbookUpstreamError, failed)
    except _GiveUp as stop:
        raise stop.error
    finally:
        _local.refused = []


class _GiveUp(Exception):
    """Carries an error past the retry loop."""

    def __init__(self, error):
        super().__init__(str(error))
        self.error = error


# ---- one request ---------------------------------------------------------------------

def _get(url, label, paced=True, timeout=PAGE_TIMEOUT):
    """One GET -> the response, or the site's error. A challenge page is
    PitchbookBlocked (a 429 also rests the exit), a redirect is _Redirected,
    404 / 410 are PitchbookNotFound."""
    exit_ = _pick(paced)
    _local.last_exit = exit_
    try:
        resp = _session(exit_).get(url, headers=PAGE_HEADERS, timeout=timeout, allow_redirects=False)
    except Exception as error:
        raise PitchbookUpstreamError(f"request failed for {label}: {type(error).__name__}: {error}")
    status = resp.status_code
    if 300 <= status < 400:
        raise _Redirected(resp.headers.get("location") or "")
    head = resp.text[:4000] if "html" in (resp.headers.get("content-type") or "") else ""
    if is_challenged(status, resp.headers, head):
        if status == 429:
            _rest(exit_)
        raise PitchbookBlocked(f"challenge page (HTTP {status}) for {label}")
    if paced and status in (200, 404, 410):
        _answered(exit_)
    if status in (404, 410):
        title = _page_title(head).lower()
        if REMOVED_TITLE in title:
            raise PitchbookNotFound(f"{label} was removed from PitchBook")
        raise PitchbookNotFound(f"{label} not found")
    if status in (401, 403, 429):
        if status == 429:
            _rest(exit_)
        raise PitchbookBlocked(f"HTTP {status} for {label}")
    if status != 200:
        raise PitchbookUpstreamError(f"HTTP {status} for {label}")
    return resp


def _page(path, label, marker):
    """The HTML of a /profiles page. `marker` is a text every real page of
    that kind holds: a 200 without it is not the page (retryable)."""
    def once():
        text = _get(refs.SITE + path, label).text
        if marker not in text:
            raise PitchbookUpstreamError(f"unexpected page for {label}: {_page_title(text)[:80]!r}")
        return text
    return _retrying(once)


# ---- the surfaces --------------------------------------------------------------------

def fetch_profile(kind, profile_id):
    """The page of one profile. `kind` is company / investor / fund /
    limited_partner / advisor. An id that belongs to another kind is
    PitchbookNotFound with the endpoint to call instead."""
    noun = kind.replace("_", " ")
    label = f"{noun} {profile_id}"
    try:
        return _page(f"/profiles/{refs.PROFILE_PATHS[kind]}/{profile_id}", label, "data-anchor-section")
    except _Redirected as moved:
        found = refs.entity_of_link(moved.location)
        if found and found["type"] != kind:
            raise PitchbookNotFound(
                f"{profile_id} is not {refs.with_article(noun)}: it is {refs.with_article(found['type'].replace('_', ' '))} "
                f"(call /pitchbook/{refs.COLLECTIONS[found['type']]}/details)")
        raise PitchbookNotFound(f"{label} not found")


def fetch_industry(slug):
    """The page of one industry (vertical)."""
    return _slug_page("industry", slug, f"industry {slug}")


def fetch_screener(slug):
    """The page of one screener (curated list)."""
    return _slug_page("screeners", slug, f"screener {slug}")


def _slug_page(path_kind, slug, label):
    try:
        return _page(f"/profiles/{path_kind}/{slug}", label, "data-anchor-section")
    except _Redirected:
        raise PitchbookNotFound(f"{label} not found")


def fetch_search(query, page=1):
    """One page of the profile search (15 rows; a page past the end has none)."""
    params = {"q": query}
    if page and page > 1:
        params["page"] = page
    try:
        return _page("/profiles/search?" + urlencode(params), f"search {query!r} page {page}", "Results for")
    except _Redirected as moved:
        raise PitchbookUpstreamError(f"search was redirected to {moved.location[:120]!r}")


def _sitemap(path, label):
    def once():
        try:
            resp = _get(refs.SITE + path, label, paced=False, timeout=SITEMAP_TIMEOUT)
        except _Redirected as moved:
            raise PitchbookUpstreamError(f"{label} was redirected to {moved.location[:120]!r}")
        body = resp.content
        if body[:2] == b"\x1f\x8b":                  # a .xml.gz file arrives packed
            try:
                body = gzip.decompress(body)
            except (OSError, EOFError) as error:
                raise PitchbookUpstreamError(f"{label} did not unpack: {error}")
        text = body.decode("utf-8", "replace")
        if "<loc>" not in text:
            raise PitchbookUpstreamError(f"unexpected answer for {label}: {text[:80]!r}")
        return text
    return _retrying(once)


def fetch_sitemap_index():
    """/sitemap.xml: the list of every sitemap file."""
    return _sitemap("/sitemap.xml", "the sitemap index")


def fetch_sitemap_file(prefix, number):
    """One sitemap file (`company-profiles`, 75) as XML text. A file past
    the last one answers 404: PitchbookNotFound."""
    return _sitemap(f"/{prefix}-sitemap-{number}.xml.gz", f"sitemap file {prefix} {number}")
