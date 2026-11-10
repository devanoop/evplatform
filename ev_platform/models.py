"""Database tables.

vehicles        one row per buyable variant (make + model + variant + market), holding the merged specs
spec_records    one row per (vehicle, source): the raw values each source reported, for provenance
ingest_runs     one row per source per ingest run, with counts and errors
"""

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Vehicle(Base):
    __tablename__ = "vehicles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    market: Mapped[str] = mapped_column(String(8), index=True)  # IN, EU, US, GLOBAL
    make: Mapped[str] = mapped_column(String(80), index=True)
    model: Mapped[str] = mapped_column(String(120), index=True)
    variant: Mapped[str] = mapped_column(String(160), default="")
    body_type: Mapped[str | None] = mapped_column(String(40))
    vehicle_type: Mapped[str] = mapped_column(String(20), default="car")
    model_year: Mapped[int | None] = mapped_column(Integer)

    battery_kwh: Mapped[float | None] = mapped_column(Float)
    battery_chemistry: Mapped[str | None] = mapped_column(String(20))
    range_km: Mapped[float | None] = mapped_column(Float, index=True)
    range_standard: Mapped[str | None] = mapped_column(String(30))  # MIDC, ARAI, WLTP, EPA
    power_kw: Mapped[float | None] = mapped_column(Float)
    torque_nm: Mapped[float | None] = mapped_column(Float)
    drivetrain: Mapped[str | None] = mapped_column(String(10))
    dc_charge_max_kw: Mapped[float | None] = mapped_column(Float)
    ac_charge_max_kw: Mapped[float | None] = mapped_column(Float)
    dc_charge_time_note: Mapped[str | None] = mapped_column(String(200))
    efficiency_wh_per_km: Mapped[float | None] = mapped_column(Float)

    price_min_inr: Mapped[float | None] = mapped_column(Float, index=True)
    price_max_inr: Mapped[float | None] = mapped_column(Float)
    price_note: Mapped[str | None] = mapped_column(Text)

    extra: Mapped[dict] = mapped_column(JSON, default=dict)
    field_sources: Mapped[dict] = mapped_column(JSON, default=dict)  # field -> source name
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    records: Mapped[list["SpecRecord"]] = relationship(
        back_populates="vehicle", cascade="all, delete-orphan"
    )


class SpecRecord(Base):
    __tablename__ = "spec_records"
    __table_args__ = (UniqueConstraint("vehicle_id", "source", name="uq_record_vehicle_source"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(40), index=True)
    source_url: Mapped[str | None] = mapped_column(Text)
    source_ref: Mapped[str | None] = mapped_column(String(200))  # id inside the source dataset
    license: Mapped[str | None] = mapped_column(String(120))
    values: Mapped[dict] = mapped_column(JSON, default=dict)
    checksum: Mapped[str] = mapped_column(String(64))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    vehicle: Mapped[Vehicle] = relationship(back_populates="records")


class IngestRun(Base):
    __tablename__ = "ingest_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(20), default="running")  # running, ok, failed, skipped
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stats: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text)


class ModelPhoto(Base):
    """One freely licensed photo per car model (not per variant), with what's needed to credit it.

    status is "ok" (photo found), "none" (searched, nothing usable) or "blocked" (a human said
    not to use any photo for this model)."""

    __tablename__ = "model_photos"
    __table_args__ = (UniqueConstraint("make", "model", name="uq_photo_make_model"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    make: Mapped[str] = mapped_column(String(80))
    model: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(10), default="none")
    file: Mapped[str | None] = mapped_column(String(300))       # "File:Tata Nexon EV 2023.jpg"
    image_url: Mapped[str | None] = mapped_column(Text)          # resized thumbnail to show
    page_url: Mapped[str | None] = mapped_column(Text)           # Commons description page
    author: Mapped[str | None] = mapped_column(String(300))
    license: Mapped[str | None] = mapped_column(String(80))
    license_url: Mapped[str | None] = mapped_column(Text)
    chosen_by: Mapped[str] = mapped_column(String(10), default="search")  # search | curated
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
