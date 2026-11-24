"""Offline tests for the PitchBook parsers and reference resolvers.

    python -m pytest pitchbook/test_parsers.py -q

Fixtures are real pitchbook.com pages captured 2026-11-21 and 2026-11-23
(pitchbook/fixtures/, packed with gzip): a venture-backed company (Stripe),
an acquired one whose funding and investor tables are kept for subscribers
(Automic Software), a public one (Microsoft), one with a cap table (Chef
Software) and a sparse one; an accelerator, a venture firm and an angel;
two funds, two limited partners, three advisors (a small one, a lender, a
law firm); an industry, two screeners, five search pages and four sitemap
files. No network.
"""
import gzip
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pitchbook import parsers as P, refs  # noqa: E402

FX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def fixture(name):
    with gzip.open(os.path.join(FX, name + ".gz"), "rt", encoding="utf-8") as f:
        return f.read()


def parsed(parser, name, _memo={}):
    if name not in _memo:
        _memo[name] = parser(fixture(name))
    return _memo[name]


COMPANIES = ("company_stripe_54782-29.html", "company_acquired_10874-98.html", "company_public_11026-45.html",
             "company_cap_table_43099-57.html", "company_sparse_358833-25.html")
INVESTORS = ("investor_accelerator_57670-21.html", "investor_vc_11295-73.html", "investor_angel_226728-91.html")
FUNDS = ("fund_11295-73F.html", "fund_sparse_27537-40F.html")
LIMITED_PARTNERS = ("limited_partner_10716-13.html", "limited_partner_pension_11079-46.html")
ADVISORS = ("advisor_110600-56.html", "advisor_lender_10243-45.html", "advisor_law_firm_10019-98.html")
PROFILE_CASES = ([(P.parse_company, name) for name in COMPANIES] + [(P.parse_investor, name) for name in INVESTORS]
                 + [(P.parse_fund, name) for name in FUNDS]
                 + [(P.parse_limited_partner, name) for name in LIMITED_PARTNERS]
                 + [(P.parse_advisor, name) for name in ADVISORS])


def walk(value):
    """Every plain value inside a result."""
    if isinstance(value, dict):
        for item in value.values():
            yield from walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from walk(item)
    else:
        yield value


def keys_of(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from keys_of(item)
    elif isinstance(value, list):
        for item in value:
            yield from keys_of(item)


# ---- values ---------------------------------------------------------------------------

@pytest.mark.parametrize("text, expected", [
    ("$418K", (418000, "USD")),
    ("$9.7B", (9700000000, "USD")),
    ("$3.6T", (3600000000000, "USD")),
    ("$484.52", (484.52, "USD")),
    ("€1.2B", (1200000000, "EUR")),
    ("£900M", (900000000, "GBP")),
    ("7.43B", (7430000000, None)),
    ("3,788,737,282", (3788737282, None)),
    ("(1,234)", (-1234, None)),
    ("12.5%", (12.5, None)),
    ("1.8x", (1.8, None)),
    ("Completed", (None, None)),
    ("", (None, None)),
    (None, (None, None)),
])
def test_amounts(text, expected):
    assert P._amount(text) == expected


@pytest.mark.parametrize("text, expected", [
    ("28-Jun-2026", "2026-06-28"),
    ("1-Jan-2027", "2027-01-01"),
    ("August 3, 2026", "2026-08-03"),
    ("Oct 1, 2026", "2026-10-01"),
    ("November, 17, 2026", "2026-11-17"),
    ("Jun 2014", "2014-06"),
    ("2017", "2017"),
    ("someday", "someday"),
    ("", None),
    (None, None),
])
def test_dates(text, expected):
    assert P._date(text) == expected


def test_counts_are_whole_numbers():
    assert P._int("1,470") == 1470
    assert P._int("10,000") == 10000
    assert P._int("n/a") is None
    assert P._int("12 buyers") is None


# ---- every profile page ---------------------------------------------------------------

@pytest.mark.parametrize("parser, name", PROFILE_CASES)
def test_profile_identity_and_shape(parser, name):
    record = parsed(parser, name)
    path_kind, ref = P.page_reference(fixture(name))
    assert record["id"] == ref and ref in name
    assert record["type"] == refs.KIND_OF_PATH[path_kind]
    assert record["link"] == refs.profile_link(record["type"], ref)
    assert record["name"]
    assert list(record)[:5] == ["id", "type", "name", "link", "logo"]
    for value in walk(record):
        assert value != "", "an empty text must be null"
        if isinstance(value, str):
            assert not re.search(r"<[a-z/][^>]*>", value), value      # no tag left in a value
            assert "&#" not in value and "​" not in value, value
    for key in keys_of(record):
        assert key == key.lower() and " " not in key and key != "url", key


@pytest.mark.parametrize("parser, name", PROFILE_CASES)
def test_same_keys_for_every_page_of_a_kind(parser, name):
    """A sparse page answers the same keys as a rich one (null / [] where the site has nothing)."""
    first = next(other for fn, other in PROFILE_CASES if fn is parser)
    assert list(parsed(parser, name)) == list(parsed(parser, first))


# ---- companies ------------------------------------------------------------------------

def test_company_overview():
    c = parsed(P.parse_company, "company_stripe_54782-29.html")
    assert c["name"] == "Stripe" and c["status"] == "Private"
    assert c["logo"].startswith("https://image.pitchbook.com/")
    assert c["description"].startswith("Developer of an online financial infrastructure platform")
    assert (c["year_founded"], c["employees"], c["employees_as_of"]) == (2010, 10000, 2026)
    assert c["ownership_status"] == "Privately Held (backing)"
    assert c["financing_status"] == "Venture Capital-Backed"
    assert c["formerly_known_as"] == ["DevPayments", "HGSC", "SlashDevSlashFinance"]
    assert c["primary_industry"] == "Other Financial Services"
    assert c["other_industries"] == ["Financial Software"]
    assert c["verticals"][0] == {"name": "SaaS", "slug": "saas", "link": "https://pitchbook.com/profiles/industry/saas"}
    assert [v["slug"] for v in c["verticals"]] == ["saas", "artificial-intelligence-and-machine-learning", "fintech", "mobile"]
    assert (c["latest_deal_type"], c["latest_deal_amount"], c["currency"]) == ("Debt", 418000, "USD")
    assert c["total_raised"] == 9700000000          # only the FAQ carries it
    assert (c["investors_count"], c["investments_count"], c["competitors_count"], c["subsidiaries_count"]) == (166, 135, 119, 19)


def test_company_contact_block():
    c = parsed(P.parse_company, "company_stripe_54782-29.html")
    assert c["website"] == "http://www.stripe.com"
    assert c["social"] == {"linkedin": "https://www.linkedin.com/company/stripe",
                           "twitter": "https://twitter.com/stripe",
                           "facebook": "https://www.facebook.com/StripeHQ"}
    assert c["office"] == {"street": "354 Oyster Point Boulevard", "city": "South San Francisco",
                           "region": "California", "postal_code": "94080", "country": "United States",
                           "address": "354 Oyster Point Boulevard, South San Francisco, CA 94080, United States"}


@pytest.mark.parametrize("parser, name", PROFILE_CASES)
def test_a_masked_phone_is_null(parser, name):
    """The site prints '+1 (888)' and greys the rest: the stub is not returned."""
    record = parsed(parser, name)
    for key in ("phone", "manager_phone"):
        assert record.get(key) is None


def test_company_funding_rounds():
    rounds = parsed(P.parse_company, "company_stripe_54782-29.html")["funding_rounds"]
    assert len(rounds) == 10
    assert rounds[0] == {"deal_number": 30, "deal_type": "Debt - General", "date": None, "amount": 418000,
                         "raised_to_date": None, "post_valuation": None, "currency": "USD",
                         "status": "Completed", "stage": "Profitable"}
    assert rounds[1]["date"] == "2026-03-27" and rounds[1]["amount"] is None      # an empty cell
    assert all(r["raised_to_date"] is None for r in rounds[:8])                  # greyed for visitors
    assert rounds[8]["raised_to_date"] == 9700000000 and rounds[8]["currency"] == "USD"   # shown on two rows
    assert [r["deal_number"] for r in rounds] == list(range(30, 20, -1))
    other = parsed(P.parse_company, "company_cap_table_43099-57.html")["funding_rounds"]
    assert other[0]["deal_type"] == "Merger/Acquisition" and other[0]["amount"] == 220000000
    assert other[0]["date"] == "2020-10-05"


def test_tables_kept_for_subscribers_are_null_not_empty():
    acquired = parsed(P.parse_company, "company_acquired_10874-98.html")
    assert acquired["funding_rounds"] is None                 # header shown, rows kept back
    assert parsed(P.parse_company, "company_public_11026-45.html")["investors"] is None
    assert parsed(P.parse_investor, "investor_vc_11295-73.html")["funds"] is None
    assert parsed(P.parse_fund, "fund_11295-73F.html")["returns"] is None
    assert parsed(P.parse_advisor, "advisor_lender_10243-45.html")["investment_preferences"] is None
    sparse = parsed(P.parse_company, "company_sparse_358833-25.html")
    assert sparse["funding_rounds"] == [] and sparse["investors"] == []     # no such section at all


def test_company_tables():
    c = parsed(P.parse_company, "company_stripe_54782-29.html")
    assert c["competitors"][0] == {
        "id": "96534-82", "type": "company", "name": "Payscout",
        "link": "https://pitchbook.com/profiles/company/96534-82", "financing_status": "Venture Capital-Backed",
        "location": "Sherman Oaks, CA", "employees": None, "total_raised": None, "last_financing": None,
        "last_financing_amount": None, "currency": None}
    assert len(c["competitors"]) == 5 and len(c["investments"]) == 5 and len(c["affiliates"]) == 5
    assert c["investments"][0]["name"] == "OpenRouter" and c["investments"][0]["deal_date"] == "2026-11-16"
    assert c["investments"][0]["deal_type"] == "Merger/Acquisition" and c["investments"][0]["deal_size"] is None
    assert c["affiliates"][0]["year_founded"] == 2023 and c["affiliates"][0]["location"] == "New York, NY"
    assert c["exits"] == [] and c["cap_table"] == []


def test_company_investors_take_their_links_from_the_faq():
    """The investors table prints names without links; the FAQ links the same five."""
    c = parsed(P.parse_company, "company_stripe_54782-29.html")
    assert c["investors"][0] == {"id": "166301-20", "type": "investor", "name": "Irving Investors",
                                 "link": "https://pitchbook.com/profiles/investor/166301-20",
                                 "investor_type": "Growth/Expansion", "holding": "Minority",
                                 "investor_since": None, "participating_rounds": None}
    acquired = parsed(P.parse_company, "company_acquired_10874-98.html")
    assert [i["name"] for i in acquired["investors"]] == ["Capexit", "Carlyle Investment Management", "EQT",
                                                          "Firestartr", "Idinvest Partners"]
    assert acquired["investors"][0]["id"] == "41701-60" and acquired["investors_count"] == 8


def test_a_word_in_the_company_name_does_not_pick_another_faq():
    """'Who are Investors Title’s competitors?' is not the investors question, and
    'When was Acquired Labs founded?' is not the acquisition one."""
    public = P.parse_company(fixture("company_public_11026-45.html").replace("Microsoft", "Investors Title"))
    assert public["name"] == "Investors Title" and public["competitors"][0]["name"] == "Oracle"
    assert public["investors"] is None                        # kept for subscribers: the competitors are no investors
    acquired = P.parse_company(fixture("company_acquired_10874-98.html").replace("Automic Software", "Acquired Labs"))
    assert acquired["acquired_date"] == "2017-09-30"
    assert [i["name"] for i in acquired["investors"]][:2] == ["Capexit", "Carlyle Investment Management"]


def test_one_other_industry_with_a_comma_is_one_industry():
    """The site prints one line per other industry (Microsoft has two): a single one is not split."""
    page = fixture("company_stripe_54782-29.html").replace("Financial Software", "Movies, Music and Entertainment")
    assert P.parse_company(page)["other_industries"] == ["Movies, Music and Entertainment"]
    assert parsed(P.parse_company, "company_public_11026-45.html")["other_industries"] == [
        "Business/Productivity Software", "Systems and Information Management"]


def test_company_acquired():
    c = parsed(P.parse_company, "company_acquired_10874-98.html")
    assert c["status"] == "Acquired/Merged"                   # the page writes a zero-width space after the slash
    assert c["acquirer"] == {"id": "11723-41", "type": "company", "name": "CA Technologies",
                             "link": "https://pitchbook.com/profiles/company/11723-41"}
    assert c["acquired_date"] == "2017-09-30"
    assert c["financing_rounds_count"] == 6 and c["competitors_count"] == 145
    assert c["office"]["country"] == "Austria" and c["office"]["region"] is None
    chef = parsed(P.parse_company, "company_cap_table_43099-57.html")
    assert chef["ownership_status"] == "Acquired/Merged (Operating Subsidiary)"   # a <br> inside the title
    assert chef["parent_company"]["name"] == "Progress Software" and chef["parent_company"]["id"] == "41106-43"
    assert chef["total_raised"] == 105000000


def test_company_cap_table():
    rows = parsed(P.parse_company, "company_cap_table_43099-57.html")["cap_table"]
    assert [r["stock"] for r in rows][:2] == ["Series E", "Series D"]
    assert set(rows[0]) == {"stock", "shares_authorized", "par_value", "dividend_rate_percent",
                            "original_issue_price", "liquidation", "liquidation_preference_multiple",
                            "conversion_price", "currency", "percent_owned"}
    assert all(value is None for key, value in rows[0].items() if key != "stock")     # greyed for visitors


def test_public_company_stock_and_financials():
    c = parsed(P.parse_company, "company_public_11026-45.html")
    assert c["status"] == "Public"
    assert c["stock"] == {"exchange": "NAS", "symbol": "MSFT", "price": 484.52, "previous_close": 498.3,
                          "week_52_low": 349.2, "week_52_high": 559.15, "market_cap": 3600000000000,
                          "shares": 7430000000, "average_volume": 23800000, "eps": 19.21, "currency": "USD",
                          "as_of": "2026-11-20"}
    financials = c["financials"]
    assert financials["currency"] == "USD" and len(financials["periods"]) == 4
    assert financials["periods"][0] == {"period": "TTM", "period_end": "2026-09-30", "ev": 3788737282000,
                                        "revenue": 346445000000, "ebitda": 219871000000,
                                        "net_income": 142631000000, "total_assets": 779403000000,
                                        "total_debt": 57200000000}       # printed in thousands
    assert financials["periods"][1]["period"] == "FY 2026"
    assert c["esg"] == {"risk_rating": 15.86, "risk_level": "Low Risk", "exposure": None, "management": None,
                        "updated": "2026-11-17", "peer_groups": [
                            {"group": "covered_companies", "name": "Global", "rank": None,
                             "companies_count": 13592, "percentile": None},
                            {"group": "industry", "name": "Software & Services", "rank": None,
                             "companies_count": 899, "percentile": None},
                            {"group": "subindustry", "name": "Enterprise and Infrastructure Software", "rank": None,
                             "companies_count": 374, "percentile": None}]}
    assert c["exits_count"] == 195 and c["exits"][0]["name"] == "Protect AI"
    assert c["exits"][0]["exit_date"] == "2024-12-17" and c["exits"][1]["buyers"] == "2 buyers"
    private = parsed(P.parse_company, "company_stripe_54782-29.html")
    assert private["stock"] is None and private["financials"] is None and private["esg"] is None


def test_company_patents_research_news_faqs():
    c = parsed(P.parse_company, "company_stripe_54782-29.html")
    assert c["patents"]["total_documents"] == 1215 and c["patents"]["granted"] == 864 and c["patents"]["pending"] == 164
    assert c["patents"]["total_families"] is None          # greyed
    assert c["patents"]["recent"][0] == {
        "publication_id": "US-20260361757-A1",
        "title": "Systems and methods for controlling computing systems associated with network operations",
        "status": "Pending", "first_filing_date": "2026-07-20", "technology_cpc": None, "citations": None}
    assert c["research"][0]["title"] == "AI Report: Fundraising Surpasses $500 Billion in 2026, a New Record"
    assert c["research"][0]["date"] == "2026-11-04"
    assert c["research"][0]["link"].startswith("https://pitchbook.com/news/reports/")
    news = c["news"][0]
    assert news["date"] == "2026-08-19" and news["category"] == "News" and news["summary"]
    assert news["link"] == "https://pitchbook.com/news/articles/stripes-openrouter-deal-shift-to-ai-plumbing"
    faqs = {f["question"]: f["answer"] for f in c["faqs"]}
    assert faqs["When was Stripe founded?"] == "Stripe was founded in 2010."
    assert faqs["What is Stripe’s current revenue?"] is None      # 'The current revenue for Stripe is .'
    assert faqs["How much funding has Stripe raised over time?"] == "Stripe has raised $9.7B."


def test_sparse_company():
    c = parsed(P.parse_company, "company_sparse_358833-25.html")
    assert c["name"] == "Arlene 's Truck Stop" and c["logo"] is None and c["website"] is None
    assert c["social"] == {"linkedin": None, "twitter": None, "facebook": None}
    assert (c["year_founded"], c["employees"]) == (1967, 35)
    assert c["patents"] is None and c["competitors"] == [] and c["verticals"] == [] and c["news"] == []
    assert c["office"]["city"] == "Battle Creek" and len(c["faqs"]) == 6


# ---- investors ------------------------------------------------------------------------

def test_investor():
    i = parsed(P.parse_investor, "investor_accelerator_57670-21.html")
    assert i["name"] == "Microsoft for Startups" and i["investor_type"] == "Accelerator/Incubator"
    assert i["status"] == "Active" and i["investor_status"] == "Actively Seeking New Investments"
    assert (i["year_founded"], i["professionals_count"]) == (2011, 3)
    assert (i["investments_count"], i["portfolio_count"], i["exits_count"], i["co_investors_count"]) == (1470, 672, 682, 77)
    assert i["website"] == "http://startups.microsoft.com"
    assert i["formerly_known_as"] == ["Bing Fund", "Microsoft Accelerator", "Microsoft ScaleUp", "Microsoft BizSpark"]
    assert len(i["investments"]) == 10 and len(i["exits"]) == 10 and len(i["co_investors"]) == 5
    first = i["investments"][0]
    assert first["name"] == "Aide Chemists" and first["id"] == "528618-61" and first["deal_date"] == "2026-06-28"
    assert first["deal_type"] == "Accelerator/Incubator" and first["deal_size"] is None
    assert first["industry"] == "Other Healthcare Technology Systems" and first["company_stage"] == "Generating Revenue"
    assert i["investments"][1]["deal_type"] is None           # greyed in that row
    assert i["exits"][0]["name"] == "Farmitix" and i["exits"][0]["exit_type"] == "Out of Business"
    assert i["co_investors"][0]["name"] == "Amazon Web Services" and i["co_investors"][0]["deals_together"] == 5


def test_venture_firm():
    i = parsed(P.parse_investor, "investor_vc_11295-73.html")
    assert i["name"] == "Sequoia Capital" and i["primary_investor_type"] == "Venture Capital"
    assert i["other_investor_types"] == ["Growth/Expansion"]
    assert i["trade_associations"] == ["Indian Venture Capital Association (INVCA)",
                                       "National Venture Capital Association (NVCA)"]
    assert i["affiliates"][0]["name"] == "Sequoia Arc" and i["affiliates"][0]["type"] == "investor"
    assert len(i["news"]) == 5 and i["co_investors"][0]["deals_together"] == 74 and i["subsidiaries_count"] == 3


def test_angel_investor():
    i = parsed(P.parse_investor, "investor_angel_226728-91.html")
    assert i["name"] == "Patrick Collison" and i["investor_type"] == "Angel"
    assert i["primary_investor_type"] == "Angel (individual)"
    assert i["status"] is None and i["year_founded"] is None and i["website"] is None and i["logo"] is None
    # the site prints a person's profile as linkedin.com/company/linkedin.com/in/<name>
    assert i["social"]["linkedin"] == "https://www.linkedin.com/in/patrickcollison/"
    assert (i["investments_count"], i["portfolio_count"], i["exits_count"]) == (76, 55, 12)


# ---- funds ----------------------------------------------------------------------------

def test_fund():
    f = parsed(P.parse_fund, "fund_11295-73F.html")
    assert f["id"] == "11295-73F" and f["name"] == "Thomas H. Lee Equity Partners V"
    assert (f["strategy"], f["status"], f["category"], f["vintage"]) == ("Buyout", "Liquidated", "Private Equity", 2000)
    assert (f["size"], f["currency"], f["native_currency"]) == (6110000000, "USD", "USD")
    assert f["dry_powder"] is None and f["open_date"] is None
    assert f["manager"] == {"id": "11316-52", "type": "investor", "name": "Thomas H. Lee Partners",
                            "link": "https://pitchbook.com/profiles/investor/11316-52"}
    assert f["manager_website"] == "https://www.thl.com" and f["domiciles"] == ["United States"]
    assert f["manager_office"]["city"] == "Boston" and f["manager_office"]["postal_code"] == "02110"
    assert (f["investments_count"], f["limited_partners_count"], f["benchmark_funds_count"]) == (21, 134, 32)
    assert f["limited_partners"][0] == {
        "id": "10716-13", "type": "limited_partner", "name": "John Hancock",
        "link": "https://pitchbook.com/profiles/limited-partner/10716-13", "institution_type": None,
        "status": "Former", "commitment": None, "currency": None, "date": "2005-11-30", "commitment_type": "Original"}
    assert f["benchmark_funds"][0]["id"] == "13093-12F" and f["benchmark_funds"][0]["as_of_date"] == "2026-03-31"
    assert len(f["benchmark_funds"]) == 10 and f["investments"][0]["deal_date"] == "2005-03-09"


def test_sparse_fund():
    f = parsed(P.parse_fund, "fund_sparse_27537-40F.html")
    assert f["name"] == "Stripe 100" and f["status"] == "Closed" and f["native_currency"] == "EUR"
    assert f["size"] is None and f["logo"] is None and f["manager_website"] is None
    assert f["manager"] == {"id": None, "type": None, "name": "Waystone Management Company (IE) Limited", "link": None}
    assert f["manager_office"]["country"] == "Ireland"
    assert f["investments"] == [] and f["limited_partners"] == [] and f["benchmark_funds"] == []


# ---- limited partners -----------------------------------------------------------------

def test_limited_partner():
    lp = parsed(P.parse_limited_partner, "limited_partner_pension_11079-46.html")
    assert lp["name"] == "California Public Employees' Retirement System"
    assert (lp["institution_type"], lp["year_founded"], lp["professionals_count"]) == ("Public Pension Fund", 1932, 62)
    assert lp["website"] == "http://www.calpers.ca.gov" and lp["aum"] is None
    assert lp["formerly_known_as"] == ["California State Employees' Retirement System"]
    assert (lp["commitments_count"], lp["mandates_count"]) == (2691, 11)
    # a commitment names a fund (greyed here) and its manager: neither is the row itself
    assert lp["commitments"][0] == {
        "fund": None,
        "fund_manager": {"id": "596487-52", "type": "investor", "name": "Niobrara Capital",
                         "link": "https://pitchbook.com/profiles/investor/596487-52"},
        "fund_location": "New York, NY", "vintage": 2026, "fund_size": None, "commitment_date": None,
        "commitment": None, "currency": None}
    assert lp["mandates"][0] == {"fund_type": "Buyout", "mandate_amount": 500000000, "currency": "USD",
                                 "announced_date": None, "timeframe_start": "2018-06-06",
                                 "timeframe_end": "2018-06-10"}
    assert len(lp["affiliates"]) == 4 and len(lp["news"]) == 5 and len(lp["faqs"]) == 3
    assert lp["subsidiaries_count"] == 4


def test_limited_partner_contact_person_is_masked():
    """The primary contact: the site shows the title and greys the name, the email after two letters
    and the phone after its area code."""
    lp = parsed(P.parse_limited_partner, "limited_partner_10716-13.html")
    assert lp["primary_contact"] == {"name": None, "title": "Chief Financial Officer", "email": None, "phone": None}
    assert lp["is_open_to_secondaries"] is None and lp["commitment_size"] is None
    assert lp["commitments_count"] == 203 and lp["mandates"] == [] and lp["faqs"] == []
    assert lp["affiliates"][0]["type"] == "advisor" and lp["affiliates"][1]["type"] == "limited_partner"


# ---- advisors -------------------------------------------------------------------------

def test_law_firm():
    a = parsed(P.parse_advisor, "advisor_law_firm_10019-98.html")
    assert a["name"] == "Kirkland & Ellis" and a["service_type"] == "Law Firm"
    assert (a["year_founded"], a["employees"]) == (1909, 8153)
    assert a["website"] == "http://www.kirkland.com" and a["social"]["twitter"] == "https://twitter.com/Kirkland_Ellis"
    assert (a["serviced_companies_count"], a["serviced_deals_count"], a["serviced_investors_count"]) == (3126, 3693, 2572)
    assert len(a["company_services"]) == 10 and len(a["buy_side_services"]) == 10 and len(a["sell_side_services"]) == 10
    assert a["company_services"][0] == {
        "id": "185866-84", "type": "company", "name": "IntraBio",
        "link": "https://pitchbook.com/profiles/company/185866-84", "service_provided": "Legal Advisor",
        "deal_date": "2026-11", "deal_type": None, "deal_amount": None, "currency": None}
    assert a["sell_side_services"][0]["name"] == "Speedcast" and a["news"][0]["date"] == "2026-09-11"
    # the totals of the three lists, from their headings ("Service on a Deal — Buy Side (7,909)")
    assert (a["company_services_count"], a["buy_side_services_count"], a["sell_side_services_count"]) == (3699, 7909, 1651)


def test_lender_and_small_advisor():
    lender = parsed(P.parse_advisor, "advisor_lender_10243-45.html")
    assert lender["service_type"] == "Lender" and lender["professionals_count"] == 2602
    assert (lender["financed_companies_count"], lender["financings_count"], lender["co_lenders_count"]) == (81, 91, 166)
    assert lender["company_services"][0]["financing_date"] == "2026-07"
    assert lender["co_lenders"][0] == {
        "id": "62747-92", "type": "advisor", "name": "AB Private Credit Investors",
        "link": "https://pitchbook.com/profiles/advisor/62747-92", "lender_type": "Lender",
        "lender_location": "Austin, TX", "total_shared_financings": 1, "last_shared_financing": None}
    assert lender["office"]["postal_code"] == "M4W 1E5" and lender["website"] is None
    assert lender["company_services_count"] == 138        # "You’re viewing 10 of 138 services to companies"
    small = parsed(P.parse_advisor, "advisor_110600-56.html")
    assert small["description"] is None and small["logo"] is None and small["service_type"] == "Financing Advisory"
    assert small["company_services"][0]["deal_date"] == "2014-06"
    assert small["buy_side_services"][0]["name"] == "IDI Group" and small["co_lenders"] == []


# ---- industries and screeners ---------------------------------------------------------

def test_industry():
    i = parsed(P.parse_industry, "industry_saas.html")
    assert (i["slug"], i["name"], i["link"]) == ("saas", "SaaS", "https://pitchbook.com/profiles/industry/saas")
    assert (i["companies_count"], i["deals_count"], i["investors_count"], i["exits_count"]) == (176387, 433027, 135427, 69948)
    assert i["largest_deal"] is None and i["capital_invested"] is None and i["median_post_valuation"] is None
    assert len(i["companies_to_watch"]) == 10
    assert i["companies_to_watch"][0] == {
        "id": "92115-91", "type": "company", "name": "Superhuman",
        "link": "https://pitchbook.com/profiles/company/92115-91",
        "logo": "https://image.pitchbook.com/JINP1sE6du51p22bKjGx4sX1KWM1791368293325_200x200",
        "last_deal_type": "Series C", "last_post_valuation": None, "currency": None}
    assert i["top_private_companies"][0]["name"] == "OpenAI" and i["top_private_companies"][0]["last_deal_type"] == "IPO"
    microsoft = i["top_public_companies"][0]
    assert (microsoft["name"], microsoft["stock_exchange"], microsoft["stock_symbol"]) == ("Microsoft", "NAS", "MSFT")
    assert microsoft["market_cap"] == 3600000000000 and microsoft["currency"] == "USD"
    assert i["top_investors"][0]["name"] == "Y Combinator" and i["top_investors"][0]["investments_count"] == 5354
    assert len(i["research"]) == 3 and len(i["news"]) == 5 and len(i["faqs"]) == 5
    assert i["description"].startswith("Information technology companies")


def test_screener_of_investors():
    s = parsed(P.parse_screener, "screener_angel_investors.html")
    assert (s["slug"], s["name"]) == ("angel-investors", "Angel Investors")
    assert (s["investors_count"], s["funds_count"], s["companies_count"], s["deals_count"],
            s["limited_partners_count"], s["contacts_count"]) == (129298, 7657, 371057, 698928, 3631, 927745)
    assert [len(s[key]) for key in ("top_investors", "most_active_investors", "top_funds", "top_companies",
                                    "recent_deals", "top_limited_partners")] == [10] * 6
    assert s["top_investors"][0]["rank"] == 1 and s["top_investors"][0]["id"] is None      # printed without a link
    assert s["top_investors"][0]["name"] == "U.S. Department of Health and Human Services"
    assert s["top_investors"][1] == {
        "rank": 2, "id": "40420-36", "type": "investor", "name": "Y Combinator",
        "link": "https://pitchbook.com/profiles/investor/40420-36",
        "logo": "https://image.pitchbook.com/WeD6C1mJ8uvortDkc6UvmG705oN1779094948939_200x200",
        "investments_count": 9838, "last_investment_size": None, "currency": None}
    assert s["top_funds"][0]["vintage"] is None and s["top_funds"][1]["vintage"] == 2021     # '—' is null
    assert s["recent_deals"][1]["deal_date"] == "2027-01-01" and s["top_limited_partners"][1]["commitments_count"] == 2413
    assert s["top_private_companies"] == [] and s["new_companies"] == []


def test_screener_of_companies():
    s = parsed(P.parse_screener, "screener_acquired_ai_companies.html")
    assert s["name"] == "Acquired Artificial Intelligence Companies"
    assert (s["companies_count"], s["deals_count"], s["investors_count"], s["exits_count"]) == (8913, 34071, 29147, 9743)
    assert (s["largest_deal"], s["capital_invested_year_to_date"], s["currency"]) == (250000000000, 1090000000000, "USD")
    assert s["median_post_valuation"] is None
    assert len(s["top_private_companies"]) == 10 and len(s["top_public_companies"]) == 10 and len(s["new_companies"]) == 10
    assert s["new_companies"][0]["year_founded"] == 2026 and s["new_companies"][0]["name"] == "Aegis"
    assert s["top_public_companies"][0]["stock_price"] == 96.91 and s["top_public_companies"][0]["market_cap"] == 1190000000000
    assert list(parsed(P.parse_screener, "screener_angel_investors.html")) == list(s)


# ---- search ---------------------------------------------------------------------------

def test_search_page():
    rows, total_pages = P.parse_search(fixture("search_stripe_page_1.html"))
    assert len(rows) == P.SEARCH_PAGE_SIZE == 15 and total_pages == 8
    assert rows[0] == {"id": "439834-78", "type": "company", "name": "Stripe Theory",
                       "link": "https://pitchbook.com/profiles/company/439834-78",
                       "logo": "https://image.pitchbook.com/llGaQS51jLDbvGoisogvTOq35qI1785304888993_200x200"}
    assert {row["type"] for row in rows} == {"company", "investor"}
    assert any(row["name"] == "Stripe & Stare" for row in rows)         # an entity in a title is unescaped


def test_search_last_page_past_end_and_no_result():
    rows, total_pages = P.parse_search(fixture("search_stripe_last_page_8.html"))
    assert len(rows) == 13 and total_pages == 8
    assert P.parse_search(fixture("search_past_end.html")) == ([], None)
    assert P.parse_search(fixture("search_no_result.html")) == ([], None)


def test_search_single_page_and_missing_logo():
    rows, total_pages = P.parse_search(fixture("search_calpers_one_page.html"))
    assert len(rows) == 15 and total_pages == 1           # no page links: one page
    assert {row["type"] for row in rows} == {"fund", "limited_partner"}
    assert rows[0]["id"] == "12617-74F" and rows[0]["logo"] is None      # the placeholder icon is no logo


# ---- the sitemap ----------------------------------------------------------------------

def test_sitemap_index():
    counts = P.parse_sitemap_index(fixture("sitemap_index.xml"))
    assert counts["company-profiles"] == 75 and counts["fund-profiles"] == 8 and counts["investor-profiles"] == 7
    assert counts["advisor-profiles"] == 5 and counts["limited-partner-profiles"] == 2
    assert counts[refs.INDUSTRY_SITEMAP] == 1 and counts[refs.SCREENER_SITEMAP] == 1
    assert all(prefix in counts for prefix in refs.SITEMAP_PREFIXES.values())


def test_sitemap_profiles():
    rows = P.parse_sitemap_profiles(fixture("sitemap_company_profiles_75_first_200.xml"))
    assert len(rows) == 200
    assert rows[0] == {"id": "549237-43", "type": "company",
                       "link": "https://pitchbook.com/profiles/company/549237-43",
                       "last_modified": "2026-11-11T13:17:55Z"}


def test_sitemap_industries_and_screeners():
    industries = P.parse_sitemap_slugs(fixture("sitemap_industry_profiles.xml"), "industry", refs.industry_link)
    assert len(industries) == 59
    assert industries[0] == {"slug": "3d-printing", "link": "https://pitchbook.com/profiles/industry/3d-printing",
                             "last_modified": "2026-11-21T04:00:00Z"}
    screeners = P.parse_sitemap_slugs(fixture("sitemap_screener_profiles.xml"), "screeners", refs.screener_link)
    assert len(screeners) == 173 and screeners[0]["slug"] == "accredited-investors"
    assert screeners[-1]["link"] == "https://pitchbook.com/profiles/screeners/west-coast-banking-companies"


# ---- references -----------------------------------------------------------------------

@pytest.mark.parametrize("resolver, value, expected", [
    (refs.resolve_company, "54782-29", "54782-29"),
    (refs.resolve_company, " https://pitchbook.com/profiles/company/54782-29?utm=x ", "54782-29"),
    (refs.resolve_company, "pitchbook.com/profiles/company/54782-29", "54782-29"),
    (refs.resolve_company, "/profiles/company/54782-29", "54782-29"),
    (refs.resolve_investor, "https://www.pitchbook.com/profiles/investor/40420-36#investments", "40420-36"),
    (refs.resolve_fund, "11295-73f", "11295-73F"),
    (refs.resolve_fund, "https://pitchbook.com/profiles/fund/11295-73F", "11295-73F"),
    (refs.resolve_limited_partner, "https://pitchbook.com/profiles/limited-partner/11079-46", "11079-46"),
    (refs.resolve_advisor, "10019-98", "10019-98"),
    (refs.resolve_industry, "SaaS", "saas"),
    (refs.resolve_industry, "https://pitchbook.com/profiles/industry/cloudtech-and-devops", "cloudtech-and-devops"),
    (refs.resolve_screener, "https://pitchbook.com/profiles/screeners/angel-investors", "angel-investors"),
])
def test_references_accepted(resolver, value, expected):
    assert resolver(value) == expected


@pytest.mark.parametrize("resolver, value, words", [
    (refs.resolve_company, "stripe", "not a PitchBook company id"),
    (refs.resolve_company, "https://example.com/profiles/company/54782-29", "not a pitchbook.com link"),
    (refs.resolve_company, "https://pitchbook.com/news/articles/x", "not a profile"),
    (refs.resolve_company, "https://pitchbook.com/profiles/investor/40420-36", "/pitchbook/investors/details"),
    (refs.resolve_investor, "https://pitchbook.com/profiles/company/54782-29", "this is a company profile"),
    (refs.resolve_company, "11295-73F", "/pitchbook/funds/details"),
    (refs.resolve_fund, "11295-73", "ends in F"),
    (refs.resolve_company, "https://pitchbook.com/profiles/industry/saas", "industry page"),
    (refs.resolve_industry, "two words", "not a PitchBook industry"),
    (refs.resolve_industry, "https://pitchbook.com/profiles/company/54782-29", "not a PitchBook industry page"),
    (refs.resolve_screener, "https://pitchbook.com/profiles/industry/saas", "not a PitchBook screener page"),
])
def test_references_refused(resolver, value, words):
    with pytest.raises(ValueError) as error:
        resolver(value)
    assert words in str(error.value)


def test_links_found_in_a_page():
    assert refs.entity_of_link("/profiles/limited-partner/10716-13") == {
        "id": "10716-13", "type": "limited_partner", "link": "https://pitchbook.com/profiles/limited-partner/10716-13"}
    assert refs.entity_of_link("/profiles/industry/saas") is None and refs.entity_of_link("/news") is None
    assert refs.vertical_of_link("/profiles/industry/saas") == "saas"
    assert P.page_reference(fixture("company_stripe_54782-29.html")) == ("company", "54782-29")
    assert P.page_reference(fixture("challenge_403.html")) == (None, None)
