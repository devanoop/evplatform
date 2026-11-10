"""Common shape every data source produces, plus helpers for building stable keys."""

import re
from collections.abc import Iterator
from typing import Protocol

from pydantic import BaseModel, Field, model_validator

# Fields on VehicleSpec that map 1:1 onto Vehicle columns and take part in merging.
SPEC_FIELDS = (
    "body_type",
    "vehicle_type",
    "model_year",
    "battery_kwh",
    "battery_chemistry",
    "range_km",
    "range_standard",
    "power_kw",
    "torque_nm",
    "drivetrain",
    "dc_charge_max_kw",
    "ac_charge_max_kw",
    "dc_charge_time_note",
    "efficiency_wh_per_km",
    "price_min_inr",
    "price_max_inr",
    "price_note",
)


_MAX_LEN = {
    "make": 80, "model": 120, "variant": 160, "body_type": 40, "vehicle_type": 20,
    "battery_chemistry": 20, "range_standard": 30, "drivetrain": 10, "dc_charge_time_note": 200,
}


class VehicleSpec(BaseModel):
    """One variant as reported by one source. Unknown values stay None, never guessed."""

    market: str = "GLOBAL"
    make: str
    model: str
    variant: str = ""

    body_type: str | None = None
    vehicle_type: str = "car"
    model_year: int | None = None
    battery_kwh: float | None = None
    battery_chemistry: str | None = None
    range_km: float | None = None
    range_standard: str | None = None
    power_kw: float | None = None
    torque_nm: float | None = None
    drivetrain: str | None = None
    dc_charge_max_kw: float | None = None
    ac_charge_max_kw: float | None = None
    dc_charge_time_note: str | None = None
    efficiency_wh_per_km: float | None = None
    price_min_inr: float | None = None
    price_max_inr: float | None = None
    price_note: str | None = None

    extra: dict = Field(default_factory=dict)

    # Provenance
    source_url: str | None = None
    source_ref: str | None = None

    @model_validator(mode="after")
    def _fit_columns(self):
        # Keep free-text values (which may come from scraped pages) inside column limits.
        for field, n in _MAX_LEN.items():
            v = getattr(self, field)
            if isinstance(v, str) and len(v) > n:
                object.__setattr__(self, field, v[: n - 1] + "…")
        return self

    @property
    def slug(self) -> str:
        return make_slug(self.market, self.make, self.model, self.variant)[:200]


class Source(Protocol):
    name: str
    license: str

    def fetch(self) -> Iterator[VehicleSpec]: ...


def _slugify(s: str) -> str:
    s = s.lower().replace("+", " plus ")
    s = re.sub(r"[^a-z0-9.]+", "-", s)
    s = re.sub(r"(?<!\d)\.|\.(?!\d)", "-", s)  # keep dots only inside numbers (45.0)
    return re.sub(r"-+", "-", s).strip("-")


def make_slug(market: str, make: str, model: str, variant: str = "") -> str:
    parts = [market, make, model] + ([variant] if variant else [])
    return _slugify(" ".join(parts))


PS_TO_KW = 0.73549875
HP_TO_KW = 0.7457


def ps_to_kw(ps: float | None) -> float | None:
    return round(ps * PS_TO_KW, 1) if ps is not None else None


def lakh_to_inr(lakh: float | None) -> float | None:
    return round(lakh * 100_000) if lakh is not None else None
