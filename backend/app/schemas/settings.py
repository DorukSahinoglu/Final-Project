from pydantic import BaseModel


class GoogleSettingsRead(BaseModel):
    google_api_key: str | None = None
    geocode_provider: str
    matrix_provider: str


class GoogleSettingsUpdate(BaseModel):
    google_api_key: str | None = None
