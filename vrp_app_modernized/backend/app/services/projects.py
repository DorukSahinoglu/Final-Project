from __future__ import annotations

from sqlalchemy.orm import Session

from app.db import models
from app.schemas.project import ProjectCreate, ProjectRead, ProjectSolutionSummary, ProjectUpdate
from app.utils.ids import new_id
from app.utils.json import dumps, loads


class ProjectService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create_project(self, payload: ProjectCreate) -> ProjectRead:
        self._validate_project_payload(payload)
        project = models.Project(
            id=new_id(),
            name=payload.name,
            description=payload.description,
            status="draft",
            settings_json=dumps(payload.settings),
        )
        self.db.add(project)
        self._replace_project_children(project, payload.addresses, payload.fleet_units)

        self.db.commit()
        self.db.refresh(project)
        return self._to_project_read(project)

    def update_project(self, project_id: str, payload: ProjectUpdate) -> ProjectRead:
        self._validate_project_payload(payload)
        project = self.get_project(project_id)
        project.name = payload.name
        project.description = payload.description
        project.status = "draft"
        project.settings_json = dumps(payload.settings)

        # Derived artifacts become stale whenever addresses or fleet change.
        for collection in (project.jobs, project.solutions, project.matrices):
            for item in list(collection):
                self.db.delete(item)
        self.db.flush()

        self._replace_project_children(project, payload.addresses, payload.fleet_units)

        self.db.commit()
        self.db.refresh(project)
        return self._to_project_read(project)

    def get_project(self, project_id: str) -> models.Project:
        project = self.db.get(models.Project, project_id)
        if project is None:
            raise ValueError("Project not found.")
        return project

    def list_project_solutions(self, project_id: str) -> list[ProjectSolutionSummary]:
        project = self.get_project(project_id)
        ordered = sorted(project.solutions, key=lambda item: item.created_at, reverse=True)
        return [
            ProjectSolutionSummary(
                id=solution.id,
                solver_key=solution.solver_key,
                summary=loads(solution.summary_json, {}),
                analytics=loads(solution.analytics_json, {}),
                created_at=solution.created_at,
            )
            for solution in ordered
        ]

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

    def _replace_project_children(self, project: models.Project, addresses, fleet_units) -> None:
        project.addresses.clear()
        project.fleet_units.clear()

        for item in addresses:
            project.addresses.append(
                models.Address(
                    id=getattr(item, "id", None) or new_id(),
                    label=item.label.strip(),
                    address_line=item.address_line.strip(),
                    demand=item.demand,
                    is_depot=item.is_depot,
                    latitude=item.latitude,
                    longitude=item.longitude,
                    notes=item.notes,
                    geocode_status="ready" if item.latitude is not None and item.longitude is not None else "pending",
                    service_time_min=item.service_time_min,
                    time_window_start_min=item.time_window_start_min,
                    time_window_end_min=item.time_window_end_min,
                )
            )
        for item in fleet_units:
            project.fleet_units.append(
                models.FleetUnit(
                    id=getattr(item, "id", None) or new_id(),
                    vehicle_type_id=item.vehicle_type_id.strip(),
                    label=item.label.strip(),
                    count=item.count,
                    capacity=item.capacity,
                    fixed_cost=item.fixed_cost,
                    cost_per_km=item.cost_per_km,
                    speed_kmh=item.speed_kmh,
                    max_route_distance_km=item.max_route_distance_km,
                    max_route_time_min=item.max_route_time_min,
                )
            )

    def _validate_project_payload(self, payload: ProjectCreate | ProjectUpdate) -> None:
        if not payload.addresses:
            raise ValueError("At least one address is required.")
        if not payload.fleet_units:
            raise ValueError("At least one fleet definition is required.")

        depot_count = sum(1 for item in payload.addresses if item.is_depot)
        if depot_count != 1:
            raise ValueError("Exactly one depot must be selected.")

        seen_labels: set[str] = set()
        seen_address_lines: set[str] = set()
        for item in payload.addresses:
            label_key = item.label.strip().lower()
            address_key = item.address_line.strip().lower()
            if not label_key or not address_key:
                raise ValueError("Address labels and address text cannot be empty.")
            if label_key in seen_labels:
                raise ValueError(f"Duplicate address label detected: {item.label}")
            if address_key in seen_address_lines:
                raise ValueError(f"Duplicate address detected: {item.address_line}")
            if not item.is_depot and item.demand < 0:
                raise ValueError(f"Demand cannot be negative for {item.label}.")
            seen_labels.add(label_key)
            seen_address_lines.add(address_key)
