"""Configuration for the PitchBook Scraper. Everything can be set with an environment
variable; the defaults work out of the box.

    PORT              port the API listens on (default 8000)
    PITCHBOOK_PROXY   proxy URL for every request, e.g. http://user:pass@host:port
                      (default: none, requests go out from your own connection)

Works on your own connection for about 10 profile pages a minute. For more, set a residential proxy in `PITCHBOOK_PROXY`.

Everything else below is a plain constant with a working default.
"""
import os

PORT = int(os.environ.get("PORT", "8000"))

PITCHBOOK_PROXY = os.environ.get("PITCHBOOK_PROXY") or None


# ---- what the code reads off config: defaults for a direct run ----
MAX_RETRIES = 3
# PitchBook answers about 15 profile pages a minute per connection, then refuses that connection
# for about ten minutes. Your own connection is kept under that: 10 a minute, and a 10-minute rest
# after a refusal. A rotating proxy needs neither: each new try leaves from another address.
PITCHBOOK_COUNTRY_PER_MINUTE = 0 if PITCHBOOK_PROXY else 10
PITCHBOOK_COUNTRY_REST_S = 0 if PITCHBOOK_PROXY else 600
PITCHBOOK_EXIT = "proxy" if PITCHBOOK_PROXY else None      # the exit every session leaves through: your proxy, or your own connection
PITCHBOOK_EXIT_COUNTRIES = ()
PITCHBOOK_MAX_TRIES = 6 if PITCHBOOK_PROXY else 2
PITCHBOOK_RETRY_PAUSE = 0.5
RETRY_BACKOFF = 2
