"""
All Pydantic v2 request/response models for NIKOLA backend.
Never define models inline in main.py.
"""

from typing import Any, Literal, Optional
from pydantic import BaseModel, Field


# === RAG Models ===


class AskRequest(BaseModel):
    """Request to ask a question."""

    query: str = Field(..., min_length=1, description="User question")
    use_rag: bool = Field(default=False, description="Use RAG context explicitly")
    conversation_id: Optional[str] = Field(
        default=None, description="Conversation ID for multi-turn"
    )
    stream: Optional[bool] = Field(default=False, description="Stream SSE response")
    source: Literal["text", "voice", "telegram"] = Field(
        default="text",
        description="Input modality; this never changes action permissions",
    )


class AskResponse(BaseModel):
    """Response to question."""

    answer: str = Field(..., description="Generated answer")
    sources: list[str] = Field(default_factory=list, description="Source files used")
    conversation_id: str = Field(..., description="Conversation ID")
    action_result: Optional[dict[str, Any]] = Field(
        default=None,
        description="Structured result when the request performs an application action",
    )
    action_state: Optional[str] = Field(
        default=None,
        description="Application action lifecycle state for the desktop UI",
    )
    action_id: Optional[str] = Field(
        default=None,
        description="Identifier for polling the application action lifecycle",
    )


class IndexRequest(BaseModel):
    """Request to index a file."""

    file_path: str = Field(..., description="Path to file to index")


class IndexResponse(BaseModel):
    """Response after indexing."""

    success: bool = Field(..., description="Index success")
    chunks_added: int = Field(..., description="Number of chunks indexed")
    filename: str = Field(..., description="Indexed filename")


class RemoveRequest(BaseModel):
    """Request to remove indexed file."""

    filename: str = Field(..., description="Filename to remove")
    confirm: bool = Field(default=False, description="Explicit confirmation to delete the source file")


class RemoveResponse(BaseModel):
    """Response after removing file."""

    ok: bool = Field(..., description="Removal success")
    filename: str = Field(..., description="Removed filename")
    chunks_deleted: int = Field(..., description="Chunks removed from RAG")


class ClearAllRequest(BaseModel):
    """Request to clear all indexed files."""

    confirm: bool = Field(..., description="Explicit confirmation")


class ClearAllResponse(BaseModel):
    """Response after clearing all."""

    ok: bool = Field(..., description="Clear success")
    chunks_deleted: int = Field(..., description="Total chunks deleted")
    files_removed: int = Field(..., description="Total files deleted")


# === Autofill Models ===


class AutofillProfileField(BaseModel):
    """Profile field with value."""

    field: str = Field(..., description="Field name")
    value: str = Field(..., description="Field value")


class AutofillFillRequest(BaseModel):
    """Request to fill form fields."""

    form_fields: list[dict] = Field(..., description="Form fields to fill")


class AutofillFillResponse(BaseModel):
    """Response with field mappings."""

    mappings: dict = Field(..., description="Field name -> value mapping")
    confidence: dict = Field(..., description="Field name -> confidence 0-1")
    sources: Optional[dict] = Field(default=None, description="Source type per field")


class AutofillClearResponse(BaseModel):
    """Response after clearing profile."""

    ok: bool = Field(..., description="Clear success")


# === Voice Models ===


class VoiceSpeakRequest(BaseModel):
    """Request to speak text."""

    text: str = Field(..., min_length=1, description="Text to speak")


class VoiceTranscribeResponse(BaseModel):
    """Response after transcribing audio."""

    text: str = Field(..., description="Transcribed text")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score")
    error: Optional[str] = Field(default=None, description="Error if any")


# === Vision Models ===


class ScreenRequest(BaseModel):
    """Request to analyze screen state."""
    query: Optional[str] = Field(default="Analyze this screen and diagnose potential issues.", description="Question about the screen")
    screenshot_base64: Optional[str] = Field(default=None, description="Optional Electron-captured JPEG image")


class SolveScreenResponse(BaseModel):
    """Response after analyzing screenshot."""

    description: str = Field(..., description="What I see")
    solution: str = Field(..., description="Problem and solution")
    timestamp: str = Field(..., description="ISO8601 timestamp")


# === Status Models ===


class StatusResponse(BaseModel):
    """System status response."""

    indexed_files: int = Field(..., description="Total indexed files")
    collection_size: int = Field(..., description="Total chunks in RAG")
    models_loaded: list[str] = Field(..., description="Loaded AI models")
    voice_active: bool = Field(..., description="Voice engine running")
    voice_state: str = Field(default="VOICE_UNAVAILABLE", description="Voice lifecycle state")
    microphone_state: str = Field(default="MICROPHONE_UNKNOWN", description="Physical microphone state")
    microphone_device: Optional[str] = Field(default=None, description="Selected input device name")
    wake_word: Optional[str] = Field(default=None, description="Configured wake phrase")
    uptime_seconds: float = Field(..., description="Backend uptime")
    backend_state: str = Field(default="BACKEND_READY", description="Verified backend lifecycle state")
    model_state: str = Field(default="MODEL_LOADING", description="Verified local model lifecycle state")
    rag_state: str = Field(default="RAG_LOADING", description="Verified RAG lifecycle state")
    vision_state: str = Field(default="VISION_UNAVAILABLE", description="Verified vision lifecycle state")
    startup_error: Optional[str] = Field(default=None, description="Safe startup diagnostic")
    request_count: int = Field(default=0, description="Requests observed since startup")
    error_count: int = Field(default=0, description="Requests ending in a server error")
    average_latency_ms: float = Field(default=0.0, description="Average request latency in milliseconds")
    service_errors: dict[str, str] = Field(default_factory=dict, description="Optional service initialization errors")


# === NL Models ===


class NLCommandRequest(BaseModel):
    """Request to process natural language command."""

    text: str = Field(..., min_length=1, description="Natural language command")
    stream: Optional[bool] = Field(default=False, description="Stream SSE response")


class NLCommandResponse(BaseModel):
    """Response after processing NL command."""

    action: str = Field(..., description="Action type")
    description: str = Field(..., description="Human description")
    success: bool = Field(..., description="Command success")
    result: dict = Field(default_factory=dict, description="Detailed result")
    error: Optional[str] = Field(default=None, description="Error message")
    was_healed: Optional[bool] = Field(default=False)
    healing_explanation: Optional[str] = Field(default=None)
    healing_log: Optional[list] = Field(default=None)
    confidence: Optional[float] = Field(default=None)
    action_id: Optional[str] = Field(default=None)
    action_state: Optional[str] = Field(default=None)


class IntentResult(BaseModel):
    intent: str
    confidence: float
    description: str
    action: str

class DisambiguationResponse(BaseModel):
    query: str
    interpretations: list[IntentResult]
    auto_executed: bool
    result: Optional[dict] = None


# === File Models ===


class FileBrowserResponse(BaseModel):
    """Response when browsing files."""

    path: str = Field(..., description="Browsed path")
    items: list[dict] = Field(..., description="Items in directory")
    count: int = Field(..., description="Item count")
    error: Optional[str] = Field(default=None, description="Error if any")


class FileReadResponse(BaseModel):
    """Response when reading file."""

    path: str = Field(..., description="File path")
    content: str = Field(..., description="File content")
    size: int = Field(..., description="File size in bytes")
    error: Optional[str] = Field(default=None, description="Error if any")


# === Error Models ===


class ErrorResponse(BaseModel):
    """Generic error response."""

    error: str = Field(..., description="Error message")
    status: int = Field(..., description="HTTP status code")


class MemoryWriteRequest(BaseModel):
    tier: str = Field(..., pattern=r"^(project|long_term)$")
    fact: str = Field(..., min_length=1, max_length=1000)
    approved: bool = Field(default=False, description="Required for long-term memory")


class MemoryQueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    session_id: Optional[str] = Field(default=None, max_length=200)


# === Model Management Models ===


class ModelInfo(BaseModel):
    name: str = Field(..., description="Model filename")
    path: str = Field(..., description="Absolute path to model file")
    size_mb: float = Field(..., description="File size in MB")
    active: bool = Field(..., description="Whether this is the currently loaded model")


class ModelListResponse(BaseModel):
    models: list[ModelInfo] = Field(..., description="List of available AI models")
    active_model: str = Field(..., description="Currently active model name")


class SwitchModelRequest(BaseModel):
    model_name: str = Field(..., description="Name of the model to switch to")


class SwitchModelResponse(BaseModel):
    success: bool = Field(..., description="Switch success")
    active_model: str = Field(..., description="New active model name")
    message: str = Field(..., description="Status message")


class ModelDownloadRequest(BaseModel):
    repo_id: Optional[str] = Field(default="Qwen/Qwen2.5-1.5B-Instruct-GGUF", description="HuggingFace repo ID")
    filename: Optional[str] = Field(default="qwen2.5-1.5b-instruct-q4_k_m.gguf", description="Model filename")
    url: Optional[str] = Field(default=None, description="Direct download URL")
