import Link from "next/link";
import { notFound } from "next/navigation";
import { getEntity, getImages, getLinks } from "@/lib/db";
import { TablesSection, RecipeSection } from "@/components/DataView";

export default async function EntityPage({
  params,
}: {
  params: Promise<{ type: string; code: string }>;
}) {
  const { type, code } = await params;
  const entity = getEntity(type, code);
  if (!entity) notFound();

  const data = JSON.parse(entity.data_json) as {
    tables?: Parameters<typeof TablesSection>[0]["tables"];
    recipe?: Parameters<typeof RecipeSection>[0]["recipe"];
  };
  const images = getImages(entity.url);
  const links = getLinks(entity.url);

  const linksByType = links.reduce<Record<string, typeof links>>((acc, l) => {
    const key = l.target_type || "other";
    (acc[key] ??= []).push(l);
    return acc;
  }, {});

  return (
    <div>
      <Link href={`/${type}`} className="text-sm text-amber-700 hover:underline">
        ← {type}
      </Link>
      <h1 className="text-2xl font-bold mt-2">{entity.title || entity.code}</h1>
      {entity.summary && <p className="text-stone-600 mt-1">{entity.summary}</p>}
      <p className="text-xs text-stone-400 mt-1">
        <a href={entity.url} target="_blank" rel="noreferrer" className="hover:underline">
          {entity.url}
        </a>{" "}
        · extracted {entity.extracted_at}
      </p>

      {data.recipe && (
        <section className="mt-6">
          <RecipeSection recipe={data.recipe} />
        </section>
      )}

      {!!data.tables?.length && (
        <section className="mt-6">
          <TablesSection tables={data.tables} />
        </section>
      )}

      {entity.body_text && (
        <section className="mt-6">
          <h2 className="font-semibold text-stone-700 mb-2">Notes</h2>
          <div className="text-sm text-stone-700 space-y-3 max-w-prose whitespace-pre-line">
            {entity.body_text}
          </div>
        </section>
      )}

      {images.length > 0 && (
        <section className="mt-6">
          <h2 className="font-semibold text-stone-700 mb-2">Images ({images.length})</h2>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
            {images.map((img) => (
              <figure key={img.id} className="text-xs">
                {/* eslint-disable-next-line @next/next/no-img-element -- images are on S3, not configured for next/image */}
                <img src={img.src_url} alt={img.caption || ""} className="rounded border border-stone-200 w-full object-cover" />
                {img.caption && <figcaption className="mt-1 text-stone-500">{img.caption}</figcaption>}
              </figure>
            ))}
          </div>
        </section>
      )}

      {!!links.length && (
        <section className="mt-6">
          <h2 className="font-semibold text-stone-700 mb-2">Linked from this page ({links.length})</h2>
          <div className="space-y-2">
            {Object.entries(linksByType).map(([t, ls]) => (
              <div key={t} className="text-sm">
                <span className="text-stone-500">{t}: </span>
                {ls.map((l, i) => {
                  const targetCode = l.target_url.split("/").pop();
                  return (
                    <span key={l.id}>
                      <Link href={`/${t}/${targetCode}`} className="text-amber-700 hover:underline">
                        {l.label || targetCode}
                      </Link>
                      {i < ls.length - 1 && ", "}
                    </span>
                  );
                })}
              </div>
            ))}
          </div>
        </section>
      )}

      {entity.raw_export && (
        <section className="mt-6">
          <h2 className="font-semibold text-stone-700 mb-2">Raw export (embedded on page by Tony&apos;s own site)</h2>
          <pre className="text-xs bg-stone-100 rounded p-3 overflow-auto max-h-64">{entity.raw_export}</pre>
        </section>
      )}
    </div>
  );
}
