from fastapi import APIRouter, UploadFile, File
import tempfile
import os

from app.models.remediation import RemediationResponse
from app.models.schemas import IncidentRequest, IncidentResponse, VisionResponse
from app.services.curio import Curio
from inference.model_gateway import model_gateway


router = APIRouter(prefix="/api/v1/incidents", tags=["incidents"])
curio = Curio()


@router.post("", response_model=IncidentResponse)
async def create_incident(incident: IncidentRequest) -> IncidentResponse:
    return await curio.diagnose_incident(incident)


@router.post("/autofix", response_model=RemediationResponse)
async def autofix_incident(incident: IncidentRequest) -> RemediationResponse:
    return await curio.remediate_incident(incident)


@router.post("/vision", response_model=VisionResponse)
async def analyze_vision(file: UploadFile = File(...)) -> VisionResponse:
    with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        messages = [
            {"role": "user", "content": "Extract the visible deployment error text from this screenshot. Only return the extracted logs."}
        ]
        extracted = await model_gateway.generate_vision(image_path=tmp_path, messages=messages)
        return VisionResponse(extracted_logs=extracted)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
