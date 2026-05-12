from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AddressBase(BaseModel):
    label: str
    address_line: str
    demand: float = 1.0
    is_depot: bool = False
    latitude: float | None = None
    longitude: float | None = None
    service_time_min: float = 0.0
    time_window_start_min: float | None = None
    time_window_end_min: float | None = None
    notes: str | None = None

    @field_validator("demand", "service_time_min")
    @classmethod
    def non_negative_numbers(cls, value: float) -> float:
        if value < 0:
            raise ValueError("Demand and service time must be non-negative.")
        return value


class AddressCreate(AddressBase):
    pass


class AddressUpdate(AddressBase):
    id: str | None = None


class AddressRead(AddressBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    geocode_status: str
    geocode_provider: str | None = None


class FleetUnitBase(BaseModel):
    vehicle_type_id: str
    label: str
    count: int = Field(ge=1)
    capacity: float = Field(gt=0)
    fixed_cost: float = Field(ge=0)
    cost_per_km: float = Field(ge=0)
    speed_kmh: float = Field(gt=0, default=35.0)
    max_route_distance_km: float | None = Field(default=None, gt=0)
    max_route_time_min: float | None = Field(default=None, gt=0)


class FleetUnitCreate(FleetUnitBase):
    pass


class FleetUnitUpdate(FleetUnitBase):
    id: str | None = None


class FleetUnitRead(FleetUnitBase):
    model_config = ConfigDict(from_attributes=True)

    id: str


class ProjectCreate(BaseModel):
    name: str
    description: str | None = None
    settings: dict = Field(default_factory=dict)
    addresses: list[AddressCreate] = Field(default_factory=list)
    fleet_units: list[FleetUnitCreate] = Field(default_factory=list)


class ProjectUpdate(BaseModel):
    name: str
    description: str | None = None
    settings: dict = Field(default_factory=dict)
    addresses: list[AddressUpdate] = Field(default_factory=list)
    fleet_units: list[FleetUnitUpdate] = Field(default_factory=list)


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


class ProjectSolutionSummary(BaseModel):
    id: str
    solver_key: str
    summary: dict = Field(default_factory=dict)
    analytics: dict = Field(default_factory=dict)
    created_at: datetime
