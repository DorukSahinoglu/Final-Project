from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db import models
from app.schemas.geocode import GeocodeResponse, GeocodeResult
from app.services.settings import SettingsService


logger = get_logger(__name__)


class GeocodingService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.settings = get_settings()
        self.settings_service = SettingsService(db)

    def geocode_project(self, project_id: str, address_ids: list[str]) -> GeocodeResponse:
        project = self.db.get(models.Project, project_id)
        if project is None:
            raise ValueError("Project not found.")

        selected = [
            address
            for address in project.addresses
            if not address_ids or address.id in address_ids
        ]
        results: list[GeocodeResult] = []
        for address in selected:
            if not address.address_line.strip():
                address.geocode_status = "failed"
                results.append(
                    GeocodeResult(
                        address_id=address.id,
                        label=address.label,
                        address_line=address.address_line,
                        latitude=address.latitude,
                        longitude=address.longitude,
                        status=address.geocode_status,
                        provider=address.geocode_provider,
                        message="Address text is empty.",
                    )
                )
                continue
            result = self._geocode_address(address.address_line)
            if result["status"] == "ready":
                address.latitude = result["latitude"]
                address.longitude = result["longitude"]
                address.geocode_status = "ready"
                address.geocode_provider = result["provider"]
            else:
                address.geocode_status = "failed"
                address.geocode_provider = result.get("provider")
            results.append(
                GeocodeResult(
                    address_id=address.id,
                    label=address.label,
                    address_line=address.address_line,
                    latitude=address.latitude,
                    longitude=address.longitude,
                    status=address.geocode_status,
                    provider=address.geocode_provider,
                    message=result.get("message"),
                )
            )
        self.db.commit()
        return GeocodeResponse(project_id=project_id, results=results)

    def _geocode_address(self, address_line: str) -> dict[str, Any]:
        google_api_key = self.settings_service.get_google_api_key()
        if not google_api_key:
            return {
                "status": "failed",
                "provider": "google",
                "message": "Google API key is missing. Open Settings and save a valid Google Geocoding API key.",
            }
        return self._geocode_google(address_line, google_api_key)

    def _geocode_google(self, address_line: str, api_key: str) -> dict[str, Any]:
        params = {"address": address_line, "key": api_key}
        try:
            with httpx.Client(timeout=20.0) as client:
                response = client.get("https://maps.googleapis.com/maps/api/geocode/json", params=params)
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPError as exc:
            logger.warning("Google geocoding request failed for '%s': %s", address_line, exc)
            return {"status": "failed", "provider": "google", "message": f"Google geocoding request failed: {exc}"}
        if payload.get("status") != "OK" or not payload.get("results"):
            error_message = payload.get("error_message")
            return {
                "status": "failed",
                "provider": "google",
                "message": error_message or payload.get("status", "Google geocode failed."),
            }
        location = payload["results"][0]["geometry"]["location"]
        return {
            "status": "ready",
            "provider": "google",
            "latitude": float(location["lat"]),
            "longitude": float(location["lng"]),
        }

    def _geocode_nominatim(self, address_line: str) -> dict[str, Any]:
        params = {"q": address_line, "format": "jsonv2", "limit": 1}
        headers = {"User-Agent": self.settings.geocoder_user_agent}
        try:
            with httpx.Client(timeout=20.0, headers=headers) as client:
                response = client.get(f"{self.settings.nominatim_base_url}/search", params=params)
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPError as exc:
            logger.warning("Nominatim geocoding request failed for '%s': %s", address_line, exc)
            return {"status": "failed", "provider": "nominatim", "message": f"Nominatim request failed: {exc}"}

        if not payload:
            return {"status": "failed", "provider": "nominatim", "message": "Address not found."}

        item = payload[0]
        logger.info("Geocoded address '%s' via Nominatim", address_line)
        return {
            "status": "ready",
            "provider": "nominatim",
            "latitude": float(item["lat"]),
            "longitude": float(item["lon"]),
        }
