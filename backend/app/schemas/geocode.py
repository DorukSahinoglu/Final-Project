from pydantic import BaseModel, Field


class GeocodeRequest(BaseModel):
    project_id: str
    address_ids: list[str] = Field(default_factory=list)


class GeocodeResult(BaseModel):
    address_id: str
    label: str
    address_line: str
    latitude: float | None
    longitude: float | None
    status: str
    provider: str | None = None
    message: str | None = None


class GeocodeResponse(BaseModel):
    project_id: str
    results: list[GeocodeResult]
