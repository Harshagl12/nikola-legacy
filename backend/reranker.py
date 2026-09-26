"""
Lightweight Local Reranker for Nikola AI RAG.
Reranks candidate document chunks retrieved from Vector Search and BM25.
Fully local, configurable via RAG_RERANK_ENABLED.
"""
from typing import List, Dict, Any
from backend.config import settings
from backend.logger import get_logger

logger = get_logger(__name__)


class LocalReranker:
    """Lightweight local reranker using token overlap and score fusion."""

    def __init__(self):
        self.enabled = getattr(settings, "RAG_RERANK_ENABLED", True)

    def rerank(self, query: str, candidates: List[Dict[str, Any]], top_k: int = 5) -> List[Dict[str, Any]]:
        """Rerank candidates and return top_k most relevant chunks."""
        if not candidates:
            return []

        if not self.enabled:
            # Reranker disabled: preserve order and deduplicate
            return self._deduplicate(candidates)[:top_k]

        query_terms = set(query.lower().split())

        scored_candidates = []
        for cand in candidates:
            text = cand.get("text", "")
            filename = cand.get("filename", "")
            symbol = cand.get("symbol", "")
            
            # 1. Base score from vector / BM25
            vector_score = cand.get("vector_score", 0.5)
            bm25_score = cand.get("bm25_score", 0.0)

            # 2. Exact match bonuses
            text_lower = text.lower()
            exact_term_matches = sum(1 for term in query_terms if term in text_lower)
            symbol_bonus = 2.0 if any(term in symbol.lower() for term in query_terms if term) else 0.0
            filename_bonus = 2.0 if any(term in filename.lower() for term in query_terms if term) else 0.0

            # Combined score formula
            final_score = (vector_score * 0.4) + (bm25_score * 0.3) + (exact_term_matches * 0.2) + symbol_bonus + filename_bonus
            
            cand_copy = dict(cand)
            cand_copy["rerank_score"] = round(final_score, 4)
            scored_candidates.append(cand_copy)

        # Sort by final score descending
        scored_candidates.sort(key=lambda x: x.get("rerank_score", 0.0), reverse=True)
        return self._deduplicate(scored_candidates)[:top_k]

    def _deduplicate(self, candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Remove duplicate text chunks while preserving highest ranking item."""
        seen_texts = set()
        deduped = []
        for cand in candidates:
            text = cand.get("text", "").strip()
            if text and text not in seen_texts:
                seen_texts.add(text)
                deduped.append(cand)
        return deduped
