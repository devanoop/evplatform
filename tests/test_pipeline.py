from sqlalchemy import select

from ev_platform.models import Vehicle
from ev_platform.pipeline import run_ingest
from ev_platform.sources.base import VehicleSpec, make_slug
from ev_platform.sources.india_curated import IndiaCuratedSource
from ev_platform.sources.oem_pages import OEMPagesSource, page_text
from ev_platform.sources.open_ev_data import OpenEVDataSource

OPEN_EV_FIXTURE = {
    "data": [
        {"id": "a", "brand": "Tesla", "model": "Model 3", "variant": "LR", "release_year": 2024,
         "usable_battery_size": 75, "energy_consumption": {"average_consumption": 15.1},
         "ac_charger": {"max_power": 11}, "dc_charger": {"max_power": 250}},
        {"id": "b", "brand": "Abarth", "model": "500e", "variant": "", "release_year": 2024,
         "usable_battery_size": 37.8, "dc_charger": {"max_power": 37.8}},
        {"id": "c", "brand": "BYD", "model": "44.", "variant": "9kwh active"},
    ]
}


class FakeSource:
    def __init__(self, name, specs):
        self.name, self.license, self._specs = name, "test", specs

    def fetch(self):
        yield from self._specs


def test_curated_yaml_loads_and_converts_units():
    specs = {s.slug: s for s in IndiaCuratedSource().fetch()}
    assert len({(s.make, s.model) for s in specs.values()}) >= 55
    be6 = specs["in-mahindra-be-6-79-kwh"]
    assert be6.power_kw == 210.3  # 282 bhp
    assert be6.price_min_inr == 1_945_000 and be6.price_max_inr == 2_770_000
    assert be6.battery_chemistry == "LFP"  # inherited from the model
    ev9 = specs["in-kia-ev9-gt-line-99.8-kwh-awd"]
    assert ev9.price_min_inr == 13_000_000  # 1.30 crore
    for s in specs.values():
        assert s.market == "IN"
        assert s.source_url.startswith("https://"), f"{s.slug} has no source"
        assert s.battery_kwh, f"{s.slug} has no battery size"


def test_open_ev_data_mapping_and_cleanup():
    specs = list(OpenEVDataSource(payload=OPEN_EV_FIXTURE).fetch())
    assert [s.make for s in specs] == ["Tesla", "Abarth"]  # broken "44." row dropped
    tesla, abarth = specs
    assert tesla.efficiency_wh_per_km == 151.0 and tesla.dc_charge_max_kw == 250
    assert abarth.dc_charge_max_kw is None  # placeholder equal to battery size


def test_ingest_is_idempotent_and_tracks_changes(session):
    curated = IndiaCuratedSource()
    run_ingest(session, ["india_curated"], {"india_curated": curated})
    n = session.query(Vehicle).count()
    runs = run_ingest(session, ["india_curated"], {"india_curated": curated})
    assert session.query(Vehicle).count() == n
    assert runs[0].stats["unchanged"] == n and runs[0].stats["changed_records"] == 0


def test_merge_prefers_higher_priority_source(session):
    slug_args = dict(market="IN", make="Tata", model="Nexon EV", variant="45 kWh")
    curated = FakeSource("india_curated", [VehicleSpec(**slug_args, range_km=489, battery_kwh=45)])
    scraped = FakeSource("oem_pages", [VehicleSpec(**slug_args, range_km=500, dc_charge_max_kw=60)])
    run_ingest(session, ["oem_pages", "india_curated"], {"oem_pages": scraped, "india_curated": curated})
    v = session.scalar(select(Vehicle).where(Vehicle.slug == make_slug(**slug_args)))
    assert v.range_km == 489 and v.field_sources["range_km"] == "india_curated"
    assert v.dc_charge_max_kw == 60 and v.field_sources["dc_charge_max_kw"] == "oem_pages"


def test_failing_source_does_not_block_others(session):
    class Boom:
        name, license = "open_ev_data", "x"

        def fetch(self):
            raise RuntimeError("network down")
            yield

    runs = run_ingest(session, ["open_ev_data", "india_curated"],
                      {"open_ev_data": Boom(), "india_curated": IndiaCuratedSource()})
    assert [r.status for r in runs] == ["failed", "ok"]
    assert session.query(Vehicle).count() > 0


def test_oem_source_skips_without_api_key(tmp_path):
    cfg = tmp_path / "pages.yaml"
    cfg.write_text("pages:\n  - {make: Tata, model: Nexon EV, url: https://example.com/x, enabled: true}\n")
    src = OEMPagesSource(path=cfg)
    assert list(src.fetch()) == []
    assert src.skipped == [{"reason": "ANTHROPIC_API_KEY not set"}]


def test_oem_source_respects_robots(tmp_path):
    from ev_platform.http import RobotsDisallowed

    class NoRobots:
        def get(self, url):
            raise RobotsDisallowed(url)

    class Extractor:
        def extract(self, *a):
            raise AssertionError("must not extract a disallowed page")

    cfg = tmp_path / "pages.yaml"
    cfg.write_text("pages:\n  - {make: Tata, model: Nexon EV, url: https://example.com/x}\n")
    src = OEMPagesSource(path=cfg, extractor=Extractor(), client=NoRobots())
    assert list(src.fetch()) == []
    assert src.skipped[0]["reason"] == "robots.txt disallows"


def test_page_text_strips_scripts():
    assert page_text("<html><script>x=1</script><p>Range 489 km</p></html>") == "Range 489 km"
