"""
CLI Reindexing Script for Nikola AI RAG.
Discovers, parses, smart-chunks, embeds, and indexes documents into ChromaDB & BM25.
Usage: python -m backend.reindex --all
"""
import sys
import argparse
import asyncio
from pathlib import Path
from backend.config import settings
from backend.filesystem_policy import FileOperation, authorize_path
from backend.logger import get_logger
from backend.rag import RAGPipeline

logger = get_logger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Nikola RAG Reindexer")
    parser.add_argument("--all", action="store_true", help="Reindex documents")
    parser.add_argument("--dir", type=str, default=None, help="Target directory to index")
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of files to index")
    args = parser.parse_args()

    print("[Nikola RAG] Initializing Reindexer...")
    rag = RAGPipeline(settings.CHROMA_PATH, settings.VAULT_PATH)
    
    target_dir = authorize_path(
        args.dir if args.dir else settings.VAULT_PATH,
        FileOperation.READ,
        explicit_read=bool(args.dir),
    )
    if not target_dir.exists():
        raise FileNotFoundError(f"Index directory does not exist: {target_dir}")

    supported_exts = {".txt", ".md", ".pdf", ".py", ".js", ".ts", ".json", ".csv", ".html", ".css"}
    all_files = []
    for candidate in target_dir.glob("**/*"):
        if not candidate.is_file() or candidate.suffix.lower() not in supported_exts:
            continue
        try:
            all_files.append(authorize_path(candidate, FileOperation.READ, explicit_read=True))
        except (PermissionError, OSError):
            continue
    if args.limit:
        files = all_files[:args.limit]
    else:
        files = all_files
    print(f"[Nikola RAG] Found {len(files)} document file(s) to process.")

    indexed_count = 0
    total_chunks = 0
    errors = 0

    for file_path in files:
        try:
            print(f"Indexing {file_path.name}...")
            res = asyncio.run(rag.index_file(str(file_path)))
            if res.get("success"):
                indexed_count += 1
                total_chunks += res.get("chunks_added", 0)
                print(f"  [OK] {file_path.name} ({res.get('chunks_added', 0)} chunks)")
            else:
                print(f"  [SKIP] {file_path.name}")
        except Exception as e:
            errors += 1
            print(f"  [ERROR] {file_path.name}: {e}")

    print("\n--- Reindex Summary ---")
    print(f"Files Indexed: {indexed_count}/{len(files)}")
    print(f"Total Chunks: {total_chunks}")
    print(f"Errors: {errors}")
    print("Reindexing complete!")


if __name__ == "__main__":
    main()
