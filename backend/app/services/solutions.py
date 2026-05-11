from __future__ import annotations

from app.db import models
from app.schemas.solution import RouteRead, SolutionRead
from app.utils.json import loads


class SolutionService:
    def __init__(self, db) -> None:
        self.db = db

    def get_solution(self, solution_id: str) -> SolutionRead:
        solution = self.db.get(models.Solution, solution_id)
        if solution is None:
            raise ValueError("Solution not found.")
        return SolutionRead(
            id=solution.id,
            project_id=solution.project_id,
            solver_key=solution.solver_key,
            summary=loads(solution.summary_json, {}),
            routes=[RouteRead(**item) for item in loads(solution.routes_json, [])],
            analytics=loads(solution.analytics_json, {}),
            raw_payload=loads(solution.raw_payload_json, {}),
            created_at=solution.created_at,
        )
