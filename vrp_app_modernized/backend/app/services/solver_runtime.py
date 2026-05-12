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
        ordered_addresses = sorted(project.addresses, key=lambda item: (not item.is_depot, item.created_at))
        routes = self._build_route_payloads(
            routes=(primary_solution.routes if primary_solution else []),
            ordered_addresses=ordered_addresses,
            fleet_units=list(project.fleet_units),
            solver_key=solver_key,
        )
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
                    "warnings": result.warnings,
                    "problem_type": result.problem_type.value,
                    "metadata": result.metadata,
                    "is_multiobjective": result.is_multiobjective,
                },
                "routes": routes,
                "analytics": analytics,
                "raw_payload": primary_solution.raw_payload if primary_solution else {},
            },
        }

    def _build_problem(self, project: models.Project, matrix: models.MatrixSnapshot, solver_key: str, solver_params: dict) -> VRPProblemData:
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
        effective_demands = [
            (0.0 if item.is_depot else (1.0 if solver_key == "nsga2" else item.demand))
            for item in ordered_addresses
        ]
        demands = [CustomerDemand(node_id=index, demand=effective_demands[index]) for index in range(len(ordered_addresses))]
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
        fleet_source = list(project.fleet_units)
        if solver_key == "nsga2" and fleet_source:
            representative = fleet_source[0]
            fleet_source = [
                models.FleetUnit(
                    id=representative.id,
                    project_id=representative.project_id,
                    vehicle_type_id=representative.vehicle_type_id,
                    label=representative.label,
                    count=sum(item.count for item in project.fleet_units),
                    capacity=representative.capacity,
                    fixed_cost=representative.fixed_cost,
                    cost_per_km=representative.cost_per_km,
                    speed_kmh=representative.speed_kmh,
                    max_route_distance_km=representative.max_route_distance_km,
                    max_route_time_min=representative.max_route_time_min,
                )
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
            for item in fleet_source
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

    def _build_route_payloads(self, routes, ordered_addresses: list[models.Address], fleet_units: list[models.FleetUnit], solver_key: str) -> list[dict]:
        depot_index = next((index for index, item in enumerate(ordered_addresses) if item.is_depot), 0)
        addresses_by_index = {index: item for index, item in enumerate(ordered_addresses)}
        fleet_by_type = {item.vehicle_type_id: item for item in fleet_units}
        route_payloads: list[dict] = []

        for route in routes:
            raw_nodes = list(route.nodes)
            customer_indices = [node for node in raw_nodes if node != depot_index]
            sequence_indices = raw_nodes if solver_key == "nsga2" else [depot_index, *customer_indices, depot_index]
            stop_labels = [addresses_by_index[node].label for node in sequence_indices if node in addresses_by_index]
            address_ids = [addresses_by_index[node].id for node in sequence_indices if node in addresses_by_index]
            fleet = fleet_by_type.get(route.vehicle_type_id or "")
            effective_load = sum(0.0 if addresses_by_index[node].is_depot else 1.0 if solver_key == "nsga2" else addresses_by_index[node].demand for node in customer_indices)
            capacity = fleet.capacity if fleet else None

            route_payloads.append(
                {
                    **route.__dict__,
                    "nodes": sequence_indices,
                    "address_ids": address_ids,
                    "stop_labels": stop_labels,
                    "route_load": round(effective_load, 3),
                    "capacity": capacity,
                    "utilization": round(effective_load / capacity, 4) if capacity else None,
                    "customer_count": len(customer_indices),
                    "starts_at_depot": bool(sequence_indices and sequence_indices[0] == depot_index),
                    "ends_at_depot": bool(sequence_indices and sequence_indices[-1] == depot_index),
                }
            )
        return route_payloads
