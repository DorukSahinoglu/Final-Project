from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.db import models
from app.schemas.job import JobRead
from app.schemas.matrix import MatrixSummary
from app.schemas.project import ProjectCreate, ProjectRead, ProjectSolutionSummary, ProjectUpdate
from app.schemas.project_bundle import ProjectBundle, ProjectSaveRequest
from app.schemas.solution import SolutionRead
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
        return self._to_project_read(self.get_project(project.id))

    def update_project(self, project_id: str, payload: ProjectUpdate) -> ProjectRead:
        self._validate_project_payload(payload)
        project = self.get_project(project_id)
        children_changed = self._project_children_changed(project, payload.addresses, payload.fleet_units)
        project.name = payload.name
        project.description = payload.description
        project.status = "draft"
        project.settings_json = dumps(payload.settings)

        if children_changed:
            # Derived artifacts become stale whenever addresses or fleet change.
            for collection in (project.jobs, project.solutions, project.matrices):
                for item in list(collection):
                    self.db.delete(item)
            self.db.flush()
            self._replace_project_children(project, payload.addresses, payload.fleet_units)

        self.db.commit()
        return self._to_project_read(self.get_project(project.id))

    def get_project(self, project_id: str) -> models.Project:
        project = self.db.get(models.Project, project_id)
        if project is None:
            raise ValueError("Project not found.")
        return project

    def delete_project(self, project_id: str) -> None:
        project = self.get_project(project_id)
        self.db.delete(project)
        self.db.commit()

    def list_projects(self) -> list:
        return (
            self.db.query(models.Project)
            .order_by(models.Project.updated_at.desc())
            .all()
        )

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
            updated_at=project.updated_at,
        )

    def save_project_bundle(self, payload: ProjectSaveRequest) -> ProjectRead:
        project_payload = (
            ProjectUpdate.model_validate(payload.project)
            if payload.project_id
            else ProjectCreate.model_validate(payload.project)
        )
        project_id = payload.project_id
        saved = self.update_project(project_id, project_payload) if project_id else self.create_project(project_payload)
        project = self.get_project(saved.id)
        self._replace_project_runtime_state(project, payload.matrix, payload.solutions, payload.jobs)
        self.db.commit()
        return self._to_project_read(self.get_project(project.id))

    def export_project_bundle(self, project_id: str) -> ProjectBundle:
        project = self.get_project(project_id)
        latest_matrix = max(project.matrices, key=lambda item: item.created_at, default=None)
        solutions = sorted(project.solutions, key=lambda item: item.created_at, reverse=True)
        jobs = sorted(project.jobs, key=lambda item: item.created_at, reverse=True)
        return ProjectBundle(
            exported_at=datetime.utcnow(),
            version=1,
            project=self._to_project_read(project),
            matrix=self._matrix_to_summary(latest_matrix) if latest_matrix else None,
            solutions=[self._solution_to_read(item) for item in solutions],
            jobs=[self._job_to_read(item) for item in jobs],
        )

    def _replace_project_children(self, project: models.Project, addresses, fleet_units) -> None:
        project.addresses.clear()
        project.fleet_units.clear()
        self.db.flush()

        for item in addresses:
            project.addresses.append(
                models.Address(
                    id=getattr(item, "id", None) or new_id(),
                    project_id=project.id,
                    label=item.label.strip(),
                    address_line=item.address_line.strip(),
                    demand=item.demand,
                    is_depot=item.is_depot,
                    latitude=item.latitude,
                    longitude=item.longitude,
                    notes=item.notes,
                    geocode_status="ready" if item.latitude is not None and item.longitude is not None else "pending",
                    time_window_start_min=item.time_window_start_min,
                    time_window_end_min=item.time_window_end_min,
                )
            )
        for item in fleet_units:
            project.fleet_units.append(
                models.FleetUnit(
                    id=getattr(item, "id", None) or new_id(),
                    project_id=project.id,
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

    def _replace_project_runtime_state(
        self,
        project: models.Project,
        matrix: MatrixSummary | None,
        solutions: list[SolutionRead],
        jobs: list[JobRead],
    ) -> None:
        for collection in (project.jobs, project.solutions, project.matrices):
            for item in list(collection):
                self.db.delete(item)
        self.db.flush()

        if matrix is not None:
            self._validate_matrix_dimensions(matrix, len(project.addresses))
            project.matrices.append(
                models.MatrixSnapshot(
                    id=matrix.id or new_id(),
                    project_id=project.id,
                    status=matrix.status,
                    provider=matrix.provider,
                    metadata_json=dumps(matrix.metadata),
                    distance_matrix_json=dumps(matrix.distance_matrix),
                    time_matrix_json=dumps(matrix.time_matrix),
                )
            )

        for current_solution in solutions:
            project.solutions.append(
                models.Solution(
                    id=current_solution.id or new_id(),
                    project_id=project.id,
                    solver_key=current_solution.solver_key,
                    summary_json=dumps(current_solution.summary),
                    routes_json=dumps([route.model_dump(mode="json") if hasattr(route, "model_dump") else route for route in current_solution.routes]),
                    analytics_json=dumps(current_solution.analytics),
                    raw_payload_json=dumps(current_solution.raw_payload),
                )
            )

        for item in jobs:
            project.jobs.append(
                models.Job(
                    id=item.id or new_id(),
                    project_id=project.id,
                    matrix_snapshot_id=item.matrix_snapshot_id,
                    solution_id=item.solution_id,
                    job_type=item.job_type,
                    solver_key=item.solver_key,
                    status=item.status,
                    progress=item.progress,
                    message=item.message,
                    logs_json=dumps([log.model_dump(mode="json") if hasattr(log, "model_dump") else log for log in item.logs]),
                    result_json=dumps(item.result),
                    error_json=dumps(item.error),
                    cancel_requested=item.cancel_requested,
                    started_at=item.started_at,
                    completed_at=item.completed_at,
                )
            )

    def _validate_matrix_dimensions(self, matrix: MatrixSummary, address_count: int) -> None:
        if matrix.size != address_count:
            raise ValueError(
                f"Imported matrix size {matrix.size} does not match project address count {address_count}."
            )
        if len(matrix.distance_matrix) != address_count or len(matrix.time_matrix) != address_count:
            raise ValueError("Imported matrix payload dimensions do not match the project address count.")
        if any(len(row) != address_count for row in matrix.distance_matrix):
            raise ValueError("Imported distance matrix must be square and match the project address count.")
        if any(len(row) != address_count for row in matrix.time_matrix):
            raise ValueError("Imported time matrix must be square and match the project address count.")

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

    def _project_children_changed(self, project: models.Project, addresses, fleet_units) -> bool:
        current_addresses = [
            (
                item.id,
                item.label,
                item.address_line,
                item.demand,
                item.is_depot,
                item.latitude,
                item.longitude,
                item.notes,
                item.time_window_start_min,
                item.time_window_end_min,
            )
            for item in project.addresses
        ]
        next_addresses = [
            (
                getattr(item, "id", None),
                item.label,
                item.address_line,
                item.demand,
                item.is_depot,
                item.latitude,
                item.longitude,
                item.notes,
                item.time_window_start_min,
                item.time_window_end_min,
            )
            for item in addresses
        ]
        current_fleet = [
            (
                item.id,
                item.vehicle_type_id,
                item.label,
                item.count,
                item.capacity,
                item.fixed_cost,
                item.cost_per_km,
                item.speed_kmh,
                item.max_route_distance_km,
                item.max_route_time_min,
            )
            for item in project.fleet_units
        ]
        next_fleet = [
            (
                getattr(item, "id", None),
                item.vehicle_type_id,
                item.label,
                item.count,
                item.capacity,
                item.fixed_cost,
                item.cost_per_km,
                item.speed_kmh,
                item.max_route_distance_km,
                item.max_route_time_min,
            )
            for item in fleet_units
        ]
        return current_addresses != next_addresses or current_fleet != next_fleet

    def _matrix_to_summary(self, matrix: models.MatrixSnapshot) -> MatrixSummary:
        return MatrixSummary(
            id=matrix.id,
            project_id=matrix.project_id,
            status=matrix.status,
            provider=matrix.provider,
            size=len(loads(matrix.distance_matrix_json, [])),
            metadata=loads(matrix.metadata_json, {}),
            distance_matrix=loads(matrix.distance_matrix_json, []),
            time_matrix=loads(matrix.time_matrix_json, []),
        )

    def _solution_to_read(self, solution: models.Solution) -> SolutionRead:
        return SolutionRead(
            id=solution.id,
            project_id=solution.project_id,
            solver_key=solution.solver_key,
            summary=loads(solution.summary_json, {}),
            routes=loads(solution.routes_json, []),
            analytics=loads(solution.analytics_json, {}),
            raw_payload=loads(solution.raw_payload_json, {}),
            created_at=solution.created_at,
        )

    def _job_to_read(self, job: models.Job) -> JobRead:
        return JobRead(
            id=job.id,
            project_id=job.project_id,
            matrix_snapshot_id=job.matrix_snapshot_id,
            solution_id=job.solution_id,
            job_type=job.job_type,
            solver_key=job.solver_key,
            status=job.status,
            progress=job.progress,
            message=job.message,
            cancel_requested=job.cancel_requested,
            logs=loads(job.logs_json, []),
            result=loads(job.result_json, {}),
            error=loads(job.error_json, {}),
            created_at=job.created_at,
            updated_at=job.updated_at,
            started_at=job.started_at,
            completed_at=job.completed_at,
        )
