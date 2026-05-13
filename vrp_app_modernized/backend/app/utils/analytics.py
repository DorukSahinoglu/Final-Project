from __future__ import annotations

from typing import Any


def normalize_routes_with_matrices(
    routes: list[dict[str, Any]],
    *,
    distance_matrix: list[list[float]] | None = None,
    time_matrix: list[list[float]] | None = None,
) -> list[dict[str, Any]]:
    if not routes:
        return []

    normalized_routes: list[dict[str, Any]] = []
    for route in routes:
        normalized = dict(route)
        nodes = route.get("nodes")
        if not isinstance(nodes, list) or len(nodes) < 2:
            normalized_routes.append(normalized)
            continue

        if distance_matrix and _can_use_matrix(nodes, distance_matrix):
            normalized["route_distance"] = round(_sum_route(nodes, distance_matrix), 6)
        if time_matrix and _can_use_matrix(nodes, time_matrix):
            normalized["route_time"] = round(_sum_route(nodes, time_matrix), 6)
        normalized_routes.append(normalized)
    return normalized_routes


def build_solution_analytics(routes: list[dict[str, Any]], total_cost: float) -> dict[str, Any]:
    route_count = len(routes)
    total_distance = sum((route.get("route_distance") or 0.0) for route in routes)
    total_time = sum((route.get("route_time") or 0.0) for route in routes)
    total_stops = sum(int(route.get("customer_count") or 0) for route in routes)
    total_load = sum(float(route.get("route_load") or 0.0) for route in routes)
    used_capacities = [float(route.get("capacity") or 0.0) for route in routes if route.get("capacity")]
    utilization_values = [float(route.get("utilization") or 0.0) for route in routes if route.get("utilization") is not None]
    return {
        "total_cost": total_cost,
        "total_distance": total_distance,
        "total_time": total_time,
        "route_count": route_count,
        "vehicles_used": route_count,
        "total_stops": total_stops,
        "total_load": total_load,
        "total_capacity_used": sum(used_capacities),
        "average_stops_per_route": (total_stops / route_count) if route_count else 0.0,
        "average_utilization": (sum(utilization_values) / len(utilization_values)) if utilization_values else 0.0,
        "distance_unit": "km",
        "time_unit": "minutes",
        "cost_unit": "cost",
    }


def _sum_route(nodes: list[Any], matrix: list[list[float]]) -> float:
    total = 0.0
    for index in range(len(nodes) - 1):
        total += float(matrix[int(nodes[index])][int(nodes[index + 1])])
    return total


def _can_use_matrix(nodes: list[Any], matrix: list[list[float]]) -> bool:
    size = len(matrix)
    return all(
        isinstance(node, int) and 0 <= node < size
        for node in nodes
    )


def ensure_solution_summary(
    summary: dict[str, Any],
    *,
    solver_key: str,
    total_cost: float | None = None,
    parameters_used: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized = dict(summary)
    normalized.setdefault("algorithm_name", "NSGA-II" if solver_key == "nsga2" else "Bloodhound")
    normalized.setdefault("runtime_seconds", 0.0)
    normalized.setdefault("parameters_used", parameters_used or normalized.get("algorithm_parameters", {}))
    normalized.setdefault("algorithm_parameters", parameters_used or normalized.get("parameters_used", {}))
    normalized.setdefault(
        "units",
        {
            "distance": "km",
            "time": "minutes",
            "cost": "cost",
            "runtime": "seconds",
        },
    )
    if total_cost is not None:
        normalized.setdefault("total_cost", total_cost)
    return normalized
