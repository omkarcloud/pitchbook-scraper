"""Marshmallow request schemas for every /pitchbook/* route.

ONE param per input: a record is named by its PitchBook id (or, for an
industry and a screener, its name in the link) OR by any pitchbook.com link
of it, in the same param:

    company           54782-29     or https://pitchbook.com/profiles/company/54782-29
    investor          40420-36     or its /profiles/investor/ link
    fund              11295-73F    or its /profiles/fund/ link (a fund id ends in F)
    limited_partner   11079-46     or its /profiles/limited-partner/ link
    advisor           10019-98     or its /profiles/advisor/ link
    industry          saas         or https://pitchbook.com/profiles/industry/saas
    screener          angel-investors   or its /profiles/screeners/ link

A link of another kind of record is refused with the endpoint to call
instead (pitchbook/refs.py).
"""
from marshmallow import missing, pre_load

from pitchbook import refs
from schema_fields import BaseSchema as _SharedBaseSchema
from schema_fields import ChoiceField, PageField, QueryField, RefField

MAX_SEARCH_PAGE = 34        # the site's search ends at page 34 (500 results), whatever the query
MAX_QUERY_LENGTH = 200      # the search box's own limit
MAX_LIST_PAGE = 2000        # /profiles/list: the largest kind (companies) has 1,494 pages of 1,000 today
PROFILE_TYPES = list(refs.SITEMAP_PREFIXES)


class BaseSchema(_SharedBaseSchema):
    """The base of every /pitchbook/* schema."""

    @pre_load
    def empty_is_absent(self, data, **kwargs):
        """An optional param sent empty (`page=`, `website_contacts_crawl_mode=`:
        a form or an automation that sends every field) is the absent param,
        so it takes its default (`page=` was refused as not a valid integer).
        A required param sent empty is still refused."""
        required = {field.data_key or name for name, field in self.fields.items() if field.required}
        return {key: value for key, value in data.items()
                if key in required or not (isinstance(value, str) and not value.strip())}


class CompanyRefField(RefField):
    resolver = staticmethod(refs.resolve_company)


class InvestorRefField(RefField):
    resolver = staticmethod(refs.resolve_investor)


class FundRefField(RefField):
    resolver = staticmethod(refs.resolve_fund)


class LimitedPartnerRefField(RefField):
    resolver = staticmethod(refs.resolve_limited_partner)


class AdvisorRefField(RefField):
    resolver = staticmethod(refs.resolve_advisor)


class IndustryRefField(RefField):
    resolver = staticmethod(refs.resolve_industry)


class ScreenerRefField(RefField):
    resolver = staticmethod(refs.resolve_screener)


class ProfilesSearchSchema(BaseSchema):
    query = QueryField(max_length=MAX_QUERY_LENGTH, metadata={
        "description": "name to search for: a company, investor, fund, limited partner or advisor"})
    page = PageField(max_page=MAX_SEARCH_PAGE, metadata={
        "description": "page of results, 15 a page (1 to 34: PitchBook lists at most 500 results for a name)"})


class ProfilesListSchema(BaseSchema):
    type = ChoiceField(PROFILE_TYPES, required=True, load_default=missing, metadata={
        "description": "kind of profile to list: company, investor, fund, limited_partner or advisor"})
    page = PageField(max_page=MAX_LIST_PAGE, metadata={
        "description": "page of the list, 1,000 profiles a page"})


class CompanySchema(BaseSchema):
    company = CompanyRefField(metadata={
        "description": "PitchBook company id (54782-29), or the company's pitchbook.com link"})


class InvestorSchema(BaseSchema):
    investor = InvestorRefField(metadata={
        "description": "PitchBook investor id (40420-36), or the investor's pitchbook.com link"})


class FundSchema(BaseSchema):
    fund = FundRefField(metadata={
        "description": "PitchBook fund id, which ends in F (11295-73F), or the fund's pitchbook.com link"})


class LimitedPartnerSchema(BaseSchema):
    limited_partner = LimitedPartnerRefField(metadata={
        "description": "PitchBook limited partner id (11079-46), or its pitchbook.com link"})


class AdvisorSchema(BaseSchema):
    advisor = AdvisorRefField(metadata={
        "description": "PitchBook advisor or lender id (10019-98), or its pitchbook.com link"})


class IndustrySchema(BaseSchema):
    industry = IndustryRefField(metadata={
        "description": "industry name as in its link (saas, fintech; see /pitchbook/industries/list), or the page's pitchbook.com link"})


class ScreenerSchema(BaseSchema):
    screener = ScreenerRefField(metadata={
        "description": "screener name as in its link (angel-investors; see /pitchbook/screeners/list), or the page's pitchbook.com link"})


class NoParamsSchema(BaseSchema):
    """An endpoint that takes no parameter (the two reference lists)."""
