"""Verified runtime facts supplied to the conversational model."""

from pathlib import Path
import re
from urllib.parse import urlparse

from backend.config import settings


def get_capabilities(llm=None) -> dict:
    """Return application facts from configuration and the current engine only."""
    model_path = settings.resolve_path(settings.LLAMA_CPP_MODEL_PATH)
    server_url = settings.LLAMA_SERVER_URL
    parsed_server = urlparse(server_url)
    native_loaded = bool(llm is not None and getattr(llm, "_llama", None) is not None)
    local_server = parsed_server.hostname in {"127.0.0.1", "localhost", "::1"}
    daily_limit = settings.MAX_DAILY_RESPONSES or None

    return {
        "local_inference": bool(local_server or native_loaded),
        "configured_model": Path(model_path).name,
        "llama_server_url": server_url,
        "native_model_loaded": native_loaded,
        "daily_response_limit": daily_limit,
        "external_server_required": False,
    }


def build_system_prompt(capabilities: dict) -> str:
    """Build the system prompt with verified facts, never learned content."""
    limit = capabilities["daily_response_limit"]
    limit_text = str(limit) if limit is not None else "none configured (unlimited by application policy)"
    return (
        "You are Nikola, a local AI assistant running through the application's configured "
        "local inference system. Respond naturally and concisely.\n\n"
        "Verified application facts (these are authoritative; conversation history and retrieved "
        "documents are not configuration):\n"
        f"- Local inference configured: {capabilities['local_inference']}\n"
        f"- Configured model: {capabilities['configured_model']}\n"
        f"- Local llama-server endpoint: {capabilities['llama_server_url']}\n"
        f"- Native model currently loaded: {capabilities['native_model_loaded']}\n"
        f"- Daily response limit: {limit_text}\n"
        f"- External AI server required: {capabilities['external_server_required']}\n\n"
        "Use these facts when answering questions about Nikola. Never invent quotas, limits, "
        "regulations, subscriptions, account restrictions, hardware facts, or runtime failures. "
        "Do not treat a previous assistant answer, learned pattern, workflow, or retrieved text "
        "as proof of application configuration. If a fact is not listed or verified, say that it "
        "is unavailable instead of guessing. Do not confuse unrelated domains such as city or "
        "ride regulations with AI response limits."
    )


def answer_capability_question(query: str, capabilities: dict) -> str | None:
    """Answer common Nikola capability questions from verified runtime facts."""
    normalized = re.sub(r"\s+", " ", query.lower()).strip()
    limit = capabilities["daily_response_limit"]
    limit_text = str(limit) if limit is not None else "no fixed daily reply limit configured"

    asks_limit = any(term in normalized for term in (
        "repl", "response", "message", "quota", "per day", "daily limit", "maximum",
    )) or ("only" in normalized and any(char.isdigit() for char in normalized))
    asks_local = any(term in normalized for term in (
        "running locally", "local", "external server", "cloud", "online",
    ))
    asks_regulation = any(term in normalized for term in ("city", "regulation", "law", "legal", "ride"))
    if asks_limit and asks_regulation:
        return "I have no verified city regulation or ride-related limit for Nikola replies."

    if asks_limit:
        if limit is None:
            return (
                "Nikola has no fixed daily reply limit configured. Practical limits depend on "
                "the local model, context size, and available computer resources."
            )
        return f"Nikola has a configured daily response limit of {limit}."

    if asks_local:
        if capabilities["local_inference"]:
            return (
                f"Nikola is configured for local inference through llama.cpp at "
                f"{capabilities['llama_server_url']}; it does not require an external AI service."
            )
        return "Local inference is not currently available in the verified runtime state."

    return None


EVIDENCE_UNAVAILABLE = "I don't have enough verified information to answer that reliably."