from __future__ import annotations

from app.db import models
from app.schemas.matrix import MatrixGenerateRequest, MatrixSummary
from app.utils.geo import haversine_km
from app.utils.ids import new_id
from app.utils.json import dumps, loads


class MatrixService:
    def __init__(self, db) -> None:
        self.db = db

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
        distance_matrix: list[list[float]] = []
        time_matrix: list[list[float]] = []
        for source in addresses:
            distance_row: list[float] = []
            time_row: list[float] = []
            for target in addresses:
                distance = haversine_km(source.latitude, source.longitude, target.latitude, target.longitude)
                duration_min = 0.0 if source.id == target.id else (distance / payload.speed_kmh) * 60.0
                distance_row.append(round(distance, 3))
                time_row.append(round(duration_min, 3))
            distance_matrix.append(distance_row)
            time_matrix.append(time_row)

        matrix = models.MatrixSnapshot(
            id=new_id(),
            project_id=project.id,
            status="ready",
            provider="haversine",
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
