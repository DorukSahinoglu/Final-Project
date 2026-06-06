from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.job import JobRead
from app.schemas.matrix import MatrixSummary
from app.schemas.project import ProjectRead, ProjectSummary
from app.schemas.solution import SolutionRead


class ProjectBundle(BaseModel):
    exported_at: datetime
    version: int = 1
    project: ProjectRead
    matrix: MatrixSummary | None = None
    solutions: list[SolutionRead] = Field(default_factory=list)
    jobs: list[JobRead] = Field(default_factory=list)


class ProjectSaveRequest(BaseModel):
    project_id: str | None = None
    project: dict = Field(default_factory=dict)
    matrix: MatrixSummary | None = None
    solutions: list[SolutionRead] = Field(default_factory=list)
    jobs: list[JobRead] = Field(default_factory=list)
    include_google_api_key: bool = False


class ProjectImportRequest(BaseModel):
    bundle: ProjectBundle


class ProjectLibraryResponse(BaseModel):
    projects: list[ProjectSummary] = Field(default_factory=list)
