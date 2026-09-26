"""Deterministic post-generation grounding checks for retrieved evidence."""

import re

from backend.capabilities import EVIDENCE_UNAVAILABLE

_STOP_WORDS = {
    "about", "after", "again", "also", "because", "being", "could", "from",
    "have", "into", "just", "more", "over", "that", "their", "there", "these",
    "they", "this", "those", "using", "what", "when", "where", "which", "while",
    "with", "would", "your", "the", "and", "for", "are", "was", "were", "has",
    "had", "not", "but", "can", "does", "its", "you", "our", "out", "all",
}


def _terms(text: str) -> set[str]:
    return {
        token for token in re.findall(r"[a-z0-9_]{3,}", text.casefold())
        if token not in _STOP_WORDS
    }


def verify_answer(answer: str, evidence_chunks: list[str]) -> tuple[str, dict]:
    """Keep only answer sentences supported by retrieved evidence terms.

    This is intentionally independent of the generator: the model cannot mark
    its own claims as verified.
    """
    evidence_terms = _terms(" ".join(evidence_chunks))
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", answer.strip()) if part.strip()]
    supported: list[str] = []
    rejected = 0
    for sentence in sentences:
        claim_terms = _terms(sentence)
        if not claim_terms or len(claim_terms & evidence_terms) >= 1:
            supported.append(sentence)
        else:
            rejected += 1
    if not supported:
        return EVIDENCE_UNAVAILABLE, {"supported": False, "rejected_claims": rejected}
    return " ".join(supported), {"supported": rejected == 0, "rejected_claims": rejected}
