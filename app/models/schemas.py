from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class IncidentRequest(BaseModel):
    source: str = Field(min_length=1)
    repository: str = Field(min_length=1)
    branch: str = Field(min_length=1)
    logs: str = Field(min_length=1)


class Diagnosis(BaseModel):
    error_type: str
    root_cause: str
    affected_files: list[str]
    proposed_fix: str
    confidence: float = Field(ge=0.0, le=1.0)
    safe_to_autofix: bool


class IncidentResponse(Diagnosis):
    status: Literal["diagnosed"] = "diagnosed"
    incident_id: UUID


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    conversation_id: str | None = None


class ChatResponse(BaseModel):
    conversation_id: str
    message: str


class VisionResponse(BaseModel):
    extracted_logs: str
    summary: str
    suggested_action: str
