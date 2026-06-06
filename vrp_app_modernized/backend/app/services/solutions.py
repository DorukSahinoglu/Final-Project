from __future__ import annotations

from app.db import models
from app.schemas.solution import CandidateSolutionRead, RouteRead, SolutionRead
from app.utils.analytics import build_solution_analytics, ensure_solution_summary, normalize_routes_with_matrices
from app.utils.json import loads


class SolutionService:
    def __init__(self, db) -> None:
        self.db = db

    def get_solution(self, solution_id: str) -> SolutionRead:
        solution = self.db.get(models.Solution, solution_id)
        if solution is None:
            raise ValueError("Solution not found.")
        project = self.db.get(models.Project, solution.project_id)
        latest_matrix = max(project.matrices, key=lambda item: item.created_at, default=None) if project else None
        distance_matrix = loads(latest_matrix.distance_matrix_json, []) if latest_matrix else None
        time_matrix = loads(latest_matrix.time_matrix_json, []) if latest_matrix else None
        raw_payload = loads(solution.raw_payload_json, {})
        candidate_solutions = [
            CandidateSolutionRead(
                solution_id=item.get("summary", {}).get("solution_id", f"candidate-{index + 1}"),
                summary=ensure_solution_summary(
                    item.get("summary", {}),
                    solver_key=solution.solver_key,
                    total_cost=float(item.get("summary", {}).get("total_cost", 0.0) or 0.0),
                    parameters_used=item.get("summary", {}).get("algorithm_parameters", {}),
                ),
                routes=[
                    RouteRead(**route)
                    for route in normalize_routes_with_matrices(
                        item.get("routes", []),
                        distance_matrix=distance_matrix,
                        time_matrix=time_matrix,
                    )
                ],
                analytics=build_solution_analytics(
                    routes=normalize_routes_with_matrices(
                        item.get("routes", []),
                        distance_matrix=distance_matrix,
                        time_matrix=time_matrix,
                    ),
                    total_cost=float(item.get("summary", {}).get("total_cost", 0.0) or 0.0),
                ),
                raw_payload=item.get("raw_payload", {}),
            )
            for index, item in enumerate(raw_payload.get("candidate_solutions", []))
        ]
        normalized_routes = normalize_routes_with_matrices(
            loads(solution.routes_json, []),
            distance_matrix=distance_matrix,
            time_matrix=time_matrix,
        )
        routes = [RouteRead(**item) for item in normalized_routes]
        total_cost = float(loads(solution.summary_json, {}).get("total_cost", 0.0) or 0.0)
        return SolutionRead(
            id=solution.id,
            project_id=solution.project_id,
            solver_key=solution.solver_key,
            summary=ensure_solution_summary(
                loads(solution.summary_json, {}),
                solver_key=solution.solver_key,
                total_cost=total_cost,
                parameters_used=loads(solution.summary_json, {}).get("algorithm_parameters", {}),
            ),
            routes=routes,
            analytics=build_solution_analytics(
                routes=[item.model_dump(mode="json") for item in routes],
                total_cost=total_cost,
            ),
            raw_payload=raw_payload,
            candidate_solutions=candidate_solutions,
            created_at=solution.created_at,
        )
