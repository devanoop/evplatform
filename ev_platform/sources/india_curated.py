"""Hand-curated Indian-market specs from data/india/*.yaml, each model with a cited source.

File layout (see data/india/_README.md): a file has an optional top-level `make` and a list of
`models`. Any key set on a model applies to all its variants unless the variant overrides it.
"""

from collections.abc import Iterator
from pathlib import Path

import yaml

from .base import HP_TO_KW, SPEC_FIELDS, VehicleSpec, lakh_to_inr, ps_to_kw

DEFAULT_DIR = Path(__file__).resolve().parents[2] / "data" / "india"
LAST_VERIFIED = "2026-11-10"

_MODEL_ONLY = {"make", "model", "variants", "source_url", "other_sources", "note"}


class IndiaCuratedSource:
    name = "india_curated"
    license = "Facts compiled by hand from cited sources; see source_url per vehicle"

    def __init__(self, path: Path | str = DEFAULT_DIR):
        self.path = Path(path)

    def _files(self) -> list[Path]:
        if self.path.is_file():
            return [self.path]
        return sorted(p for p in self.path.glob("*.yaml"))

    def fetch(self) -> Iterator[VehicleSpec]:
        for f in self._files():
            doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
            file_make = doc.get("make")
            verified = doc.get("last_verified", LAST_VERIFIED)
            for car in doc.get("models", []):
                make = car.get("make", file_make)
                if not make:
                    raise ValueError(f"{f.name}: model {car.get('model')} has no make")
                defaults = {k: v for k, v in car.items() if k not in _MODEL_ONLY}
                for v in car.get("variants") or [{}]:
                    row = defaults | dict(v)
                    notes = [n for n in (car.get("note"), v.get("note")) if n]
                    row.pop("note", None)
                    yield self._to_spec(make, car["model"], row, car, notes, verified, f.name)

    @staticmethod
    def _to_spec(make, model, row, car, notes, verified, filename) -> VehicleSpec:
        row = dict(row)
        if (ps := row.pop("power_ps", None)) is not None:
            row["power_kw"] = ps_to_kw(ps)
        if (hp := row.pop("power_hp", None)) is not None:
            row["power_kw"] = round(hp * HP_TO_KW, 1)

        lo = hi = None
        if "price_crore" in row:
            lo, hi = (list(row.pop("price_crore") or []) + [None, None])[:2]
            lo, hi = [x * 100 if x is not None else None for x in (lo, hi)]  # crore -> lakh
        if "price_lakh" in row:
            lo, hi = (list(row.pop("price_lakh") or []) + [None, None])[:2]

        unknown = set(row) - set(SPEC_FIELDS) - {"variant"}
        if unknown:
            raise ValueError(f"{filename}: {make} {model}: unknown keys {sorted(unknown)}")

        extra = {"last_verified": verified}
        if notes:
            extra["note"] = " ".join(notes)
        if car.get("other_sources"):
            extra["other_sources"] = car["other_sources"]
        return VehicleSpec(
            market="IN",
            make=make,
            model=model,
            price_min_inr=lakh_to_inr(lo),
            price_max_inr=lakh_to_inr(hi),
            extra=extra,
            source_url=car["source_url"],
            source_ref=f"{make} {model} {row.get('variant', '')}".strip(),
            **row,
        )
