from pydantic import BaseModel, Field


class MatrixGenerateRequest(BaseModel):
    project_id: str
    speed_kmh: float = Field(default=35.0, gt=0)


class MatrixSummary(BaseModel):
    id: str
    project_id: str
    status: str
    provider: str
    size: int
    metadata: dict
    distance_matrix: list[list[float]]
    time_matrix: list[list[float]]

