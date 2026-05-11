from __future__ import annotations

from sqlalchemy.orm import Session

from app.db import models
from app.schemas.project import ProjectCreate, ProjectRead
from app.utils.ids import new_id
from app.utils.json import dumps, loads


class ProjectService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create_project(self, payload: ProjectCreate) -> ProjectRead:
        project = models.Project(
            id=new_id(),
            name=payload.name,
            description=payload.description,
            status="draft",
            settings_json=dumps(payload.settings),
        )
        self.db.add(project)

        for item in payload.addresses:
            project.addresses.append(
                models.Address(
                    id=new_id(),
                    label=item.label,
                    address_line=item.address_line,
                    demand=item.demand,
                    is_depot=item.is_depot,
                    latitude=item.latitude,
                    longitude=item.longitude,
                    geocode_status="ready" if item.latitude is not None and item.longitude is not None else "pending",
                    service_time_min=item.service_time_min,
                    time_window_start_min=item.time_window_start_min,
                    time_window_end_min=item.time_window_end_min,
                )
            )
        for item in payload.fleet_units:
            project.fleet_units.append(
                models.FleetUnit(
                    id=new_id(),
                    vehicle_type_id=item.vehicle_type_id,
                    label=item.label,
                    count=item.count,
                    capacity=item.capacity,
                    fixed_cost=item.fixed_cost,
                    cost_per_km=item.cost_per_km,
                    speed_kmh=item.speed_kmh,
                )
            )

        self.db.commit()
        self.db.refresh(project)
        return self._to_project_read(project)

    def get_project(self, project_id: str) -> models.Project:
        project = self.db.get(models.Project, project_id)
        if project is None:
            raise ValueError("Project not found.")
        return project

    def _to_project_read(self, project: models.Project) -> ProjectRead:
        return ProjectRead(
            id=project.id,
            name=project.name,
            description=project.description,
            status=project.status,
            settings=loads(project.settings_json, {}),
            addresses=list(project.addresses),
            fleet_units=list(project.fleet_units),
        )
