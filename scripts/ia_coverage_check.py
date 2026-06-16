#!/usr/bin/env python3
"""Check how many of our discovered URLs have Wayback Machine captures.

Run this before starting the main crawl to understand WB coverage and
decide on the crawl strategy (live-only, WB-only, or mixed).

Usage:
    python scripts/ia_coverage_check.py
    python scripts/ia_coverage_check.py --sample 20   # larger per-type sample
"""
import argparse
import sqlite3
import time
import urllib.parse
import urllib.request
import json
import sys

DB_PATH = "data/db/digitalfire.sqlite"
CDX = "https://web.archive.org/cdx/search/cdx"

TYPES = [
    "recipe", "oxide", "material", "glossary", "article",
    "picture", "test", "hazard", "trouble", "mineral",
    "property", "schedule", "temperature", "video", "typecode",
]


def cdx_check(url: str, timeout: float = 12) -> str | None:
    """Return the most recent WB capture timestamp for url, or None."""
    q = (
        f"{CDX}?url={urllib.parse.quote(url, safe='')}"
        "&output=json&limit=1&fl=timestamp&filter=statuscode:200&fastLatest=true"
    )
    try:
        with urllib.request.urlopen(q, timeout=timeout) as r:
            data = json.loads(r.read())
        return data[1][0] if len(data) > 1 else None
    except Exception:
        return None


def fmt_ts(ts: str) -> str:
    return f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}" if ts and len(ts) >= 8 else "---"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=int, default=10,
                        help="URLs to check per type (default: 10)")
    parser.add_argument("--delay", type=float, default=0.5,
                        help="seconds between CDX API calls (default: 0.5)")
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)
    print(f"\nWayback Machine coverage sample ({args.sample} random URLs per type)\n")
    print(f"{'type':14s} {'total':>8s} {'in IA':>6s} {'est %':>6s}  "
          f"{'oldest cap':11s}  {'newest cap':11s}")
    print("-" * 75)

    grand_total = grand_covered = 0
    for type_ in TYPES:
        rows = conn.execute(
            "SELECT url FROM pages WHERE type=? ORDER BY RANDOM() LIMIT ?",
            (type_, args.sample),
        ).fetchall()
        if not rows:
            continue
        total_for_type = conn.execute(
            "SELECT COUNT(*) FROM pages WHERE type=?", (type_,)
        ).fetchone()[0]

        covered, timestamps = 0, []
        for (url,) in rows:
            ts = cdx_check(url)
            if ts:
                covered += 1
                timestamps.append(ts)
            time.sleep(args.delay)

        pct = 100 * covered // len(rows) if rows else 0
        oldest = fmt_ts(min(timestamps)) if timestamps else "---"
        newest = fmt_ts(max(timestamps)) if timestamps else "---"
        est_covered = int(total_for_type * pct / 100)
        print(
            f"  {type_:12s} {total_for_type:8d} {pct:5d}%  "
            f"~{est_covered:6d}  {oldest:11s}  {newest:11s}"
        )
        grand_total += total_for_type
        grand_covered += est_covered

    print("-" * 75)
    print(f"  {'TOTAL':12s} {grand_total:8d}        ~{grand_covered:6d}")
    print(f"\nEstimated WB coverage: ~{100*grand_covered//grand_total}% of {grand_total} discovered URLs")
    print("\nNote: 'oldest cap' is the oldest capture in the SAMPLE, not necessarily")
    print("the oldest capture in IA's database. IA has captures going back to 1996.")


if __name__ == "__main__":
    main()
