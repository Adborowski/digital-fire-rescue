"""SQLite schema + small helpers.

Design goal: ONE schema for all 22 content types on digitalfire.com
(recipe, oxide, material, glossary, article, picture, ...). Pages look
different on the surface, but they all reduce to the same shape:

    a title, a short description, a flexible bag of key/value facts
    (formula/weight for an oxide, materials+grams for a recipe, cone/type
    for a glossary term, ...), free-form notes text, a gallery of images,
    and a set of cross-links to other entries.

So rather than 22 bespoke tables, we have one `entities` table with a
`data_json` blob for the type-specific key/value facts, plus `images` and
`links` tables that every type shares. This is what makes the corpus
queryable and rebuildable later, independent of Tony's original HTML.
"""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS pages (
    url TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    code TEXT,
    lastmod TEXT,
    status TEXT NOT NULL DEFAULT 'pending',   -- pending|fetched|error|skipped
    http_status INTEGER,
    html_path TEXT,
    content_hash TEXT,
    etag TEXT,
    last_modified_header TEXT,
    fetched_at TEXT,
    error TEXT
);

CREATE INDEX IF NOT EXISTS idx_pages_type ON pages(type);
CREATE INDEX IF NOT EXISTS idx_pages_status ON pages(status);

CREATE TABLE IF NOT EXISTS entities (
    url TEXT PRIMARY KEY REFERENCES pages(url),
    type TEXT NOT NULL,
    code TEXT,
    title TEXT,
    summary TEXT,
    body_text TEXT,
    data_json TEXT,        -- type-specific key/value facts, as JSON
    raw_export TEXT,       -- e.g. a recipe's embedded XML/code block, verbatim
    extracted_at TEXT
);

CREATE TABLE IF NOT EXISTS images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_url TEXT NOT NULL REFERENCES entities(url),
    src_url TEXT NOT NULL,
    caption TEXT,
    local_path TEXT,
    picture_page_url TEXT   -- set if the image also has its own /picture/N page
);

CREATE TABLE IF NOT EXISTS links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_url TEXT NOT NULL REFERENCES entities(url),
    target_url TEXT NOT NULL,
    target_type TEXT,
    label TEXT
);
"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


@contextmanager
def cursor():
    conn = connect()
    try:
        cur = conn.cursor()
        yield cur
        conn.commit()
    finally:
        conn.close()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def upsert_page(cur, *, url: str, type_: str, code: str | None, lastmod: str | None) -> None:
    cur.execute(
        """
        INSERT INTO pages (url, type, code, lastmod, status)
        VALUES (?, ?, ?, ?, 'pending')
        ON CONFLICT(url) DO UPDATE SET
            type = excluded.type,
            code = excluded.code,
            lastmod = excluded.lastmod
        """,
        (url, type_, code, lastmod),
    )


def upsert_entity(cur, *, url: str, type_: str, code, title, summary, body_text, data: dict, raw_export) -> None:
    cur.execute(
        """
        INSERT INTO entities (url, type, code, title, summary, body_text, data_json, raw_export, extracted_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(url) DO UPDATE SET
            type = excluded.type,
            code = excluded.code,
            title = excluded.title,
            summary = excluded.summary,
            body_text = excluded.body_text,
            data_json = excluded.data_json,
            raw_export = excluded.raw_export,
            extracted_at = excluded.extracted_at
        """,
        (url, type_, code, title, summary, body_text, json.dumps(data, ensure_ascii=False), raw_export, now_iso()),
    )
