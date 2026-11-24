"""The /pitchbook/* endpoint functions (route_glue's route_table calls them
with the schema's loaded kwargs).

Every endpoint caches inside (cache.cached_call, keyed on the validated
params): one parsed page per profile, per industry, per screener and per
search page. The profile list reads the site's sitemap: 20,000 links a
file, served here 1,000 a page, with the parsed file kept in the process so
that paging through a file downloads it once.
"""
import math
import threading
from collections import OrderedDict

from cache import cached_call
from pitchbook import cache_config as ttl
from pitchbook import parsers, refs
from pitchbook.fetch import (PitchbookNotFound, fetch_industry, fetch_profile, fetch_screener, fetch_search,
                             fetch_sitemap_file, fetch_sitemap_index)
from scraper_utils import memo

SEARCH_PAGE_SIZE = parsers.SEARCH_PAGE_SIZE
LIST_PAGE_SIZE = 1000                                   # rows of one /profiles/list page
PAGES_PER_FILE = parsers.SITEMAP_FILE_SIZE // LIST_PAGE_SIZE

_PARSERS = {
    "company": parsers.parse_company,
    "investor": parsers.parse_investor,
    "fund": parsers.parse_fund,
    "limited_partner": parsers.parse_limited_partner,
    "advisor": parsers.parse_advisor,
}


# ---- profiles ------------------------------------------------------------------------

def _profile(kind, id):
    return _PARSERS[kind](fetch_profile(kind, id))


def _cached_profile(kind, profile_id):
    return cached_call("pitchbook.profile", {"kind": kind, "id": profile_id}, _profile, ttl.PROFILE_CACHE)


def company_details(company):
    """A company's public profile: overview, contact block, funding rounds,
    competitors, investors, investments, patents, and for a public company
    its stock line and financials."""
    return _cached_profile("company", company)


def investor_details(investor):
    """An investor's public profile (a firm, an accelerator or an angel)."""
    return _cached_profile("investor", investor)


def fund_details(fund):
    """A fund's public profile."""
    return _cached_profile("fund", fund)


def limited_partner_details(limited_partner):
    """A limited partner's public profile."""
    return _cached_profile("limited_partner", limited_partner)


def advisor_details(advisor):
    """An advisor's or lender's public profile."""
    return _cached_profile("advisor", advisor)


# ---- profiles/search -----------------------------------------------------------------

def _search(query, page):
    rows, total_pages = parsers.parse_search(fetch_search(query, page))
    # The site publishes no result count, only the number of its last page.
    # A page past the end has no rows and no page links.
    return {
        "query": query,
        "results": rows,
        "pagination": {
            "page": page,
            "items_per_page": SEARCH_PAGE_SIZE,
            "has_next": bool(total_pages and page < total_pages),
            "total_pages": total_pages,
            "total_count": None,
        },
    }


def profiles_search(**data):
    return cached_call("pitchbook.search", data, _search, ttl.SEARCH_CACHE)


# ---- profiles/list (the sitemap) -----------------------------------------------------

_files = OrderedDict()          # (prefix, number) -> the parsed rows of one sitemap file
_files_lock = threading.Lock()
FILES_KEPT = 3                  # parsed files kept in the process (about 3 MB each)


def _sitemap_counts():
    """{file prefix: number of files}, from the sitemap index."""
    return cached_call("pitchbook.sitemap_index", {}, lambda: parsers.parse_sitemap_index(fetch_sitemap_index()),
                       ttl.SITEMAP_CACHE)


def _file_rows(prefix, number):
    return memo.memoized(_files, _files_lock, FILES_KEPT, (prefix, number),
                         lambda: parsers.parse_sitemap_profiles(fetch_sitemap_file(prefix, number)),
                         ttl.SITEMAP_FILE_MEMO_SECONDS)


def _last_file_size(prefix, number):
    return len(_file_rows(prefix, number))


def _list(type, page):
    prefix = refs.SITEMAP_PREFIXES[type]
    files = _sitemap_counts().get(prefix) or 0
    if not files:
        raise PitchbookNotFound(f"PitchBook's sitemap lists no {type.replace('_', ' ')} profiles")
    # Every file but the last holds 20,000 links, so the total needs the size of the last one only.
    last = cached_call("pitchbook.sitemap_last", {"prefix": prefix, "number": files}, _last_file_size, ttl.SITEMAP_CACHE)
    total = (files - 1) * parsers.SITEMAP_FILE_SIZE + last
    number = (page - 1) // PAGES_PER_FILE + 1
    start = ((page - 1) % PAGES_PER_FILE) * LIST_PAGE_SIZE
    rows = _file_rows(prefix, number)[start:start + LIST_PAGE_SIZE] if number <= files else []
    return {
        "type": type,
        "results": rows,
        "pagination": {
            "page": page,
            "items_per_page": LIST_PAGE_SIZE,
            "total_pages": math.ceil(total / LIST_PAGE_SIZE),
            "total_count": total,
        },
    }


def profiles_list(**data):
    """Every profile of one kind, from the site's sitemap: id, link and the
    date the site last changed the page."""
    return cached_call("pitchbook.list", data, _list, ttl.SITEMAP_CACHE)


# ---- industries and screeners --------------------------------------------------------

def _industries():
    rows = parsers.parse_sitemap_slugs(fetch_sitemap_file(refs.INDUSTRY_SITEMAP, 1), "industry", refs.industry_link)
    return {"count": len(rows), "results": rows}


def industries_list():
    """Every industry (vertical) PitchBook has a page for."""
    return cached_call("pitchbook.industries", {}, _industries, ttl.SITEMAP_CACHE)


def _industry(industry):
    return parsers.parse_industry(fetch_industry(industry))


def industry_details(**data):
    return cached_call("pitchbook.industry", data, _industry, ttl.INDUSTRY_CACHE)


def _screeners():
    rows = parsers.parse_sitemap_slugs(fetch_sitemap_file(refs.SCREENER_SITEMAP, 1), "screeners", refs.screener_link)
    return {"count": len(rows), "results": rows}


def screeners_list():
    """Every screener (curated list) PitchBook has a page for."""
    return cached_call("pitchbook.screeners", {}, _screeners, ttl.SITEMAP_CACHE)


def _screener(screener):
    return parsers.parse_screener(fetch_screener(screener))


def screener_details(**data):
    return cached_call("pitchbook.screener", data, _screener, ttl.SCREENER_CACHE)
