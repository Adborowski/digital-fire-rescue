"""Reconcile the archive against itself: are we actually done, or did
something silently fall through?

Checked, per type: discovered vs fetched vs extracted counts, error pages,
and entities that extracted suspiciously empty (likely a markup variant the
generic extractor didn't handle -- worth eyeballing a sample by hand).
"""
import logging

from . import db

log = logging.getLogger("verify")


def run() -> None:
    with db.cursor() as cur:
        rows = cur.execute(
            """
            SELECT
                pages.type,
                COUNT(*) AS discovered,
                SUM(CASE WHEN pages.status = 'fetched' THEN 1 ELSE 0 END) AS fetched,
                SUM(CASE WHEN pages.status = 'error' THEN 1 ELSE 0 END) AS errored,
                SUM(CASE WHEN pages.status = 'skipped' THEN 1 ELSE 0 END) AS skipped,
                SUM(CASE WHEN entities.url IS NOT NULL THEN 1 ELSE 0 END) AS extracted,
                SUM(CASE WHEN entities.url IS NOT NULL AND (entities.title IS NULL OR entities.title = '')
                         THEN 1 ELSE 0 END) AS empty_title
            FROM pages LEFT JOIN entities ON pages.url = entities.url
            GROUP BY pages.type
            ORDER BY discovered DESC
            """
        ).fetchall()

        error_samples = cur.execute(
            "SELECT url, error FROM pages WHERE status = 'error' LIMIT 20"
        ).fetchall()

    print(f"{'type':14s} {'discov.':>8s} {'fetched':>8s} {'extract':>8s} {'error':>6s} {'skip':>6s} {'empty':>6s}")
    totals = {"discovered": 0, "fetched": 0, "extracted": 0, "errored": 0, "skipped": 0, "empty_title": 0}
    for r in rows:
        print(f"{r['type']:14s} {r['discovered']:8d} {r['fetched'] or 0:8d} {r['extracted'] or 0:8d} "
              f"{r['errored'] or 0:6d} {r['skipped'] or 0:6d} {r['empty_title'] or 0:6d}")
        for k in totals:
            totals[k] += r[k] or (r["discovered"] if k == "discovered" else 0)

    print("\nTOTALS:", totals)
    if error_samples:
        print(f"\nFirst {len(error_samples)} errors:")
        for e in error_samples:
            print(f"  {e['url']}: {e['error']}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    run()
