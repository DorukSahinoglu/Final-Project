from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class AddressCreate(BaseModel):
    label: str
    address_line: str
    demand: float = 1.0
    is_depot: bool = False
    latitude: float | None = None
    longitude: float | None = None
    service_time_min: float = 0.0
    time_window_start_min: float | None = None
    time_window_end_min: float | None = None


class AddressRead(AddressCreate):
    model_config = ConfigDict(from_attributes=True)

    id: str
    geocode_status: str
    geocode_provider: str | None = None


class FleetUnitCreate(BaseModel):
    vehicle_type_id: str
    label: str
    count: int = Field(ge=1)
    capacity: float = Field(gt=0)
    fixed_cost: float = Field(ge=0)
    cost_per_km: float = Field(ge=0)
    speed_kmh: float = Field(gt=0, default=35.0)


class FleetUnitRead(FleetUnitCreate):
    model_config = ConfigDict(from_attributes=True)

    id: str


class ProjectCreate(BaseModel):
    name: str
    description: str | None = None
    settings: dict = Field(default_factory=dict)
    addresses: list[AddressCreate] = Field(default_factory=list)
    fleet_units: list[FleetUnitCreate] = Field(default_factory=list)


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str | None
    status: str
    settings: dict
    addresses: list[AddressRead]
    fleet_units: list[FleetUnitRead]


class ProjectSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str | None
    status: str
