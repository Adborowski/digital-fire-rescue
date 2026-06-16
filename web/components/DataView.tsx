// Renders whatever shape extract.py put in entities.data_json -- see
// ../../src/digitalfire_archive/extract.py. There's no fixed per-type
// schema by design, so this renders generically:
//   - a {label: value} object -> a definition list
//   - a {rows: string[][]} object -> a plain table
//   - the recipe-specific {name, keywords, lines: [...]} block -> its own
//     small ingredients table, since it's the one truly structured,
//     verbatim-from-source block we have (see the embedded XML in
//     extract.py's extract_recipe_xml)

type TableBlock = { heading: string | null; rows?: string[][]; [key: string]: unknown };
type RecipeBlock = {
  name?: string;
  keywords?: string;
  codenum?: string;
  date?: string;
  lines: { material: string; amount: string }[];
};

function KeyValueTable({ entries }: { entries: [string, unknown][] }) {
  return (
    <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 text-sm">
      {entries.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-stone-500">{k}</dt>
          <dd>{String(v)}</dd>
        </div>
      ))}
    </dl>
  );
}

function RowsTable({ rows }: { rows: string[][] }) {
  return (
    <table className="text-sm border-collapse w-full">
      <tbody>
        {rows.map((row, i) => (
          <tr key={i} className="border-b border-stone-100 last:border-0">
            {row.map((cell, j) => (
              <td key={j} className="py-1 pr-4 align-top">
                {cell}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function TablesSection({ tables }: { tables: TableBlock[] }) {
  if (!tables?.length) return null;
  return (
    <div className="space-y-6">
      {tables.map((t, i) => {
        const { heading, rows, ...kv } = t;
        const entries = Object.entries(kv);
        return (
          <div key={i}>
            {heading && <h3 className="font-semibold text-stone-700 mb-1">{heading}</h3>}
            {rows ? <RowsTable rows={rows} /> : <KeyValueTable entries={entries} />}
          </div>
        );
      })}
    </div>
  );
}

export function RecipeSection({ recipe }: { recipe: RecipeBlock }) {
  return (
    <div>
      <h3 className="font-semibold text-stone-700 mb-1">Ingredients (from embedded recipe export)</h3>
      <table className="text-sm border-collapse w-full max-w-sm">
        <tbody>
          {recipe.lines.map((line, i) => (
            <tr key={i} className="border-b border-stone-100">
              <td className="py-1 pr-4">{line.material}</td>
              <td className="py-1 text-right font-mono">{line.amount}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
