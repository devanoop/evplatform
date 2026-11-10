"""Ingest: run each source, store what it reported, then merge into one row per vehicle.

Merging is by source priority (the order of INGEST_SOURCES): for each field, the first
source in that order that has a non-null value wins, and Vehicle.field_sources records which
one. Hand-curated data therefore beats scraped data, which beats generic open datasets.
"""

import hashlib
import json
import logging
import traceback
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .models import IngestRun, SpecRecord, Vehicle, utcnow
from .sources import REGISTRY
from .sources.base import SPEC_FIELDS, VehicleSpec

log = logging.getLogger(__name__)


def _checksum(values: dict) -> str:
    return hashlib.sha256(json.dumps(values, sort_keys=True, default=str).encode()).hexdigest()


def store_specs(db: Session, source_name: str, license: str, specs: Iterable[VehicleSpec]) -> tuple[dict, set[int]]:
    stats = {"seen": 0, "created_vehicles": 0, "new_records": 0, "changed_records": 0, "unchanged": 0}
    touched: set[int] = set()
    vehicles = {v.slug: v for v in db.scalars(select(Vehicle))}
    records = {
        r.vehicle_id: r for r in db.scalars(select(SpecRecord).where(SpecRecord.source == source_name))
    }
    seen_slugs: set[str] = set()

    for spec in specs:
        stats["seen"] += 1
        slug = spec.slug
        if slug in seen_slugs and spec.model_year:
            # Same name twice in one dataset usually means different model years.
            spec.variant = f"{spec.variant} {spec.model_year}".strip()
            slug = spec.slug
        if slug in seen_slugs:
            stats.setdefault("duplicates_skipped", 0)
            stats["duplicates_skipped"] += 1
            continue
        seen_slugs.add(slug)

        vehicle = vehicles.get(slug)
        if vehicle is None:
            vehicle = Vehicle(slug=slug, market=spec.market, make=spec.make, model=spec.model,
                              variant=spec.variant, extra={}, field_sources={})
            db.add(vehicle)
            db.flush()
            vehicles[slug] = vehicle
            stats["created_vehicles"] += 1

        values = spec.model_dump(include=set(SPEC_FIELDS) | {"extra"})
        checksum = _checksum(values)
        now = utcnow()
        rec = records.get(vehicle.id)
        if rec is None:
            rec = SpecRecord(vehicle_id=vehicle.id, source=source_name, values=values, checksum=checksum,
                             source_url=spec.source_url, source_ref=spec.source_ref, license=license,
                             fetched_at=now, changed_at=now)
            db.add(rec)
            records[vehicle.id] = rec
            stats["new_records"] += 1
            touched.add(vehicle.id)
        elif rec.checksum != checksum:
            rec.values, rec.checksum, rec.changed_at = values, checksum, now
            rec.fetched_at, rec.source_url, rec.source_ref = now, spec.source_url, spec.source_ref
            stats["changed_records"] += 1
            touched.add(vehicle.id)
        else:
            rec.fetched_at = now
            stats["unchanged"] += 1
    db.flush()
    return stats, touched


def merge_vehicle(db: Session, vehicle: Vehicle, priority: list[str]) -> None:
    recs = sorted(vehicle.records, key=lambda r: priority.index(r.source) if r.source in priority else 99)
    field_sources: dict[str, str] = {}
    extra: dict = {}
    for f in SPEC_FIELDS:
        value = None
        for r in recs:
            v = r.values.get(f)
            if v is not None:
                value = v
                field_sources[f] = r.source
                break
        setattr(vehicle, f, value)
    for r in reversed(recs):  # higher-priority extras overwrite lower ones
        extra.update({k: v for k, v in (r.values.get("extra") or {}).items() if v is not None})
    vehicle.vehicle_type = vehicle.vehicle_type or "car"
    vehicle.extra = extra
    vehicle.field_sources = field_sources
    vehicle.updated_at = utcnow()


def run_ingest(db: Session, sources: list[str] | None = None, instances: dict | None = None) -> list[IngestRun]:
    """Run the given sources (default: INGEST_SOURCES). `instances` lets tests inject sources."""
    priority = get_settings().source_list
    names = sources or priority
    runs: list[IngestRun] = []
    touched: set[int] = set()

    for name in names:
        run = IngestRun(source=name, status="running", stats={})
        db.add(run)
        db.commit()
        try:
            src = (instances or {}).get(name) or REGISTRY[name]()
            stats, t = store_specs(db, name, src.license, src.fetch())
            skipped = getattr(src, "skipped", None)
            if skipped:
                stats["skipped"] = skipped[:50]
            run.status = "ok" if stats["seen"] or not skipped else "skipped"
            run.stats = stats
            touched |= t
            db.commit()
        except Exception as e:
            db.rollback()
            log.exception("source %s failed", name)
            run.status, run.error = "failed", f"{e}\n{traceback.format_exc()[-2000:]}"
        run.finished_at = utcnow()
        db.commit()
        runs.append(run)

    if touched:
        for v in db.scalars(select(Vehicle).where(Vehicle.id.in_(touched))):
            merge_vehicle(db, v, priority)
        db.commit()
    log.info("ingest finished: %s", [(r.source, r.status, r.stats) for r in runs])
    return runs


def run_full_update(db: Session, sources: list[str] | None = None) -> list[IngestRun]:
    """Ingest specs, then refresh car photos (unless ENABLE_PHOTOS=false or only some sources ran).

    A photo failure is logged, never fatal: specs matter more than pictures."""
    runs = run_ingest(db, sources)
    if get_settings().enable_photos and not sources:
        try:
            from .photos import refresh_photos

            refresh_photos(db)
        except Exception:
            db.rollback()
            log.exception("photo refresh failed")
    return runs
