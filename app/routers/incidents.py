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


from fastapi import Form
import json
import re

@router.post("/vision", response_model=VisionResponse)
async def analyze_vision(
    file: UploadFile = File(...),
    message: str | None = Form(None)
) -> VisionResponse:
    if not file.content_type.startswith("image/"):
        from fastapi import HTTPException
        raise HTTPException(400, "File must be an image")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        prompt = message or "Analyze this screenshot. Extract visible deployment error logs, provide a brief summary, and suggest next steps."
        messages = [
            {"role": "system", "content": "You are a DevOps assistant. Always respond in valid JSON format with keys: 'extracted_logs', 'summary', 'suggested_action'. 'suggested_action' should usually be 'analyze' or 'autofix'."},
            {"role": "user", "content": prompt}
        ]
        extracted = await model_gateway.generate_vision(image_path=tmp_path, messages=messages)
        
        cleaned = re.sub(r'```json\n|\n```|```', '', extracted.strip())
        try:
            data = json.loads(cleaned)
            return VisionResponse(
                extracted_logs=data.get("extracted_logs", ""),
                summary=data.get("summary", ""),
                suggested_action=data.get("suggested_action", "analyze")
            )
        except json.JSONDecodeError:
            return VisionResponse(
                extracted_logs=extracted,
                summary="Failed to parse structured JSON. See raw output.",
                suggested_action="analyze"
            )
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
