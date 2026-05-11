from __future__ import annotations

from pydantic import BaseModel, Field


class SolveRequest(BaseModel):
    project_id: str
    matrix_id: str
    solver_params: dict = Field(default_factory=dict)

