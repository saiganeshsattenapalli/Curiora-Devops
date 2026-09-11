from fastapi import APIRouter, HTTPException

from app.models.schemas import ChatRequest, ChatResponse
from app.services.chat import chat_service

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])

@router.post("", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    try:
        conversation_id, response_text = await chat_service.chat(
            request.message, request.conversation_id
        )
        return ChatResponse(conversation_id=conversation_id, message=response_text)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
