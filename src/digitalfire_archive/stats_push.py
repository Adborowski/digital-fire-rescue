"""Push a stats snapshot from the SQLite database to Vercel KV.

Called by GitHub Actions after each crawl batch so the Vercel dashboard
stays current. Requires two env vars (set them as repository secrets):
  KV_REST_API_URL   -- from Vercel project → Storage → KV → .env.local
  KV_REST_API_TOKEN -- same place

Safe to run even when those vars are missing -- it just prints stats
to stdout and exits 0, so CI never fails over a missing dashboard push.

Usage:
    PYTHONPATH=src python -m digitalfire_archive.stats_push [--recent N]
"""
import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone

import requests

from . import config, db

log = logging.getLogger("stats_push")

# Accept both Upstash's current names and the old Vercel KV names.
KV_URL   = os.environ.get("UPSTASH_REDIS_REST_URL")   or os.environ.get("KV_REST_API_URL",   "")
KV_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN") or os.environ.get("KV_REST_API_TOKEN", "")


def collect_stats(recent_n: int = 25) -> dict:
    conn = db.connect()
    conn.row_factory = None  # plain tuples for this script

    # Per-type counts
    by_type_rows = conn.execute(
        """SELECT pages.type,
                  COUNT(*) AS discovered,
                  SUM(CASE WHEN pages.status = 'fetched' THEN 1 ELSE 0 END) AS fetched,
                  SUM(CASE WHEN entities.url IS NOT NULL THEN 1 ELSE 0 END) AS extracted,
                  SUM(CASE WHEN pages.status = 'error' THEN 1 ELSE 0 END) AS errors,
                  SUM(CASE WHEN pages.error LIKE 'soft 404%' THEN 1 ELSE 0 END) AS soft404s
           FROM pages LEFT JOIN entities ON pages.url = entities.url
           GROUP BY pages.type
           ORDER BY discovered DESC"""
    ).fetchall()

    by_type = [
        {"type": t, "discovered": d, "fetched": f, "extracted": e, "errors": err, "soft404s": s}
        for t, d, f, e, err, s in by_type_rows
    ]

    totals = {
        "discovered": sum(r["discovered"] for r in by_type),
        "fetched": sum(r["fetched"] for r in by_type),
        "extracted": sum(r["extracted"] for r in by_type),
        "errors": sum(r["errors"] for r in by_type),
        # Source split: read from fetch log if available, else approximate
        "via_live": 0,
        "via_wayback": 0,
    }

    # Approximate live vs wayback split from log file if present
    log_path = config.LOG_DIR / "fetch.log"
    if log_path.exists():
        live, wb = 0, 0
        with open(log_path) as f:
            for line in f:
                if "fetched" in line:
                    if "wayback" in line:
                        wb += 1
                    elif "live/" in line:
                        live += 1
        totals["via_live"] = live
        totals["via_wayback"] = wb

    # Pages-per-hour estimate from recent fetch log entries (last 100 lines)
    pph = None
    if log_path.exists():
        try:
            import subprocess
            tail = subprocess.check_output(["tail", "-n", "200", str(log_path)], text=True)
            lines = [l for l in tail.splitlines() if "fetched" in l and l[:4].isdigit()]
            if len(lines) >= 2:
                # Parse timestamps from "2026-06-16 22:34:42,644 [1/18] fetched ..."
                def parse_ts(line: str) -> float | None:
                    try:
                        return time.mktime(time.strptime(line[:19], "%Y-%m-%d %H:%M:%S"))
                    except Exception:
                        return None
                t0 = parse_ts(lines[0])
                t1 = parse_ts(lines[-1])
                if t0 and t1 and t1 > t0:
                    pph = round(len(lines) / ((t1 - t0) / 3600))
        except Exception:
            pass

    # Estimated completion
    eta = None
    remaining = totals["discovered"] - totals["fetched"] - totals["errors"]
    if pph and pph > 0 and remaining > 0:
        secs = (remaining / pph) * 3600
        eta = datetime.fromtimestamp(time.time() + secs, tz=timezone.utc).isoformat()

    # Most recently fetched pages for the activity feed
    recent_rows = conn.execute(
        """SELECT pages.url, pages.type, pages.status, pages.fetched_at
           FROM pages
           WHERE pages.status IN ('fetched', 'error') AND pages.fetched_at IS NOT NULL
           ORDER BY pages.fetched_at DESC LIMIT ?""",
        (recent_n,),
    ).fetchall()

    def guess_source(url: str, fetched_at: str) -> str:
        # We don't persist source in the DB yet; approximate from log
        return "fetched"

    recent = [
        {"url": url, "type": type_, "status": status, "source": guess_source(url, ts), "ts": ts or ""}
        for url, type_, status, ts in recent_rows
    ]

    return {
        "updated_at": datetime.now(tz=timezone.utc).isoformat(),
        "run_id": os.environ.get("GITHUB_RUN_ID"),
        "totals": totals,
        "by_type": by_type,
        "recent": recent,
        "pages_per_hour": pph,
        "estimated_done_at": eta,
    }


def push_to_kv(stats: dict) -> bool:
    """POST stats to Vercel KV via the Upstash REST API. Returns True on success."""
    if not KV_URL or not KV_TOKEN:
        return False
    payload = [["SET", "df:stats", json.dumps(stats, ensure_ascii=False)]]
    try:
        resp = requests.post(
            f"{KV_URL}/pipeline",
            json=payload,
            headers={"Authorization": f"Bearer {KV_TOKEN}"},
            timeout=15,
        )
        resp.raise_for_status()
        return True
    except requests.RequestException as exc:
        log.warning("KV push failed: %s", exc)
        return False


def run(recent_n: int = 25) -> None:
    db.init_db()
    stats = collect_stats(recent_n=recent_n)
    totals = stats["totals"]
    pct = 100 * totals["fetched"] // totals["discovered"] if totals["discovered"] else 0
    print(
        f"Stats: {totals['fetched']:,}/{totals['discovered']:,} fetched ({pct}%), "
        f"{totals['extracted']:,} extracted, {totals['errors']:,} errors"
    )
    if stats["pages_per_hour"]:
        print(f"       {stats['pages_per_hour']} pages/hour, est. done: {stats['estimated_done_at']}")

    if KV_URL and KV_TOKEN:
        ok = push_to_kv(stats)
        print(f"KV push: {'✓ ok' if ok else '✗ failed (non-fatal)'}")
    else:
        print("KV_REST_API_URL / KV_REST_API_TOKEN not set — printing only, not pushing.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recent", type=int, default=25, help="recent events to include")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    run(recent_n=args.recent)
