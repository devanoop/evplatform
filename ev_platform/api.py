"""Public read API for EV specs, plus a token-protected endpoint to trigger ingestion."""

import logging
import secrets
import threading
from pathlib import Path
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Literal

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session, selectinload

from .config import get_settings
from .db import get_db, session_scope
from .models import IngestRun, ModelPhoto, SpecRecord, Vehicle
from .pipeline import run_full_update
from .sources import REGISTRY

WEB_DIR = Path(__file__).parent / "web"

log = logging.getLogger(__name__)


# Schemas -------------------------------------------------------------------------------
class VehicleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    slug: str
    market: str
    make: str
    model: str
    variant: str
    body_type: str | None
    vehicle_type: str
    model_year: int | None
    battery_kwh: float | None
    battery_chemistry: str | None
    range_km: float | None
    range_standard: str | None
    power_kw: float | None
    torque_nm: float | None
    drivetrain: str | None
    dc_charge_max_kw: float | None
    ac_charge_max_kw: float | None
    dc_charge_time_note: str | None
    efficiency_wh_per_km: float | None
    price_min_inr: float | None
    price_max_inr: float | None
    price_note: str | None
    extra: dict
    field_sources: dict
    updated_at: datetime


class SpecRecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source: str
    source_url: str | None
    source_ref: str | None
    license: str | None
    values: dict
    fetched_at: datetime
    changed_at: datetime


class VehicleDetail(VehicleOut):
    records: list[SpecRecordOut]


class Page(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[VehicleOut]


class IngestRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    stats: dict
    error: str | None


# App -----------------------------------------------------------------------------------
_stop = threading.Event()


def _scheduler_loop(interval_hours: float) -> None:
    while not _stop.wait(timeout=5):
        with session_scope() as db:
            last = db.scalar(select(func.max(IngestRun.started_at)))
        now = datetime.now(last.tzinfo) if last and last.tzinfo else datetime.utcnow()
        if last is None or (now - last).total_seconds() >= interval_hours * 3600:
            try:
                with session_scope() as db:
                    run_full_update(db)
            except Exception:
                log.exception("scheduled ingest failed")
        _stop.wait(timeout=600)


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    t = None
    if s.enable_inprocess_scheduler:
        t = threading.Thread(target=_scheduler_loop, args=(s.inprocess_ingest_interval_hours,), daemon=True)
        t.start()
    yield
    _stop.set()


app = FastAPI(
    title="Rangewise API",
    version="0.1.0",
    description="Specifications of every electric car on sale in India, with the source of every field.",
    lifespan=lifespan,
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"])


def require_admin(authorization: str | None = Header(default=None)) -> None:
    token = get_settings().admin_token
    if not token:
        raise HTTPException(404, "admin endpoints disabled; set ADMIN_TOKEN")
    if not authorization or not secrets.compare_digest(authorization, f"Bearer {token}"):
        raise HTTPException(401, "bad token")


@app.get("/", include_in_schema=False)
def web_app():
    """The browse/compare web app. Everything else on this server is the JSON API."""
    return FileResponse(WEB_DIR / "index.html")


@app.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok"}


SortKey = Literal["price", "-price", "range", "-range", "battery", "-battery", "name"]
_SORTS = {
    "price": Vehicle.price_min_inr.asc().nulls_last(),
    "-price": Vehicle.price_min_inr.desc().nulls_last(),
    "range": Vehicle.range_km.asc().nulls_last(),
    "-range": Vehicle.range_km.desc().nulls_last(),
    "battery": Vehicle.battery_kwh.asc().nulls_last(),
    "-battery": Vehicle.battery_kwh.desc().nulls_last(),
}


@app.get("/vehicles", response_model=Page)
def list_vehicles(
    db: Session = Depends(get_db),
    market: str | None = Query(None, description="Defaults to this deployment's MARKET (IN)"),
    make: str | None = None,
    q: str | None = Query(None, description="Search make, model or variant"),
    body_type: str | None = None,
    min_price_inr: float | None = None,
    max_price_inr: float | None = None,
    min_range_km: float | None = None,
    min_battery_kwh: float | None = None,
    vehicle_type: str | None = "car",
    sort: SortKey = "name",
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    stmt = select(Vehicle).where(Vehicle.market == (market or get_settings().market).upper())
    if make:
        stmt = stmt.where(func.lower(Vehicle.make) == make.lower())
    if body_type:
        stmt = stmt.where(func.lower(Vehicle.body_type) == body_type.lower())
    if vehicle_type:
        stmt = stmt.where(Vehicle.vehicle_type == vehicle_type)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(Vehicle.make).like(like), func.lower(Vehicle.model).like(like),
                              func.lower(Vehicle.variant).like(like)))
    if min_price_inr is not None:
        stmt = stmt.where(Vehicle.price_min_inr >= min_price_inr)
    if max_price_inr is not None:
        stmt = stmt.where(Vehicle.price_min_inr <= max_price_inr)
    if min_range_km is not None:
        stmt = stmt.where(Vehicle.range_km >= min_range_km)
    if min_battery_kwh is not None:
        stmt = stmt.where(Vehicle.battery_kwh >= min_battery_kwh)

    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    order = [_SORTS[sort]] if sort in _SORTS else []
    order += [Vehicle.make, Vehicle.model, Vehicle.variant]
    items = db.scalars(stmt.order_by(*order).limit(limit).offset(offset)).all()
    return Page(total=total or 0, limit=limit, offset=offset, items=items)


@app.get("/vehicles/{slug}", response_model=VehicleDetail)
def get_vehicle(slug: str, db: Session = Depends(get_db)):
    v = db.scalar(select(Vehicle).where(Vehicle.slug == slug).options(selectinload(Vehicle.records)))
    if not v:
        raise HTTPException(404, "vehicle not found")
    return v


@app.get("/compare", response_model=list[VehicleOut])
def compare(slugs: str = Query(..., description="Comma-separated slugs, up to 4"), db: Session = Depends(get_db)):
    wanted = [s.strip() for s in slugs.split(",") if s.strip()][:4]
    found = {v.slug: v for v in db.scalars(select(Vehicle).where(Vehicle.slug.in_(wanted)))}
    missing = [s for s in wanted if s not in found]
    if missing:
        raise HTTPException(404, f"not found: {', '.join(missing)}")
    return [found[s] for s in wanted]


class PhotoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    make: str
    model: str
    status: str
    image_url: str | None
    page_url: str | None
    author: str | None
    license: str | None
    license_url: str | None
    file: str | None
    chosen_by: str


@app.get("/photos", response_model=list[PhotoOut])
def photos(all: bool = Query(False, description="Include models with no usable photo, for review"),
           db: Session = Depends(get_db)):
    """One freely licensed photo per model, with the credit the app must show next to it."""
    stmt = select(ModelPhoto).order_by(ModelPhoto.make, ModelPhoto.model)
    if not all:
        stmt = stmt.where(ModelPhoto.status == "ok")
    return db.scalars(stmt).all()


@app.get("/makes")
def makes(market: str | None = None, db: Session = Depends(get_db)):
    stmt = (select(Vehicle.make, func.count())
            .where(Vehicle.market == (market or get_settings().market).upper())
            .group_by(Vehicle.make).order_by(Vehicle.make))
    return [{"make": m, "variants": n} for m, n in db.execute(stmt)]


@app.get("/sources")
def sources(db: Session = Depends(get_db)):
    counts = dict(db.execute(select(SpecRecord.source, func.count()).group_by(SpecRecord.source)).all())
    enabled = get_settings().source_list
    return [
        {"name": name, "license": cls.license, "enabled": name in enabled, "records": counts.get(name, 0)}
        for name, cls in REGISTRY.items()
    ]


@app.get("/ingest/runs", response_model=list[IngestRunOut])
def ingest_runs(limit: int = Query(20, le=100), db: Session = Depends(get_db)):
    return db.scalars(select(IngestRun).order_by(IngestRun.id.desc()).limit(limit)).all()


@app.post("/admin/ingest", status_code=202, dependencies=[Depends(require_admin)])
def trigger_ingest(background: BackgroundTasks, source: str | None = None):
    if source and source not in REGISTRY:
        raise HTTPException(400, f"unknown source {source}")

    def _job():
        with session_scope() as db:
            run_full_update(db, [source] if source else None)

    background.add_task(_job)
    return {"queued": source or "all"}
