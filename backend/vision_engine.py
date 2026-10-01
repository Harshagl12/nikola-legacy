"""Local Moondream2 vision client backed by llama.cpp libmtmd."""

import base64
from pathlib import Path

import httpx

from backend.config import settings
from backend.logger import get_logger

logger = get_logger(__name__)


class VisionEngine:
    """Call the separately managed Moondream2 llama-server."""

    def __init__(self) -> None:
        self.server_url = settings.VISION_SERVER_URL.rstrip("/")
        self.model_path = Path(settings.resolve_path(settings.VISION_MODEL_PATH))
        self.mmproj_path = Path(settings.resolve_path(settings.VISION_MMPROJ_PATH))
        self.last_error: str | None = None

    def _request(self, image_base64: str, query: str) -> str:
        payload = {
            "prompt": query,
            "image_data": [{"data": image_base64}],
            "max_tokens": 256,
            "temperature": 0.2,
            "stream": False,
        }
        response = httpx.post(
            self.server_url.replace("/v1", "") + "/completion",
            json=payload,
            timeout=120.0,
        )
        response.raise_for_status()
        content = response.json().get("content", "")
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("Moondream2 returned an empty response")
        return content.strip()

    def infer(self, image_base64: str, query: str) -> str:
        if not image_base64:
            raise ValueError("Vision inference requires non-empty image data")
        if not self.model_path.is_file():
            raise FileNotFoundError(f"Moondream2 text model is missing: {self.model_path}")
        if not self.mmproj_path.is_file():
            raise FileNotFoundError(f"Moondream2 mmproj is missing: {self.mmproj_path}")
        try:
            return self._request(image_base64, query)
        except Exception as error:
            self.last_error = str(error)
            logger.error("Moondream2 inference failed", error=str(error))
            raise

    def is_ready(self) -> bool:
        if not self.model_path.is_file() or not self.mmproj_path.is_file():
            return False
        try:
            response = httpx.get(f"{self.server_url}/models", timeout=3.0)
            return response.status_code == 200
        except Exception:
            return False

    def verify_inference(self, image_base64: str) -> str:
        """Run a real image request before reporting VISION_READY."""
        return self.infer(image_base64, "What is visible in this image?")
