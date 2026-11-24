"""Offline tests for the /pitchbook/* request schemas.

    python -m pytest pitchbook/test_schemas.py -q
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pitchbook import schemas as S  # noqa: E402
from schema_fields import load_query  # noqa: E402


def ok(schema, query):
    data, error = load_query(schema, query)
    assert error is None, error
    return data


def bad(schema, query):
    data, error = load_query(schema, query)
    assert data is None
    return error


# ---- profiles/search ------------------------------------------------------------------

def test_search_accepted():
    assert ok(S.ProfilesSearchSchema, {"query": "  stripe  "}) == {"query": "stripe", "page": 1}
    assert ok(S.ProfilesSearchSchema, {"query": "SAP SE", "page": "34"}) == {"query": "SAP SE", "page": 34}


@pytest.mark.parametrize("query, field", [
    ({}, "query"),
    ({"query": ""}, "query"),                      # the site answers unrelated rows for an empty name
    ({"query": "x" * 201}, "query"),
    ({"query": "stripe", "page": "0"}, "page"),
    ({"query": "stripe", "page": "35"}, "page"),   # the site's search ends at page 34
    ({"query": "stripe", "page": "two"}, "page"),
    ({"query": "stripe", "type": "investor"}, "type"),   # the site ignores it: refused, not unfiltered
    ({"q": "stripe"}, "q"),
])
def test_search_refused(query, field):
    error = bad(S.ProfilesSearchSchema, query)
    assert field in error["errors"] and field in error["error"]


# ---- profiles/list --------------------------------------------------------------------

def test_list_accepted():
    assert ok(S.ProfilesListSchema, {"type": "company"}) == {"type": "company", "page": 1}
    assert ok(S.ProfilesListSchema, {"type": "Limited_Partner", "page": "3"}) == {"type": "limited_partner", "page": 3}
    for kind in ("company", "investor", "fund", "limited_partner", "advisor"):
        assert ok(S.ProfilesListSchema, {"type": kind})["type"] == kind


@pytest.mark.parametrize("query, field", [
    ({}, "type"),
    ({"type": "person"}, "type"),
    ({"type": "industry"}, "type"),
    ({"type": "company", "page": "0"}, "page"),
    ({"type": "company", "page": "2001"}, "page"),
])
def test_list_refused(query, field):
    error = bad(S.ProfilesListSchema, query)
    assert field in error["errors"]
    if query.get("type") == "person":
        assert "company, investor, fund, limited_partner, advisor" in error["error"]


# ---- one record: an id or its link ----------------------------------------------------

@pytest.mark.parametrize("schema, field, value, expected", [
    (S.CompanySchema, "company", "54782-29", "54782-29"),
    (S.CompanySchema, "company", "https://pitchbook.com/profiles/company/54782-29", "54782-29"),
    (S.InvestorSchema, "investor", "https://pitchbook.com/profiles/investor/40420-36?x=1", "40420-36"),
    (S.FundSchema, "fund", "11295-73f", "11295-73F"),
    (S.FundSchema, "fund", "https://pitchbook.com/profiles/fund/11295-73F", "11295-73F"),
    (S.LimitedPartnerSchema, "limited_partner", "https://pitchbook.com/profiles/limited-partner/11079-46", "11079-46"),
    (S.AdvisorSchema, "advisor", "10019-98", "10019-98"),
    (S.IndustrySchema, "industry", "SaaS", "saas"),
    (S.IndustrySchema, "industry", "https://pitchbook.com/profiles/industry/saas", "saas"),
    (S.ScreenerSchema, "screener", "https://pitchbook.com/profiles/screeners/angel-investors", "angel-investors"),
])
def test_record_accepted(schema, field, value, expected):
    assert ok(schema, {field: value}) == {field: expected}


@pytest.mark.parametrize("schema, field, value, words", [
    (S.CompanySchema, "company", "stripe", "not a PitchBook company id"),
    (S.CompanySchema, "company", "https://www.crunchbase.com/organization/stripe", "not a pitchbook.com link"),
    (S.CompanySchema, "company", "https://pitchbook.com/profiles/investor/40420-36", "call /pitchbook/investors/details"),
    (S.CompanySchema, "company", "11295-73F", "call /pitchbook/funds/details"),
    (S.InvestorSchema, "investor", "https://pitchbook.com/profiles/fund/11295-73F", "this is a fund profile"),
    (S.FundSchema, "fund", "11295-73", "a PitchBook fund id ends in F"),
    (S.LimitedPartnerSchema, "limited_partner", "calpers", "not a PitchBook limited partner id"),
    (S.AdvisorSchema, "advisor", "https://pitchbook.com/profiles/company/54782-29", "this endpoint takes an advisor"),
    (S.IndustrySchema, "industry", "software as a service", "not a PitchBook industry"),
    (S.ScreenerSchema, "screener", "https://pitchbook.com/profiles/industry/saas", "not a PitchBook screener page"),
])
def test_record_refused_with_a_message(schema, field, value, words):
    error = bad(schema, {field: value})
    assert words in error["errors"][field][0]
    assert error["error"].startswith(f"Invalid parameters: {field}: ")


@pytest.mark.parametrize("schema, field", [
    (S.CompanySchema, "company"), (S.InvestorSchema, "investor"), (S.FundSchema, "fund"),
    (S.LimitedPartnerSchema, "limited_partner"), (S.AdvisorSchema, "advisor"),
    (S.IndustrySchema, "industry"), (S.ScreenerSchema, "screener"),
])
def test_record_param_is_required_and_alone(schema, field):
    assert field in bad(schema, {})["errors"]
    assert field in bad(schema, {field: ""})["errors"]
    assert "url" in bad(schema, {field: "54782-29", "url": "https://pitchbook.com"})["errors"]
    assert list(schema().fields) == [field]              # one param per input: no id + link pair


def test_an_optional_param_sent_empty_is_the_absent_param():
    """A form or an automation sends every field, the unset ones empty (`page=`)."""
    for empty in ("", "   "):
        assert ok(S.ProfilesSearchSchema, {"query": "stripe", "page": empty}) == {"query": "stripe", "page": 1}
        assert ok(S.ProfilesListSchema, {"type": "company", "page": empty}) == {"type": "company", "page": 1}
    # an option a route adds to a schema (website_contacts_crawl_mode) takes its default as well
    with_option = type("CompanySchema", (S.CompanySchema,), {"mode": S.ChoiceField(["off", "homepage"], load_default="off")})
    assert ok(with_option, {"company": "54782-29", "mode": ""}) == {"company": "54782-29", "mode": "off"}
    # a required param sent empty is still refused
    assert "query" in bad(S.ProfilesSearchSchema, {"query": "", "page": ""})["errors"]
    assert "type" in bad(S.ProfilesListSchema, {"type": "", "page": ""})["errors"]


def test_reference_lists_take_no_param():
    assert ok(S.NoParamsSchema, {}) == {}
    assert "page" in bad(S.NoParamsSchema, {"page": "2"})["errors"]


def test_every_field_is_described():
    for schema in (S.ProfilesSearchSchema, S.ProfilesListSchema, S.CompanySchema, S.InvestorSchema, S.FundSchema,
                   S.LimitedPartnerSchema, S.AdvisorSchema, S.IndustrySchema, S.ScreenerSchema):
        for name, field in schema().fields.items():
            assert field.metadata.get("description"), f"{schema.__name__}.{name}"
