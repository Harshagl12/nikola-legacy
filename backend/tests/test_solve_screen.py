from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from backend.main import app
from backend.config import settings

def test_solve_screen_fallback():
    client = TestClient(app)
    
    mock_llm = MagicMock()
    mock_llm.supports_vision = False
    mock_llm.text_infer.return_value = "Text fallback solution"
    
    with patch("backend.llm_engine.get_llm", return_value=mock_llm), \
         patch("backend.main._get_screen_text_context", return_value="Active Window: Notepad - test.txt"):
        
        res = client.post(
            "/solve-screen",
            json={"query": "What is open?"},
            headers={"X-API-Key": settings.NIKOLA_API_KEY}
        )
        
        assert res.status_code == 200
        data = res.json()
        assert data["solution"] == "Text fallback solution"
        assert "Notepad" in data["description"]
        mock_llm.text_infer.assert_called_once()
        mock_llm.vision_infer.assert_not_called()
