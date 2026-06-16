import Database from "better-sqlite3";
import path from "path";

// The scraper (Python, ../src/digitalfire_archive) and this viewer share one
// SQLite file rather than a second copy of the data -- see ../README.md.
const DB_PATH = path.join(process.cwd(), "..", "data", "db", "digitalfire.sqlite");

let _db: Database.Database | null = null;

export function getDb(): Database.Database {
  if (!_db) {
    _db = new Database(DB_PATH, { readonly: true, fileMustExist: true });
  }
  return _db;
}

export type PageRow = {
  url: string;
  type: string;
  code: string | null;
  status: string;
};

export type EntityRow = {
  url: string;
  type: string;
  code: string | null;
  title: string | null;
  summary: string | null;
  body_text: string | null;
  data_json: string;
  raw_export: string | null;
  extracted_at: string;
};

export type ImageRow = {
  id: number;
  entity_url: string;
  src_url: string;
  caption: string | null;
  local_path: string | null;
  picture_page_url: string | null;
};

export type LinkRow = {
  id: number;
  source_url: string;
  target_url: string;
  target_type: string | null;
  label: string | null;
};

export function typeCounts(): { type: string; discovered: number; extracted: number }[] {
  const db = getDb();
  return db
    .prepare(
      `SELECT pages.type AS type,
              COUNT(*) AS discovered,
              SUM(CASE WHEN entities.url IS NOT NULL THEN 1 ELSE 0 END) AS extracted
       FROM pages LEFT JOIN entities ON pages.url = entities.url
       GROUP BY pages.type
       ORDER BY discovered DESC`
    )
    .all() as { type: string; discovered: number; extracted: number }[];
}

export function listEntities(type: string, limit = 100): EntityRow[] {
  const db = getDb();
  return db
    .prepare(`SELECT * FROM entities WHERE type = ? ORDER BY code LIMIT ?`)
    .all(type, limit) as EntityRow[];
}

export function getEntity(type: string, code: string): EntityRow | undefined {
  const db = getDb();
  return db
    .prepare(`SELECT * FROM entities WHERE type = ? AND code = ?`)
    .get(type, code) as EntityRow | undefined;
}

export function getImages(entityUrl: string): ImageRow[] {
  const db = getDb();
  return db.prepare(`SELECT * FROM images WHERE entity_url = ?`).all(entityUrl) as ImageRow[];
}

export function getLinks(entityUrl: string): LinkRow[] {
  const db = getDb();
  return db.prepare(`SELECT * FROM links WHERE source_url = ?`).all(entityUrl) as LinkRow[];
}

export function getPageStatus(url: string): PageRow | undefined {
  const db = getDb();
  return db.prepare(`SELECT url, type, code, status FROM pages WHERE url = ?`).get(url) as
    | PageRow
    | undefined;
}
