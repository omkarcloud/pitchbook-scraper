"""Cache TTL per /pitchbook/* endpoint (cache.py, keyed on the validated
params). PitchBook's public previews move slowly: a profile changes when a
deal, a filing or a new headcount lands, and the site rebuilds its sitemap
once a day. A cached answer also saves the scarce thing here, a request
under the site's rate limit.
"""
from datetime import timedelta

# One row per profile (kind + id): the parsed page. A deal table gains a row
# on the day of a deal; a public company's stock line is the last close.
PROFILE_CACHE = timedelta(hours=24)
# Industry and screener pages are aggregates the site recomputes daily.
INDUSTRY_CACHE = timedelta(hours=24)
SCREENER_CACHE = timedelta(hours=24)
# Name search: profiles are added and renamed slowly.
SEARCH_CACHE = timedelta(hours=12)
# The sitemap is rebuilt once a day (its industry file is stamped 04:00 UTC).
SITEMAP_CACHE = timedelta(hours=24)
# One sitemap file (20,000 links) kept parsed in the process, so paging
# through it costs one download.
SITEMAP_FILE_MEMO_SECONDS = 6 * 3600
