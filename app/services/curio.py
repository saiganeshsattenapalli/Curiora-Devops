from uuid import uuid4

from app.models.model_requests import TextDiagnosisRequest
from app.models.schemas import IncidentRequest, IncidentResponse
from app.services.model_router import ModelRouter


class Curio:
    def __init__(self, model_router: ModelRouter | None = None) -> None:
        self.model_router = model_router if model_router is not None else ModelRouter()

    async def diagnose_incident(self, incident: IncidentRequest) -> IncidentResponse:
        request = TextDiagnosisRequest(
            source=incident.source,
            repository=incident.repository,
            branch=incident.branch,
            logs=incident.logs,
        )
        diagnosis = await self.model_router.diagnose_text(request)
        return IncidentResponse(
            incident_id=uuid4(),
            **diagnosis.model_dump(),
        )
