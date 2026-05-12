from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db_session
from app.schemas.solution import SolutionRead
from app.services.solutions import SolutionService


router = APIRouter()


@router.get("/{solution_id}", response_model=SolutionRead)
def get_solution(solution_id: str, db: Session = Depends(get_db_session)) -> SolutionRead:
    try:
        return SolutionService(db).get_solution(solution_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
