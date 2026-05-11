from fastapi import APIRouter

from app.core.config import get_settings
from app.schemas.health import HealthResponse


router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def get_health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(status="ok", app=settings.app_name, env=settings.app_env)
