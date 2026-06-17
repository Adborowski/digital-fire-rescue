"""Per-page pipeline: fetch → extract → assets → checkpoint.

Replaces running fetch / extract / assets as three separate passes.
After every `--checkpoint-every` pages the SQLite DB is uploaded to the
GitHub Release so a job cancellation never loses more than that many pages
of work.  The dashboard (KV) is also updated at the same cadence.

Usage (GitHub Actions):
    PYTHONPATH=src python -m digitalfire_archive.pipeline \\
        --fallback-wayback --delay 20 --max-duration 3000 --checkpoint-every 100

Usage (local, no GH Release / KV):
    PYTHONPATH=src python -m digitalfire_archive.pipeline --limit 10 --delay 5
"""
import argparse
import logging
import os
import subprocess
import time

import requests
from bs4 import BeautifulSoup

from . import config, db, extract, fetch as fetch_mod, assets as assets_mod
from .stats_push import collect_stats, push_to_kv

log = logging.getLogger("pipeline")


def _save_db_checkpoint() -> bool:
    """Upload just the SQLite file to the GitHub Release.

    Requires the gh CLI and GH_TOKEN / GITHUB_TOKEN env var, both of which
    are present in GitHub Actions. Returns True on success, False otherwise
    (non-fatal -- the crawl continues without the checkpoint).
    """
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        log.debug("no GH_TOKEN -- skipping DB checkpoint")
        return False
    try:
        result = subprocess.run(
            ["gh", "release", "upload", "archive",
             str(config.DB_PATH), "--clobber"],
            capture_output=True, text=True, timeout=90,
            env={**os.environ, "GH_TOKEN": token},
        )
        if result.returncode == 0:
            log.info("DB checkpoint saved to GitHub Release")
            return True
        log.warning("DB checkpoint failed: %s", result.stderr.strip())
        return False
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        log.warning("DB checkpoint skipped (%s)", exc)
        return False


def _push_dashboard() -> None:
    """Push stats to Vercel KV dashboard (non-fatal if credentials missing)."""
    from .stats_push import KV_URL, KV_TOKEN
    if not KV_URL or not KV_TOKEN:
        return
    try:
        stats = collect_stats(recent_n=25)
        push_to_kv(stats)
    except Exception as exc:
        log.warning("dashboard push failed (non-fatal): %s", exc)


def run(
    *,
    limit: int | None,
    type_filter: str | None = None,
    delay: float,
    fallback_wayback: bool,
    via_wayback: bool,
    max_duration: float | None,
    checkpoint_every: int,
    allow_disallowed: bool,
) -> dict[str, int]:
    db.init_db()
    start_time = time.time()
    session = fetch_mod.make_session()
    asset_session = requests.Session()
    asset_session.headers["User-Agent"] = config.USER_AGENT

    with db.cursor() as cur:
        query = "SELECT * FROM pages WHERE status = 'pending'"
        params: list = []
        if type_filter:
            query += " AND type = ?"
            params.append(type_filter)
        query += " ORDER BY type, code"
        if limit:
            query += f" LIMIT {int(limit)}"
        rows = cur.execute(query, params).fetchall()

    log.info("%d pending pages queued", len(rows))
    counts = {"fetched": 0, "extracted": 0, "assets": 0, "errors": 0}

    for i, row in enumerate(rows, 1):
        if max_duration and (time.time() - start_time) >= max_duration:
            remaining = len(rows) - i + 1
            log.info("time budget exhausted; %d pages remain (still pending)", remaining)
            break

        if fetch_mod.is_disallowed(row["url"]) and not allow_disallowed:
            with db.cursor() as cur:
                cur.execute(
                    "UPDATE pages SET status='skipped', error='robots.txt disallow' WHERE url=?",
                    (row["url"],),
                )
            continue

        # ── Step 1: Fetch ────────────────────────────────────────────────────
        status, detail = fetch_mod.fetch_one(
            session, row, force=False,
            via_wayback=via_wayback, fallback_wayback=fallback_wayback,
        )
        log.info("[%d/%d] %-12s %s (%s)", i, len(rows), status, row["url"], detail)

        if status != "fetched":
            counts["errors"] += 1
            if i < len(rows):
                time.sleep(delay)
            continue
        counts["fetched"] += 1

        # Re-read the row to get the html_path written by fetch_one
        with db.cursor() as cur:
            updated = cur.execute(
                "SELECT * FROM pages WHERE url=?", (row["url"],)
            ).fetchone()

        # ── Step 2: Extract ──────────────────────────────────────────────────
        if updated and updated["html_path"]:
            html_path = config.ROOT_DIR / updated["html_path"]
            try:
                html = html_path.read_text(encoding="utf-8", errors="replace")
                soup = BeautifulSoup(html, "lxml")
                if extract.is_soft_404(soup):
                    log.warning("soft 404 body: %s", row["url"])
                    with db.cursor() as cur:
                        cur.execute(
                            "UPDATE pages SET status='error', "
                            "error='soft 404 - HTTP 200 but error body' WHERE url=?",
                            (row["url"],),
                        )
                    counts["errors"] += 1
                else:
                    result = extract.extract_one(html)
                    with db.cursor() as cur:
                        extract.save_extraction(cur, row["url"], row["type"], row["code"], result)
                    counts["extracted"] += 1

                    # ── Step 3: Assets ───────────────────────────────────────
                    downloaded = assets_mod.download_for_entity(
                        row["url"], asset_session, delay=0.3
                    )
                    counts["assets"] += downloaded

            except Exception as exc:
                log.warning("extract/assets error for %s: %s", row["url"], exc)

        # ── Checkpoint every N pages ─────────────────────────────────────────
        if counts["fetched"] > 0 and counts["fetched"] % checkpoint_every == 0:
            log.info("checkpoint at %d pages fetched", counts["fetched"])
            _save_db_checkpoint()
            _push_dashboard()

        if i < len(rows):
            time.sleep(delay)

    # Final checkpoint and dashboard push
    log.info("pipeline done: %s", counts)
    _save_db_checkpoint()
    _push_dashboard()
    return counts


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--type", dest="type_filter", help="only process this content type")
    parser.add_argument("--delay", type=float, default=config.DEFAULT_CRAWL_DELAY_SECONDS)
    parser.add_argument("--max-duration", type=float, default=None,
                        help="stop gracefully after N seconds")
    parser.add_argument("--checkpoint-every", type=int, default=100,
                        help="upload DB to GitHub Release every N pages (default 100)")
    parser.add_argument("--fallback-wayback", action="store_true",
                        help="try live first, fall back to Wayback on soft-404/error")
    parser.add_argument("--via-wayback", action="store_true",
                        help="skip live entirely, always use Wayback Machine")
    parser.add_argument("--allow-disallowed", action="store_true",
                        help="also fetch /uploads/ etc (only with Tony's OK)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(config.LOG_DIR / "pipeline.log"),
        ],
    )
    run(
        limit=args.limit,
        type_filter=args.type_filter,
        delay=args.delay,
        fallback_wayback=args.fallback_wayback,
        via_wayback=args.via_wayback,
        max_duration=args.max_duration,
        checkpoint_every=args.checkpoint_every,
        allow_disallowed=args.allow_disallowed,
    )
