from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db_session
from app.schemas.geocode import GeocodeRequest, GeocodeResponse
from app.services.geocoding import GeocodingService


router = APIRouter()


@router.post("/geocode", response_model=GeocodeResponse)
def geocode(payload: GeocodeRequest, db: Session = Depends(get_db_session)) -> GeocodeResponse:
    try:
        return GeocodingService(db).geocode_project(payload.project_id, payload.address_ids)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
