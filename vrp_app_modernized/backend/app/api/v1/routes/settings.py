from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db_session
from app.schemas.settings import GoogleSettingsRead, GoogleSettingsUpdate
from app.services.settings import SettingsService


router = APIRouter(prefix="/settings")


@router.get("/google", response_model=GoogleSettingsRead)
def get_google_settings(db: Session = Depends(get_db_session)) -> GoogleSettingsRead:
    return SettingsService(db).get_google_settings()


@router.put("/google", response_model=GoogleSettingsRead)
def update_google_settings(payload: GoogleSettingsUpdate, db: Session = Depends(get_db_session)) -> GoogleSettingsRead:
    return SettingsService(db).update_google_settings(payload)
