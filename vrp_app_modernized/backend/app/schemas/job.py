from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class JobLogEntry(BaseModel):
    timestamp: datetime
    level: str = "info"
    message: str
    context: dict = Field(default_factory=dict)


class JobAcceptedResponse(BaseModel):
    job_id: str
    status: str


class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    matrix_snapshot_id: str | None = None
    solution_id: str | None = None
    job_type: str
    solver_key: str | None = None
    status: str
    progress: float
    message: str | None = None
    cancel_requested: bool
    logs: list[JobLogEntry] = Field(default_factory=list)
    result: dict = Field(default_factory=dict)
    error: dict = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
