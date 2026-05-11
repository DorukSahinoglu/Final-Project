from __future__ import annotations

from typing import Any


def build_solution_analytics(routes: list[dict[str, Any]], total_cost: float) -> dict[str, Any]:
    route_count = len(routes)
    total_distance = sum((route.get("route_distance") or 0.0) for route in routes)
    total_time = sum((route.get("route_time") or 0.0) for route in routes)
    total_stops = sum(max(0, len(route.get("nodes", [])) - 2) for route in routes)
    average_utilization = 0.0
    if route_count:
        average_utilization = total_stops / route_count
    return {
        "total_cost": total_cost,
        "total_distance": total_distance,
        "total_time": total_time,
        "route_count": route_count,
        "total_stops": total_stops,
        "average_stops_per_route": average_utilization,
    }
