"""Offline tests for the /pitchbook/* endpoint functions: the shape of a
search page, and how the profile list pages through the sitemap files.

    python -m pytest pitchbook/test_api.py -q

No network and no cache: the fetch functions answer from the fixtures.
"""
import gzip
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pitchbook import api  # noqa: E402
from scraper_errors import NotFound  # noqa: E402

FX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def load(name):
    with gzip.open(os.path.join(FX, name + ".gz"), "rt", encoding="utf-8") as f:
        return f.read()


def sitemap_file(first, count):
    rows = "".join(f"<url><loc>https://pitchbook.com/profiles/company/{number}-11</loc>"
                   f"<lastmod>2026-11-20T08:00:00.000+00:00</lastmod></url>" for number in range(first, first + count))
    return f'<?xml version="1.0"?><urlset>{rows}</urlset>'


@pytest.fixture
def site(monkeypatch):
    """No cache, and a sitemap of 3 company files: 20,000 + 20,000 + 2,500 links."""
    calls = []
    monkeypatch.setattr(api, "cached_call", lambda namespace, data, fn, ttl: fn(**data))
    monkeypatch.setattr(api, "fetch_sitemap_index", lambda: calls.append("index") or (
        '<sitemapindex><sitemap><loc>https://pitchbook.com/company-profiles-sitemap-1.xml.gz</loc></sitemap>'
        '<sitemap><loc>https://pitchbook.com/company-profiles-sitemap-3.xml.gz</loc></sitemap>'
        '<sitemap><loc>https://pitchbook.com/industry-profiles-sitemap-1.xml.gz</loc></sitemap></sitemapindex>'))

    def file(prefix, number):
        calls.append((prefix, number))
        if prefix == "company-profiles":
            return sitemap_file(100000 * number, 2500 if number == 3 else 20000)
        return load({"industry-profiles": "sitemap_industry_profiles.xml",
                     "screener-profiles": "sitemap_screener_profiles.xml"}[prefix])

    monkeypatch.setattr(api, "fetch_sitemap_file", file)
    api._files.clear()
    yield calls
    api._files.clear()


def test_search_page(monkeypatch, site):
    monkeypatch.setattr(api, "fetch_search", lambda query, page: load("search_stripe_page_1.html"))
    answer = api.profiles_search(query="stripe", page=1)
    assert list(answer) == ["query", "results", "pagination"] and answer["query"] == "stripe"
    assert len(answer["results"]) == 15 and answer["results"][2]["name"] == "Stripe"
    assert answer["pagination"] == {"page": 1, "items_per_page": 15, "has_next": True, "total_pages": 8,
                                    "total_count": None}


def test_search_last_page_and_past_the_end(monkeypatch, site):
    monkeypatch.setattr(api, "fetch_search", lambda query, page: load("search_stripe_last_page_8.html"))
    last = api.profiles_search(query="stripe", page=8)
    assert len(last["results"]) == 13 and last["pagination"]["has_next"] is False
    monkeypatch.setattr(api, "fetch_search", lambda query, page: load("search_past_end.html"))
    past = api.profiles_search(query="stripe", page=9)
    assert past["results"] == []                           # an empty page, not an error
    assert past["pagination"] == {"page": 9, "items_per_page": 15, "has_next": False, "total_pages": None,
                                  "total_count": None}


def test_list_pages_through_the_sitemap_files(site):
    first = api.profiles_list(type="company", page=1)
    assert first["type"] == "company" and len(first["results"]) == api.LIST_PAGE_SIZE == 1000
    assert first["results"][0] == {"id": "100000-11", "type": "company",
                                   "link": "https://pitchbook.com/profiles/company/100000-11",
                                   "last_modified": "2026-11-20T08:00:00Z"}
    assert first["pagination"] == {"page": 1, "items_per_page": 1000, "total_pages": 43, "total_count": 42500}
    assert api.profiles_list(type="company", page=2)["results"][0]["id"] == "101000-11"     # the same file, further in
    assert api.profiles_list(type="company", page=20)["results"][-1]["id"] == "119999-11"   # the end of file 1
    assert api.profiles_list(type="company", page=21)["results"][0]["id"] == "200000-11"    # file 2 starts
    assert site.count(("company-profiles", 1)) == 1                                         # one download for 3 pages


def test_list_last_page_and_past_the_end(site):
    last = api.profiles_list(type="company", page=43)
    assert len(last["results"]) == 500 and last["results"][-1]["id"] == "302499-11"
    assert api.profiles_list(type="company", page=44)["results"] == []       # inside the last file, past its links
    past = api.profiles_list(type="company", page=61)                        # past the last file: no download
    assert past["results"] == [] and past["pagination"]["total_pages"] == 43
    assert ("company-profiles", 4) not in site


def test_list_of_a_kind_the_sitemap_does_not_have(site):
    with pytest.raises(NotFound):
        api.profiles_list(type="fund", page=1)


def test_reference_lists(site):
    industries = api.industries_list()
    assert industries["count"] == 59 and industries["results"][0]["slug"] == "3d-printing"
    screeners = api.screeners_list()
    assert screeners["count"] == 173 and screeners["results"][0]["slug"] == "accredited-investors"
    assert ("industry-profiles", 1) in site and ("screener-profiles", 1) in site


def test_details_parse_the_page_of_their_kind(monkeypatch, site):
    asked = []
    pages = {"company": "company_sparse_358833-25.html", "investor": "investor_angel_226728-91.html",
             "fund": "fund_sparse_27537-40F.html", "limited_partner": "limited_partner_10716-13.html",
             "advisor": "advisor_110600-56.html"}
    monkeypatch.setattr(api, "fetch_profile", lambda kind, profile_id: asked.append((kind, profile_id)) or load(pages[kind]))
    assert api.company_details(company="358833-25")["type"] == "company"
    assert api.investor_details(investor="226728-91")["name"] == "Patrick Collison"
    assert api.fund_details(fund="27537-40F")["id"] == "27537-40F"
    assert api.limited_partner_details(limited_partner="10716-13")["type"] == "limited_partner"
    assert api.advisor_details(advisor="110600-56")["type"] == "advisor"
    assert asked == [("company", "358833-25"), ("investor", "226728-91"), ("fund", "27537-40F"),
                     ("limited_partner", "10716-13"), ("advisor", "110600-56")]
    monkeypatch.setattr(api, "fetch_industry", lambda slug: load("industry_saas.html"))
    monkeypatch.setattr(api, "fetch_screener", lambda slug: load("screener_angel_investors.html"))
    assert api.industry_details(industry="saas")["slug"] == "saas"
    assert api.screener_details(screener="angel-investors")["slug"] == "angel-investors"
