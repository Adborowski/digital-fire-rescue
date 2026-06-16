"""Trigger Internet Archive "Save Page Now" captures for every discovered
URL -- a fast, public, redundant safety net that doesn't depend on us
finishing our own crawl in time.

robots.txt explicitly allows `ia_archiver` unrestricted access (including
/uploads/ and /videos/, which our own fetch.py respects as off-limits by
default), so this can legitimately cover ground ours can't without Tony's
sign-off.

Anonymous use of the public /save/<url> endpoint works but is slow and
rate-limited at this scale (11k+ URLs). For a real run, get free API keys
at https://archive.org/account/s3.php and set IA_ACCESS_KEY / IA_SECRET_KEY
-- that switches this to the proper SPN2 API with much higher throughput.
"""
import argparse
import logging
import os
import time

import requests

from . import config, db

log = logging.getLogger("ia_backstop")

SPN2_ENDPOINT = "https://web.archive.org/save"


def run(*, type_filter: str | None, limit: int | None, delay: float) -> dict[str, int]:
    access_key = os.environ.get("IA_ACCESS_KEY")
    secret_key = os.environ.get("IA_SECRET_KEY")
    headers = {"User-Agent": config.USER_AGENT}
    if access_key and secret_key:
        headers["Authorization"] = f"LOW {access_key}:{secret_key}"
        log.info("using authenticated SPN2 API")
    else:
        log.warning("no IA_ACCESS_KEY/IA_SECRET_KEY set -- using slow anonymous endpoint")

    with db.cursor() as cur:
        query = "SELECT url FROM pages"
        params: list = []
        if type_filter:
            query += " WHERE type = ?"
            params.append(type_filter)
        if limit:
            query += f" LIMIT {int(limit)}"
        urls = [r["url"] for r in cur.execute(query, params).fetchall()]

    counts = {"ok": 0, "error": 0}
    log_path = config.LOG_DIR / "ia_captures.jsonl"
    with open(log_path, "a", encoding="utf-8") as logfile:
        for i, url in enumerate(urls, 1):
            try:
                resp = requests.post(f"{SPN2_ENDPOINT}/{url}" if not access_key else SPN2_ENDPOINT,
                                      data={"url": url} if access_key else None,
                                      headers=headers, timeout=30)
                ok = resp.status_code in (200, 201, 302)
                counts["ok" if ok else "error"] += 1
                logfile.write(f'{{"url": {url!r}, "status": {resp.status_code}, "ts": {db.now_iso()!r}}}\n')
                log.info("[%d/%d] %s %s", i, len(urls), resp.status_code, url)
            except requests.RequestException as exc:
                counts["error"] += 1
                log.warning("[%d/%d] failed %s: %s", i, len(urls), url, exc)
            if i < len(urls):
                time.sleep(delay)
    return counts


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--type", dest="type_filter")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--delay", type=float, default=2.0)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    print(run(type_filter=args.type_filter, limit=args.limit, delay=args.delay))
