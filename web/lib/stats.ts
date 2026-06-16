/**
 * Shared stats types and the function that reads them from SQLite (local)
 * or Vercel KV (production). The crawler pushes these via
 * src/digitalfire_archive/stats_push.py after each batch.
 */

export type TypeStats = {
  type: string;
  discovered: number;
  fetched: number;
  extracted: number;
  errors: number;
  soft404s: number;
};

export type RecentEvent = {
  url: string;
  type: string;
  status: "fetched" | "error";
  source: string; // e.g. "live/200", "wayback/20250312", "error: soft-404"
  ts: string;     // ISO timestamp
};

export type ArchiveStats = {
  updated_at: string | null;
  run_id: string | null;
  totals: {
    discovered: number;
    fetched: number;
    extracted: number;
    errors: number;
    via_live: number;      // approximated from fetch log patterns
    via_wayback: number;
  };
  by_type: TypeStats[];
  recent: RecentEvent[];
  pages_per_hour: number | null;
  estimated_done_at: string | null;
};

/** Build stats directly from the local SQLite database. */
export function statsFromDb(): ArchiveStats {
  // Only import better-sqlite3 at runtime (not in edge runtimes).
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { getDb } = require("./db") as typeof import("./db");
  const db = getDb();

  const byType = db
    .prepare(
      `SELECT
         pages.type,
         COUNT(*) AS discovered,
         SUM(CASE WHEN pages.status = 'fetched' THEN 1 ELSE 0 END) AS fetched,
         SUM(CASE WHEN entities.url IS NOT NULL THEN 1 ELSE 0 END) AS extracted,
         SUM(CASE WHEN pages.status = 'error' THEN 1 ELSE 0 END) AS errors,
         SUM(CASE WHEN pages.error LIKE 'soft 404%' THEN 1 ELSE 0 END) AS soft404s
       FROM pages LEFT JOIN entities ON pages.url = entities.url
       GROUP BY pages.type
       ORDER BY discovered DESC`
    )
    .all() as TypeStats[];

  const totals = byType.reduce(
    (acc, r) => ({
      discovered: acc.discovered + r.discovered,
      fetched: acc.fetched + r.fetched,
      extracted: acc.extracted + r.extracted,
      errors: acc.errors + r.errors,
      via_live: 0,    // SQLite doesn't track source separately yet
      via_wayback: 0,
    }),
    { discovered: 0, fetched: 0, extracted: 0, errors: 0, via_live: 0, via_wayback: 0 }
  );

  return {
    updated_at: new Date().toISOString(),
    run_id: null,
    totals,
    by_type: byType,
    recent: [],
    pages_per_hour: null,
    estimated_done_at: null,
  };
}
