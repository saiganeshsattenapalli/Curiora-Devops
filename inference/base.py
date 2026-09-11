from typing import Protocol

from app.models.model_requests import TextDiagnosisRequest
from app.models.schemas import Diagnosis


class TextDiagnosisProvider(Protocol):
    async def diagnose(self, request: TextDiagnosisRequest) -> Diagnosis:
        ...
