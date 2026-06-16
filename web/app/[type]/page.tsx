import Link from "next/link";
import { notFound } from "next/navigation";
import { listEntities, typeCounts } from "@/lib/db";

export default async function TypeListPage({ params }: { params: Promise<{ type: string }> }) {
  const { type } = await params;
  const known = typeCounts().some((r) => r.type === type);
  if (!known) notFound();

  const entities = listEntities(type, 200);

  return (
    <div>
      <Link href="/" className="text-sm text-amber-700 hover:underline">
        ← all types
      </Link>
      <h1 className="text-2xl font-bold mt-2 mb-4">{type}</h1>
      {entities.length === 0 ? (
        <p className="text-stone-500">
          Nothing extracted yet for this type. Run <code>make fetch ARGS=&quot;--type {type}&quot;</code> then{" "}
          <code>make extract</code>.
        </p>
      ) : (
        <ul className="space-y-3">
          {entities.map((e) => (
            <li key={e.url} className="border-b border-stone-200 pb-3">
              <Link href={`/${type}/${e.code}`} className="font-medium text-amber-700 hover:underline">
                {e.title || e.code}
              </Link>
              {e.summary && <p className="text-sm text-stone-600 mt-0.5">{e.summary}</p>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
