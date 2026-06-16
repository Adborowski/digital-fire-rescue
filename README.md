# digitalfire-archive

A personal, careful archive of [digitalfire.com](https://digitalfire.com) —
Tony Hansen's 35-year ceramics reference library (glaze recipes, materials,
oxide chemistry, glossary, articles, pictures, and more) — ahead of its
**June 26, 2026** shutdown.

## Why a universal schema, not a 1:1 HTML mirror

The site has 22 content types but they all reduce to the same shape: a
title, a short description, a flexible bag of type-specific key/value facts
(formula+weight for an oxide, materials+grams for a recipe, cone+type for a
glossary term...), free-form notes text, a gallery of captioned images, and
a set of cross-links to other entries. So there's one `entities` table with
a `data_json` blob for the type-specific facts, plus shared `images` and
`links` tables — see [src/digitalfire_archive/db.py](src/digitalfire_archive/db.py).
That's what makes the corpus queryable and rebuildable later, independent
of Tony's original page layout.

Raw HTML is also saved verbatim alongside the structured extraction, so
nothing is lost if a parser misses something.

## Status

- [x] **Discovery** — exact, validated URL inventory via the site's own
      sitemap index, cross-checked against each type's `/<type>/list` page
      to catch sitemap bugs (it already found two: digitalfire's own
      `sitemap-video.xml` points most entries at a malformed date string
      instead of a URL, and several sitemaps typo the domain as
      `digitlfire.com`). Current count: **11,431 unique URLs** across 22
      types. Run it again any time with `make discover`.
- [ ] **Fetch** — polite, resumable HTML fetch of every URL in the
      inventory (respects `Crawl-delay: 20` from robots.txt by default).
- [ ] **Extract** — per-type HTML → universal schema (recipes have an
      embedded XML export block on-page worth capturing verbatim too).
- [ ] **Assets** — download every referenced image/PDF.
- [ ] **Verify** — reconcile fetched/extracted counts against discovery,
      flag 404s and orphans.
- [ ] **IA backstop** — trigger Internet Archive Save Page Now captures for
      every URL (IA's crawler is unrestricted in robots.txt, including
      `/uploads/`, which our own crawler is not — see `ROBOTS_DISALLOWED_PREFIXES`
      in [config.py](src/digitalfire_archive/config.py)).
- [ ] **Outreach** — [draft email to Tony](outreach/tony_email_draft.md)
      asking for a raw export and/or permission to exceed the crawl-delay
      and reach `/uploads/`. Sending it is the highest-leverage single step
      in this whole project; everything else here is the fallback in case
      it doesn't land before the 26th.

## Setup

```
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```
PYTHONPATH=src python -m digitalfire_archive.discover
```

Data lands in `data/db/digitalfire.sqlite` (`pages` table). Raw HTML, in
`data/raw_html/`, mirrors `<type>/<code>.html`. Nothing here touches
`/uploads/` or `/videos/` — robots.txt blocks the default user-agent from
those, by design, pending Tony's answer.
