from __future__ import annotations

import sys
from dataclasses import asdict
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from vrp_app_final.schemas import (
    CustomerDemand,
    FleetUnit,
    LocationRecord,
    SolverConfig,
    SolverKey,
    TimeWindow,
    VRPProblemData,
)
from vrp_app_final.solver_contracts import BloodhoundAdapter, NSGA2Adapter

from app.db import models
from app.utils.analytics import build_solution_analytics, ensure_solution_summary


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
        selected_address_ids: list[str],
        progress_callback,
        stop_flag,
    ) -> dict:
        adapter = self._adapters[solver_key]
        problem, selected_addresses, selection_metadata = self._build_problem(project, matrix, solver_key, solver_params, selected_address_ids)
        result = adapter.solve(problem=problem, progress_callback=progress_callback, stop_flag=stop_flag)

        solution_payloads = [
            self._build_solution_payload(
                solution=solution,
                ordered_addresses=selected_addresses,
                fleet_units=list(project.fleet_units),
                solver_key=solver_key,
                result=result,
                selection_metadata=selection_metadata,
            )
            for solution in result.solutions
        ]
        primary_solution = solution_payloads[0] if solution_payloads else None
        return {
            "solver_key": solver_key,
            "problem_type": result.problem_type.value,
            "is_multiobjective": result.is_multiobjective,
            "objective_names": result.objective_names,
            "warnings": result.warnings,
            "metadata": result.metadata,
            "solutions": solution_payloads,
            "debug": {
                "algorithm_name": "NSGA-II" if solver_key == "nsga2" else "Bloodhound",
                "raw_solver_output": [item["raw_payload"].get("raw_result", {}) for item in solution_payloads],
                "normalized_output": [
                    {
                        "summary": item["summary"],
                        "analytics": item["analytics"],
                    }
                    for item in solution_payloads
                ],
            },
            "primary_solution": {
                "summary": {
                    "solution_id": primary_solution["summary"]["solution_id"] if primary_solution else None,
                    "total_cost": primary_solution["summary"]["total_cost"] if primary_solution else 0.0,
                    "objectives": primary_solution["summary"]["objectives"] if primary_solution else {},
                    "notes": primary_solution["summary"]["notes"] if primary_solution else [],
                    "warnings": result.warnings,
                    "problem_type": result.problem_type.value,
                    "metadata": result.metadata,
                    "selected_address_ids": selection_metadata["selected_address_ids"],
                    "selected_address_labels": selection_metadata["selected_address_labels"],
                    "selected_customer_count": selection_metadata["selected_customer_count"],
                    "matrix_subset_size": selection_metadata["matrix_subset_size"],
                    "is_multiobjective": result.is_multiobjective,
                    "solution_count": len(solution_payloads),
                },
                "routes": primary_solution["routes"] if primary_solution else [],
                "analytics": primary_solution["analytics"] if primary_solution else {},
                "raw_payload": primary_solution["raw_payload"] if primary_solution else {},
            },
        }

    def _build_problem(self, project: models.Project, matrix: models.MatrixSnapshot, solver_key: str, solver_params: dict, selected_address_ids: list[str]) -> tuple[VRPProblemData, list[models.Address], dict]:
        ordered_addresses = sorted(project.addresses, key=lambda item: (not item.is_depot, item.created_at))
        from app.utils.json import loads

        distance_matrix = loads(matrix.distance_matrix_json, [])
        time_matrix = loads(matrix.time_matrix_json, [])
        if len(distance_matrix) != len(ordered_addresses) or len(time_matrix) != len(ordered_addresses):
            raise ValueError(
                f"Matrix size mismatch. Project has {len(ordered_addresses)} addresses but matrix snapshot has "
                f"{len(distance_matrix)} distance rows and {len(time_matrix)} time rows."
            )

        subset_addresses = self._select_addresses_for_run(ordered_addresses, selected_address_ids)
        index_by_address_id = {item.id: index for index, item in enumerate(ordered_addresses)}
        subset_indices = [index_by_address_id[item.id] for item in subset_addresses]
        subset_distance_matrix = self._build_submatrix(distance_matrix, subset_indices)
        subset_time_matrix = self._build_submatrix(time_matrix, subset_indices)

        locations = [
            LocationRecord(
                node_id=index,
                name=item.label,
                address=item.address_line,
                lat=item.latitude,
                lon=item.longitude,
                is_depot=item.is_depot,
            )
            for index, item in enumerate(subset_addresses)
        ]
        effective_demands = [
            (0.0 if item.is_depot else (1.0 if solver_key == "nsga2" else item.demand))
            for item in subset_addresses
        ]
        demands = [CustomerDemand(node_id=index, demand=effective_demands[index]) for index in range(len(subset_addresses))]
        time_windows = [
            TimeWindow(
                node_id=index,
                start_min=(item.time_window_start_min or 0.0),
                end_min=(item.time_window_end_min if item.time_window_end_min is not None else float("inf")),
            )
            for index, item in enumerate(subset_addresses)
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
        selection_metadata = {
            "selected_address_ids": [item.id for item in subset_addresses],
            "selected_address_labels": [item.label for item in subset_addresses],
            "selected_customer_count": sum(1 for item in subset_addresses if not item.is_depot),
            "matrix_subset_size": len(subset_addresses),
        }

        return VRPProblemData(
            locations=locations,
            distance_matrix=subset_distance_matrix,
            time_matrix=subset_time_matrix,
            demands=demands,
            fleet=fleet,
            time_windows=time_windows,
            solver_config=solver_config,
        ), subset_addresses, selection_metadata

    def _build_solution_payload(self, solution, ordered_addresses: list[models.Address], fleet_units: list[models.FleetUnit], solver_key: str, result, selection_metadata: dict) -> dict:
        routes = self._build_route_payloads(
            routes=solution.routes,
            ordered_addresses=ordered_addresses,
            fleet_units=fleet_units,
            solver_key=solver_key,
        )
        analytics = build_solution_analytics(routes=routes, total_cost=solution.total_cost)
        return {
            "summary": ensure_solution_summary(
                {
                    "solution_id": solution.solution_id,
                    "total_cost": solution.total_cost,
                    "objectives": solution.objectives,
                    "notes": solution.notes,
                    "warnings": result.warnings,
                    "problem_type": result.problem_type.value,
                    "metadata": result.metadata,
                    "selected_address_ids": selection_metadata["selected_address_ids"],
                    "selected_address_labels": selection_metadata["selected_address_labels"],
                    "selected_customer_count": selection_metadata["selected_customer_count"],
                    "matrix_subset_size": selection_metadata["matrix_subset_size"],
                    "is_multiobjective": result.is_multiobjective,
                },
                solver_key=solver_key,
                total_cost=solution.total_cost,
            ),
            "routes": routes,
            "analytics": analytics,
            "raw_payload": solution.raw_payload,
        }

    def _select_addresses_for_run(self, ordered_addresses: list[models.Address], selected_address_ids: list[str]) -> list[models.Address]:
        depot = next((item for item in ordered_addresses if item.is_depot), None)
        if depot is None:
            raise ValueError("A depot is required before running optimization.")
        if not selected_address_ids:
            subset = ordered_addresses
        else:
            selected_set = set(selected_address_ids)
            selected_set.add(depot.id)
            unknown = [item_id for item_id in selected_address_ids if item_id not in {address.id for address in ordered_addresses}]
            if unknown:
                raise ValueError(f"Selected addresses are not part of the current project: {', '.join(unknown)}")
            subset = [item for item in ordered_addresses if item.id in selected_set]
        if sum(1 for item in subset if not item.is_depot) == 0:
            raise ValueError("Select at least one customer before running optimization.")
        return subset

    def _build_submatrix(self, matrix: list[list[float]], indices: list[int]) -> list[list[float]]:
        return [[float(matrix[row][col]) for col in indices] for row in indices]

    def _build_route_payloads(self, routes, ordered_addresses: list[models.Address], fleet_units: list[models.FleetUnit], solver_key: str) -> list[dict]:
        depot_index = next((index for index, item in enumerate(ordered_addresses) if item.is_depot), 0)
        addresses_by_index = {index: item for index, item in enumerate(ordered_addresses)}
        fleet_by_type = {item.vehicle_type_id: item for item in fleet_units}
        route_payloads: list[dict] = []

        for route in routes:
            raw_nodes = list(route.nodes)
            customer_indices = [node for node in raw_nodes if node != depot_index]
            sequence_indices = [depot_index, *customer_indices, depot_index]
            stop_labels = [addresses_by_index[node].label for node in sequence_indices if node in addresses_by_index]
            address_ids = [addresses_by_index[node].id for node in sequence_indices if node in addresses_by_index]
            fleet = fleet_by_type.get(route.vehicle_type_id or "")
            effective_load = sum(0.0 if addresses_by_index[node].is_depot else 1.0 if solver_key == "nsga2" else addresses_by_index[node].demand for node in customer_indices)
            capacity = fleet.capacity if fleet else None

            route_payloads.append(
                {
                    **asdict(route),
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
