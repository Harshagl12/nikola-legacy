from unittest.mock import patch, MagicMock
import pytest
import os
import gc
from backend.llm_engine import LLMEngine
from backend.config import settings

def test_model_switch(tmp_path):
    model_a = tmp_path / "model_a.gguf"
    model_a.write_text("dummy a")
    model_b = tmp_path / "model_b.gguf"
    model_b.write_text("dummy b")
    
    mock_llama_instance_a = MagicMock()
    mock_llama_instance_b = MagicMock()
    
    with patch("backend.llm_engine.Llama") as mock_llama_cls, \
         patch("gc.collect", wraps=gc.collect) as mock_gc:
        
        mock_llama_cls.side_effect = [mock_llama_instance_a, mock_llama_instance_b]
        
        LLMEngine._instance = None
        settings.LLAMA_CPP_MODEL_PATH = str(model_a)
        inst_a = LLMEngine.get_instance()
        assert inst_a._llama == mock_llama_instance_a
        
        inst_b = LLMEngine.switch_model(str(model_b))
        
        mock_llama_instance_a.close.assert_called_once()
        assert mock_gc.called
        assert inst_b._llama == mock_llama_instance_b
        assert LLMEngine._instance == inst_b
        
        LLMEngine._instance = None
