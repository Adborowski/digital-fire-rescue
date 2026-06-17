"""Raw HTML -> the universal schema (title/summary/body_text/data_json/raw_export
+ images + links -- see db.py).

The site's markup is consistent enough across all 22 types that one
generic parser handles all of them, rather than 22 bespoke ones:

  - title:   <h1>, falling back to <title>
  - summary: <meta name="description">
  - data:    the table right after a "Data" heading -> {label: value}
             (falls back to a raw row list for tables that aren't a clean
             2-column shape, e.g. material chemistry grids)
  - body:    every <p> in the page, minus nav/footer/donate boilerplate
  - images:  every content <img>, with its nearest caption-ish heading/alt
             text, and its /picture/N detail page if linked
  - links:   every <a href> pointing at another digitalfire.com entity
             (oxide/material/recipe/glossary/...), deduped

One genuine special case: recipe (and possibly other) pages embed a
`<pre id="xmlContent">` block -- Tony's own Insight-Live export format. It's
strictly better structured data than anything we'd get by scraping the
ingredients table, so when present we keep it verbatim as `raw_export` and
also parse it into `data_json["recipe"]`.
"""
import argparse
import logging
from xml.etree import ElementTree as ET

from bs4 import BeautifulSoup

from . import config, db
from .discover import KNOWN_TYPES, classify

log = logging.getLogger("extract")

SHUTDOWN_BANNER_PREFIX = "Digitalfire will shut down"
BOILERPLATE_MARKERS = ("PayPal", "Follow me on", "Ko-fi")
SKIP_IMG_MARKERS = ("PayPalDonate", "skulllogo", "ReferenceLibrary", "favicon")


def parse_data_table(table) -> dict:
    rows_text = []
    kv = {}
    for tr in table.find_all("tr"):
        cells = tr.find_all(["th", "td"])
        texts = [c.get_text(" ", strip=True) for c in cells]
        if any(texts):
            rows_text.append(texts)
        if len(cells) == 2 and texts[0]:
            kv[texts[0]] = texts[1]
    if rows_text and len(kv) == len(rows_text):
        return kv
    return {"rows": rows_text}


def extract_title(soup) -> str | None:
    h1 = soup.find("h1")
    if h1 and h1.get_text(strip=True):
        return h1.get_text(" ", strip=True)
    return soup.title.get_text(strip=True) if soup.title else None


def extract_summary(soup) -> str | None:
    meta = soup.find("meta", attrs={"name": "description"})
    content = meta.get("content") if meta else None
    return content.strip() if content else None


def extract_tables(soup) -> list[dict]:
    """Every content table on the page (class="...table..."), tagged with
    whichever heading most closely precedes it.

    We deliberately don't chase specific heading labels like "Data" per
    type: a material's most important table (its oxide chemistry analysis)
    sits *before* any heading at all, while oxide pages have separate
    "Data" and "Mechanisms" tables. Grabbing every bordered table and noting
    its nearest heading is the type-agnostic equivalent that needs no
    per-type special-casing.
    """
    tables = []
    for table in soup.find_all("table", class_=lambda c: c and "table" in c):
        heading = table.find_previous(["h1", "h2", "h3", "h4"])
        tables.append({
            "heading": heading.get_text(" ", strip=True) if heading else None,
            **parse_data_table(table),
        })
    return tables


def extract_body_text(soup) -> str:
    parts = []
    for p in soup.find_all("p"):
        if p.find_parent("nav"):
            continue
        text = p.get_text(" ", strip=True)
        if not text or text.startswith(SHUTDOWN_BANNER_PREFIX):
            continue
        if any(marker in text for marker in BOILERPLATE_MARKERS):
            continue
        parts.append(text)
    return "\n\n".join(parts)


def extract_links(soup) -> list[dict]:
    links, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("/"):
            href = config.BASE_URL + href
        if not href.startswith(config.BASE_URL) or href in seen:
            continue
        target_type, code = classify(href)
        if target_type not in KNOWN_TYPES or not code or code == "list":
            continue
        seen.add(href)
        links.append({"target_url": href, "target_type": target_type, "label": a.get_text(" ", strip=True)})
    return links


def extract_images(soup) -> list[dict]:
    images = []
    for img in soup.find_all("img"):
        src = img.get("src") or ""
        if not src or any(marker in src for marker in SKIP_IMG_MARKERS) or src.endswith(".svg"):
            continue
        if src.startswith("/"):
            src = config.BASE_URL + src
        caption = (img.get("alt") or "").strip()
        if not caption:
            heading = img.find_previous(["h2", "h3"])
            caption = heading.get_text(" ", strip=True) if heading else None
        picture_page_url = None
        link_parent = img.find_parent("a", href=True)
        if link_parent:
            t, _ = classify(config.BASE_URL + link_parent["href"] if link_parent["href"].startswith("/") else link_parent["href"])
            if t == "picture":
                picture_page_url = link_parent["href"]
                if picture_page_url.startswith("/"):
                    picture_page_url = config.BASE_URL + picture_page_url
        images.append({"src_url": src, "caption": caption, "picture_page_url": picture_page_url})
    return images


def extract_recipe_xml(soup) -> tuple[str | None, dict | None]:
    pre = soup.find("pre", id="xmlContent")
    if not pre:
        return None, None
    raw_xml = pre.get_text()  # BeautifulSoup already unescapes entities here
    try:
        root = ET.fromstring(raw_xml)
        recipe_el = root.find("recipe")
        if recipe_el is None:
            return raw_xml, None
        lines = [
            {"material": rl.get("material"), "amount": rl.get("amount")}
            for rl in recipe_el.findall("./recipelines/recipeline")
        ]
        parsed = {
            "name": recipe_el.get("name"),
            "keywords": recipe_el.get("keywords"),
            "id": recipe_el.get("id"),
            "date": recipe_el.get("date"),
            "codenum": recipe_el.get("codenum"),
            "lines": lines,
        }
        return raw_xml, parsed
    except ET.ParseError as exc:
        log.warning("could not parse embedded recipe XML: %s", exc)
        return raw_xml, None


def is_soft_404(soup) -> bool:
    """Detect pages the server returned as HTTP 200 but are actually error
    pages (common on PHP legacy sites). Tony's site emits a page whose first
    h3 is 'Error 404' and body text starts with 'Operation timed out' or
    'Request Not Recognized' when a URL doesn't resolve."""
    first_h3 = soup.find("h3")
    if first_h3 and "error 404" in first_h3.get_text(strip=True).lower():
        return True
    body_text = soup.body.get_text(" ", strip=True) if soup.body else ""
    return "Operation timed out" in body_text or "Request Not Recognized" in body_text


def extract_one(html: str) -> dict:
    soup = BeautifulSoup(html, "lxml")
    raw_export, recipe_data = extract_recipe_xml(soup)
    data = {"tables": extract_tables(soup)}
    if recipe_data:
        data["recipe"] = recipe_data
    return {
        "title": extract_title(soup),
        "summary": extract_summary(soup) or (recipe_data["keywords"] if recipe_data else None),
        "body_text": extract_body_text(soup),
        "data": data,
        "raw_export": raw_export,
        "images": extract_images(soup),
        "links": extract_links(soup),
    }


def save_extraction(cur, url: str, type_: str, code, result: dict) -> None:
    """Persist one extract_one() result to the DB.

    Factored out of run() so pipeline.py can call it per-page without
    duplicating the upsert + image/link insertion logic.
    """
    db.upsert_entity(
        cur, url=url, type_=type_, code=code,
        title=result["title"], summary=result["summary"],
        body_text=result["body_text"], data=result["data"],
        raw_export=result["raw_export"],
    )
    cur.execute("DELETE FROM images WHERE entity_url = ?", (url,))
    cur.execute("DELETE FROM links WHERE source_url = ?", (url,))
    for img in result["images"]:
        cur.execute(
            "INSERT INTO images (entity_url, src_url, caption, picture_page_url) VALUES (?, ?, ?, ?)",
            (url, img["src_url"], img["caption"], img["picture_page_url"]),
        )
    for link in result["links"]:
        cur.execute(
            "INSERT INTO links (source_url, target_url, target_type, label) VALUES (?, ?, ?, ?)",
            (url, link["target_url"], link["target_type"], link["label"]),
        )


def run(*, type_filter: str | None, limit: int | None) -> dict[str, int]:
    db.init_db()
    with db.cursor() as cur:
        query = "SELECT * FROM pages WHERE status = 'fetched'"
        params: list = []
        if type_filter:
            query += " AND type = ?"
            params.append(type_filter)
        if limit:
            query += f" LIMIT {int(limit)}"
        rows = cur.execute(query, params).fetchall()

    counts = {"extracted": 0, "error": 0}
    with db.cursor() as cur:
        for row in rows:
            path = config.ROOT_DIR / row["html_path"]
            try:
                html = path.read_text(encoding="utf-8", errors="replace")
                soup_check = BeautifulSoup(html, "lxml")
                if is_soft_404(soup_check):
                    log.warning("soft 404 (HTTP 200 with error body): %s", row["url"])
                    with db.cursor() as cur2:
                        cur2.execute(
                            "UPDATE pages SET status='error', error='soft 404 - page served as HTTP 200 but body is an error page' WHERE url=?",
                            (row["url"],),
                        )
                    counts["error"] += 1
                    continue
                result = extract_one(html)
            except Exception as exc:  # keep going -- one bad page shouldn't kill the run
                log.warning("failed to extract %s: %s", row["url"], exc)
                counts["error"] += 1
                continue

            save_extraction(cur, row["url"], row["type"], row["code"], result)
            counts["extracted"] += 1
    return counts


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--type", dest="type_filter")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    print(run(type_filter=args.type_filter, limit=args.limit))
