"""
Central Model Registry for Nikola AI.
Stores paths, parameters, hardware allocations, and runtime configurations
for all 5 core local models:
1. Primary LLM: Qwen3 1.7B / Qwen2.5 1.5B Q4_K_M GGUF
2. Vision: Moondream2
3. Embeddings: Qwen3-Embedding-0.6B
4. Speech-to-Text: Faster-Whisper Base
5. Text-to-Speech: Piper TTS
"""
import os
from pathlib import Path
from typing import Dict, Any, Optional
from backend.config import settings
from backend.logger import get_logger

logger = get_logger(__name__)


class ModelRegistry:
    """Central registry and manager for all local AI models in Nikola."""

    MODELS: Dict[str, Dict[str, Any]] = {
        "llm": {
            "name": "Qwen3 1.7B Q4_K_M",
            "model_id": "qwen2.5-1.5b-instruct-q4_k_m.gguf",
            "type": "gguf",
            "role": "Primary Local Text Inference & Desktop Automation",
            "path": settings.resolve_path(settings.LLAMA_CPP_MODEL_PATH),
            "context_length": 8192,
            "gpu_layers": -1,  # Full GPU offload for RTX 2050
            "vram_budget_mb": 1150,
            "system_ram_mb": 500,
            "runtime": "llama-server / llama_cpp",
            "format": "chatml",
            "stop_tokens": ["<|im_end|>", "<|endoftext|>"],
            "always_loaded": True
        },
        "embedding": {
            "name": "Qwen3-Embedding-0.6B",
            "model_id": "Qwen3-Embedding-0.6B",
            "type": "dense_embedding",
            "role": "Document Semantic Vectorization",
            "path": settings.resolve_path(settings.EMBEDDING_MODEL_PATH),
            "dimensions": 1024,
            "vram_budget_mb": 0,  # CPU int8 / RAM for minimal VRAM contention
            "system_ram_mb": 600,
            "always_loaded": False
        },
        "vision": {
            "name": "Moondream2",
            "model_id": "moondream2",
            "type": "vision_encoder",
            "role": "Desktop Screenshot & Visual Diagnosis",
            "path": settings.resolve_path(settings.VISION_MODEL_PATH),
            "mmproj_path": settings.resolve_path(settings.VISION_MMPROJ_PATH),
            "vram_budget_mb": 1200,
            "system_ram_mb": 800,
            "always_loaded": False  # Load on-demand for /solve-screen
        },
        "stt": {
            "name": "Faster-Whisper Base",
            "model_id": "base",
            "type": "audio_transcription",
            "role": "Always-On Voice & Command Transcription",
            "wake_word": settings.WAKE_WORD,
            "vram_budget_mb": 150,
            "system_ram_mb": 250,
            "compute_type": "int8",
            "always_loaded": True
        },
        "tts": {
            "name": "Piper TTS",
            "model_id": getattr(settings, "PIPER_MODEL_PATH", "en_US-lessac-medium"),
            "type": "acoustic_vocoder",
            "role": "Offline Speech Synthesis",
            "path": getattr(settings, "PIPER_MODEL_PATH", "C:/nikola/backend/models/piper/en_US-lessac-medium.onnx"),
            "sample_rate": 16000,
            "vram_budget_mb": 0,  # Runs lightweight on CPU
            "system_ram_mb": 100,
            "fallback": "pyttsx3",
            "always_loaded": False
        }
    }

    @classmethod
    def get_model_spec(cls, model_key: str) -> Optional[Dict[str, Any]]:
        return cls.MODELS.get(model_key)

    @classmethod
    def get_all_specs(cls) -> Dict[str, Dict[str, Any]]:
        return cls.MODELS

    @classmethod
    def verify_paths(cls) -> Dict[str, bool]:
        """Check presence of model files on disk."""
        status = {}
        for key, spec in cls.MODELS.items():
            path_str = spec.get("path")
            if path_str:
                status[key] = os.path.exists(path_str)
            else:
                status[key] = True
        return status

    @classmethod
    def get_vram_summary(cls) -> Dict[str, Any]:
        """Calculate total VRAM and RAM footprint for RTX 2050 (4 GB) budget."""
        total_vram = sum(m.get("vram_budget_mb", 0) for m in cls.MODELS.values())
        total_ram = sum(m.get("system_ram_mb", 0) for m in cls.MODELS.values())
        return {
            "target_gpu": "NVIDIA GeForce RTX 2050 (4 GB VRAM)",
            "target_ram": "16 GB System RAM",
            "total_allocated_vram_mb": total_vram,
            "vram_headroom_mb": 4096 - total_vram,
            "total_allocated_ram_mb": total_ram,
            "fits_in_4gb_vram": total_vram <= 4096
        }
