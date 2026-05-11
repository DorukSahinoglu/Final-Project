from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from vrp_app_final.schemas import (
    CustomerDemand,
    FleetUnit,
    LocationRecord,
    ServiceTime,
    SolverConfig,
    SolverKey,
    TimeWindow,
    VRPProblemData,
)
from vrp_app_final.solver_contracts import BloodhoundAdapter, NSGA2Adapter

from app.db import models
from app.utils.analytics import build_solution_analytics


class SolverRuntimeService:
    def __init__(self) -> None:
        self._adapters = {
            "nsga2": NSGA2Adapter(),
            "bloodhound": BloodhoundAdapter(),
        }

    def run_solver(
        self,
        project: models.Project,
        matrix: models.MatrixSnapshot,
        solver_key: str,
        solver_params: dict,
        progress_callback,
        stop_flag,
    ) -> dict:
        adapter = self._adapters[solver_key]
        problem = self._build_problem(project, matrix, solver_key, solver_params)
        result = adapter.solve(problem=problem, progress_callback=progress_callback, stop_flag=stop_flag)

        primary_solution = result.solutions[0] if result.solutions else None
        routes = [route.__dict__ for route in (primary_solution.routes if primary_solution else [])]
        total_cost = primary_solution.total_cost if primary_solution else 0.0
        analytics = build_solution_analytics(routes=routes, total_cost=total_cost)
        return {
            "solver_key": solver_key,
            "problem_type": result.problem_type.value,
            "is_multiobjective": result.is_multiobjective,
            "objective_names": result.objective_names,
            "warnings": result.warnings,
            "metadata": result.metadata,
            "primary_solution": {
                "summary": {
                    "solution_id": primary_solution.solution_id if primary_solution else None,
                    "total_cost": total_cost,
                    "objectives": primary_solution.objectives if primary_solution else {},
                    "notes": primary_solution.notes if primary_solution else [],
                },
                "routes": routes,
                "analytics": analytics,
                "raw_payload": primary_solution.raw_payload if primary_solution else {},
            },
        }

    def _build_problem(self, project: models.Project, matrix: models.MatrixSnapshot, solver_key: str, solver_params: dict) -> VRPProblemData:
        del solver_key, solver_params
        ordered_addresses = sorted(project.addresses, key=lambda item: (not item.is_depot, item.created_at))
        locations = [
            LocationRecord(
                node_id=index,
                name=item.label,
                address=item.address_line,
                lat=item.latitude,
                lon=item.longitude,
                is_depot=item.is_depot,
            )
            for index, item in enumerate(ordered_addresses)
        ]
        demands = [CustomerDemand(node_id=index, demand=(0.0 if item.is_depot else item.demand)) for index, item in enumerate(ordered_addresses)]
        time_windows = [
            TimeWindow(
                node_id=index,
                start_min=(item.time_window_start_min or 0.0),
                end_min=(item.time_window_end_min if item.time_window_end_min is not None else float("inf")),
            )
            for index, item in enumerate(ordered_addresses)
        ]
        service_times = [
            ServiceTime(node_id=index, duration_min=item.service_time_min)
            for index, item in enumerate(ordered_addresses)
        ]
        fleet = [
            FleetUnit(
                vehicle_type_id=item.vehicle_type_id,
                label=item.label,
                count=item.count,
                capacity=item.capacity,
                fixed_cost=item.fixed_cost,
                cost_per_km=item.cost_per_km,
                speed_kmh=item.speed_kmh,
            )
            for item in project.fleet_units
        ]
        solver_config = SolverConfig(
            solver_key=SolverKey.NSGA2 if solver_key == "nsga2" else SolverKey.BLOODHOUND,
            params=solver_params,
        )

        from app.utils.json import loads

        return VRPProblemData(
            locations=locations,
            distance_matrix=loads(matrix.distance_matrix_json, []),
            time_matrix=loads(matrix.time_matrix_json, []),
            demands=demands,
            fleet=fleet,
            time_windows=time_windows,
            service_times=service_times,
            solver_config=solver_config,
        )
