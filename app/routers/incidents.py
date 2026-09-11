from fastapi import APIRouter

from app.models.schemas import IncidentRequest, IncidentResponse
from app.services.curio import Curio


router = APIRouter(prefix="/api/v1/incidents", tags=["incidents"])
curio = Curio()


@router.post("", response_model=IncidentResponse)
async def create_incident(incident: IncidentRequest) -> IncidentResponse:
    return await curio.diagnose_incident(incident)
