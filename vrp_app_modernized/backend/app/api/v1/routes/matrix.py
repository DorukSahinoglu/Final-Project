from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db_session
from app.schemas.matrix import MatrixGenerateRequest, MatrixLoadJsonRequest, MatrixSummary
from app.services.matrix import MatrixService


router = APIRouter()


@router.post("/generate", response_model=MatrixSummary, status_code=status.HTTP_201_CREATED)
def generate_matrix(payload: MatrixGenerateRequest, db: Session = Depends(get_db_session)) -> MatrixSummary:
    try:
        return MatrixService(db).generate(payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/load-json", response_model=MatrixSummary, status_code=status.HTTP_201_CREATED)
def load_matrix_json(payload: MatrixLoadJsonRequest, db: Session = Depends(get_db_session)) -> MatrixSummary:
    try:
        return MatrixService(db).load_json(payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
