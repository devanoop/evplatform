from fastapi.testclient import TestClient

from ev_platform.api import app
from ev_platform.pipeline import run_ingest
from ev_platform.sources.india_curated import IndiaCuratedSource


def test_api_end_to_end(session, monkeypatch):
    run_ingest(session, ["india_curated"], {"india_curated": IndiaCuratedSource()})
    c = TestClient(app)
    assert c.get("/health").json() == {"status": "ok"}

    page = c.get("/vehicles", params={"market": "IN", "max_price_inr": 1_500_000, "min_range_km": 400}).json()
    assert page["total"] >= 1
    assert all(v["range_km"] >= 400 and v["price_min_inr"] <= 1_500_000 for v in page["items"])

    cheapest = c.get("/vehicles", params={"sort": "price", "limit": 1}).json()["items"][0]
    assert cheapest["model"] == "Tiago EV"  # market defaults to IN

    detail = c.get("/vehicles/in-tata-nexon-ev-45-kwh").json()
    assert detail["records"][0]["source"] == "india_curated"
    assert c.get("/vehicles/nope").status_code == 404

    cmp = c.get("/compare", params={"slugs": "in-tata-nexon-ev-45-kwh,in-mahindra-be-6-59-kwh"}).json()
    assert [v["model"] for v in cmp] == ["Nexon EV", "BE 6"]

    assert c.post("/admin/ingest").status_code == 404  # no ADMIN_TOKEN configured
