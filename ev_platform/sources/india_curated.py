"""Hand-curated Indian-market specs from data/india_curated.yaml, each with a cited source."""

from collections.abc import Iterator
from pathlib import Path

import yaml

from .base import HP_TO_KW, VehicleSpec, lakh_to_inr, ps_to_kw

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "data" / "india_curated.yaml"

_INHERITED = ("body_type", "price_lakh", "price_note", "source_url")


class IndiaCuratedSource:
    name = "india_curated"
    license = "Facts compiled by hand; see source_url per vehicle"

    def __init__(self, path: Path | str = DEFAULT_PATH):
        self.path = Path(path)

    def fetch(self) -> Iterator[VehicleSpec]:
        doc = yaml.safe_load(self.path.read_text(encoding="utf-8"))
        market = doc.get("market", "IN")
        verified = doc.get("last_verified")
        for car in doc["vehicles"]:
            for v in car.get("variants") or [{}]:
                row = {k: car[k] for k in _INHERITED if k in car} | dict(v)
                yield self._to_spec(market, car["make"], car["model"], row, verified)

    @staticmethod
    def _to_spec(market: str, make: str, model: str, row: dict, verified: str | None) -> VehicleSpec:
        row = dict(row)
        if (ps := row.pop("power_ps", None)) is not None:
            row["power_kw"] = ps_to_kw(ps)
        if (hp := row.pop("power_hp", None)) is not None:
            row["power_kw"] = round(hp * HP_TO_KW, 1)
        lo, hi = (list(row.pop("price_lakh", None) or []) + [None, None])[:2]
        extra = row.pop("extra", {}) or {}
        if verified:
            extra["last_verified"] = verified
        return VehicleSpec(
            market=market,
            make=make,
            model=model,
            price_min_inr=lakh_to_inr(lo),
            price_max_inr=lakh_to_inr(hi),
            extra=extra,
            source_ref=f"{make} {model} {row.get('variant', '')}".strip(),
            **row,
        )
