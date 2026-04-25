from __future__ import annotations

import math
from importlib.machinery import SourceFileLoader
from pathlib import Path

from ..schemas import FleetUnit, LocationRecord


ROOT_DIR = Path(__file__).resolve().parents[2]
BLOODHOUND_SOURCE = ROOT_DIR / "research" / "algorithms" / "Bloodhound_Optimizer_VRP"

_LEGACY_BLOODHOUND = None


def load_legacy_bloodhound():
    global _LEGACY_BLOODHOUND
    if _LEGACY_BLOODHOUND is None:
        _LEGACY_BLOODHOUND = SourceFileLoader(
            "vrp_app_final_legacy_bloodhound",
            str(BLOODHOUND_SOURCE),
        ).load_module()
    return _LEGACY_BLOODHOUND


class MatrixBackedHCVRPProblem:
    def __init__(
        self,
        coords: list[tuple[float, float]],
        demands: list[float],
        vehicles: list,
        time_windows: list[tuple[float, float]] | None = None,
        service_times: list[float] | None = None,
        distance_matrix: list[list[float]] | None = None,
        time_matrix: list[list[float]] | None = None,
    ) -> None:
        self.coords = coords
        self.demands = demands
        self.vehicles = vehicles
        self.time_windows = time_windows or [(0.0, float("inf")) for _ in coords]
        self.service_times = service_times or [0.0 for _ in coords]
        self.n_nodes = len(coords)
        self.customer_ids = list(range(1, self.n_nodes))

        if len(self.demands) != self.n_nodes:
            raise ValueError("Demand vector length must match the number of nodes.")
        if not self.vehicles:
            raise ValueError("At least one vehicle must be defined.")
        if len(self.time_windows) != self.n_nodes:
            raise ValueError("time_windows length must match the number of nodes.")
        if len(self.service_times) != self.n_nodes:
            raise ValueError("service_times length must match the number of nodes.")

        self.dist = distance_matrix or self.build_tsplib_euc2d_matrix(coords)
        self.time_matrix = time_matrix

    @staticmethod
    def build_tsplib_euc2d_matrix(coords: list[tuple[float, float]]) -> list[list[float]]:
        n = len(coords)
        dist = [[0.0] * n for _ in range(n)]
        for i in range(n):
            x1, y1 = coords[i]
            for j in range(n):
                x2, y2 = coords[j]
                dx = x1 - x2
                dy = y1 - y2
                dist[i][j] = int(math.sqrt(dx * dx + dy * dy) + 0.5)
        return dist

    def route_distance(self, route: list[int]) -> float:
        total = 0.0
        for i in range(len(route) - 1):
            total += self.dist[route[i]][route[i + 1]]
        return total

    def travel_time(self, from_node: int, to_node: int, vehicle) -> float:
        if self.time_matrix is not None:
            return self.time_matrix[from_node][to_node]
        if vehicle.speed <= 0:
            raise ValueError("Vehicle speed must be positive.")
        return self.dist[from_node][to_node] / vehicle.speed

    def route_load(self, route: list[int]) -> float:
        return sum(self.demands[node] for node in route)

    def customers_covered_once(self, routes: list[list[int]]) -> bool:
        seen: list[int] = []
        for route in routes:
            for node in route:
                if node != 0:
                    seen.append(node)
        return sorted(seen) == self.customer_ids


def expand_fleet_units(fleet: list[FleetUnit]) -> list:
    legacy = load_legacy_bloodhound()
    vehicles = []
    vehicle_id = 0
    for unit in fleet:
        for _ in range(unit.count):
            vehicles.append(
                legacy.Vehicle(
                    vehicle_id=vehicle_id,
                    capacity=unit.capacity,
                    cost_per_km=unit.cost_per_km,
                    fixed_cost=unit.fixed_cost,
                    speed=unit.speed_kmh if unit.speed_kmh is not None else 1.0,
                )
            )
            vehicle_id += 1
    return vehicles


def build_coords(locations: list[LocationRecord]) -> list[tuple[float, float]]:
    coords: list[tuple[float, float]] = []
    for location in locations:
        if location.lat is not None and location.lon is not None:
            coords.append((location.lat, location.lon))
        else:
            coords.append((0.0, 0.0))
    return coords


def run_bloodhound_with_matrices(
    locations: list[LocationRecord],
    distance_matrix: list[list[float]],
    time_matrix: list[list[float]] | None,
    demands: list[float],
    fleet: list[FleetUnit],
    time_windows: list[tuple[float, float]] | None = None,
    service_times: list[float] | None = None,
    solver_params: dict | None = None,
):
    legacy = load_legacy_bloodhound()
    vehicles = expand_fleet_units(fleet)
    coords = build_coords(locations)
    problem = MatrixBackedHCVRPProblem(
        coords=coords,
        demands=demands,
        vehicles=vehicles,
        time_windows=time_windows,
        service_times=service_times,
        distance_matrix=distance_matrix,
        time_matrix=time_matrix,
    )
    params = {
        "num_wolves": 12,
        "num_hunts": 20,
        "explore_iterations": 120,
        "reserve_blood": 2.0,
        "lambda_reg": 0.30,
        "a": 1.5,
        "b": 2.0,
        "c": 1.0,
        "b_par": 1.2,
        "inherit_frac": 0.35,
        "ruin_frac": 0.20,
        "rr_repeats": 2,
        "verbose": False,
    }
    if solver_params:
        params.update(solver_params)
    return legacy.run_bloodhound_hcvrp(problem=problem, **params)
