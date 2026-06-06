from pydantic import BaseModel, Field


class MatrixGenerateRequest(BaseModel):
    project_id: str


class MatrixLoadJsonRequest(BaseModel):
    project_id: str
    distance_matrix: list[list[float]]
    time_matrix: list[list[float]] | None = None
    node_ids: list[str] | None = None
    address_ids: list[str] | None = None
    metadata: dict = Field(default_factory=dict)


class MatrixSummary(BaseModel):
    id: str
    project_id: str
    status: str
    provider: str
    size: int
    metadata: dict
    distance_matrix: list[list[float]]
    time_matrix: list[list[float]]
