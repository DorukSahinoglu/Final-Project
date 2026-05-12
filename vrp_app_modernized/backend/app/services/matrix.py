from __future__ import annotations

import httpx

from app.db import models
from app.schemas.matrix import MatrixGenerateRequest, MatrixSummary
from app.services.settings import SettingsService
from app.utils.geo import haversine_km
from app.utils.ids import new_id
from app.utils.json import dumps, loads


class MatrixService:
    def __init__(self, db) -> None:
        self.db = db
        self.settings_service = SettingsService(db)

    def generate(self, payload: MatrixGenerateRequest) -> MatrixSummary:
        project = self.db.get(models.Project, payload.project_id)
        if project is None:
            raise ValueError("Project not found.")
        addresses = sorted(project.addresses, key=lambda item: (not item.is_depot, item.created_at))
        if not addresses:
            raise ValueError("Project has no addresses.")
        if any(item.latitude is None or item.longitude is None for item in addresses):
            raise ValueError("All addresses must be geocoded before matrix generation.")

        size = len(addresses)
        google_api_key = self.settings_service.get_google_api_key()
        if google_api_key:
            distance_matrix, time_matrix = self._build_google_matrix(addresses, google_api_key)
            provider = "google_distance_matrix"
        else:
            distance_matrix, time_matrix = self._build_haversine_matrix(addresses, payload.speed_kmh)
            provider = "haversine"

        matrix = models.MatrixSnapshot(
            id=new_id(),
            project_id=project.id,
            status="ready",
            provider=provider,
            metadata_json=dumps({"speed_kmh": payload.speed_kmh, "address_count": size}),
            distance_matrix_json=dumps(distance_matrix),
            time_matrix_json=dumps(time_matrix),
        )
        self.db.add(matrix)
        project.status = "matrix_ready"
        self.db.commit()
        self.db.refresh(matrix)
        return MatrixSummary(
            id=matrix.id,
            project_id=matrix.project_id,
            status=matrix.status,
            provider=matrix.provider,
            size=size,
            metadata=loads(matrix.metadata_json, {}),
            distance_matrix=loads(matrix.distance_matrix_json, []),
            time_matrix=loads(matrix.time_matrix_json, []),
        )

    def _build_haversine_matrix(self, addresses, speed_kmh: float) -> tuple[list[list[float]], list[list[float]]]:
        distance_matrix: list[list[float]] = []
        time_matrix: list[list[float]] = []
        for source in addresses:
            distance_row: list[float] = []
            time_row: list[float] = []
            for target in addresses:
                distance = haversine_km(source.latitude, source.longitude, target.latitude, target.longitude)
                duration_min = 0.0 if source.id == target.id else (distance / speed_kmh) * 60.0
                distance_row.append(round(distance, 3))
                time_row.append(round(duration_min, 3))
            distance_matrix.append(distance_row)
            time_matrix.append(time_row)
        return distance_matrix, time_matrix

    def _build_google_matrix(self, addresses, api_key: str) -> tuple[list[list[float]], list[list[float]]]:
        origins = "|".join(f"{item.latitude},{item.longitude}" for item in addresses)
        destinations = "|".join(f"{item.latitude},{item.longitude}" for item in addresses)
        params = {
            "origins": origins,
            "destinations": destinations,
            "key": api_key,
            "mode": "driving",
        }
        with httpx.Client(timeout=30.0) as client:
            response = client.get("https://maps.googleapis.com/maps/api/distancematrix/json", params=params)
            response.raise_for_status()
            payload = response.json()
        if payload.get("status") != "OK":
            raise ValueError(f"Google Distance Matrix failed: {payload.get('status', 'unknown')}")

        distance_matrix: list[list[float]] = []
        time_matrix: list[list[float]] = []
        for row in payload.get("rows", []):
            d_row: list[float] = []
            t_row: list[float] = []
            for element in row.get("elements", []):
                if element.get("status") != "OK":
                    raise ValueError(f"Google Distance Matrix element failed: {element.get('status', 'unknown')}")
                d_row.append(round(float(element["distance"]["value"]) / 1000.0, 3))
                t_row.append(round(float(element["duration"]["value"]) / 60.0, 3))
            distance_matrix.append(d_row)
            time_matrix.append(t_row)
        return distance_matrix, time_matrix
