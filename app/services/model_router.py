from app.models.model_requests import TextDiagnosisRequest
from app.models.schemas import Diagnosis
from inference.base import TextDiagnosisProvider
from inference.curio_text import CurioTextProvider


class ModelRouter:
    def __init__(self, text_provider: TextDiagnosisProvider | None = None) -> None:
        self.text_provider: TextDiagnosisProvider = (
            text_provider if text_provider is not None else CurioTextProvider()
        )

    async def diagnose_text(self, request: TextDiagnosisRequest) -> Diagnosis:
        return await self.text_provider.diagnose(request)
