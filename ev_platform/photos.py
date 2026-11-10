"""Car photos from Wikimedia Commons, used only under licences that allow commercial reuse.

For each car model we pick one exterior photo and keep the author, licence and link needed to
credit it. Photos are chosen in this order:

1. `photo_file: "File:....jpg"` on the model in data/india/*.yaml (a human picked it), or
   `photo_file: none` to never show a photo for that model.
2. Otherwise a Commons search for "<make> <model>", keeping only files whose title names the
   model, that are landscape, large enough, not of interiors or details, and licensed CC0,
   public domain, CC BY or CC BY-SA. NC (non-commercial) and ND (no derivatives, we crop) are
   rejected, as are files Commons flags with personality or other restrictions.

Search can still pick a poor or wrong photo (an older generation, a petrol sibling), so the
pick is visible at GET /photos for review, and a curated `photo_file` always wins.

This uses the MediaWiki API, which Wikimedia asks clients to call with a descriptive
User-Agent (set HTTP_USER_AGENT with a contact URL) and one request at a time. It isn't
crawling, so robots.txt (which covers page crawlers) isn't consulted.
"""

import html
import logging
import re
from datetime import timedelta
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .http import PoliteClient
from .models import ModelPhoto, Vehicle, utcnow

log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "india"
THUMB_WIDTH = 1280
ALLOWED_LICENSE = re.compile(r"^(cc0|public domain|pd\b|cc[ -]by(-sa)?[ -]?\d)", re.I)
BLOCKED_LICENSE = re.compile(r"\b(nc|nd)\b|non-?commercial|no ?deriv", re.I)
BAD_WORDS = re.compile(
    r"interior|dashboard|cockpit|steering|seats?\b|boot|trunk|engine|badge|logo|emblem|wheel|"
    r"rim|tyre|tire|light|lamp|charging port|charger|screen|display|detail|close|key|"
    r"brochure|poster|toy|model car|scale|diecast|crash|accident|sketch|drawing|render", re.I)


def curated_overrides(path: Path = DATA_DIR) -> dict[tuple[str, str], str]:
    """(make, model) -> "File:..." or "none", from photo_file keys in the curated YAML."""
    out = {}
    for f in sorted(path.glob("*.yaml")):
        doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        for car in doc.get("models", []):
            if car.get("photo_file"):
                out[(car.get("make", doc.get("make")), car["model"])] = str(car["photo_file"])
    return out


def _plain(s: str | None) -> str | None:
    """Commons metadata is HTML; credits need plain text."""
    if not s:
        return None
    s = html.unescape(re.sub(r"<[^>]+>", "", s)).strip()
    return re.sub(r"\s+", " ", s)[:300] or None


def _tokens(s: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9]+", s.lower()) if t and t not in {"ev", "electric", "e"}]


def _photo_from_page(page: dict) -> dict | None:
    """Turn one Commons API page (with imageinfo) into a photo dict, or None if not reusable."""
    info = (page.get("imageinfo") or [None])[0]
    if not info:
        return None
    meta = info.get("extmetadata") or {}
    lic = _plain((meta.get("LicenseShortName") or {}).get("value")) or ""
    restrictions = _plain((meta.get("Restrictions") or {}).get("value")) or ""
    if not ALLOWED_LICENSE.search(lic) or BLOCKED_LICENSE.search(lic) or restrictions:
        return None
    if info.get("mime") not in ("image/jpeg", "image/png", "image/webp"):
        return None
    author = _plain((meta.get("Artist") or {}).get("value")) or _plain((meta.get("Credit") or {}).get("value"))
    if not author and not re.match(r"cc0|public domain|pd\b", lic, re.I):
        return None  # CC BY needs a name to credit
    return {
        "file": page["title"],
        "image_url": info.get("thumburl") or info.get("url"),
        "page_url": info.get("descriptionurl"),
        "author": author or "Unknown",
        "license": lic,
        "license_url": (meta.get("LicenseUrl") or {}).get("value"),
        "width": info.get("width") or 0,
        "height": info.get("height") or 0,
    }


def pick_from_search(make: str, model: str, pages: list[dict]) -> dict | None:
    """Best usable search result for a model, or None. Pure function so it can be tested."""
    want = _tokens(model)
    electric_name = bool(re.search(r"\b(ev|electric)\b", model, re.I))
    best, best_score = None, -1.0
    for page in pages:
        title = page.get("title", "")
        name = title.removeprefix("File:").rsplit(".", 1)[0]
        have = _tokens(name)
        if not want or not all(t in have for t in want) or BAD_WORDS.search(name):
            continue
        # "Nexon EV" and "Creta Electric" share a name with petrol cars: insist the file says EV
        if electric_name and not re.search(r"(\bev\b|electric|\bbev\b|ev\b)", name, re.I):
            continue
        p = _photo_from_page(page)
        if not p or p["width"] < 1000 or p["width"] < p["height"] * 1.2:
            continue
        score = min(p["width"], 4000) / 4000
        score += 0.5 if make.lower().split()[0] in name.lower() else 0
        score += 0.3 if re.search(r"\b20(2[3-9]|3\d)\b", name) else 0  # recent photos first
        score += 0.2 if re.search(r"front|side|profile|three.quarter", name, re.I) else 0
        score -= 0.1 * page.get("index", 0) / 10
        if score > best_score:
            best, best_score = p, score
    return best


class CommonsClient:
    def __init__(self):
        self.s = get_settings()
        self.c = PoliteClient(delay=1)

    def _query(self, **params) -> list[dict]:
        params |= {"action": "query", "format": "json", "formatversion": "2", "prop": "imageinfo",
                   "iiprop": "url|size|mime|extmetadata", "iiurlwidth": THUMB_WIDTH,
                   "iiextmetadatafilter": "LicenseShortName|LicenseUrl|Artist|Credit|Restrictions"}
        r = self.c.get(self.s.commons_api_url, params=params, check_robots=False)
        return r.json().get("query", {}).get("pages", [])

    def search(self, make: str, model: str) -> list[dict]:
        return self._query(generator="search", gsrnamespace=6, gsrlimit=25,
                           gsrsearch=f'{make} "{model}" filetype:bitmap')

    def file(self, title: str) -> list[dict]:
        return self._query(titles=title)

    def close(self):
        self.c.close()


def refresh_photos(db: Session, client=None, force: bool = False) -> dict:
    """Find or refresh a photo for every model in the catalogue. Returns counts for logging."""
    s = get_settings()
    overrides = curated_overrides()
    existing = {(p.make, p.model): p for p in db.scalars(select(ModelPhoto))}
    models = sorted(set(db.execute(select(Vehicle.make, Vehicle.model).where(Vehicle.market == s.market)).all()))
    stale_before = utcnow() - timedelta(days=s.photo_refresh_days)
    own = client is None
    client = client or CommonsClient()
    stats = {"models": len(models), "ok": 0, "none": 0, "blocked": 0, "unchanged": 0, "errors": 0}
    try:
        for make, model in models:
            row = existing.get((make, model))
            override = overrides.get((make, model))
            curated_changed = override and (row is None or row.chosen_by != "curated"
                                            or (row.file or "none") != override)
            checked = row.checked_at if row else None
            if checked is not None and checked.tzinfo is None:
                checked = checked.replace(tzinfo=stale_before.tzinfo)
            if row and not force and not curated_changed and checked > stale_before:
                stats["unchanged"] += 1
                continue
            if row is None:
                row = ModelPhoto(make=make, model=model)
                db.add(row)
            try:
                if override and override.lower() == "none":
                    photo, row.chosen_by = None, "curated"
                elif override:
                    pages = client.file(override)
                    photo = _photo_from_page(pages[0]) if pages else None
                    row.chosen_by = "curated"
                    if photo is None:
                        log.warning("curated photo %s for %s %s is missing or not freely licensed", override, make, model)
                else:
                    photo = pick_from_search(make, model, client.search(make, model))
                    row.chosen_by = "search"
            except Exception:
                log.exception("photo lookup failed for %s %s", make, model)
                stats["errors"] += 1
                continue
            blocked = bool(override and override.lower() == "none")
            row.status = "blocked" if blocked else "ok" if photo else "none"
            for k in ("file", "image_url", "page_url", "author", "license", "license_url"):
                setattr(row, k, (photo or {}).get(k))
            row.checked_at = utcnow()
            stats[row.status] += 1
            db.commit()
    finally:
        if own:
            client.close()
    log.info("photos: %s", stats)
    return stats
