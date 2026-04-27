from __future__ import annotations

import contextlib
import math
import re
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

from ..schemas import FleetUnit, LocationRecord


def _resolve_root_dir() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parents[2]


ROOT_DIR = _resolve_root_dir()
BLOODHOUND_SOURCE = ROOT_DIR / "research" / "algorithms" / "Bloodhound_Optimizer_VRP"

_LEGACY_BLOODHOUND = None
HUNT_LINE_RE = re.compile(
    r"Hunt\s+(?P<current>\d+)/(?P<total>\d+)\s+\|\s+alpha=(?P<alpha>\d+)\s+\|\s+"
    r"hunt_best=(?P<hunt_best>[-+]?\d*\.?\d+)\s+\|\s+global_best=(?P<global_best>[-+]?\d*\.?\d+)"
)


def load_legacy_bloodhound():
    global _LEGACY_BLOODHOUND
    if _LEGACY_BLOODHOUND is None:
        _LEGACY_BLOODHOUND = SourceFileLoader(
            "vrp_app_final_legacy_bloodhound",
            str(BLOODHOUND_SOURCE),
        ).load_module()
    return _LEGACY_BLOODHOUND


class _ProgressWriter:
    def __init__(self, progress_callback=None) -> None:
        self._progress_callback = progress_callback
        self._buffer = ""

    def write(self, text: str) -> int:
        if not text:
            return 0
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self._emit(line.strip())
        return len(text)

    def flush(self) -> None:
        if self._buffer.strip():
            self._emit(self._buffer.strip())
        self._buffer = ""

    def _emit(self, line: str) -> None:
        if not line or self._progress_callback is None:
            return
        payload = {"phase": "bloodhound_log", "message": line}
        match = HUNT_LINE_RE.search(line)
        if match:
            payload.update(
                {
                    "current_hunt": int(match.group("current")),
                    "total_hunts": int(match.group("total")),
                    "alpha_index": int(match.group("alpha")),
                    "hunt_best": float(match.group("hunt_best")),
                    "global_best": float(match.group("global_best")),
                }
            )
        self._progress_callback(payload)


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
    progress_callback=None,
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
        "verbose": True,
    }
    if solver_params:
        params.update(solver_params)
    if progress_callback is not None:
        params["verbose"] = True
    if progress_callback is None:
        return legacy.run_bloodhound_hcvrp(problem=problem, **params)

    writer = _ProgressWriter(progress_callback=progress_callback)
    with contextlib.redirect_stdout(writer):
        result = legacy.run_bloodhound_hcvrp(problem=problem, **params)
    writer.flush()
    return result
