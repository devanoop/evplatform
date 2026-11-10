# EV Specs Platform

Data layer and API for an Indian EV buyer platform: collects electric-car specs from open data
and official sources, keeps the source of every number, and serves them over a REST API.
Built to run on Railway (Docker + Postgres + cron), but any container host works.

## What's in it

| Source | What it gives | License / rules | Default |
|---|---|---|---|
| `india_curated` | Hand-checked specs for the 10-car India launch list (17 variants), a cited URL on every model | facts compiled by hand | on |
| `oem_pages` | Official manufacturer spec pages, turned into structured data by Claude | allowlist in `data/oem_pages.yaml`, robots.txt enforced, terms checked by a human before enabling | needs `ANTHROPIC_API_KEY`; all pages start disabled |
| `open_ev_data` | ~1,270 mostly EU/US EVs: usable battery, efficiency, AC/DC charging | MIT with attribution (Open EV Data) | on |
| `wikidata` | Discovery of electric car models worldwide, battery/range where editors filled them | CC0 | on |

Each field on a vehicle is merged from the highest-priority source that has it (order of
`INGEST_SOURCES`), and `field_sources` says which source won. `GET /vehicles/{slug}` returns
the raw record from every source, with URL, license and fetch time.

Known data caveats:
* Open EV Data has no Tata, Mahindra or Maruti models, and its file was last updated April 2025.
  About 40% of its rows copy the battery size into DC charge power as a placeholder; those values
  are dropped on import.
* Indian prices change often and some brands sell with battery rental (BaaS). Check `price_note`.
* Range standards differ (MIDC P1, MIDC P1+P2, ARAI, claimed real-world). `range_standard` says which.

## API

| Endpoint | |
|---|---|
| `GET /vehicles` | filter by `market` (IN, GLOBAL), `make`, `q`, `body_type`, `min_price_inr`, `max_price_inr`, `min_range_km`, `min_battery_kwh`; `sort` = price, -price, range, -range, battery, -battery, name; `limit`/`offset` |
| `GET /vehicles/{slug}` | one variant with per-source records |
| `GET /compare?slugs=a,b,c` | up to 4 side by side |
| `GET /makes`, `GET /sources`, `GET /ingest/runs` | browsing and pipeline status |
| `POST /admin/ingest[?source=x]` | run ingestion now; needs `Authorization: Bearer $ADMIN_TOKEN` |
| `GET /docs` | interactive OpenAPI docs |

## Run locally

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-dev.txt
export DATABASE_URL=sqlite:///./ev.db          # or a Postgres URL
.venv/bin/python -m ev_platform.cli ingest      # migrates, then pulls all sources
.venv/bin/uvicorn ev_platform.api:app --reload
.venv/bin/pytest
```

Or `docker compose up` and then `docker compose run --rm api python -m ev_platform.cli ingest`.

## Deploy to Railway

1. New project, deploy from this GitHub repo. Railway picks up `railway.json` (Dockerfile build,
   `/health` check). Migrations run on boot.
2. Add a PostgreSQL database and set the web service's `DATABASE_URL` to `${{Postgres.DATABASE_URL}}`.
3. Set `ADMIN_TOKEN` (and `ANTHROPIC_API_KEY` if you enable OEM pages).
4. Add a second service from the same repo for ingestion. In its settings, set the config file
   path to `railway.ingest.json`: it runs `python -m ev_platform.cli ingest` daily at 03:00 IST
   (21:30 UTC) and exits. Give it the same variables.
5. Generate a domain for the web service and run the first ingest with
   `curl -X POST -H "Authorization: Bearer $ADMIN_TOKEN" https://<domain>/admin/ingest`.

Single-service alternative: set `ENABLE_INPROCESS_SCHEDULER=true` and `WEB_CONCURRENCY=1` on the
web service, and it ingests every `INPROCESS_INGEST_INTERVAL_HOURS` (default 24) itself.

Scaling: the API is stateless, so add replicas or raise `WEB_CONCURRENCY`; reads are indexed on
market, make, price and range. Ingestion is a separate job, so it never slows the API down.

## Adding data

* **A new Indian car**: add it to `data/india_curated.yaml` with a `source_url`. Only enter
  numbers the source states; leave the rest out.
* **A manufacturer page**: add it to `data/oem_pages.yaml`, read the site's terms, fill in
  `terms_checked_on`, then set `enabled: true`.
* **A new source**: write a class with `name`, `license` and a `fetch()` that yields
  `VehicleSpec`, register it in `ev_platform/sources/__init__.py`, and add it to `INGEST_SOURCES`.
  Use `ev_platform.http.PoliteClient` for any web access so robots.txt and rate limits apply.
