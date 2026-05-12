from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db_session
from app.schemas.project import ProjectCreate, ProjectRead, ProjectSolutionSummary, ProjectUpdate
from app.services.projects import ProjectService


router = APIRouter()


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
def create_project(payload: ProjectCreate, db: Session = Depends(get_db_session)) -> ProjectRead:
    try:
        return ProjectService(db).create_project(payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/{project_id}", response_model=ProjectRead)
def get_project(project_id: str, db: Session = Depends(get_db_session)) -> ProjectRead:
    try:
        project = ProjectService(db).get_project(project_id)
        return ProjectService(db)._to_project_read(project)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/{project_id}", response_model=ProjectRead)
def update_project(project_id: str, payload: ProjectUpdate, db: Session = Depends(get_db_session)) -> ProjectRead:
    try:
        return ProjectService(db).update_project(project_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/{project_id}/solutions", response_model=list[ProjectSolutionSummary])
def list_project_solutions(project_id: str, db: Session = Depends(get_db_session)) -> list[ProjectSolutionSummary]:
    try:
        return ProjectService(db).list_project_solutions(project_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
