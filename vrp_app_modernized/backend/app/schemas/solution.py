from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class RouteRead(BaseModel):
    nodes: list[int]
    address_ids: list[str] = Field(default_factory=list)
    stop_labels: list[str] = Field(default_factory=list)
    route_load: float | None = None
    capacity: float | None = None
    utilization: float | None = None
    customer_count: int | None = None
    starts_at_depot: bool = True
    ends_at_depot: bool = True
    vehicle_label: str | None = None
    vehicle_type_id: str | None = None
    route_distance: float | None = None
    route_time: float | None = None
    route_cost: float | None = None
    fixed_cost: float | None = None
    variable_cost: float | None = None


class SolutionRead(BaseModel):
    id: str
    project_id: str
    solver_key: str
    summary: dict = Field(default_factory=dict)
    routes: list[RouteRead] = Field(default_factory=list)
    analytics: dict = Field(default_factory=dict)
    raw_payload: dict = Field(default_factory=dict)
    created_at: datetime
