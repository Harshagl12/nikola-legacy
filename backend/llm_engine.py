"""
LLMEngine - Thread-safe Singleton managing GGUF model lifecycle and inference.
Supports local llama-server HTTP API (OpenAI-compatible) and in-process llama_cpp fallback.
Optimized for Qwen3 1.7B GGUF with low latency streaming.
"""
import os
import gc
import json
import hashlib
import math
import threading
import psutil
import httpx
from pathlib import Path
from backend.config import settings
from backend.logger import get_logger
from backend.network_policy import require_local_url
from backend.runtime_compat import detect_cpu_features, runtime_requirements, supports_avx512


def llama_cpp_system_info() -> str:
    if llama_cpp is None:
        return ""
    info = llama_cpp.llama_print_system_info()
    return info.decode() if isinstance(info, bytes) else str(info)


def classify_runtime_error(error: Exception) -> dict[str, str]:
    detail = str(error)
    if "0xc000001d" in detail or "1073741795" in detail:
        return {
            "type": "cpu_incompatible",
            "detail": "llama.cpp raised illegal instruction (0xc000001d)",
        }
    if isinstance(error, FileNotFoundError):
        return {"type": "missing_model", "detail": detail}
    return {"type": "model_load_failure", "detail": detail}

logger = get_logger(__name__)

try:
    from llama_cpp import Llama
    import llama_cpp
    LLAMA_CPP_AVAILABLE = True
except ImportError:
    LLAMA_CPP_AVAILABLE = False
    Llama = None
    llama_cpp = None


class LLMEngine:
    _instance: "LLMEngine | None" = None
    _lock = threading.Lock()

    def __init__(self, model_path: str):
        self.model_path = model_path
        self.server_url = require_local_url(getattr(settings, "LLAMA_SERVER_URL", "http://127.0.0.1:8080/v1"))
        self.ollama_url = require_local_url(os.getenv("OLLAMA_URL", "http://127.0.0.1:11434"))
        self.ollama_model = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
        
        # Check if model file exists or if we can auto-detect a Qwen GGUF model in backend/models
        if not os.path.exists(model_path):
            detected = self._auto_detect_model()
            if detected:
                self.model_path = detected
                logger.info("Auto-detected model file", model_path=self.model_path)
            else:
                logger.warning(f"Model file not found at {model_path}. Server mode or fallback will be used.")

        model_name = Path(self.model_path).name.lower()
        self.supports_vision = any(x in model_name for x in ["vl", "vision", "moondream", "minicpm", "llava"])
        self._llama = None
        self.runtime_error: dict[str, str] | None = None
        
        # Try initializing local llama-cpp in-process if available (used if llama-server isn't running)
        if Llama is not None and os.path.exists(self.model_path):
            try:
                system_info = llama_cpp_system_info()
                required = runtime_requirements(system_info)
                cpu = detect_cpu_features()
                missing = [
                    name for name in ("AVX", "AVX2", "FMA", "F16C")
                    if required.get(name) and not cpu.get(name)
                ]
                if required.get("AVX512") and not supports_avx512():
                    missing.append("AVX512")
                if missing:
                    self.runtime_error = {
                        "type": "cpu_incompatible",
                        "detail": f"Runtime requires unsupported instruction set(s): {', '.join(missing)}",
                    }
                    logger.error("Incompatible llama.cpp runtime", **self.runtime_error)
                    return
                self._llama = Llama(
                    model_path=self.model_path,
                    n_ctx=8192,
                    n_gpu_layers=-1,
                    verbose=False
                )
                logger.info("Initialized in-process LLMEngine", model_path=self.model_path)
            except Exception as e:
                self.runtime_error = classify_runtime_error(e)
                logger.warning(f"Native Llama engine failed to load ({str(e)}). Relying on HTTP server/fallback.")
                self._llama = None

    def _auto_detect_model(self) -> str | None:
        models_dir = Path(self.model_path).expanduser().parent
        if not models_dir.exists():
            models_dir = Path(__file__).resolve().parent / "models"
        if not models_dir.exists():
            return None
        # Prefer Qwen GGUF files first
        qwen_files = list(models_dir.glob("*Qwen*.gguf")) + list(models_dir.glob("*qwen*.gguf"))
        if qwen_files:
            return str(qwen_files[0].resolve())
        # Otherwise any GGUF
        gguf_files = list(models_dir.glob("*.gguf"))
        if gguf_files:
            return str(gguf_files[0].resolve())
        return None

    def close(self):
        """Release native Llama.cpp resources."""
        if self._llama is None:
            return
        if hasattr(self._llama, "close"):
            try:
                self._llama.close()
            except Exception as e:
                logger.error("Error closing Llama instance", error=str(e))
        self._llama = None

    @classmethod
    def get_instance(cls):
        with cls._lock:
            if cls._instance is None:
                model_path = settings.resolve_path(settings.LLAMA_CPP_MODEL_PATH)
                cls._instance = cls(model_path)
            return cls._instance

    @classmethod
    def list_models(cls):
        models_dir = Path(settings.resolve_path(settings.LLAMA_CPP_MODEL_PATH)).parent
        if not models_dir.exists():
            models_dir = Path(__file__).resolve().parent / "models"
        
        current_model_path = settings.resolve_path(settings.LLAMA_CPP_MODEL_PATH)
        current_name = Path(current_model_path).name
        
        models = []
        if models_dir.exists():
            for f in models_dir.glob("*.gguf"):
                name = f.name
                # Exclude deleted Llama models from recommended selectable list if needed
                models.append({
                    "name": name,
                    "path": str(f.resolve()),
                    "size_mb": round(f.stat().st_size / (1024 * 1024), 1),
                    "active": name.lower() == current_name.lower()
                })
        return models, current_name

    @classmethod
    def switch_model(cls, model_name_or_path: str):
        with cls._lock:
            models_dir = Path(settings.resolve_path(settings.LLAMA_CPP_MODEL_PATH)).parent
            if not models_dir.exists():
                models_dir = Path(__file__).resolve().parent / "models"
            
            if os.path.exists(model_name_or_path):
                target_path = Path(model_name_or_path)
            else:
                target_path = models_dir / model_name_or_path
            
            if not target_path.exists():
                raise FileNotFoundError(f"Model {model_name_or_path} not found in {models_dir}")
            
            if cls._instance is not None:
                cls._instance.close()
                cls._instance = None
                gc.collect()
            
            settings.LLAMA_CPP_MODEL_PATH = str(target_path.resolve())
            cls._instance = cls(str(target_path.resolve()))
            return cls._instance

    def _query_server_chat(self, messages: list, max_tokens: int = 512, temperature: float = 0.7, stop: list = None) -> dict | None:
        """Attempt to query local llama-server HTTP OpenAI-compatible endpoint."""
        url = f"{self.server_url}/chat/completions"
        payload = {
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False
        }
        if stop:
            payload["stop"] = stop
            
        try:
            with httpx.Client(timeout=30.0) as client:
                res = client.post(url, json=payload)
                if res.status_code == 200:
                    return res.json()
        except Exception:
            pass
        return None

    def _query_ollama_chat(self, messages: list, max_tokens: int = 512, temperature: float = 0.7) -> dict | None:
        """Use the local Ollama model when llama-server/GGUF is unavailable."""
        payload = {
            "model": self.ollama_model,
            "messages": messages,
            "stream": False,
            "options": {"num_predict": max_tokens, "temperature": temperature},
        }
        try:
            with httpx.Client(timeout=90.0) as client:
                res = client.post(f"{self.ollama_url}/api/chat", json=payload)
                if res.status_code == 200:
                    data = res.json()
                    return {"choices": [{"message": data.get("message", {})}]}
        except Exception as exc:
            logger.warning("Ollama fallback unavailable", error=str(exc))
        return None

    def create_chat_completion(self, messages: list, max_tokens: int = 512, temperature: float = 0.7, **kwargs):
        # 1. Try local llama-server HTTP API
        server_res = self._query_server_chat(messages, max_tokens=max_tokens, temperature=temperature)
        if server_res:
            return server_res

        if settings.ENABLE_OLLAMA_FALLBACK:
            ollama_res = self._query_ollama_chat(messages, max_tokens=max_tokens, temperature=temperature)
            if ollama_res:
                return ollama_res

        # 2. Try in-process llama_cpp
        if self._llama is not None:
            try:
                return self._llama.create_chat_completion(
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    **kwargs
                )
            except Exception as e:
                logger.error("In-process llama_cpp chat completion failed", error=str(e))

        raise RuntimeError("Local model server is unavailable and the configured local model is not loaded")

    def create_completion(self, prompt: str, max_tokens: int = 512, **kwargs):
        messages = [{"role": "user", "content": prompt}]
        res = self.create_chat_completion(messages=messages, max_tokens=max_tokens, **kwargs)
        if "choices" in res and len(res["choices"]) > 0:
            msg = res["choices"][0].get("message", {})
            text = msg.get("content", "")
            return {"choices": [{"text": text}]}
        raise RuntimeError("Local model returned an invalid completion response")

    def is_ready(self) -> bool:
        """Return true only when an inference engine can accept local requests."""
        if self._llama is not None:
            return True
        try:
            with httpx.Client(timeout=2.0) as client:
                return client.get(f"{self.server_url}/models").status_code == 200
        except Exception:
            return False

    def create_embedding(self, input_text: str | list):
        """Generate embedding vector."""
        if isinstance(input_text, list):
            input_text = " ".join(input_text)
            
        # Try llama-server embedding endpoint if available
        try:
            url = f"{self.server_url}/embeddings"
            with httpx.Client(timeout=10.0) as client:
                res = client.post(url, json={"input": input_text})
                if res.status_code == 200:
                    return res.json()
        except Exception:
            pass

        # Try in-process llama
        if self._llama is not None and hasattr(self._llama, "create_embedding"):
            try:
                return self._llama.create_embedding(input_text)
            except Exception:
                pass

        # The configured llama-server is a text-generation server and may not
        # expose /embeddings. Keep document indexing local and deterministic in
        # that case instead of silently dropping every chunk. This is a lexical
        # fallback, not a replacement for the configured embedding model.
        return {"data": [{"embedding": self._fallback_embedding(input_text)}]}

    @staticmethod
    def _fallback_embedding(input_text: str, dimensions: int = 1024) -> list[float]:
        """Create a deterministic local lexical vector when no embedder exists."""
        vector = [0.0] * dimensions
        tokens = input_text.lower().split()
        for token in tokens:
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "little") % dimensions
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(value * value for value in vector))
        if norm:
            vector = [value / norm for value in vector]
        return vector

    def stream_infer(self, prompt: str, max_tokens: int = 512, **kwargs):
        """Yield token strings for SSE streaming using Qwen3 template."""
        messages = [{"role": "user", "content": prompt}]
        yield from self.stream_infer_messages(messages, max_tokens=max_tokens, **kwargs)

    def stream_infer_messages(self, messages: list, max_tokens: int = 512, **kwargs):
        """Stream a chat response while preserving system prompt and history."""
        
        # Try llama-server streaming
        url = f"{self.server_url}/chat/completions"
        payload = {
            "messages": messages,
            "max_tokens": max_tokens,
            "stream": True
        }
        try:
            with httpx.stream("POST", url, json=payload, timeout=60.0) as response:
                if response.status_code == 200:
                    for line in response.iter_lines():
                        if line.startswith("data: "):
                            data_str = line[6:].strip()
                            if data_str == "[DONE]":
                                break
                            try:
                                chunk = json.loads(data_str)
                                delta = chunk["choices"][0].get("delta", {})
                                content = delta.get("content", "")
                                if content:
                                    yield content
                            except Exception:
                                continue
                    return
        except Exception:
            pass

        if settings.ENABLE_OLLAMA_FALLBACK:
            try:
                payload = {
                    "model": self.ollama_model,
                    "messages": messages,
                    "stream": True,
                    "options": {"num_predict": max_tokens},
                }
                with httpx.stream("POST", f"{self.ollama_url}/api/chat", json=payload, timeout=90.0) as response:
                    if response.status_code == 200:
                        for line in response.iter_lines():
                            if not line:
                                continue
                            try:
                                content = json.loads(line).get("message", {}).get("content", "")
                                if content:
                                    yield content
                            except json.JSONDecodeError:
                                continue
                        return
            except Exception as exc:
                logger.warning("Ollama streaming fallback unavailable", error=str(exc))

        try:
            # Fallback to in-process llama_cpp streaming
            if self._llama is None:
                raise RuntimeError("Local model server is unavailable and the configured local model is not loaded")
        except RuntimeError:
            raise
        
        if self._llama is not None:
            try:
                for chunk in self._llama.create_chat_completion(messages=messages, max_tokens=max_tokens, stream=True, **kwargs):
                    if "choices" in chunk and len(chunk["choices"]) > 0:
                        delta = chunk["choices"][0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            yield content
                return
            except Exception:
                pass


    def text_infer(self, context_text: str, query: str):
        """Infer solution for screen text metadata."""
        prompt = f"System Context:\n{context_text}\n\nUser Query: {query}\n\nProvide an actionable diagnosis or shortcut:"
        res = self.create_chat_completion(messages=[{"role": "user", "content": prompt}], max_tokens=256)
        return res["choices"][0]["message"]["content"]

    def vision_infer(self, image_base64: str, query: str):
        """Infer solution from screen visual base64 image or multimodal context."""
        if not self.supports_vision:
            return self.text_infer("Image analysis context.", query)
        
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": query or "Analyze this screen and diagnose potential issues."},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}}
                ]
            }
        ]
        res = self.create_chat_completion(messages=messages, max_tokens=384)
        return res["choices"][0]["message"]["content"]


def get_llm():
    return LLMEngine.get_instance()
