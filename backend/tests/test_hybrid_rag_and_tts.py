import pytest
from backend.smart_chunker import SmartChunker
from backend.bm25_retriever import BM25Retriever
from backend.reranker import LocalReranker
from backend.piper_tts import PiperTTSEngine


def test_smart_chunker_python():
    chunker = SmartChunker(max_chunk_size=500)
    code = """
import os
import sys

class DataProcessor:
    def process(self, item):
        return item.strip()

def run_pipeline():
    p = DataProcessor()
    return p.process("test")
"""
    chunks = chunker.chunk_file("test.py", code)
    assert len(chunks) >= 2
    symbols = [c.get("symbol") for c in chunks]
    assert any("DataProcessor" in s for s in symbols)
    assert any("run_pipeline" in s for s in symbols)


def test_smart_chunker_markdown():
    chunker = SmartChunker(max_chunk_size=500)
    doc = """
# Introduction
This is the intro section.

## Architecture
Nikola AI uses hybrid RAG and local Qwen inference.

## Verification
Run pytest tests.
"""
    chunks = chunker.chunk_file("readme.md", doc)
    assert len(chunks) == 3
    sections = [c.get("section") for c in chunks]
    assert "Introduction" in sections
    assert "Architecture" in sections
    assert "Verification" in sections


def test_bm25_retriever():
    retriever = BM25Retriever()
    docs = [
        {"filename": "math.py", "symbol": "calculate_fibonacci", "text": "def calculate_fibonacci(n): return n"},
        {"filename": "network.py", "symbol": "http_request", "text": "def http_request(url): return fetch(url)"},
        {"filename": "database.py", "symbol": "query_users", "text": "SELECT * FROM users WHERE active = 1"}
    ]
    retriever.fit(docs)
    
    res = retriever.search("calculate_fibonacci", top_k=2)
    assert len(res) > 0
    assert res[0]["symbol"] == "calculate_fibonacci"
    assert res[0]["filename"] == "math.py"


def test_local_reranker():
    reranker = LocalReranker()
    candidates = [
        {"filename": "app.py", "symbol": "run", "text": "generic text", "vector_score": 0.5, "bm25_score": 0.1},
        {"filename": "auth.py", "symbol": "validate_token", "text": "exact token validator", "vector_score": 0.8, "bm25_score": 0.9}
    ]
    results = reranker.rerank("validate token authentication", candidates, top_k=2)
    assert len(results) == 2
    assert results[0]["symbol"] == "validate_token"
    assert results[0]["rerank_score"] > results[1]["rerank_score"]


def test_piper_tts_synthesis():
    engine = PiperTTSEngine()
    audio, mime = engine.synthesize("Testing offline speech.")
    assert len(audio) > 0
    assert mime == "audio/wav"


def test_model_registry():
    from backend.model_registry import ModelRegistry
    specs = ModelRegistry.get_all_specs()
    assert "llm" in specs
    assert "vision" in specs
    assert "embedding" in specs
    assert "stt" in specs
    assert "tts" in specs
    summary = ModelRegistry.get_vram_summary()
    assert summary["fits_in_4gb_vram"] is True

