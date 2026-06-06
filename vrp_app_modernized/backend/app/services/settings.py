from __future__ import annotations

from sqlalchemy.orm import Session

from app.db import models
from app.schemas.settings import GoogleSettingsRead, GoogleSettingsUpdate


class SettingsService:
    GOOGLE_API_KEY = "google_api_key"

    def __init__(self, db: Session) -> None:
        self.db = db

    def get_google_settings(self) -> GoogleSettingsRead:
        key = self._get_value(self.GOOGLE_API_KEY)
        provider = "google" if key else "unconfigured"
        matrix_provider = "osrm"
        return GoogleSettingsRead(google_api_key=key, geocode_provider=provider, matrix_provider=matrix_provider)

    def update_google_settings(self, payload: GoogleSettingsUpdate) -> GoogleSettingsRead:
        self._set_value(self.GOOGLE_API_KEY, (payload.google_api_key or "").strip())
        self.db.commit()
        return self.get_google_settings()

    def get_google_api_key(self) -> str | None:
        value = self._get_value(self.GOOGLE_API_KEY)
        return value or None

    def _get_value(self, key: str) -> str | None:
        item = self.db.get(models.AppSetting, key)
        return item.value if item else None

    def _set_value(self, key: str, value: str) -> None:
        item = self.db.get(models.AppSetting, key)
        if item is None:
            item = models.AppSetting(key=key, value=value)
            self.db.add(item)
        else:
            item.value = value
