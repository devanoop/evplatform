from fastapi.testclient import TestClient
from sqlalchemy import select

from ev_platform.api import app
from ev_platform.models import ModelPhoto
from ev_platform.photos import pick_from_search, refresh_photos
from ev_platform.pipeline import run_ingest
from ev_platform.sources.india_curated import IndiaCuratedSource


def page(title, lic="CC BY-SA 4.0", w=4000, h=2600, artist='<a href="x">Jane Doe</a>', restrictions="", index=1):
    return {"title": title, "index": index, "imageinfo": [{
        "url": "https://upload.wikimedia.org/full.jpg", "thumburl": "https://upload.wikimedia.org/thumb.jpg",
        "descriptionurl": "https://commons.wikimedia.org/wiki/" + title, "width": w, "height": h, "mime": "image/jpeg",
        "extmetadata": {"LicenseShortName": {"value": lic}, "LicenseUrl": {"value": "https://creativecommons.org/licenses/by-sa/4.0"},
                        "Artist": {"value": artist}, "Restrictions": {"value": restrictions}}}]}


def test_pick_rejects_unusable_photos():
    pages = [
        page("File:Tata Nexon EV interior.jpg"),                  # interior
        page("File:Tata Nexon EV 2024 front.jpg", lic="CC BY-NC 2.0"),  # non-commercial
        page("File:Tata Nexon EV 2024 side.jpg", lic="CC BY-ND 4.0"),   # no derivatives
        page("File:Tata Nexon EV portrait.jpg", w=1500, h=2000),  # portrait
        page("File:Tata Nexon EV small.jpg", w=640, h=400),       # too small
        page("File:Tata Nexon 2018 front.jpg", w=5000),           # the petrol Nexon
        page("File:Tata Nexon EV at show.jpg", restrictions="personality"),
        page("File:Tata Nexon EV 2024 front.jpg", lic="CC BY-SA 4.0"),
    ]
    best = pick_from_search("Tata", "Nexon EV", pages)
    assert best["file"] == "File:Tata Nexon EV 2024 front.jpg"
    assert best["author"] == "Jane Doe" and best["license"] == "CC BY-SA 4.0"
    assert best["image_url"].endswith("thumb.jpg")
    assert pick_from_search("Tata", "Punch EV", pages) is None  # never a different model
    assert pick_from_search("Tata", "Nexon EV", [page("File:Tata Nexon EV.jpg", artist="")]) is None  # no one to credit


class FakeCommons:
    def __init__(self):
        self.searches = 0

    def search(self, make, model):
        self.searches += 1
        return [page(f"File:{make} {model} 2025 front.jpg")] if model == "Nexon EV" else []

    def file(self, title):
        return [page(title, lic="CC0")]


def test_refresh_and_api(session):
    run_ingest(session, ["india_curated"], {"india_curated": IndiaCuratedSource()})
    fake = FakeCommons()
    stats = refresh_photos(session, client=fake)
    assert stats["ok"] >= 1 and stats["errors"] == 0
    nexon = session.scalar(select(ModelPhoto).where(ModelPhoto.model == "Nexon EV"))
    assert nexon.status == "ok" and nexon.chosen_by == "search"

    again = refresh_photos(session, client=fake)  # nothing stale, no new lookups
    assert again["unchanged"] == stats["models"] and fake.searches == stats["models"]

    c = TestClient(app)
    got = c.get("/photos").json()
    assert [p["model"] for p in got] == ["Nexon EV"] and got[0]["author"] == "Jane Doe"
    assert len(c.get("/photos", params={"all": True}).json()) == stats["models"]
