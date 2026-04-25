from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ProblemType(str, Enum):
    HOMOGENEOUS = "homogeneous"
    HETEROGENEOUS = "heterogeneous"


class SolverKey(str, Enum):
    NSGA2 = "nsga2"
    BLOODHOUND = "bloodhound"


@dataclass(slots=True)
class LocationRecord:
    node_id: int
    name: str
    address: str
    lat: float | None = None
    lon: float | None = None
    is_depot: bool = False


@dataclass(slots=True)
class FleetUnit:
    vehicle_type_id: str
    label: str
    count: int
    capacity: float
    fixed_cost: float
    cost_per_km: float
    speed_kmh: float | None = None


@dataclass(slots=True)
class CustomerDemand:
    node_id: int
    demand: float


@dataclass(slots=True)
class TimeWindow:
    node_id: int
    start_min: float
    end_min: float


@dataclass(slots=True)
class ServiceTime:
    node_id: int
    duration_min: float


@dataclass(slots=True)
class SolverConfig:
    solver_key: SolverKey
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class VRPProblemData:
    locations: list[LocationRecord]
    distance_matrix: list[list[float]]
    time_matrix: list[list[float]]
    demands: list[CustomerDemand]
    fleet: list[FleetUnit]
    time_windows: list[TimeWindow] = field(default_factory=list)
    service_times: list[ServiceTime] = field(default_factory=list)
    solver_config: SolverConfig | None = None

    def infer_problem_type(self) -> ProblemType:
        if not self.fleet:
            raise ValueError("Fleet cannot be empty.")

        signature = {
            (
                unit.capacity,
                unit.fixed_cost,
                unit.cost_per_km,
                unit.speed_kmh,
            )
            for unit in self.fleet
        }
        return (
            ProblemType.HOMOGENEOUS
            if len(signature) == 1
            else ProblemType.HETEROGENEOUS
        )

    def customer_node_ids(self) -> list[int]:
        return [loc.node_id for loc in self.locations if not loc.is_depot]


@dataclass(slots=True)
class RouteResult:
    nodes: list[int]
    vehicle_label: str | None = None
    vehicle_type_id: str | None = None
    route_distance: float | None = None
    route_time: float | None = None
    route_cost: float | None = None
    fixed_cost: float | None = None
    variable_cost: float | None = None


@dataclass(slots=True)
class SolutionResult:
    solution_id: str
    objectives: dict[str, float]
    total_cost: float
    routes: list[RouteResult]
    feasible: bool = True
    notes: list[str] = field(default_factory=list)
    raw_payload: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SolverResult:
    solver_key: SolverKey
    problem_type: ProblemType
    is_multiobjective: bool
    objective_names: list[str]
    solutions: list[SolutionResult]
    metadata: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
