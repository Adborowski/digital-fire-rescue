/**
 * GET /api/stats
 *
 * Returns the current archive stats as JSON.
 *
 * Production (Vercel + Upstash Redis): reads from Redis, where the
 * GH Actions crawler pushes a snapshot via stats_push.py after each batch.
 * Set up via: Vercel dashboard → Storage → Upstash → Redis → Connect.
 * The two env vars Upstash injects (UPSTASH_REDIS_REST_URL and
 * UPSTASH_REDIS_REST_TOKEN) are all this needs.
 *
 * Local dev: reads directly from data/db/digitalfire.sqlite.
 * No Redis setup needed.
 */

import type { ArchiveStats } from "@/lib/stats";

// Never prerender this route at build time — it reads from Redis (prod) or
// a local SQLite file (dev), neither of which exists at build time on Vercel.
export const dynamic = "force-dynamic";

// Accept both Upstash's current env var names AND the old Vercel KV names
// so the code works regardless of which integration you used.
function redisConfig() {
  return {
    url:   process.env.UPSTASH_REDIS_REST_URL   ?? process.env.KV_REST_API_URL   ?? "",
    token: process.env.UPSTASH_REDIS_REST_TOKEN ?? process.env.KV_REST_API_TOKEN ?? "",
  };
}

const EMPTY: ArchiveStats = {
  updated_at: null,
  run_id: null,
  totals: { discovered: 0, fetched: 0, extracted: 0, errors: 0, via_live: 0, via_wayback: 0 },
  by_type: [],
  recent: [],
  pages_per_hour: null,
  estimated_done_at: null,
};

export async function GET(): Promise<Response> {
  const { url, token } = redisConfig();

  if (url && token) {
    // Production: Upstash Redis REST API.
    // GET https://<url>/get/<key>  →  { result: "...json..." | null }
    const res = await fetch(`${url}/get/df:stats`, {
      headers: { Authorization: `Bearer ${token}` },
      next: { revalidate: 30 },
    });

    if (!res.ok) {
      return Response.json(
        { ...EMPTY, error: `Redis read failed (HTTP ${res.status})` },
        { status: 502 }
      );
    }

    const body = (await res.json()) as { result: string | null };

    if (!body.result) {
      // Nothing pushed yet — return zeros so the dashboard renders.
      return Response.json(EMPTY);
    }

    const stats = JSON.parse(body.result) as ArchiveStats;
    return Response.json(stats, {
      headers: { "Cache-Control": "s-maxage=30, stale-while-revalidate=60" },
    });
  }

  // Local dev: read from SQLite.
  const { statsFromDb } = await import("@/lib/stats");
  return Response.json(statsFromDb());
}
