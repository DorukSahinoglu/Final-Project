from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "PulseRoute API"
    app_env: Literal["development", "staging", "production"] = "development"
    app_debug: bool = True
    api_v1_prefix: str = "/api/v1"
    api_legacy_prefix: str = "/api"
    database_url: str = "sqlite:///./pulseroute.db"
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:4173",
            "http://127.0.0.1:4173",
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:8000",
            "http://127.0.0.1:8000",
            "tauri://localhost",
            "capacitor://localhost",
            "null",
        ]
    )
    cors_origin_regex: str = r"^(https?://(localhost|127\.0\.0\.1)(:\d+)?|tauri://localhost|capacitor://localhost|app://.*|null)$"
    job_max_workers: int = 2
    log_level: str = "INFO"
    geocoder_provider: Literal["none", "nominatim"] = "nominatim"
    geocoder_user_agent: str = "PulseRoute-Local/1.0"
    nominatim_base_url: str = "https://nominatim.openstreetmap.org"
    osrm_base_url: str = "https://router.project-osrm.org"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
