"""Open EV Data (github.com/KilowattApp/open-ev-data): ~1,300 EVs, mostly EU/US models.

License: MIT with an attribution requirement. The API surfaces the attribution on every
record and in /sources, which satisfies it as long as you keep that in any UI built on top.
"""

from collections.abc import Iterator

from ..config import get_settings
from ..http import PoliteClient
from .base import VehicleSpec


class OpenEVDataSource:
    name = "open_ev_data"
    license = "MIT with attribution: Open EV Data by Tijs Teulings / KilowattApp"
    homepage = "https://github.com/KilowattApp/open-ev-data"

    def __init__(self, client: PoliteClient | None = None, payload: dict | None = None):
        self._client = client
        self._payload = payload  # allows tests to inject a fixture

    def _load(self) -> dict:
        if self._payload is not None:
            return self._payload
        url = get_settings().open_ev_data_url
        # raw.githubusercontent.com serves a static file; robots.txt there is not meaningful
        # for a single dataset download, but we still go through the polite client.
        with self._client or PoliteClient(delay=0) as c:
            return c.get(url, check_robots=False).json()

    def fetch(self) -> Iterator[VehicleSpec]:
        data = self._load()
        url = get_settings().open_ev_data_url
        for row in data.get("data", []):
            if not row.get("brand") or not row.get("model") or _looks_broken(str(row["model"])):
                continue
            ac = row.get("ac_charger") or {}
            dc = row.get("dc_charger") or {}
            cons = (row.get("energy_consumption") or {}).get("average_consumption")
            dc_kw = dc.get("max_power")
            # ~40% of upstream rows copy the battery size into dc max_power as a placeholder.
            dc_placeholder = dc_kw is not None and dc_kw == row.get("usable_battery_size")
            yield VehicleSpec(
                market="GLOBAL",
                make=row["brand"].strip(),
                model=str(row["model"]).strip(),
                variant=str(row.get("variant") or "").strip(),
                vehicle_type=row.get("vehicle_type") or "car",
                model_year=row.get("release_year"),
                battery_kwh=row.get("usable_battery_size"),
                # kWh/100km -> Wh/km
                efficiency_wh_per_km=round(cons * 10, 1) if cons else None,
                ac_charge_max_kw=ac.get("max_power"),
                dc_charge_max_kw=None if dc_placeholder else dc_kw,
                extra={
                    "ac_ports": ac.get("ports"),
                    "dc_ports": dc.get("ports"),
                    "charging_voltage": row.get("charging_voltage"),
                    "battery_is_usable_capacity": True,
                    "dc_power_dropped_as_placeholder": dc_placeholder or None,
                },
                source_url=url,
                source_ref=row.get("id"),
            )


def _looks_broken(model: str) -> bool:
    # The upstream file has a few rows where the model was split mid-number ("44." / "9kwh active").
    s = model.strip()
    return not s or s.rstrip(".").replace(".", "").isdigit()
