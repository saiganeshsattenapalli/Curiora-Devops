import unittest
import io
import json
from unittest.mock import patch, AsyncMock
from httpx import AsyncClient, ASGITransport
from app.main import app

class VisionTests(unittest.IsolatedAsyncioTestCase):
    async def test_image_validation(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            files = {'file': ('test.txt', b'not an image', 'text/plain')}
            response = await ac.post("/api/v1/incidents/vision", files=files)
            self.assertEqual(response.status_code, 400)
            self.assertIn("File must be an image", response.text)

    @patch("app.routers.incidents.model_gateway.generate_vision", new_callable=AsyncMock)
    async def test_vision_response_valid_json(self, mock_generate):
        mock_generate.return_value = '```json\n{"extracted_logs": "Error 123", "summary": "DB down", "suggested_action": "analyze"}\n```'
        
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            files = {'file': ('test.png', b'fake image data', 'image/png')}
            data = {'message': 'Check this'}
            
            response = await ac.post("/api/v1/incidents/vision", files=files, data=data)
            self.assertEqual(response.status_code, 200)
            resp_data = response.json()
            self.assertEqual(resp_data["extracted_logs"], "Error 123")
            self.assertEqual(resp_data["summary"], "DB down")
            self.assertEqual(resp_data["suggested_action"], "analyze")
            
            mock_generate.assert_called_once()
            args, kwargs = mock_generate.call_args
            messages = kwargs["messages"]
            self.assertTrue(any(m["content"] == "Check this" for m in messages if m["role"] == "user"))

    @patch("app.routers.incidents.model_gateway.generate_vision", new_callable=AsyncMock)
    async def test_vision_response_invalid_json(self, mock_generate):
        mock_generate.return_value = 'Plain text response without JSON'
        
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            files = {'file': ('test.png', b'fake image data', 'image/png')}
            
            response = await ac.post("/api/v1/incidents/vision", files=files)
            self.assertEqual(response.status_code, 200)
            resp_data = response.json()
            self.assertEqual(resp_data["extracted_logs"], "Plain text response without JSON")
            self.assertEqual(resp_data["suggested_action"], "analyze")
