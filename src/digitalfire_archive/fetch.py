"""Polite, resumable fetch of every URL discovered by discover.py.

Two modes:
  live (default)  -- fetch directly from digitalfire.com at the robots.txt
                     Crawl-delay: 20 rate. Soft-404s (HTTP 200 with error
                     body) are flagged so they can be re-tried via wayback.
  --via-wayback   -- fetch from the Wayback Machine (web.archive.org) instead,
                     using the most recent successful capture of each URL via
                     the CDX availability API. Use this when the live site is
                     down/degraded. Delay defaults to 3s (polite for IA, far
                     faster than 20s since we're not on Tony's server).

Safe to Ctrl-C at any time -- progress is committed to SQLite per page, not
batched, so resuming just picks up wherever status = 'pending'/'error' left off.
"""
import argparse
import hashlib
import logging
import time
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from . import config, db

log = logging.getLogger("fetch")

# ── Wayback Machine helpers ──────────────────────────────────────────────────
CDX_ENDPOINT = "https://web.archive.org/cdx/search/cdx"
WB_BASE = "https://web.archive.org/web"


def wayback_best_timestamp(session: requests.Session, url: str) -> str | None:
    """Ask the CDX API for the most recent successful capture of *url*."""
    try:
        resp = session.get(
            CDX_ENDPOINT,
            params={"url": url, "output": "json", "limit": "1", "fl": "timestamp",
                    "filter": "statuscode:200", "fastLatest": "true"},
            timeout=15,
        )
        data = resp.json()
        return data[1][0] if len(data) > 1 else None
    except Exception as exc:
        log.warning("CDX lookup failed for %s: %s", url, exc)
        return None


def wayback_url(timestamp: str, original_url: str) -> str:
    # `if_` modifier strips the IA toolbar so we get clean HTML close to the
    # original (no injected JS/banner rewriting URLs), same as Tony served it.
    return f"{WB_BASE}/{timestamp}if_/{original_url}"


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = config.USER_AGENT
    retry = Retry(
        total=4,
        backoff_factor=2,
        status_forcelist=[500, 502, 503, 504],
        respect_retry_after_header=True,
        allowed_methods=["GET"],
    )
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.mount("http://", HTTPAdapter(max_retries=retry))
    return s


def is_disallowed(url: str) -> bool:
    from urllib.parse import urlparse
    path = urlparse(url).path
    return any(path.startswith(p) for p in config.ROBOTS_DISALLOWED_PREFIXES)


def sanitize(name: str) -> str:
    import re
    return re.sub(r"[^A-Za-z0-9_.+-]", "_", name) or "_index"


def html_path_for(type_: str, code: str | None) -> Path:
    d = config.RAW_HTML_DIR / type_
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{sanitize(code or '_index')}.html"


_SOFT_404_MARKERS = (
    b"Operation timed out",
    b"Request Not Recognized",
    b"Error 404",
)


def is_soft_404_response(content: bytes) -> bool:
    """Quick byte-scan for Tony's PHP error responses (HTTP 200 with bad body)."""
    snip = content[:4096]
    return any(m in snip for m in _SOFT_404_MARKERS)


def _try_wayback(session: requests.Session, url: str) -> tuple[bytes | None, str]:
    """Return (content_bytes, detail_string) from the best WB capture, or (None, reason)."""
    ts = wayback_best_timestamp(session, url)
    if not ts:
        return None, "no Wayback capture found"
    wb = wayback_url(ts, url)
    try:
        r = session.get(wb, timeout=30)
        if r.status_code == 200 and not is_soft_404_response(r.content):
            return r.content, f"wayback/{ts}"
        return None, f"wayback returned {r.status_code}"
    except requests.RequestException as exc:
        return None, f"wayback error: {exc}"


def fetch_one(session: requests.Session, row, *, force: bool,
              via_wayback: bool = False, fallback_wayback: bool = False) -> tuple[str, str]:
    """Returns (status, detail) for logging purposes.

    via_wayback    -- skip the live site entirely; go straight to IA.
    fallback_wayback -- try the live site first; if it returns a soft-404 or
                        network error, automatically fall back to IA. This is
                        the recommended default for a site that's intermittently
                        available (live when it's up, IA when it's not).
    """
    headers = {}
    if not via_wayback:
        if not force and row["etag"]:
            headers["If-None-Match"] = row["etag"]
        if not force and row["last_modified_header"]:
            headers["If-Modified-Since"] = row["last_modified_header"]

    content: bytes | None = None
    source: str = ""

    if via_wayback:
        content, source = _try_wayback(session, row["url"])
        if content is None:
            return "error", source
    else:
        try:
            resp = session.get(row["url"], headers=headers, timeout=30)
            if resp.status_code == 304:
                with db.cursor() as cur:
                    cur.execute(
                        "UPDATE pages SET status='fetched', http_status=304, fetched_at=? WHERE url=?",
                        (db.now_iso(), row["url"]),
                    )
                return "not-modified", "304"
            if resp.status_code < 400 and not is_soft_404_response(resp.content):
                content = resp.content
                source = f"live/{resp.status_code}"
            elif fallback_wayback:
                log.debug("live soft-404/error for %s -- trying Wayback", row["url"])
                content, source = _try_wayback(session, row["url"])
                if content is None:
                    return "error", f"live:{resp.status_code} + {source}"
            else:
                with db.cursor() as cur:
                    err = f"soft-404 (HTTP {resp.status_code})" if resp.status_code < 400 else f"HTTP {resp.status_code}"
                    cur.execute(
                        "UPDATE pages SET status='error', http_status=?, error=?, fetched_at=? WHERE url=?",
                        (resp.status_code, err, db.now_iso(), row["url"]),
                    )
                return "error", f"HTTP {resp.status_code}"
        except requests.RequestException as exc:
            if fallback_wayback:
                log.debug("live network error for %s (%s) -- trying Wayback", row["url"], exc)
                content, source = _try_wayback(session, row["url"])
                if content is None:
                    return "error", f"live:{exc} + {source}"
            else:
                return "error", str(exc)

    # We have real content -- save it
    path = html_path_for(row["type"], row["code"])
    path.write_bytes(content)
    content_hash = hashlib.sha256(content).hexdigest()
    with db.cursor() as cur:
        cur.execute(
            """UPDATE pages SET status='fetched', http_status=200, html_path=?, content_hash=?,
               fetched_at=?, error=NULL WHERE url=?""",
            (str(path.relative_to(config.ROOT_DIR)), content_hash, db.now_iso(), row["url"]),
        )
    return "fetched", f"{source} → {path}"


def run(*, type_filter: str | None, limit: int | None, delay: float, allow_disallowed: bool, force: bool,
        max_duration: float | None = None, via_wayback: bool = False, fallback_wayback: bool = False) -> None:
    db.init_db()
    start_time = time.time()
    session = make_session()
    statuses = ("pending", "error") if force else ("pending",)
    with db.cursor() as cur:
        query = f"SELECT * FROM pages WHERE status IN ({','.join('?' * len(statuses))})"
        params = list(statuses)
        if type_filter:
            query += " AND type = ?"
            params.append(type_filter)
        if force:
            query += " UNION SELECT * FROM pages WHERE status='fetched'"
        query += " ORDER BY type, code"
        if limit:
            query += f" LIMIT {int(limit)}"
        rows = cur.execute(query, params).fetchall()

    log.info("%d pages queued (delay=%.1fs, via_wayback=%s)", len(rows), delay, via_wayback)
    counts = {"fetched": 0, "not-modified": 0, "error": 0, "skipped-robots": 0}
    for i, row in enumerate(rows, 1):
        if max_duration and (time.time() - start_time) >= max_duration:
            remaining = len(rows) - i + 1
            log.info("time budget exhausted after %.0fs; %d pages remain (still pending)", time.time() - start_time, remaining)
            break
        if is_disallowed(row["url"]) and not allow_disallowed:
            with db.cursor() as cur:
                cur.execute(
                    "UPDATE pages SET status='skipped', error='robots.txt disallow' WHERE url=?",
                    (row["url"],),
                )
            counts["skipped-robots"] += 1
            continue
        status, detail = fetch_one(session, row, force=force, via_wayback=via_wayback,
                                   fallback_wayback=fallback_wayback)
        counts[status] = counts.get(status, 0) + 1
        log.info("[%d/%d] %-13s %s (%s)", i, len(rows), status, row["url"], detail)
        if i < len(rows):
            time.sleep(delay)
    log.info("done: %s", counts)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--type", dest="type_filter", help="only fetch this content type")
    parser.add_argument("--limit", type=int, help="max pages to fetch this run")
    parser.add_argument("--delay", type=float, default=config.DEFAULT_CRAWL_DELAY_SECONDS,
                         help="seconds between requests (default: robots.txt crawl-delay)")
    parser.add_argument("--allow-disallowed", action="store_true",
                         help="also fetch /uploads/ /videos/ /cgi-bin/ -- only use with Tony's OK")
    parser.add_argument("--force", action="store_true", help="refetch even already-fetched pages")
    parser.add_argument("--max-duration", type=float, default=None,
                         help="stop gracefully after N seconds (for GitHub Actions time-boxed runs)")
    parser.add_argument("--via-wayback", action="store_true",
                         help="fetch from web.archive.org instead of the live site (use when digitalfire.com is down/degraded)")
    parser.add_argument("--fallback-wayback", action="store_true",
                         help="try live first; if soft-404 or network error, fall back to web.archive.org automatically (recommended default)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                         handlers=[logging.StreamHandler(),
                                   logging.FileHandler(config.LOG_DIR / "fetch.log")])
    run(type_filter=args.type_filter, limit=args.limit, delay=args.delay,
        allow_disallowed=args.allow_disallowed, force=args.force, max_duration=args.max_duration,
        via_wayback=args.via_wayback, fallback_wayback=args.fallback_wayback)
