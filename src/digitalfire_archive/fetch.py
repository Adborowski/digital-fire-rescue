"""Polite, resumable fetch of every URL discovered by discover.py.

Defaults to robots.txt's `Crawl-delay: 20`, single-threaded (a delay is a
per-request contract, not a concurrency limit -- running N workers in
parallel each waiting 20s defeats the point). Conditional GETs (ETag /
Last-Modified) mean re-running this after the first pass is cheap: anything
unchanged comes back as a 304 and costs no bandwidth on either end.

Safe to Ctrl-C at any time -- progress is committed to SQLite per page, not
batched, so resuming just picks up wherever `status = 'pending'` left off.
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


def fetch_one(session: requests.Session, row, *, force: bool) -> tuple[str, str]:
    """Returns (status, detail) for logging purposes."""
    headers = {}
    if not force and row["etag"]:
        headers["If-None-Match"] = row["etag"]
    if not force and row["last_modified_header"]:
        headers["If-Modified-Since"] = row["last_modified_header"]

    try:
        resp = session.get(row["url"], headers=headers, timeout=30)
    except requests.RequestException as exc:
        return "error", str(exc)

    with db.cursor() as cur:
        if resp.status_code == 304:
            cur.execute(
                "UPDATE pages SET status='fetched', http_status=304, fetched_at=? WHERE url=?",
                (db.now_iso(), row["url"]),
            )
            return "not-modified", "304"

        if resp.status_code >= 400:
            cur.execute(
                "UPDATE pages SET status='error', http_status=?, error=?, fetched_at=? WHERE url=?",
                (resp.status_code, f"HTTP {resp.status_code}", db.now_iso(), row["url"]),
            )
            return "error", f"HTTP {resp.status_code}"

        path = html_path_for(row["type"], row["code"])
        path.write_bytes(resp.content)
        content_hash = hashlib.sha256(resp.content).hexdigest()
        cur.execute(
            """UPDATE pages SET status='fetched', http_status=?, html_path=?, content_hash=?,
               etag=?, last_modified_header=?, fetched_at=?, error=NULL WHERE url=?""",
            (
                resp.status_code,
                str(path.relative_to(config.ROOT_DIR)),
                content_hash,
                resp.headers.get("ETag"),
                resp.headers.get("Last-Modified"),
                db.now_iso(),
                row["url"],
            ),
        )
        return "fetched", str(path)


def run(*, type_filter: str | None, limit: int | None, delay: float, allow_disallowed: bool, force: bool) -> None:
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

    log.info("%d pages queued (delay=%.1fs)", len(rows), delay)
    counts = {"fetched": 0, "not-modified": 0, "error": 0, "skipped-robots": 0}
    for i, row in enumerate(rows, 1):
        if is_disallowed(row["url"]) and not allow_disallowed:
            with db.cursor() as cur:
                cur.execute(
                    "UPDATE pages SET status='skipped', error='robots.txt disallow' WHERE url=?",
                    (row["url"],),
                )
            counts["skipped-robots"] += 1
            continue
        status, detail = fetch_one(session, row, force=force)
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
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                         handlers=[logging.StreamHandler(),
                                   logging.FileHandler(config.LOG_DIR / "fetch.log")])
    run(type_filter=args.type_filter, limit=args.limit, delay=args.delay,
        allow_disallowed=args.allow_disallowed, force=args.force)
