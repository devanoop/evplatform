# India EV specs, one file per brand

Covers every electric car listed as on sale in India by CarWale's electric-car listing on
2026-11-10 (64 listings), minus discontinued or superseded ones noted at the end of each file.

Rules for editing:
* Every model needs `source_url`. Use `other_sources` for extra citations.
* Only enter values the cited source states. Aggregator pages often contradict themselves; when
  they do, prefer the figure tied to a named test standard (MIDC/ARAI/WLTP), or leave it out and
  write a `note`.
* Units: `power_ps`, `power_hp` (bhp) or `power_kw`; `price_lakh` or `price_crore` as [min, max].
  The loader converts to kW and rupees.
* `range_standard`: MIDC P1, MIDC P1+P2, MIDC, ARAI, WLTP, CLTC, C75 (Tata's real-world cycle),
  or "claimed" when the source names none.

Photos: the app shows one freely licensed Wikimedia Commons photo per model, found by search
after each ingest. To pick the photo yourself, add `photo_file: "File:Exact name on Commons.jpg"`
to the model; to show the drawing instead, add `photo_file: none`. Check the current picks at
`GET /photos?all=true`. Only CC0, public-domain, CC BY and CC BY-SA files are used.
