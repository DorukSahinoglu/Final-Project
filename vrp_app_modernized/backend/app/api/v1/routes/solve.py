from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db_session
from app.core.logging import get_logger
from app.db import models
from app.schemas.job import JobAcceptedResponse
from app.schemas.solve import SolveRequest
from app.services.solver_params import normalize_solver_params
from app.workers.manager import job_manager


router = APIRouter()
logger = get_logger(__name__)


def _validate_job_request(db: Session, payload: SolveRequest) -> None:
    if db.get(models.Project, payload.project_id) is None:
        raise ValueError("Project not found.")
    if db.get(models.MatrixSnapshot, payload.matrix_id) is None:
        raise ValueError("Matrix snapshot not found.")


@router.post("/nsga2", response_model=JobAcceptedResponse, status_code=status.HTTP_202_ACCEPTED)
def solve_nsga2(payload: SolveRequest, db: Session = Depends(get_db_session)) -> JobAcceptedResponse:
    try:
        logger.info("NSGA-II solve request received.", extra={"project_id": payload.project_id, "matrix_id": payload.matrix_id, "solver_params": payload.solver_params, "selected_address_ids": payload.selected_address_ids})
        _validate_job_request(db, payload)
        normalized_params = normalize_solver_params("nsga2", payload.solver_params)
        job_id = job_manager.submit_solver_job(payload.project_id, payload.matrix_id, "nsga2", normalized_params, payload.selected_address_ids)
        return JobAcceptedResponse(job_id=job_id, status="queued")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/bloodhound", response_model=JobAcceptedResponse, status_code=status.HTTP_202_ACCEPTED)
def solve_bloodhound(payload: SolveRequest, db: Session = Depends(get_db_session)) -> JobAcceptedResponse:
    try:
        logger.info("Bloodhound solve request received.", extra={"project_id": payload.project_id, "matrix_id": payload.matrix_id, "solver_params": payload.solver_params, "selected_address_ids": payload.selected_address_ids})
        _validate_job_request(db, payload)
        normalized_params = normalize_solver_params("bloodhound", payload.solver_params)
        job_id = job_manager.submit_solver_job(payload.project_id, payload.matrix_id, "bloodhound", normalized_params, payload.selected_address_ids)
        return JobAcceptedResponse(job_id=job_id, status="queued")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
