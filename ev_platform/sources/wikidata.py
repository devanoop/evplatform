"""Wikidata (CC0): electric car models with whatever specs editors have filled in.

Coverage of specs is patchy, but it is public domain and a good way to discover new models
(including Indian ones) and their manufacturers. Uses the public SPARQL endpoint, which asks
for a descriptive User-Agent and modest query rates.
"""

from collections.abc import Iterator

from ..config import get_settings
from ..http import PoliteClient
from .base import VehicleSpec

# Q1144312 = electric car. P31 instance of / P279 subclass of, P176 manufacturer,
# P495 country of origin, P571 inception. Battery capacity (P4140) and range (P2073) are
# sparsely populated, so both are OPTIONAL.
QUERY = """
SELECT ?item ?itemLabel ?makerLabel ?inception ?capacity ?capacityUnitLabel ?range ?rangeUnitLabel WHERE {
  ?item wdt:P31/wdt:P279* wd:Q1144312 .
  OPTIONAL { ?item wdt:P176 ?maker . }
  OPTIONAL { ?item wdt:P571 ?inception . }
  OPTIONAL { ?item p:P4140/psv:P4140 [ wikibase:quantityAmount ?capacity ; wikibase:quantityUnit ?capacityUnit ] . }
  OPTIONAL { ?item p:P2073/psv:P2073 [ wikibase:quantityAmount ?range ; wikibase:quantityUnit ?rangeUnit ] . }
  FILTER(!BOUND(?inception) || YEAR(?inception) >= %(min_year)d)
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}
LIMIT %(limit)d
"""


def _num(binding: dict, key: str) -> float | None:
    try:
        return float(binding[key]["value"])
    except (KeyError, ValueError):
        return None


def _label(binding: dict, key: str) -> str | None:
    v = binding.get(key, {}).get("value")
    return v if v and not v.startswith("http") else None


class WikidataSource:
    name = "wikidata"
    license = "CC0 1.0 (Wikidata)"

    def __init__(self, min_year: int = 2015, limit: int = 5000, payload: dict | None = None):
        self.min_year = min_year
        self.limit = limit
        self._payload = payload

    def _load(self) -> dict:
        if self._payload is not None:
            return self._payload
        s = get_settings()
        with PoliteClient(delay=1) as c:
            r = c.get(
                s.wikidata_sparql_url,
                params={"query": QUERY % {"min_year": self.min_year, "limit": self.limit}},
                headers={"Accept": "application/sparql-results+json"},
            )
            return r.json()

    def fetch(self) -> Iterator[VehicleSpec]:
        seen: set[str] = set()
        for b in self._load().get("results", {}).get("bindings", []):
            qid = b["item"]["value"].rsplit("/", 1)[-1]
            if qid in seen:  # OPTIONAL joins can duplicate rows
                continue
            seen.add(qid)
            name = _label(b, "itemLabel")
            maker = _label(b, "makerLabel")
            if not name or not maker:
                continue
            model = name[len(maker) :].strip() if name.lower().startswith(maker.lower()) else name
            cap = _num(b, "capacity")
            cap_unit = (_label(b, "capacityUnitLabel") or "").lower()
            rng = _num(b, "range")
            rng_unit = (_label(b, "rangeUnitLabel") or "").lower()
            year = b.get("inception", {}).get("value", "")[:4]
            yield VehicleSpec(
                market="GLOBAL",
                make=maker,
                model=model or name,
                model_year=int(year) if year.isdigit() else None,
                battery_kwh=cap if cap and "kilowatt hour" in cap_unit else None,
                range_km=rng if rng and rng_unit == "kilometre" else None,
                extra={"wikidata_id": qid},
                source_url=f"https://www.wikidata.org/wiki/{qid}",
                source_ref=qid,
            )
