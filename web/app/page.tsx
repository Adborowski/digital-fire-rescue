import Link from "next/link";
import { typeCounts, hasLocalDb } from "@/lib/db";

export const dynamic = "force-dynamic";

function NoLocalDb() {
  return (
    <div className="text-center py-16 text-stone-500">
      <p className="text-lg font-medium mb-2">Entity browser is a local-only tool.</p>
      <p className="text-sm">It reads the SQLite database that lives next to the scraper on your machine.</p>
      <p className="mt-4 text-sm">
        For remote crawl status, use the{" "}
        <Link href="/dashboard" className="text-amber-700 underline">Live dashboard →</Link>
      </p>
    </div>
  );
}

export default function Home() {
  if (!hasLocalDb()) return <NoLocalDb />;
  const rows = typeCounts();
  const totals = rows.reduce(
    (acc, r) => ({ discovered: acc.discovered + r.discovered, extracted: acc.extracted + r.extracted }),
    { discovered: 0, extracted: 0 }
  );

  return (
    <div>
      <h1 className="text-2xl font-bold mb-1">Archive status</h1>
      <p className="text-stone-500 mb-6">
        {totals.extracted.toLocaleString()} of {totals.discovered.toLocaleString()} discovered pages extracted
        so far.
      </p>
      <table className="w-full text-sm border-collapse">
        <thead>
          <tr className="text-left border-b border-stone-300">
            <th className="py-2">Type</th>
            <th className="py-2 text-right">Discovered</th>
            <th className="py-2 text-right">Extracted</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.type} className="border-b border-stone-200 hover:bg-white">
              <td className="py-2">
                <Link href={`/${r.type}`} className="text-amber-700 hover:underline">
                  {r.type}
                </Link>
              </td>
              <td className="py-2 text-right">{r.discovered.toLocaleString()}</td>
              <td className="py-2 text-right">{r.extracted.toLocaleString()}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
