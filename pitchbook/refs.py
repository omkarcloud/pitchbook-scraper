"""Reference resolvers and link builders for /pitchbook/*.

A PitchBook profile is addressed by its kind and its id:

    https://pitchbook.com/profiles/company/54782-29
    https://pitchbook.com/profiles/investor/40420-36
    https://pitchbook.com/profiles/fund/11295-73F          a fund id ends in F
    https://pitchbook.com/profiles/limited-partner/10716-13
    https://pitchbook.com/profiles/advisor/110600-56
    https://pitchbook.com/profiles/industry/saas           a vertical: a slug
    https://pitchbook.com/profiles/screeners/angel-investors

An id belongs to ONE kind. The site redirects a path with the wrong kind to
the right one (/profiles/investor/54782-29 lands on the company), and the
same digits with and without the F are two different records (11295-73F is
a fund, 11295-73 an investor), so a resolver never adds or drops the F.

Every endpoint takes ONE param per record, which accepts the bare id (or
slug) or any pitchbook.com link of that record. A link of another kind is
refused with a message that names the endpoint to call instead.
"""
import re
from urllib.parse import urlparse

SITE = "https://pitchbook.com"

# Our public kind -> the path segment the site uses.
PROFILE_PATHS = {
    "company": "company",
    "investor": "investor",
    "fund": "fund",
    "limited_partner": "limited-partner",
    "advisor": "advisor",
}
KIND_OF_PATH = {path: kind for kind, path in PROFILE_PATHS.items()}

# Our public kind -> the collection its details endpoint lives under.
COLLECTIONS = {
    "company": "companies",
    "investor": "investors",
    "fund": "funds",
    "limited_partner": "limited-partners",
    "advisor": "advisors",
}

# The sitemap files that list every profile of a kind, 20,000 links a file
# (https://pitchbook.com/sitemap.xml, read 2026-11-21).
SITEMAP_PREFIXES = {
    "company": "company-profiles",
    "investor": "investor-profiles",
    "fund": "fund-profiles",
    "limited_partner": "limited-partner-profiles",
    "advisor": "advisor-profiles",
}
INDUSTRY_SITEMAP = "industry-profiles"
SCREENER_SITEMAP = "screener-profiles"

_ID_RE = re.compile(r"\d{3,9}-\d{2}F?")
_SLUG_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_PROFILE_PATH_RE = re.compile(r"/profiles/([a-z-]+)/([^/?#]+)")


def _is_link(value):
    return "://" in value or value.lower().startswith(("pitchbook.com", "www.pitchbook.com", "/profiles/"))


def _path_of(value):
    """The /profiles/<kind>/<ref> pair of a pitchbook.com link, or a
    ValueError that says what is wrong with it."""
    text = value if "://" in value else ("https://pitchbook.com" + value if value.startswith("/") else "https://" + value)
    parsed = urlparse(text)
    host = (parsed.hostname or "").lower()
    if host not in ("pitchbook.com", "www.pitchbook.com"):
        raise ValueError("this is not a pitchbook.com link")
    match = _PROFILE_PATH_RE.match(parsed.path)
    if not match:
        raise ValueError("this pitchbook.com link is not a profile (expected /profiles/<kind>/<id>)")
    return match.group(1), match.group(2)


def profile_link(kind, profile_id):
    """The site's own link of a profile."""
    return f"{SITE}/profiles/{PROFILE_PATHS[kind]}/{profile_id}"


def industry_link(slug):
    return f"{SITE}/profiles/industry/{slug}"


def screener_link(slug):
    return f"{SITE}/profiles/screeners/{slug}"


def entity_of_link(href):
    """{id, type, link} of a profile link found in a page, or None for any
    other link. type is our public kind (limited_partner, not the path)."""
    match = _PROFILE_PATH_RE.search(href or "")
    if not match or match.group(1) not in KIND_OF_PATH:
        return None
    kind = KIND_OF_PATH[match.group(1)]
    return {"id": match.group(2), "type": kind, "link": profile_link(kind, match.group(2))}


def vertical_of_link(href):
    """The slug of an /profiles/industry/<slug> link, or None."""
    match = _PROFILE_PATH_RE.search(href or "")
    return match.group(2) if match and match.group(1) == "industry" else None


def with_article(noun):
    return ("an " if noun[0] in "aeiou" else "a ") + noun


def _wrong_kind(found, wanted):
    return ValueError(f"this is {with_article(found.replace('_', ' '))} profile: call /pitchbook/{COLLECTIONS[found]}/details "
                      f"for it (this endpoint takes {with_article(wanted.replace('_', ' '))})")


def resolve_profile(value, kind):
    """A bare id or a pitchbook.com profile link -> the id of a `kind`
    profile. ValueError (a 400) for another site's link, a link of another
    kind, or something that is not an id."""
    value = (value or "").strip()
    noun = kind.replace("_", " ")
    if _is_link(value):
        path_kind, ref = _path_of(value)
        found = KIND_OF_PATH.get(path_kind)
        if found is None:
            raise ValueError(f"this link is a PitchBook {path_kind} page, not {with_article(noun)} profile")
        if found != kind:
            raise _wrong_kind(found, kind)
        value = ref
    profile_id = value.upper() if value[-1:] in ("f", "F") else value
    if not _ID_RE.fullmatch(profile_id):
        raise ValueError(f"not a PitchBook {noun} id: expected an id like "
                         f"{'11295-73F' if kind == 'fund' else '54782-29'} or the profile's pitchbook.com link")
    if kind == "fund" and not profile_id.endswith("F"):
        raise ValueError("a PitchBook fund id ends in F (11295-73F); the same digits without it are another record")
    if kind != "fund" and profile_id.endswith("F"):
        raise _wrong_kind("fund", kind)
    return profile_id


def resolve_company(value):
    return resolve_profile(value, "company")


def resolve_investor(value):
    return resolve_profile(value, "investor")


def resolve_fund(value):
    return resolve_profile(value, "fund")


def resolve_limited_partner(value):
    return resolve_profile(value, "limited_partner")


def resolve_advisor(value):
    return resolve_profile(value, "advisor")


def _resolve_slug(value, path_kind, noun, collection, example):
    value = (value or "").strip()
    if _is_link(value):
        found, ref = _path_of(value)
        if found != path_kind:
            raise ValueError(f"this link is not a PitchBook {noun} page (expected /profiles/{path_kind}/<name>)")
        value = ref
    slug = value.lower()
    if not _SLUG_RE.fullmatch(slug):
        raise ValueError(f"not a PitchBook {noun}: expected a name like {example} (see /pitchbook/{collection}/list) "
                         f"or the page's pitchbook.com link")
    return slug


def resolve_industry(value):
    """`saas` or https://pitchbook.com/profiles/industry/saas -> saas."""
    return _resolve_slug(value, "industry", "industry", "industries", "saas")


def resolve_screener(value):
    """`angel-investors` or its /profiles/screeners/ link -> angel-investors."""
    return _resolve_slug(value, "screeners", "screener", "screeners", "angel-investors")
