"""
RAG Pipeline for NIKOLA backend.
Handles smart document-aware chunking, file hashing, Qwen3 embeddings,
ChromaDB vector store, BM25 keyword search, and local reranking.
"""

import asyncio
import hashlib
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
import threading

import fitz  # PyMuPDF
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from concurrent.futures import ThreadPoolExecutor

from backend.config import settings
from backend.filesystem_policy import FileOperation, authorize_path, local_vault_path
from backend.logger import get_logger
from backend.vector_store import VectorStore
from backend.smart_chunker import SmartChunker
from backend.bm25_retriever import BM25Retriever
from backend.reranker import LocalReranker

logger = get_logger(__name__)

executor = ThreadPoolExecutor(max_workers=2)


class RAGPipeline:
    """Class-based Hybrid RAG pipeline with ChromaDB, BM25, and local reranker."""

    def __init__(self, chroma_path: str, vault_path: str):
        self.vault_path = local_vault_path(vault_path)
        self.chroma_path = Path(chroma_path).expanduser().resolve()
        
        self.vault_path.mkdir(parents=True, exist_ok=True)
        self.chroma_path.mkdir(parents=True, exist_ok=True)
        
        self.store = VectorStore(str(self.chroma_path))
        self.collection = self.store.collection
        self.client = self.store.client
        
        self.chunker = SmartChunker(max_chunk_size=1500, chunk_overlap=150)
        self.bm25 = BM25Retriever()
        self.reranker = LocalReranker()
        
        self.watchdog_paused = False
        self.in_progress_deletes = set()
        self._files_cache = None
        self._cache_ts = 0
        self._observer: Optional[Observer] = None
        self._file_hashes: Dict[str, str] = {}
        
        # Build initial BM25 index from existing ChromaDB store
        self._rebuild_bm25_index()
        
        logger.info("Hybrid RAG pipeline initialized", vault_path=str(self.vault_path))

    def _compute_file_hash(self, path: Path) -> str:
        """Compute MD5 hash + mtime of file to prevent reprocessing unchanged files."""
        try:
            mtime = str(path.stat().st_mtime)
            hasher = hashlib.md5()
            with open(path, "rb") as f:
                hasher.update(f.read(65536))
            return f"{hasher.hexdigest()}_{mtime}"
        except Exception:
            return ""

    def _rebuild_bm25_index(self):
        """Rebuild in-memory BM25 index from ChromaDB documents."""
        try:
            res = self.store.get()
            docs = []
            if res and "documents" in res and res["documents"]:
                documents = res["documents"]
                metadatas = res.get("metadatas", [])
                for i, doc_text in enumerate(documents):
                    meta = metadatas[i] if i < len(metadatas) else {}
                    docs.append({
                        "text": doc_text,
                        "filename": meta.get("filename", ""),
                        "symbol": meta.get("symbol", ""),
                        "section": meta.get("section", ""),
                        "chunk_id": meta.get("chunk_id", i),
                        "type": meta.get("file_type", "")
                    })
            self.bm25.fit(docs)
            logger.debug("Rebuilt BM25 index", doc_count=len(docs))
        except Exception as e:
            logger.error("Failed to rebuild BM25 index", error=str(e))

    async def index_file(self, file_path: str) -> dict:
        """Index a single file and add chunks to RAG."""
        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(executor, self._index_file_sync, file_path)
        except Exception as e:
            logger.error("Failed to index file", file_path=file_path, error=str(e))
            raise

    def _index_file_sync(self, file_path: str) -> dict:
        path = authorize_path(file_path, FileOperation.READ, explicit_read=True, allow_missing=False)
        
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        
        filename = path.name
        file_hash = self._compute_file_hash(path)

        # Check if file is unchanged
        if filename in self._file_hashes and self._file_hashes[filename] == file_hash:
            logger.debug("Skipping unchanged file indexing", filename=filename)
            return {"success": True, "chunks_added": 0, "filename": filename, "skipped": True}

        # Delete obsolete chunks before adding new ones
        self._remove_chunks_by_filename(filename)

        # Extract text based on file type
        if path.suffix.lower() == ".pdf":
            text = self._extract_pdf_text(path)
        else:
            text = self._extract_text_file(path)
        
        if not text or text.strip() == "":
            logger.warning("File extraction returned empty text", path=str(path))
            return {"success": False, "chunks_added": 0, "filename": filename}
        
        # Smart Chunking
        structured_chunks = self.chunker.chunk_file(str(path), text)
        file_size = path.stat().st_size
        timestamp = datetime.utcnow().isoformat()
        
        from backend.llm_engine import get_llm
        llm = get_llm()
        
        embeddings = []
        ids = []
        metadatas = []
        texts = []
        
        for i, chunk in enumerate(structured_chunks):
            chunk_text = chunk["text"]
            try:
                response = llm.create_embedding(chunk_text)
                embedding = response["data"][0]["embedding"]
                embeddings.append(embedding)
                
                chunk_id = f"{filename}_{i}"
                ids.append(chunk_id)
                texts.append(chunk_text)
                
                metadata = {
                    "filename": filename,
                    "section": chunk.get("section", f"Chunk {i}"),
                    "symbol": chunk.get("symbol", ""),
                    "type": chunk.get("type", path.suffix),
                    "chunk_id": i,
                    "total_chunks": len(structured_chunks),
                    "timestamp": timestamp,
                    "file_size_bytes": file_size,
                    "file_hash": file_hash
                }
                metadatas.append(metadata)
            except Exception as e:
                logger.error("Failed to embed chunk", chunk_index=i, error=str(e))
                continue
        
        if embeddings:
            self.store.add_texts(
                ids=ids,
                texts=texts,
                metadatas=metadatas,
                embeddings=embeddings
            )
            self._file_hashes[filename] = file_hash
            self._rebuild_bm25_index()
            logger.info("Indexed file with SmartChunker", filename=filename, chunks_added=len(embeddings))
        
        return {
            "success": True,
            "chunks_added": len(embeddings),
            "filename": filename
        }

    def _extract_pdf_text(self, path: Path) -> str:
        text = []
        try:
            doc = fitz.open(path)
            for page_num in range(len(doc)):
                page = doc[page_num]
                page_str = page.get_text()
                if page_str.strip():
                    text.append(f"--- Page {page_num + 1} ---\n{page_str}")
            doc.close()
        except Exception as e:
            logger.error("Failed to extract PDF text", path=str(path), error=str(e))
            raise
        return "\n".join(text)

    def _extract_text_file(self, path: Path) -> str:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except UnicodeDecodeError:
            with open(path, "r", encoding="latin-1") as f:
                return f.read()

    def _remove_chunks_by_filename(self, filename: str):
        try:
            results = self.store.get(where={"filename": filename})
            ids = results["ids"] if results and "ids" in results else []
            if ids:
                self.store.delete(ids=ids)
        except Exception:
            pass

    async def query(self, query_text: str, top_k: int = 5) -> tuple[list[str], list[str]]:
        """Query RAG with Hybrid (Vector + BM25) search and Reranking."""
        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(executor, self._query_sync, query_text, top_k)
        except Exception as e:
            logger.error("Query failed", query=query_text, error=str(e))
            return [], []

    def _query_sync(self, query_text: str, top_k: int) -> tuple[list[str], list[str]]:
        candidate_count = getattr(settings, "RAG_CANDIDATE_COUNT", 25)
        candidates = []

        # 1. Vector Search
        from backend.llm_engine import get_llm
        llm = get_llm()
        try:
            res = llm.create_embedding(query_text)
            query_embedding = res["data"][0]["embedding"]
            results = self.store.query_similar(query_embedding=query_embedding, n_results=candidate_count)
            
            docs = results["documents"][0] if results and "documents" in results and results["documents"] else []
            metas = results["metadatas"][0] if results and "metadatas" in results and results["metadatas"] else []
            distances = results.get("distances", [[]])[0] if results else []
            
            for i, doc in enumerate(docs):
                meta = metas[i] if i < len(metas) else {}
                distance = distances[i] if i < len(distances) else 1.0
                candidates.append({
                    "text": doc,
                    "filename": meta.get("filename", ""),
                    "section": meta.get("section", ""),
                    "symbol": meta.get("symbol", ""),
                    "vector_score": max(0.0, 1.0 - float(distance)),
                    "bm25_score": 0.0
                })
        except Exception as e:
            logger.error("Vector search failed in hybrid query", error=str(e))

        # 2. BM25 Search
        try:
            bm25_results = self.bm25.search(query_text, top_k=candidate_count)
            candidates.extend(bm25_results)
        except Exception as e:
            logger.error("BM25 search failed in hybrid query", error=str(e))

        # 3. Reranking candidate pool -> top 3-5
        final_k = getattr(settings, "RAG_FINAL_CHUNKS", top_k)
        reranked_chunks = self.reranker.rerank(query_text, candidates, top_k=final_k)
        min_score = getattr(settings, "RAG_MIN_SCORE", 0.25)
        reranked_chunks = [
            chunk for chunk in reranked_chunks
            if chunk.get("rerank_score", 0.0) >= min_score
        ]
        logger.debug(
            "RAG retrieval completed",
            query=query_text[:80],
            candidate_count=len(candidates),
            returned_count=len(reranked_chunks),
            scores=[chunk.get("rerank_score", 0.0) for chunk in reranked_chunks],
        )

        # Format source citations
        formatted_chunks = []
        filenames = []
        for c in reranked_chunks:
            fn = c.get("filename", "document")
            filenames.append(fn)
            sec = c.get("section", "")
            sym = c.get("symbol", "")
            
            header = f"[Source: {fn}"
            if sym:
                header += f" | Symbol: {sym}"
            elif sec:
                header += f" | Section: {sec}"
            header += "]"

            formatted_chunks.append(f"{header}\n{c.get('text', '')}")

        return formatted_chunks, list(set(filenames))

    async def remove_file(self, filename: str) -> int:
        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(executor, self._remove_file_sync, filename)
        except Exception as e:
            logger.error("Failed to remove file", filename=filename, error=str(e))
            raise

    def _remove_file_sync(self, filename: str) -> int:
        self.in_progress_deletes.add(filename)
        try:
            results = self.store.get(where={"filename": filename})
            ids = results["ids"] if results and "ids" in results else []
            
            if ids:
                self.store.delete(ids=ids)
                logger.info("Removed file from RAG", filename=filename, chunks_deleted=len(ids))
            
            if filename in self._file_hashes:
                del self._file_hashes[filename]

            vault_file = authorize_path(
                self.vault_path / filename,
                FileOperation.DELETE,
                allow_missing=True,
            )
            if vault_file.exists():
                vault_file.unlink()
                logger.info("Deleted vault file", path=str(vault_file))
            
            self._rebuild_bm25_index()
            return len(ids)
        finally:
            self.in_progress_deletes.discard(filename)

    async def clear_all(self) -> tuple[int, int]:
        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(executor, self._clear_all_sync)
        except Exception as e:
            logger.error("Failed to clear all", error=str(e))
            raise

    def _clear_all_sync(self) -> tuple[int, int]:
        self.watchdog_paused = True
        try:
            results = self.store.get()
            total_chunks = len(results["ids"]) if results and "ids" in results and results["ids"] else 0
            
            if results and "ids" in results and results["ids"]:
                self.store.delete(ids=results["ids"])
            
            files_removed = 0
            for file in self.vault_path.glob("*"):
                if file.is_file():
                    authorize_path(file, FileOperation.DELETE, allow_missing=False).unlink()
                    files_removed += 1
            
            self.in_progress_deletes.clear()
            self._files_cache = None
            self._file_hashes.clear()
            self.bm25.fit([])
            
            logger.info("Cleared all RAG data", chunks_deleted=total_chunks, files_removed=files_removed)
            return total_chunks, files_removed
        finally:
            self.watchdog_paused = False

    def get_files(self) -> list[dict]:
        now = time.time()
        if self._files_cache and (now - self._cache_ts) < 5:
            return self._files_cache
        
        try:
            results = self.store.get()
            metadatas = results["metadatas"] if results and "metadatas" in results and results["metadatas"] else []
            
            files_dict = {}
            for metadata in metadatas:
                filename = metadata.get("filename")
                if filename:
                    if filename not in files_dict:
                        files_dict[filename] = {
                            "filename": filename,
                            "chunks": 0,
                            "indexed_at": metadata.get("timestamp", ""),
                            "size_bytes": metadata.get("file_size_bytes", 0),
                            "file_exists": False,
                        }
                    files_dict[filename]["chunks"] += 1
            
            files_list = []
            for file_info in files_dict.values():
                vault_file = authorize_path(
                    self.vault_path / file_info["filename"],
                    FileOperation.READ,
                    allow_missing=True,
                )
                file_info["file_exists"] = vault_file.exists()
                files_list.append(file_info)
            
            self._files_cache = files_list
            self._cache_ts = now
            return files_list
        except Exception as e:
            logger.error("Failed to get files", error=str(e))
            return []

    def start_watchdog(self):
        class IndexHandler(FileSystemEventHandler):
            def __init__(self, rag_pipeline):
                self.rag = rag_pipeline
                self.loop = asyncio.new_event_loop()
                threading.Thread(target=self._run_loop, daemon=True).start()
            
            def _run_loop(self):
                asyncio.set_event_loop(self.loop)
                self.loop.run_forever()
            
            def on_created(self, event):
                if self.rag.watchdog_paused:
                    return
                path = Path(event.src_path)
                if path.suffix.lower() in {".pdf", ".txt", ".md", ".py", ".js", ".ts", ".json", ".html", ".css", ".csv"}:
                    logger.info("Watchdog detected file", path=str(path))
                    asyncio.run_coroutine_threadsafe(
                        self.rag.index_file(str(path)),
                        self.loop
                    )
            
            def on_deleted(self, event):
                if self.rag.watchdog_paused:
                    return
                path = Path(event.src_path)
                filename = path.name
                if filename not in self.rag.in_progress_deletes:
                    logger.info("Watchdog detected deleted file", filename=filename)
                    asyncio.run_coroutine_threadsafe(
                        self.rag.remove_file(filename),
                        self.loop
                    )
        
        handler = IndexHandler(self)
        self._observer = Observer()
        self._observer.schedule(handler, str(self.vault_path), recursive=True)
        self._observer.start()
        logger.info("Watchdog started", vault_path=str(self.vault_path))

    def stop_watchdog(self):
        if self._observer:
            self._observer.stop()
            self._observer.join()
            logger.info("Watchdog stopped")
