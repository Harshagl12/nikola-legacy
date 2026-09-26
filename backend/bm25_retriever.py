"""
BM25 Keyword Retriever for Nikola AI RAG.
Provides exact keyword and term matching for:
- File names
- Function names / class names / variable names
- Error messages
- Technical terms and code identifiers
"""
import re
import math
from collections import Counter
from typing import List, Dict, Any


class BM25Retriever:
    """Fast, local BM25 keyword retrieval engine."""

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.documents: List[Dict[str, Any]] = []
        self.doc_tokens: List[List[str]] = []
        self.doc_len: List[int] = []
        self.avgdl: float = 0.0
        self.df: Dict[str, int] = Counter()
        self.idf: Dict[str, float] = {}
        self.num_docs: int = 0

    def _tokenize(self, text: str) -> List[str]:
        """Normalize and tokenize text, preserving camelCase and snake_case terms."""
        # Split camelCase and snake_case to preserve sub-words
        text_clean = re.sub(r'([a-z])([A-Z])', r'\1 \2', text)
        words = re.findall(r'[A-Za-z0-9_.]+', text_clean.lower())
        return words

    def fit(self, documents: List[Dict[str, Any]]):
        """Index a set of document chunk dicts containing 'text' and metadata."""
        self.documents = documents
        self.num_docs = len(documents)
        if self.num_docs == 0:
            return

        self.doc_tokens = []
        self.doc_len = []
        self.df = Counter()
        total_len = 0

        for doc in documents:
            content = f"{doc.get('filename', '')} {doc.get('symbol', '')} {doc.get('section', '')} {doc.get('text', '')}"
            tokens = self._tokenize(content)
            self.doc_tokens.append(tokens)
            l = len(tokens)
            self.doc_len.append(l)
            total_len += l

            unique_tokens = set(tokens)
            for t in unique_tokens:
                self.df[t] += 1

        self.avgdl = total_len / self.num_docs if self.num_docs > 0 else 1.0

        # Precompute IDF values
        self.idf = {}
        for term, freq in self.df.items():
            # BM25 IDF formula with smoothing
            idf_val = math.log((self.num_docs - freq + 0.5) / (freq + 0.5) + 1.0)
            self.idf[term] = max(0.0, idf_val)

    def search(self, query: str, top_k: int = 20) -> List[Dict[str, Any]]:
        """Search indexed documents by BM25 keyword relevance score."""
        if not self.documents or self.num_docs == 0:
            return []

        query_tokens = self._tokenize(query)
        if not query_tokens:
            return []

        scores = [0.0] * self.num_docs

        for q in query_tokens:
            if q not in self.idf:
                continue
            q_idf = self.idf[q]

            for i, doc_tokens in enumerate(self.doc_tokens):
                tf = doc_tokens.count(q)
                if tf == 0:
                    continue
                len_norm = 1.0 - self.b + self.b * (self.doc_len[i] / self.avgdl)
                score = q_idf * (tf * (self.k1 + 1.0)) / (tf + self.k1 * len_norm)
                scores[i] += score

        # Rank documents by score
        ranked_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        
        results = []
        for idx in ranked_indices[:top_k]:
            if scores[idx] > 0.0:
                doc_copy = dict(self.documents[idx])
                doc_copy["bm25_score"] = scores[idx]
                results.append(doc_copy)

        return results
