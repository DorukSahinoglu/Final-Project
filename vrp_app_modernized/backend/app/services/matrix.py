from __future__ import annotations

import math

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db import models
from app.schemas.matrix import MatrixGenerateRequest, MatrixLoadJsonRequest, MatrixSummary
from app.utils.ids import new_id
from app.utils.json import dumps, loads


logger = get_logger(__name__)


class MatrixService:
    def __init__(self, db) -> None:
        self.db = db
        self.settings = get_settings()

    def generate(self, payload: MatrixGenerateRequest) -> MatrixSummary:
        project, addresses = self._get_project_and_addresses(payload.project_id)
        self._validate_coordinates(addresses)
        size = len(addresses)
        distance_matrix, time_matrix = self._build_osrm_matrix(addresses)

        return self._store_matrix(
            project=project,
            provider="osrm",
            distance_matrix=distance_matrix,
            time_matrix=time_matrix,
            metadata={
                "address_count": size,
                "source": "osrm",
                "unit_distance": "km",
                "unit_time": "minutes",
            },
        )

    def load_json(self, payload: MatrixLoadJsonRequest) -> MatrixSummary:
        project, addresses = self._get_project_and_addresses(payload.project_id)
        distance_matrix = payload.distance_matrix
        time_matrix = payload.time_matrix or payload.distance_matrix
        self._validate_square_matrix(distance_matrix, "distance_matrix")
        self._validate_square_matrix(time_matrix, "time_matrix")
        if len(distance_matrix) != len(time_matrix):
            raise ValueError("distance_matrix and time_matrix must have the same size.")

        provided_keys = payload.address_ids or payload.node_ids
        if provided_keys:
            if len(provided_keys) != len(distance_matrix):
                raise ValueError("The number of provided node_ids/address_ids must match the matrix size.")
            reorder_indices = self._build_reorder_indices(addresses, provided_keys)
            distance_matrix = self._reorder_matrix(distance_matrix, reorder_indices)
            time_matrix = self._reorder_matrix(time_matrix, reorder_indices)
        elif len(distance_matrix) != len(addresses):
            raise ValueError(
                f"Matrix size {len(distance_matrix)} does not match the current project address count {len(addresses)}."
            )

        metadata = {
            **payload.metadata,
            "address_count": len(addresses),
            "source": "json_import",
            "time_matrix_defaulted_from_distance": payload.time_matrix is None,
        }
        return self._store_matrix(
            project=project,
            provider="json_import",
            distance_matrix=distance_matrix,
            time_matrix=time_matrix,
            metadata=metadata,
        )

    def _build_osrm_matrix(self, addresses: list[models.Address]) -> tuple[list[list[float]], list[list[float]]]:
        coordinates = ";".join(f"{item.longitude},{item.latitude}" for item in addresses)
        params = {"annotations": "distance,duration"}
        osrm_table_url = f"{self.settings.osrm_base_url.rstrip('/')}/table/v1/driving/{coordinates}"
        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.get(osrm_table_url, params=params)
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPError as exc:
            logger.warning("OSRM matrix request failed for project coordinates: %s", exc)
            raise ValueError(f"OSRM matrix request failed: {exc}") from exc

        if payload.get("code") != "Ok":
            raise ValueError(f"OSRM matrix generation failed: {payload.get('message') or payload.get('code') or 'unknown error'}")

        distances = payload.get("distances")
        durations = payload.get("durations")
        if not isinstance(distances, list) or not isinstance(durations, list):
            raise ValueError("OSRM response did not include both distances and durations matrices.")

        self._validate_square_matrix(distances, "distance_matrix")
        self._validate_square_matrix(durations, "time_matrix")
        if len(distances) != len(addresses) or len(durations) != len(addresses):
            raise ValueError(
                f"OSRM matrix size mismatch. Expected {len(addresses)} rows but received {len(distances)} distance rows and {len(durations)} time rows."
            )

        distance_matrix = [
            [round(float(value) / 1000.0, 3) for value in row]
            for row in distances
        ]
        time_matrix = [
            [round(float(value) / 60.0, 3) for value in row]
            for row in durations
        ]
        return distance_matrix, time_matrix

    def _get_project_and_addresses(self, project_id: str) -> tuple[models.Project, list[models.Address]]:
        project = self.db.get(models.Project, project_id)
        if project is None:
            raise ValueError("Project not found.")
        addresses = sorted(project.addresses, key=lambda item: (not item.is_depot, item.created_at))
        if not addresses:
            raise ValueError("Project has no addresses.")
        return project, addresses

    def _store_matrix(self, project: models.Project, provider: str, distance_matrix: list[list[float]], time_matrix: list[list[float]], metadata: dict) -> MatrixSummary:
        matrix = models.MatrixSnapshot(
            id=new_id(),
            project_id=project.id,
            status="ready",
            provider=provider,
            metadata_json=dumps(metadata),
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
            size=len(distance_matrix),
            metadata=loads(matrix.metadata_json, {}),
            distance_matrix=loads(matrix.distance_matrix_json, []),
            time_matrix=loads(matrix.time_matrix_json, []),
        )

    def _validate_coordinates(self, addresses: list[models.Address]) -> None:
        for address in addresses:
            if address.latitude is None or address.longitude is None:
                raise ValueError(
                    f"Address '{address.label}' is missing coordinates. Geocode addresses before generating the OSRM matrix."
                )
            latitude = float(address.latitude)
            longitude = float(address.longitude)
            if not math.isfinite(latitude) or not math.isfinite(longitude):
                raise ValueError(f"Address '{address.label}' has non-finite coordinates.")
            if latitude < -90 or latitude > 90 or longitude < -180 or longitude > 180:
                raise ValueError(
                    f"Address '{address.label}' has invalid coordinates ({latitude}, {longitude})."
                )

    def _validate_square_matrix(self, matrix: list[list[float]], field_name: str) -> None:
        if not matrix:
            raise ValueError(f"{field_name} cannot be empty.")
        size = len(matrix)
        for row_index, row in enumerate(matrix):
            if len(row) != size:
                raise ValueError(f"{field_name} must be square. Row {row_index} has length {len(row)} instead of {size}.")
            for value in row:
                if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                    raise ValueError(f"{field_name} must contain only finite numeric values.")

    def _build_reorder_indices(self, addresses: list[models.Address], provided_keys: list[str]) -> list[int]:
        lookup = {}
        for index, raw_key in enumerate(provided_keys):
            normalized = self._normalize_key(raw_key)
            if normalized in lookup:
                raise ValueError(f"Duplicate node identifier in matrix JSON: {raw_key}")
            lookup[normalized] = index

        reorder_indices: list[int] = []
        missing: list[str] = []
        for address in addresses:
            candidates = {
                self._normalize_key(address.id),
                self._normalize_key(address.label),
                self._normalize_key(address.address_line),
            }
            matched = next((lookup[key] for key in candidates if key in lookup), None)
            if matched is None:
                missing.append(address.label)
                continue
            reorder_indices.append(matched)

        if missing:
            raise ValueError(
                "Provided node_ids/address_ids do not match the current project addresses. Missing matches for: "
                + ", ".join(missing)
            )
        return reorder_indices

    def _reorder_matrix(self, matrix: list[list[float]], reorder_indices: list[int]) -> list[list[float]]:
        return [
            [float(matrix[source_index][target_index]) for target_index in reorder_indices]
            for source_index in reorder_indices
        ]

    def _normalize_key(self, value: str) -> str:
        return value.strip().lower().replace(" ", "").replace("_", "").replace("-", "")
