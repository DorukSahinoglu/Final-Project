from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Project(Base, TimestampMixin):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="draft")
    settings_json: Mapped[str] = mapped_column(Text, default="{}")

    addresses: Mapped[list["Address"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    fleet_units: Mapped[list["FleetUnit"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    matrices: Mapped[list["MatrixSnapshot"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    jobs: Mapped[list["Job"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    solutions: Mapped[list["Solution"]] = relationship(back_populates="project", cascade="all, delete-orphan")


class AppSetting(Base, TimestampMixin):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")


class Address(Base, TimestampMixin):
    __tablename__ = "addresses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(String(160))
    address_line: Mapped[str] = mapped_column(Text)
    demand: Mapped[float] = mapped_column(Float, default=1.0)
    is_depot: Mapped[bool] = mapped_column(Boolean, default=False)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    geocode_status: Mapped[str] = mapped_column(String(32), default="pending")
    geocode_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    service_time_min: Mapped[float] = mapped_column(Float, default=0.0)
    time_window_start_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    time_window_end_min: Mapped[float | None] = mapped_column(Float, nullable=True)

    project: Mapped[Project] = relationship(back_populates="addresses")


class FleetUnit(Base, TimestampMixin):
    __tablename__ = "fleet_units"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    vehicle_type_id: Mapped[str] = mapped_column(String(80))
    label: Mapped[str] = mapped_column(String(120))
    count: Mapped[int] = mapped_column(Integer)
    capacity: Mapped[float] = mapped_column(Float)
    fixed_cost: Mapped[float] = mapped_column(Float)
    cost_per_km: Mapped[float] = mapped_column(Float)
    speed_kmh: Mapped[float] = mapped_column(Float, default=35.0)
    max_route_distance_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_route_time_min: Mapped[float | None] = mapped_column(Float, nullable=True)

    project: Mapped[Project] = relationship(back_populates="fleet_units")


class MatrixSnapshot(Base, TimestampMixin):
    __tablename__ = "matrix_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="ready")
    provider: Mapped[str] = mapped_column(String(64), default="osrm")
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    distance_matrix_json: Mapped[str] = mapped_column(Text, default="[]")
    time_matrix_json: Mapped[str] = mapped_column(Text, default="[]")

    project: Mapped[Project] = relationship(back_populates="matrices")
    jobs: Mapped[list["Job"]] = relationship(back_populates="matrix_snapshot")


class Solution(Base, TimestampMixin):
    __tablename__ = "solutions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    solver_key: Mapped[str] = mapped_column(String(32))
    summary_json: Mapped[str] = mapped_column(Text, default="{}")
    routes_json: Mapped[str] = mapped_column(Text, default="[]")
    analytics_json: Mapped[str] = mapped_column(Text, default="{}")
    raw_payload_json: Mapped[str] = mapped_column(Text, default="{}")

    project: Mapped[Project] = relationship(back_populates="solutions")
    jobs: Mapped[list["Job"]] = relationship(back_populates="solution")


class Job(Base, TimestampMixin):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    matrix_snapshot_id: Mapped[str | None] = mapped_column(ForeignKey("matrix_snapshots.id", ondelete="SET NULL"), nullable=True)
    solution_id: Mapped[str | None] = mapped_column(ForeignKey("solutions.id", ondelete="SET NULL"), nullable=True)
    job_type: Mapped[str] = mapped_column(String(32))
    solver_key: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="queued")
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    logs_json: Mapped[str] = mapped_column(Text, default="[]")
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    error_json: Mapped[str] = mapped_column(Text, default="{}")
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    project: Mapped[Project] = relationship(back_populates="jobs")
    matrix_snapshot: Mapped[MatrixSnapshot | None] = relationship(back_populates="jobs")
    solution: Mapped[Solution | None] = relationship(back_populates="jobs")
