from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db_session
from app.db import models
from app.schemas.common import APIMessage
from app.schemas.job import JobRead
from app.utils.json import loads
from app.workers.manager import job_manager


router = APIRouter()


@router.get("/{job_id}", response_model=JobRead)
def get_job(job_id: str, db: Session = Depends(get_db_session)) -> JobRead:
    job = db.get(models.Job, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")
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


@router.post("/{job_id}/cancel", response_model=APIMessage)
def cancel_job(job_id: str) -> APIMessage:
    try:
        job_manager.cancel_job(job_id)
        return APIMessage(message="Cancellation requested.")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
