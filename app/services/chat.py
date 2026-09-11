import uuid
from typing import Dict, List
from inference.model_gateway import model_gateway

class ChatService:
    def __init__(self) -> None:
        self.conversations: Dict[str, List[Dict[str, str]]] = {}
        self.system_prompt = (
            "You are CURIO, an AI DevOps assistant. You help engineers understand deployment "
            "errors, explain generated patches, answer DevOps questions, and explain code. "
            "You do not execute actions directly. Keep your answers concise and helpful."
        )
    
    async def chat(self, message: str, conversation_id: str | None = None) -> tuple[str, str]:
        if not message.strip():
            raise ValueError("Message cannot be empty")
        
        if not conversation_id or conversation_id not in self.conversations:
            conversation_id = str(uuid.uuid4())
            self.conversations[conversation_id] = [{"role": "system", "content": self.system_prompt}]
            
        history = self.conversations[conversation_id]
        history.append({"role": "user", "content": message})
        
        response = await model_gateway.generate_text(messages=history)
        history.append({"role": "assistant", "content": response})
        
        return conversation_id, response

chat_service = ChatService()
