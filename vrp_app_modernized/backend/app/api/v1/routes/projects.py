from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db_session
from app.schemas.project import ProjectCreate, ProjectRead, ProjectSolutionSummary, ProjectSummary, ProjectUpdate
from app.schemas.project_bundle import ProjectBundle, ProjectImportRequest, ProjectSaveRequest
from app.services.projects import ProjectService


router = APIRouter()


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
def create_project(payload: ProjectCreate, db: Session = Depends(get_db_session)) -> ProjectRead:
    try:
        return ProjectService(db).create_project(payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/save", response_model=ProjectRead)
def save_project(payload: ProjectSaveRequest, db: Session = Depends(get_db_session)) -> ProjectRead:
    try:
        return ProjectService(db).save_project_bundle(payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/import", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
def import_project(payload: ProjectImportRequest, db: Session = Depends(get_db_session)) -> ProjectRead:
    try:
        bundle = payload.bundle
        return ProjectService(db).save_project_bundle(
            ProjectSaveRequest(
                project_id=bundle.project.id,
                project=bundle.project.model_dump(mode="json"),
                matrix=bundle.matrix,
                solutions=bundle.solutions,
                jobs=bundle.jobs,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("", response_model=list[ProjectSummary])
def list_projects(db: Session = Depends(get_db_session)) -> list[ProjectSummary]:
    service = ProjectService(db)
    return [
        ProjectSummary(
            id=item.id,
            name=item.name,
            description=item.description,
            status=item.status,
            updated_at=item.updated_at,
        )
        for item in service.list_projects()
    ]


@router.get("/{project_id}", response_model=ProjectRead)
def get_project(project_id: str, db: Session = Depends(get_db_session)) -> ProjectRead:
    try:
        project = ProjectService(db).get_project(project_id)
        return ProjectService(db)._to_project_read(project)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{project_id}")
def delete_project(project_id: str, db: Session = Depends(get_db_session)) -> dict:
    try:
        ProjectService(db).delete_project(project_id)
        return {"message": "Project deleted."}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/{project_id}", response_model=ProjectRead)
def update_project(project_id: str, payload: ProjectUpdate, db: Session = Depends(get_db_session)) -> ProjectRead:
    try:
        return ProjectService(db).update_project(project_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/{project_id}/export", response_model=ProjectBundle)
def export_project(project_id: str, db: Session = Depends(get_db_session)) -> ProjectBundle:
    try:
        return ProjectService(db).export_project_bundle(project_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/{project_id}/solutions", response_model=list[ProjectSolutionSummary])
def list_project_solutions(project_id: str, db: Session = Depends(get_db_session)) -> list[ProjectSolutionSummary]:
    try:
        return ProjectService(db).list_project_solutions(project_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
