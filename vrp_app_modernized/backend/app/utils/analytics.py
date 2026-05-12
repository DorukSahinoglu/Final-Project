from __future__ import annotations

from typing import Any


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
    }
