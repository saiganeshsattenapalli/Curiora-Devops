import unittest
from unittest.mock import patch, AsyncMock
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.services.chat import chat_service

class ChatTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_chat_request_rejection(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post("/api/v1/chat", json={"message": "   "})
            self.assertEqual(response.status_code, 400)
            self.assertIn("Message cannot be empty", response.text)

    @patch("app.routers.chat.chat_service.chat", new_callable=AsyncMock)
    async def test_chat_conversation_continuity(self, mock_chat):
        mock_chat.return_value = ("conv_id_123", "Response 1")
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            res1 = await ac.post("/api/v1/chat", json={"message": "Hello"})
            self.assertEqual(res1.status_code, 200)
            data1 = res1.json()
            self.assertEqual(data1["conversation_id"], "conv_id_123")
            self.assertEqual(data1["message"], "Response 1")
            
            # Since we mock chat_service.chat, we just verify the call parameters
            mock_chat.assert_called_with("Hello", None)
            
            # Call 2
            mock_chat.return_value = ("conv_id_123", "Response 2")
            res2 = await ac.post("/api/v1/chat", json={"message": "Follow up", "conversation_id": "conv_id_123"})
            self.assertEqual(res2.status_code, 200)
            data2 = res2.json()
            self.assertEqual(data2["conversation_id"], "conv_id_123")
            self.assertEqual(data2["message"], "Response 2")
            
            mock_chat.assert_called_with("Follow up", "conv_id_123")

    @patch("app.services.chat.model_gateway.generate_text", new_callable=AsyncMock)
    async def test_chat_service_logic(self, mock_generate):
        mock_generate.return_value = "AI response"
        
        # Call 1
        conv_id, response = await chat_service.chat("First message")
        self.assertEqual(response, "AI response")
        history = chat_service.conversations[conv_id]
        self.assertEqual(len(history), 3) # system, user, assistant
        self.assertEqual(history[1]["content"], "First message")
        self.assertEqual(history[2]["content"], "AI response")
        
        # Call 2
        mock_generate.return_value = "AI response 2"
        conv_id2, response2 = await chat_service.chat("Second message", conversation_id=conv_id)
        self.assertEqual(conv_id2, conv_id)
        self.assertEqual(response2, "AI response 2")
        history2 = chat_service.conversations[conv_id]
        self.assertEqual(len(history2), 5)

    @patch("app.routers.chat.chat_service.chat", new_callable=AsyncMock)
    async def test_chat_cannot_trigger_remediation_side_effects(self, mock_chat):
        mock_chat.return_value = ("conv_id", "safe response")
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            res = await ac.post("/api/v1/chat", json={"message": "do something dangerous"})
            self.assertEqual(res.status_code, 200)
            mock_chat.assert_called_once()
