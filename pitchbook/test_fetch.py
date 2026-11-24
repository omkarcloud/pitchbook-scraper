"""Offline tests for the PitchBook transport: how each answer of the site is
read (a page, the 404 and 410 pages, a redirect to another kind, the two
Cloudflare challenge pages, a packed sitemap file) and how requests are
spread, paced and rested over the exits.

    python -m pytest pitchbook/test_fetch.py -q

No network: the thread's session is replaced by one that answers from the
fixtures (pitchbook/fixtures/, real answers captured 2026-11-21).
"""
import gzip
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
from pitchbook import fetch  # noqa: E402
from scraper_errors import Blocked, NotFound, Unavailable, UpstreamError  # noqa: E402
from scraper_utils.testing import hosted_only  # noqa: E402

FX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def load(name):
    with gzip.open(os.path.join(FX, name + ".gz"), "rt", encoding="utf-8") as f:
        return f.read()


class Response:
    def __init__(self, status, text="", headers=None, content=None):
        self.status_code = status
        self.text = text
        self.content = content if content is not None else text.encode("utf-8")
        self.headers = {"content-type": "text/html;charset=UTF-8", **(headers or {})}


def challenge(status):
    name = "challenge_403.html" if status == 403 else "challenge_429.html"
    return Response(status, load(name), {"cf-mitigated": "challenge"})


@pytest.fixture
def site(monkeypatch):
    """site(answer, answer, ...) queues the answers of the next requests (the
    last one repeats) and returns the log of (exit, url) actually sent."""
    monkeypatch.setattr(config, "PITCHBOOK_EXIT", "jp")
    monkeypatch.setattr(config, "PITCHBOOK_EXIT_COUNTRIES", ("pl", "au", "se"))
    monkeypatch.setattr(config, "PITCHBOOK_COUNTRY_PER_MINUTE", 10)
    monkeypatch.setattr(config, "PITCHBOOK_MAX_TRIES", 4)
    monkeypatch.setattr(config, "PITCHBOOK_RETRY_PAUSE", 0)
    monkeypatch.setattr(fetch, "PACE_MAX_WAIT", 0)
    monkeypatch.setattr(fetch, "_drop_session", lambda exit_=None: dropped.append(exit_ or fetch._local.last_exit))
    fetch.reset_pacing()
    sent, dropped, answers = [], [], []

    class Session:
        def __init__(self, exit_):
            self.exit = exit_

        def get(self, url, headers=None, timeout=None, allow_redirects=True):
            assert allow_redirects is False and headers is fetch.PAGE_HEADERS
            sent.append((self.exit, url))
            answer = answers.pop(0) if len(answers) > 1 else answers[0]
            if isinstance(answer, Exception):
                raise answer
            return answer

    monkeypatch.setattr(fetch, "_session", Session)

    def queue(*responses):
        answers[:] = responses
        return sent, dropped
    yield queue
    fetch.reset_pacing()


# ---- what the site answers ------------------------------------------------------------

def test_a_profile_page(site):
    sent, _ = site(Response(200, load("company_stripe_54782-29.html")))
    assert "<title>Stripe 2026 Company Profile" in fetch.fetch_profile("company", "54782-29")
    assert [url for _, url in sent] == ["https://pitchbook.com/profiles/company/54782-29"]


@pytest.mark.parametrize("kind, profile_id, path", [
    ("investor", "40420-36", "/profiles/investor/40420-36"),
    ("fund", "11295-73F", "/profiles/fund/11295-73F"),
    ("limited_partner", "11079-46", "/profiles/limited-partner/11079-46"),
    ("advisor", "10019-98", "/profiles/advisor/10019-98"),
])
def test_profile_paths(site, kind, profile_id, path):
    sent, _ = site(Response(200, load("fund_11295-73F.html")))
    fetch.fetch_profile(kind, profile_id)
    assert sent[0][1] == "https://pitchbook.com" + path


def test_unknown_and_removed_profiles_are_not_found(site):
    sent, _ = site(Response(404, load("profile_not_found_404.html")))
    with pytest.raises(NotFound) as error:
        fetch.fetch_profile("company", "99999999-99")
    assert str(error.value) == "company 99999999-99 not found" and len(sent) == 1       # never retried
    site(Response(410, load("profile_removed_410.html")))
    with pytest.raises(NotFound) as error:
        fetch.fetch_profile("company", "226728-91")
    assert "was removed from PitchBook" in str(error.value)


def test_an_id_of_another_kind_names_its_endpoint(site):
    """The site redirects /profiles/investor/<a company's id> to the company: not followed."""
    sent, _ = site(Response(302, "", {"location": "https://pitchbook.com/profiles/company/54782-29"}))
    with pytest.raises(NotFound) as error:
        fetch.fetch_profile("investor", "54782-29")
    assert str(error.value) == "54782-29 is not an investor: it is a company (call /pitchbook/companies/details)"
    assert len(sent) == 1
    site(Response(301, "", {"location": "/profiles/limited-partner/10716-13"}))
    with pytest.raises(NotFound) as error:
        fetch.fetch_profile("advisor", "10716-13")
    assert "it is a limited partner (call /pitchbook/limited-partners/details)" in str(error.value)
    site(Response(302, "", {"location": "/profiles"}))
    with pytest.raises(NotFound):
        fetch.fetch_industry("not-a-real-industry")


def test_industry_screener_and_search_paths(site):
    sent, _ = site(Response(200, load("industry_saas.html")))
    fetch.fetch_industry("saas")
    fetch.fetch_screener("angel-investors")
    site(Response(200, load("search_stripe_page_1.html")))
    fetch.fetch_search("stripe & co")
    fetch.fetch_search("stripe", 2)
    assert [url for _, url in sent] == [
        "https://pitchbook.com/profiles/industry/saas",
        "https://pitchbook.com/profiles/screeners/angel-investors",
        "https://pitchbook.com/profiles/search?q=stripe+%26+co",
        "https://pitchbook.com/profiles/search?q=stripe&page=2"]


def test_a_search_with_no_result_is_a_page_not_an_error(site):
    site(Response(200, load("search_no_result.html")))
    assert "zzqxjkvw" in fetch.fetch_search("zzqxjkvw")
    site(Response(200, load("search_past_end.html")))
    assert "Results for" in fetch.fetch_search("stripe", 9)


def test_a_page_that_is_not_the_page_is_retried(site):
    sent, dropped = site(Response(200, "<html><head><title>Maintenance</title></head></html>"),
                         Response(200, load("company_sparse_358833-25.html")))
    assert "Truck Stop" in fetch.fetch_profile("company", "358833-25")
    assert len(sent) == 2 and len(dropped) == 1


def test_a_transport_error_and_a_5xx_are_retried(site):
    sent, dropped = site(ConnectionError("reset"), Response(502, "bad gateway"),
                         Response(200, load("company_sparse_358833-25.html")))
    fetch.fetch_profile("company", "358833-25")
    assert len(sent) == 3 and len(dropped) == 2


# ---- the sitemap ----------------------------------------------------------------------

def test_a_sitemap_file_arrives_packed(site):
    xml = load("sitemap_industry_profiles.xml")
    sent, _ = site(Response(200, "", {"content-type": "application/gzip"}, gzip.compress(xml.encode("utf-8"))))
    assert fetch.fetch_sitemap_file("industry-profiles", 1) == xml
    assert sent[0][1] == "https://pitchbook.com/industry-profiles-sitemap-1.xml.gz"
    site(Response(200, load("sitemap_index.xml"), {"content-type": "application/xml"}))
    assert "<sitemapindex" in fetch.fetch_sitemap_index()
    assert sent[1][1] == "https://pitchbook.com/sitemap.xml"


def test_a_sitemap_file_past_the_last_is_not_found(site):
    site(Response(404, load("sitemap_file_not_found_404.html")))
    with pytest.raises(NotFound):
        fetch.fetch_sitemap_file("company-profiles", 76)


def test_the_sitemap_is_outside_the_pace(site):
    """The site's limit covers /profiles/* only, so sitemap calls are not counted."""
    site(Response(200, load("sitemap_index.xml"), {"content-type": "application/xml"}))
    for _ in range(50):
        fetch.fetch_sitemap_index()
    assert not any(fetch._sent.values())


# ---- challenges, the spread, the pace and the rest ------------------------------------

@hosted_only
def test_a_proven_country_is_preferred_and_a_load_is_spread(site):
    """A country that answered a real page is preferred (its data centre has budget) for its
    first requests of a minute; a load beyond that goes to the untried ones, then round all."""
    sent, _ = site(Response(200, load("company_sparse_358833-25.html")))
    for _ in range(12):
        fetch.fetch_profile("company", "358833-25")
    assert [exit_ for exit_, _ in sent] == ["jp", "jp", "pl", "pl", "au", "au", "se", "se", "jp", "pl", "au", "se"]


@hosted_only
def test_after_a_refusal_the_next_try_prefers_a_proven_country(site):
    sent, _ = site(Response(200, load("company_sparse_358833-25.html")))
    for _ in range(2):
        fetch.fetch_profile("company", "358833-25")          # jp is proven and has had its first two
    site(challenge(429), Response(200, load("company_sparse_358833-25.html")))
    fetch.fetch_profile("company", "358833-25")
    assert [exit_ for exit_, _ in sent[2:]] == ["pl", "jp"]  # the untried pl is refused: back to jp, not on to au
    assert list(fetch.resting()) == ["pl"]


@hosted_only
def test_a_not_found_answer_proves_the_country_too(site):
    sent, _ = site(Response(404, load("profile_not_found_404.html")))
    for _ in range(2):
        with pytest.raises(NotFound):
            fetch.fetch_profile("company", "99999999-99")
    assert [exit_ for exit_, _ in sent] == ["jp", "jp"]      # an untried country would have been pl


@hosted_only
def test_a_429_rests_the_country_and_the_next_try_leaves_from_another(site):
    sent, dropped = site(challenge(429), Response(200, load("company_stripe_54782-29.html")))
    assert "Stripe" in fetch.fetch_profile("company", "54782-29")
    assert [exit_ for exit_, _ in sent] == ["jp", "pl"] and dropped == ["jp"]
    assert list(fetch.resting()) == ["jp"]
    assert fetch.resting()["jp"] in range(config.PITCHBOOK_COUNTRY_REST_S - 2, config.PITCHBOOK_COUNTRY_REST_S + 1)
    for _ in range(6):
        fetch.fetch_profile("company", "54782-29")
    assert "jp" not in [exit_ for exit_, _ in sent[1:]]          # every thread stays off it


@hosted_only
def test_a_403_takes_a_new_address_without_resting_the_country(site):
    sent, dropped = site(challenge(403), Response(200, load("company_stripe_54782-29.html")))
    fetch.fetch_profile("company", "54782-29")
    assert len(sent) == 2 and dropped == ["jp"] and fetch.resting() == {}


@hosted_only
def test_a_failed_try_leaves_from_another_country_even_when_the_first_is_proven(site, monkeypatch):
    """A proven country that answers 403 (or times out) is not resting: the next try still leaves from another."""
    sent, _ = site(Response(200, load("company_sparse_358833-25.html")))
    fetch.fetch_profile("company", "358833-25")              # jp is proven
    site(challenge(403), Response(200, load("company_sparse_358833-25.html")))
    fetch.fetch_profile("company", "358833-25")
    assert [exit_ for exit_, _ in sent[1:]] == ["jp", "pl"] and fetch.resting() == {}
    site(challenge(403))
    with pytest.raises(Blocked):
        fetch.fetch_profile("company", "358833-25")
    assert len({exit_ for exit_, _ in sent[3:]}) == 4        # four tries, four countries
    monkeypatch.setattr(config, "PITCHBOOK_EXIT_COUNTRIES", ())
    del sent[:]
    with pytest.raises(Blocked):
        fetch.fetch_profile("company", "358833-25")
    assert [exit_ for exit_, _ in sent] == ["jp"] * 4        # one exit alone is tried again


@hosted_only
def test_refused_on_every_try_is_blocked(site):
    sent, _ = site(challenge(403))
    with pytest.raises(Blocked):
        fetch.fetch_profile("company", "54782-29")
    assert len(sent) == config.PITCHBOOK_MAX_TRIES == 4
    assert len({exit_ for exit_, _ in sent}) == 4               # each try from another country


@hosted_only
def test_when_every_country_rests_nothing_is_sent(site):
    sent, _ = site(challenge(429))
    with pytest.raises(UpstreamError):
        fetch.fetch_profile("company", "54782-29")
    assert sorted(fetch.resting()) == ["au", "jp", "pl", "se"] and len(sent) == 4
    with pytest.raises(Unavailable) as error:
        fetch.fetch_profile("company", "54782-29")
    assert len(sent) == 4                                       # no fifth request
    assert 1 <= error.value.retry_after <= config.PITCHBOOK_COUNTRY_REST_S
    # the sitemap is not under that limit: it still goes out
    site(Response(200, load("sitemap_index.xml"), {"content-type": "application/xml"}))
    assert "<loc>" in fetch.fetch_sitemap_index()


@hosted_only
def test_a_country_is_kept_under_its_pace(site, monkeypatch):
    monkeypatch.setattr(config, "PITCHBOOK_EXIT_COUNTRIES", ())
    monkeypatch.setattr(config, "PITCHBOOK_COUNTRY_PER_MINUTE", 3)
    sent, _ = site(Response(200, load("company_sparse_358833-25.html")))
    for _ in range(3):
        fetch.fetch_profile("company", "358833-25")
    with pytest.raises(Unavailable) as error:
        fetch.fetch_profile("company", "358833-25")
    assert len(sent) == 3 and "pace" in str(error.value) and error.value.retry_after <= 60
    monkeypatch.setattr(config, "PITCHBOOK_COUNTRY_PER_MINUTE", 0)      # 0 = no pacing
    fetch.fetch_profile("company", "358833-25")
    assert len(sent) == 4


def test_the_session_is_the_exits_own(monkeypatch):
    """A session is built by egress.exit_session on the picked exit, as safari17_0."""
    built = []
    monkeypatch.setattr(fetch.egress, "exit_session",
                        lambda exit_, impersonate="chrome": built.append((exit_, impersonate)) or object())
    monkeypatch.setattr(fetch.sessions, "close_quietly", lambda sess: None)
    fetch._local.__dict__.pop("sessions", None)
    first = fetch._session("jp")
    assert fetch._session("jp") is first and built == [("jp", "safari17_0")]
    fetch._local.last_exit = "jp"
    fetch._drop_session()
    assert fetch._session("jp") is not first and len(built) == 2
    fetch._local.__dict__.pop("sessions", None)
