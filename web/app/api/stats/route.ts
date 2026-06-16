/**
 * GET /api/stats
 *
 * Returns the current archive stats as JSON.
 *
 * In production (Vercel): reads from Vercel KV, where the GH Actions
 * crawler pushes a snapshot after each batch via stats_push.py.
 *
 * Locally: reads directly from data/db/digitalfire.sqlite via better-sqlite3.
 * No KV setup needed to use the dashboard in development.
 */

import type { ArchiveStats } from "@/lib/stats";

// Revalidate at most every 30 s when deployed (Next.js route segment config).
export const revalidate = 30;

export async function GET(): Promise<Response> {
  let stats: ArchiveStats;

  const kvUrl = process.env.KV_REST_API_URL;
  const kvToken = process.env.KV_REST_API_TOKEN;

  if (kvUrl && kvToken) {
    // Production: read from Vercel KV (Upstash REST API).
    const res = await fetch(`${kvUrl}/get/df:stats`, {
      headers: { Authorization: `Bearer ${kvToken}` },
      next: { revalidate: 30 },
    });
    if (!res.ok) {
      return Response.json({ error: "KV read failed", status: res.status }, { status: 502 });
    }
    const body = await res.json();
    // Upstash REST returns { result: "...jsonstring..." }
    if (!body.result) {
      return Response.json(
        { error: "No stats in KV yet. Run the crawler once to populate.", totals: { discovered: 0, fetched: 0, extracted: 0, errors: 0, via_live: 0, via_wayback: 0 }, by_type: [], recent: [], updated_at: null, run_id: null, pages_per_hour: null, estimated_done_at: null } as ArchiveStats,
        { status: 200 }
      );
    }
    stats = JSON.parse(body.result) as ArchiveStats;
  } else {
    // Local dev: read directly from SQLite.
    const { statsFromDb } = await import("@/lib/stats");
    stats = statsFromDb();
  }

  return Response.json(stats, {
    headers: { "Cache-Control": "s-maxage=30, stale-while-revalidate=60" },
  });
}
