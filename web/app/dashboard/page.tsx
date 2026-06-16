"use client";

import { useEffect, useState, useCallback } from "react";
import type { ArchiveStats, TypeStats } from "@/lib/stats";

const REFRESH_SECONDS = 30;
const TOTAL_URLS = 11431; // known from discovery; update if re-ran

function pct(n: number, total: number) {
  return total > 0 ? Math.round((100 * n) / total) : 0;
}

function Bar({ value, total, color = "bg-amber-500" }: { value: number; total: number; color?: string }) {
  const p = pct(value, total);
  return (
    <div className="w-full bg-stone-200 rounded-full h-2 overflow-hidden">
      <div className={`${color} h-2 rounded-full transition-all duration-700`} style={{ width: `${p}%` }} />
    </div>
  );
}

function BigNumber({ n, label }: { n: number; label: string }) {
  return (
    <div className="text-center">
      <div className="text-3xl font-bold">{n.toLocaleString()}</div>
      <div className="text-xs text-stone-500 mt-0.5">{label}</div>
    </div>
  );
}

function TypeRow({ row }: { row: TypeStats }) {
  const done = row.fetched;
  const p = pct(done, row.discovered);
  return (
    <tr className="border-b border-stone-100 hover:bg-stone-50">
      <td className="py-2 pr-3 text-sm font-medium">{row.type}</td>
      <td className="py-2 pr-3 text-right text-sm text-stone-500 tabular-nums">
        {done.toLocaleString()} / {row.discovered.toLocaleString()}
      </td>
      <td className="py-2 pr-3 text-right text-sm tabular-nums">{p}%</td>
      <td className="py-2 w-36">
        <Bar value={done} total={row.discovered} color={p === 100 ? "bg-green-500" : "bg-amber-500"} />
      </td>
      <td className="py-2 pl-3 text-right text-sm text-red-500 tabular-nums">
        {row.errors > 0 ? row.errors : ""}
      </td>
    </tr>
  );
}

export default function DashboardPage() {
  const [stats, setStats] = useState<ArchiveStats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [countdown, setCountdown] = useState(REFRESH_SECONDS);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch("/api/stats", { cache: "no-store" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setStats(await res.json());
      setError(null);
      setCountdown(REFRESH_SECONDS);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const timer = setInterval(() => {
      setCountdown((c) => {
        if (c <= 1) { load(); return REFRESH_SECONDS; }
        return c - 1;
      });
    }, 1000);
    return () => clearInterval(timer);
  }, [load]);

  const totals = stats?.totals;
  const discovered = totals?.discovered ?? TOTAL_URLS;
  const fetched = totals?.fetched ?? 0;
  const extracted = totals?.extracted ?? 0;
  const errored = totals?.errors ?? 0;
  const overallPct = pct(fetched, discovered);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Live status</h1>
        <div className="flex items-center gap-2 text-sm text-stone-500">
          {loading && <span className="w-2 h-2 rounded-full bg-amber-400 animate-pulse inline-block" />}
          <span>Refreshes in {countdown}s</span>
          <button onClick={load} className="text-amber-700 hover:underline">↻ now</button>
        </div>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 rounded p-3 text-sm">{error}</div>
      )}

      {/* Overall progress */}
      <div className="bg-white border border-stone-200 rounded-lg p-5">
        <div className="flex justify-between items-end mb-2">
          <span className="text-lg font-semibold">
            {fetched.toLocaleString()} of {discovered.toLocaleString()} pages captured
          </span>
          <span className="text-2xl font-bold text-amber-600">{overallPct}%</span>
        </div>
        <Bar value={fetched} total={discovered} color="bg-amber-500" />
        <div className="flex justify-between mt-3">
          <BigNumber n={extracted} label="extracted to DB" />
          <BigNumber n={errored} label="errors" />
          <BigNumber n={discovered - fetched - errored} label="remaining" />
          {stats?.pages_per_hour && <BigNumber n={Math.round(stats.pages_per_hour)} label="pages/hour" />}
        </div>
        {stats?.estimated_done_at && (
          <p className="text-xs text-stone-500 text-center mt-3">
            Est. completion: {new Date(stats.estimated_done_at).toLocaleString()}
          </p>
        )}
      </div>

      {/* Source split */}
      {(totals?.via_live || totals?.via_wayback) ? (
        <div className="bg-white border border-stone-200 rounded-lg p-4 grid grid-cols-2 gap-4 text-sm">
          <div>
            <div className="font-medium mb-1 text-stone-600">From live site</div>
            <div className="text-2xl font-bold">{(totals?.via_live ?? 0).toLocaleString()}</div>
            <div className="text-xs text-stone-400">fresher content</div>
          </div>
          <div>
            <div className="font-medium mb-1 text-stone-600">From Wayback Machine</div>
            <div className="text-2xl font-bold">{(totals?.via_wayback ?? 0).toLocaleString()}</div>
            <div className="text-xs text-stone-400">IA backup when live was down</div>
          </div>
        </div>
      ) : null}

      {/* Per-type breakdown */}
      {stats?.by_type && stats.by_type.length > 0 && (
        <div className="bg-white border border-stone-200 rounded-lg overflow-hidden">
          <div className="px-4 py-3 border-b border-stone-200">
            <h2 className="font-semibold">By content type</h2>
          </div>
          <div className="px-4">
            <table className="w-full">
              <thead>
                <tr className="text-xs text-stone-400 border-b border-stone-200">
                  <th className="text-left py-2 pr-3">Type</th>
                  <th className="text-right py-2 pr-3">Progress</th>
                  <th className="text-right py-2 pr-3">%</th>
                  <th className="py-2 w-36" />
                  <th className="text-right py-2 pl-3">Errors</th>
                </tr>
              </thead>
              <tbody>
                {stats.by_type.map((row) => (
                  <TypeRow key={row.type} row={row} />
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Recent activity */}
      {stats?.recent && stats.recent.length > 0 && (
        <div className="bg-white border border-stone-200 rounded-lg overflow-hidden">
          <div className="px-4 py-3 border-b border-stone-200">
            <h2 className="font-semibold">Recent activity</h2>
          </div>
          <ul className="divide-y divide-stone-100 text-sm font-mono">
            {stats.recent.map((ev, i) => (
              <li key={i} className="px-4 py-1.5 flex items-center gap-3">
                <span className={ev.status === "fetched" ? "text-green-600" : "text-red-500"}>
                  {ev.status === "fetched" ? "✓" : "✗"}
                </span>
                <span className="text-stone-400 text-xs">{ev.source}</span>
                <span className="text-stone-700 truncate">{ev.url.replace("https://digitalfire.com", "")}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Footer */}
      <p className="text-xs text-stone-400 text-center">
        {stats?.updated_at
          ? `Stats last pushed at ${new Date(stats.updated_at).toUTCString()}`
          : "No stats pushed yet — run the crawler once to populate this dashboard."}
        {stats?.run_id && ` · run ${stats.run_id}`}
      </p>
    </div>
  );
}
