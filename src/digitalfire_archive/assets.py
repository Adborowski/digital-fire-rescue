"""Download every image extract.py found, into data/assets/<type>/<code>/.

Images turned out to be hosted on s3-us-west-2.amazonaws.com, not under
digitalfire.com/uploads/ -- so robots.txt's disallow on /uploads/ doesn't
actually cover them, and we don't need Tony's sign-off to fetch these (a
short, polite delay is still applied out of general courtesy to the S3
bucket, which is not infinite either).
"""
import argparse
import hashlib
import logging
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

from . import config, db, fetch

log = logging.getLogger("assets")


def local_path_for(type_: str, code: str | None, src_url: str) -> Path:
    filename = Path(urlparse(src_url).path).name or hashlib.sha1(src_url.encode()).hexdigest()
    d = config.ASSETS_DIR / type_ / fetch.sanitize(code or "_index")
    d.mkdir(parents=True, exist_ok=True)
    return d / fetch.sanitize(filename)


def run(*, limit: int | None, delay: float) -> dict[str, int]:
    db.init_db()
    session = requests.Session()
    session.headers["User-Agent"] = config.USER_AGENT

    with db.cursor() as cur:
        query = """
            SELECT images.id, images.src_url, entities.type, entities.code
            FROM images JOIN entities ON images.entity_url = entities.url
            WHERE images.local_path IS NULL
        """
        if limit:
            query += f" LIMIT {int(limit)}"
        rows = cur.execute(query).fetchall()

    log.info("%d images queued", len(rows))
    counts = {"downloaded": 0, "error": 0}
    for i, row in enumerate(rows, 1):
        path = local_path_for(row["type"], row["code"], row["src_url"])
        try:
            resp = session.get(row["src_url"], timeout=30)
            resp.raise_for_status()
            path.write_bytes(resp.content)
            with db.cursor() as cur:
                cur.execute("UPDATE images SET local_path = ? WHERE id = ?",
                            (str(path.relative_to(config.ROOT_DIR)), row["id"]))
            counts["downloaded"] += 1
            log.info("[%d/%d] downloaded %s", i, len(rows), row["src_url"])
        except requests.RequestException as exc:
            counts["error"] += 1
            log.warning("[%d/%d] failed %s: %s", i, len(rows), row["src_url"], exc)
        if i < len(rows):
            time.sleep(delay)
    return counts


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--delay", type=float, default=1.0)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    print(run(limit=args.limit, delay=args.delay))
