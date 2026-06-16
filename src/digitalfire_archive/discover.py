"""Discovery: turn digitalfire.com's own sitemap index into a complete,
exact URL inventory -- no guessing, no BFS crawling needed.

https://digitalfire.com/sitemapindex.xml lists 22ish per-type sitemaps
(sitemap-recipe.xml, sitemap-oxide.xml, ...). Each one is a flat list of
<url><loc> entries. We fetch the index, then each sub-sitemap, classify
every URL by its /<type>/ path prefix, and upsert into `pages`.

This step is cheap (~23 small XML requests total) and safe to re-run any
time -- it's how we'll also notice if Tony adds/changes anything before
the shutdown.
"""
import logging
import re
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from . import config, db

log = logging.getLogger("discover")

KNOWN_TYPES = {
    "oxide", "material", "recipe", "glossary", "article", "hazard",
    "mineral", "property", "schedule", "temperature", "trouble", "test",
    "video", "picture", "typecode", "project", "url", "consultants",
    "schools", "stores", "potterytony",
}

# Tony's sitemap generator has a couple of known bugs we work around rather
# than report as "missing content":
#   - some sitemaps (e.g. sitemap-video.xml) point at "digitlfire.com"
#     (missing the second 'a') instead of digitalfire.com.
#   - sitemap-video.xml's <loc> is flat-out wrong for most entries -- it
#     repeats the <lastmod> date string instead of a real URL.
_TYPO_DOMAIN_RE = re.compile(r"^https?://digitlfire\.com", re.IGNORECASE)
_DATE_LIKE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T")


def normalize_url(url: str) -> str:
    url = url.strip()
    url = re.sub(r"^http://", "https://", url)
    url = _TYPO_DOMAIN_RE.sub("https://digitalfire.com", url)
    return url


def _get(url: str) -> requests.Response:
    resp = requests.get(url, headers={"User-Agent": config.USER_AGENT}, timeout=30)
    resp.raise_for_status()
    return resp


def fetch_sitemap_list() -> list[str]:
    """Return the deduped list of https://digitalfire.com/... sitemap URLs."""
    resp = _get(config.SITEMAP_INDEX_URL)
    soup = BeautifulSoup(resp.content, "xml")
    urls = [normalize_url(loc.text) for loc in soup.find_all("loc")]

    seen, deduped = set(), []
    for u in urls:
        if u.startswith(config.BASE_URL) and u not in seen:
            seen.add(u)
            deduped.append(u)
    return deduped


def classify(url: str) -> tuple[str, str | None]:
    """Map a content URL to (type, code) from its path, e.g.
    https://digitalfire.com/recipe/g1214w -> ("recipe", "g1214w")."""
    path = urlparse(url).path.strip("/")
    parts = path.split("/", 1)
    type_ = parts[0] if parts else "misc"
    code = parts[1] if len(parts) > 1 else None
    if type_ not in KNOWN_TYPES:
        type_ = "misc"
    return type_, code


def discover_via_list_page(type_: str) -> set[str]:
    """Fallback/cross-check: scrape https://digitalfire.com/<type>/list for
    real links. Some sitemaps (video, url) are buggy at the source; this
    catches what they miss. For types whose /list page is itself a JS
    search widget (e.g. material) this just yields a small subset -- that's
    fine, the sitemap is already trusted as primary for those."""
    try:
        resp = _get(f"{config.BASE_URL}/{type_}/list")
    except requests.RequestException as exc:
        log.warning("no /%s/list fallback available: %s", type_, exc)
        return set()
    soup = BeautifulSoup(resp.content, "lxml")
    found = set()
    for a in soup.find_all("a", href=True):
        href = normalize_url(a["href"]) if a["href"].startswith("http") else f"{config.BASE_URL}{a['href']}"
        t, code = classify(href)
        if t == type_ and code and code != "list" and not _DATE_LIKE_RE.match(code):
            found.add(href)
    return found


def run() -> dict[str, dict[str, int]]:
    db.init_db()
    sitemap_urls = fetch_sitemap_list()
    log.info("found %d sitemaps", len(sitemap_urls))

    from_sitemap: dict[str, dict[str, str | None]] = {}
    skipped_malformed = 0
    for sm_url in sitemap_urls:
        resp = _get(sm_url)
        soup = BeautifulSoup(resp.content, "xml")
        entries = soup.find_all("url")
        log.info("%s -> %d urls", sm_url, len(entries))
        for entry in entries:
            loc = entry.find("loc")
            if not loc:
                continue
            page_url = normalize_url(loc.text)
            type_, code = classify(page_url)
            # sitemap-video.xml repeats <lastmod> as <loc> for most entries --
            # that's not a recoverable URL, so drop it rather than store junk.
            if not page_url.startswith("https://digitalfire.com/") or not code or _DATE_LIKE_RE.match(code):
                skipped_malformed += 1
                continue
            lastmod_tag = entry.find("lastmod")
            lastmod = lastmod_tag.text.strip() if lastmod_tag else None
            from_sitemap.setdefault(type_, {})[page_url] = lastmod
    if skipped_malformed:
        log.warning("skipped %d malformed <loc> entries from sitemaps", skipped_malformed)

    report: dict[str, dict[str, int]] = {}
    with db.cursor() as cur:
        for type_ in KNOWN_TYPES | set(from_sitemap):
            sitemap_map = from_sitemap.get(type_, {})
            list_set = discover_via_list_page(type_)
            merged = set(sitemap_map) | list_set
            for page_url in merged:
                _, code = classify(page_url)
                db.upsert_page(cur, url=page_url, type_=type_, code=code, lastmod=sitemap_map.get(page_url))
            if merged:
                report[type_] = {
                    "sitemap": len(sitemap_map),
                    "list_page": len(list_set),
                    "merged": len(merged),
                    "only_in_list_page": len(list_set - set(sitemap_map)),
                }
    return report


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    result = run()
    total = sum(r["merged"] for r in result.values())
    print(f"\nDiscovered {total} URLs across {len(result)} types:")
    print(f"  {'type':14s} {'sitemap':>8s} {'/list':>8s} {'merged':>8s} {'list-only':>10s}")
    for type_, r in sorted(result.items(), key=lambda kv: -kv[1]["merged"]):
        flag = "  <- check" if r["only_in_list_page"] else ""
        print(f"  {type_:14s} {r['sitemap']:8d} {r['list_page']:8d} {r['merged']:8d} {r['only_in_list_page']:10d}{flag}")
