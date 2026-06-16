"""Project-wide configuration for the digitalfire.com archive scraper.

Everything that might need to change on short notice (rate limit, contact
info, base paths) lives here so the rest of the codebase never hardcodes it.
"""
from pathlib import Path

# --- Identity / politeness -------------------------------------------------
# Update CONTACT_EMAIL if you want a different reply-to address surfaced in
# the User-Agent string. Identifying ourselves clearly is the whole point of
# being a "polite" scraper rather than an anonymous one.
CONTACT_EMAIL = "adborowski@gmail.com"
USER_AGENT = (
    "DigitalfireArchiveBot/1.0 "
    f"(+contact: {CONTACT_EMAIL}; personal, non-commercial preservation "
    "archive of digitalfire.com ahead of its 2026-06-26 shutdown)"
)

# robots.txt for digitalfire.com specifies `Crawl-delay: 20` for the default
# user-agent. This is the safe default. If Tony Hansen grants permission to
# go faster (see outreach/tony_email_draft.md), lower this -- everything
# downstream just reads this one number.
DEFAULT_CRAWL_DELAY_SECONDS = 20.0

BASE_URL = "https://digitalfire.com"
SITEMAP_INDEX_URL = f"{BASE_URL}/sitemapindex.xml"

# --- Storage layout ----------------------------------------------------------
ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT_DIR / "data"
RAW_HTML_DIR = DATA_DIR / "raw_html"
ASSETS_DIR = DATA_DIR / "assets"
DB_PATH = DATA_DIR / "db" / "digitalfire.sqlite"
LOG_DIR = DATA_DIR / "logs"

for d in (RAW_HTML_DIR, ASSETS_DIR, DB_PATH.parent, LOG_DIR):
    d.mkdir(parents=True, exist_ok=True)

# robots.txt also disallows /uploads/ and /videos/ for the default UA. We
# respect that by default (see fetch.py) -- those paths need either an
# explicit go-ahead from Tony or a direct file transfer, not a crawler.
ROBOTS_DISALLOWED_PREFIXES = ("/cgi-bin/", "/videos/", "/uploads/")
