from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
import pytest
from backend.main import app, rag
from backend.config import settings

def test_rag_index_and_ask(tmp_path):
    client = TestClient(app)
    
    test_file = tmp_path / "test_doc.txt"
    test_file.write_text("Nikola is an AI agent that supports RAG vector indexing.")
    
    mock_llm = MagicMock()
    mock_llm.create_embedding.return_value = {"data": [{"embedding": [0.1] * 1024}]}
    mock_llm.create_chat_completion.return_value = {
        "choices": [{"message": {"content": "RAG answer based on context"}}]
    }
    
    with patch("backend.llm_engine.get_llm", return_value=mock_llm):
        try:
            # 1. Index file
            res_idx = client.post(
                "/index",
                json={"file_path": str(test_file)},
                headers={"X-API-Key": settings.NIKOLA_API_KEY}
            )
            assert res_idx.status_code == 200
            data_idx = res_idx.json()
            assert data_idx["success"] is True
            assert data_idx["chunks_added"] > 0
            
            # Verify store has chunk
            assert rag.store.count() > 0
            
            # 2. Query via /ask
            res_ask = client.post(
                "/ask",
                json={"query": "What is Nikola?", "use_rag": True},
                headers={"X-API-Key": settings.NIKOLA_API_KEY}
            )
            assert res_ask.status_code == 200
            data_ask = res_ask.json()
            assert data_ask["answer"] == "RAG answer based on context"
            assert "test_doc.txt" in data_ask["sources"]
        finally:
            rag.store.delete(where={"filename": "test_doc.txt"})
