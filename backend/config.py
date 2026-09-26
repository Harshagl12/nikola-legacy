"""
Pydantic-settings configuration loader for NIKOLA backend.
Loads from .env file with typed defaults.
"""

from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"


class Settings(BaseSettings):
    """All backend configuration from .env with typed defaults."""

    # Primary Local LLM (Qwen3 / Qwen2.5 1.5B/1.7B)
    LLAMA_CPP_MODEL_PATH: str = str(BACKEND_ROOT / "models" / "qwen2.5-1.5b-instruct-q4_k_m.gguf")
    EMBEDDING_MODEL: str = "Qwen3-Embedding-0.6B"
    EMBEDDING_MODEL_PATH: str = str(BACKEND_ROOT / "models" / "Qwen3-Embedding-0.6B")
    VISION_MODEL: str = "moondream"
    LLAMA_SERVER_PORT: int = 8080
    LLAMA_SERVER_URL: str = "http://127.0.0.1:8080/v1"
    MAX_DAILY_RESPONSES: int | None = None
    ENABLE_OLLAMA_FALLBACK: bool = False

    # File system & RAG
    VAULT_PATH: str = "~/vault"
    CHROMA_PATH: str = "~/nikola_chroma"
    CHROMA_COLLECTION: str = "nikola_documents_v2"

    # RAG Parameters
    RAG_TOP_K: int = 5
    RAG_CANDIDATE_COUNT: int = 25
    RAG_FINAL_CHUNKS: int = 5
    RAG_RERANK_ENABLED: bool = True
    RAG_MIN_SCORE: float = 0.25
    DEBUG: bool = False

    # Telegram
    BOT_TOKEN: str = ""
    ALLOWED_USER_ID: int = 0
    ALLOWED_TELEGRAM_IDS: str = ""

    # Backend
    BACKEND_URL: str = "http://localhost:8000"
    NIKOLA_API_KEY: str = ""
    RUN_COMMANDS: bool = False

    # Voice
    VOICE_ENABLED: bool = True
    WAKE_WORD: str = "hey nikola"
    WHISPER_MODEL: str = "base"
    TTS_ENGINE: str = "piper"
    PIPER_MODEL_PATH: str = str(BACKEND_ROOT / "models" / "piper" / "en_US-lessac-medium.onnx")

    # Autofill
    AUTOFILL_PROFILE_PATH: str = "~/nikola_profile.json.enc"
    AUTOFILL_ENCRYPTION_KEY: str = ""
    PROFILE_REQUIRES_CONFIRMATION: bool = True

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    @field_validator("DEBUG", "VOICE_ENABLED", "ENABLE_OLLAMA_FALLBACK", "RUN_COMMANDS", "PROFILE_REQUIRES_CONFIRMATION", mode="before")
    @classmethod
    def normalise_boolean_environment_values(cls, value):
        """Accept legacy release/development strings without hiding invalid configuration."""
        if isinstance(value, str):
            legacy = value.strip().lower()
            if legacy in {"release", "production", "prod"}:
                return False
            if legacy in {"development", "dev"}:
                return True
        return value

    def resolve_path(self, path_str: str) -> str:
        """Expand ~ and resolve path to absolute."""
        return str(Path(path_str).expanduser().resolve())


# Global singleton
settings = Settings()
