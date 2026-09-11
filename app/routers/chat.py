from fastapi import APIRouter

from app.models.schemas import ChatRequest, ChatResponse
from inference.model_gateway import model_gateway

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])

@router.post("", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    messages = []
    if request.incident_context:
        messages.append({"role": "system", "content": f"Incident context:\n{request.incident_context}"})
    messages.append({"role": "user", "content": request.message})
    
    response_text = await model_gateway.generate_text(messages=messages)
    return ChatResponse(response=response_text)
