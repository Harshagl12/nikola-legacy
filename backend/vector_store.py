"""
VectorStore - Isolates vector database operations using persistent ChromaDB.
"""
from pathlib import Path
from typing import Optional, List, Dict, Any
import chromadb
from backend.config import settings
from backend.filesystem_policy import FileOperation, authorize_path
from backend.logger import get_logger

logger = get_logger(__name__)


class VectorStore:
    def __init__(self, chroma_path: Optional[str] = None):
        path_str = chroma_path or settings.CHROMA_PATH
        self.chroma_path = authorize_path(
            path_str,
            FileOperation.WRITE,
            internal_storage=True,
        )
        self.chroma_path.mkdir(parents=True, exist_ok=True)
        
        self.client = chromadb.PersistentClient(path=str(self.chroma_path))
        collection_name = getattr(settings, "CHROMA_COLLECTION", "nikola_documents_v2")
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"}
        )
        logger.info("Initialized VectorStore", chroma_path=str(self.chroma_path), collection=collection_name)


    def add_texts(
        self,
        ids: List[str],
        texts: List[str],
        metadatas: List[Dict[str, Any]],
        embeddings: Optional[List[List[float]]] = None
    ):
        """Add or update documents in vector store."""
        kwargs = {
            "ids": ids,
            "documents": texts,
            "metadatas": metadatas,
        }
        if embeddings is not None:
            kwargs["embeddings"] = embeddings
        self.collection.upsert(**kwargs)

    def query_similar(
        self,
        query_embedding: Optional[List[float]] = None,
        query_texts: Optional[List[str]] = None,
        n_results: int = 5,
        where: Optional[Dict[str, Any]] = None
    ):
        """Query similar documents."""
        kwargs = {"n_results": n_results}
        if query_embedding is not None:
            if isinstance(query_embedding[0], float):
                kwargs["query_embeddings"] = [query_embedding]
            else:
                kwargs["query_embeddings"] = query_embedding
        elif query_texts is not None:
            kwargs["query_texts"] = query_texts
        if where is not None:
            kwargs["where"] = where
        return self.collection.query(**kwargs)

    def delete(self, ids: Optional[List[str]] = None, where: Optional[Dict[str, Any]] = None):
        """Delete documents by ids or filter."""
        if ids:
            self.collection.delete(ids=ids)
        elif where:
            self.collection.delete(where=where)

    def get(self, where: Optional[Dict[str, Any]] = None, include: Optional[List[str]] = None):
        """Get documents by filter."""
        kwargs = {}
        if where is not None:
            kwargs["where"] = where
        if include is not None:
            kwargs["include"] = include
        return self.collection.get(**kwargs)

    def count(self) -> int:
        """Count total documents in collection."""
        return self.collection.count()
