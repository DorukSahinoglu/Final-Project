from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db import models
from app.schemas.geocode import GeocodeResponse, GeocodeResult


logger = get_logger(__name__)


class GeocodingService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.settings = get_settings()

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
            result = self._geocode_address(address.address_line)
            if result["status"] == "ready":
                address.latitude = result["latitude"]
                address.longitude = result["longitude"]
                address.geocode_status = "ready"
                address.geocode_provider = result["provider"]
            else:
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
                    message=result.get("message"),
                )
            )
        self.db.commit()
        return GeocodeResponse(project_id=project_id, results=results)

    def _geocode_address(self, address_line: str) -> dict[str, Any]:
        if self.settings.geocoder_provider == "none":
            return {"status": "failed", "message": "No geocoder provider configured."}

        params = {"q": address_line, "format": "jsonv2", "limit": 1}
        headers = {"User-Agent": self.settings.geocoder_user_agent}
        with httpx.Client(timeout=20.0, headers=headers) as client:
            response = client.get(f"{self.settings.nominatim_base_url}/search", params=params)
            response.raise_for_status()
            payload = response.json()

        if not payload:
            return {"status": "failed", "message": "Address not found."}

        item = payload[0]
        logger.info("Geocoded address '%s' via Nominatim", address_line)
        return {
            "status": "ready",
            "provider": "nominatim",
            "latitude": float(item["lat"]),
            "longitude": float(item["lon"]),
        }
