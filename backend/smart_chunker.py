"""
Smart Document Chanker for Nikola AI RAG.
Provides document-aware semantic chunking for:
- Python (AST-based: imports, classes, functions, methods, docstrings)
- Markdown (Heading-based hierarchy: h1, h2, h3, paragraphs)
- PDF (Page number, section, paragraph structure)
- JS/TS, JSON, CSV, HTML, CSS (Block & structure-aware chunking)
"""
import ast
import re
from pathlib import Path
from typing import List, Dict, Any


class SmartChunker:
    """Document-aware smart chunker producing structured chunks with rich metadata."""

    def __init__(self, max_chunk_size: int = 1500, chunk_overlap: int = 150):
        self.max_chunk_size = max_chunk_size
        self.chunk_overlap = chunk_overlap

    def chunk_file(self, file_path: str, text: str) -> List[Dict[str, Any]]:
        path = Path(file_path)
        suffix = path.suffix.lower()

        if suffix == ".py":
            chunks = self._chunk_python(path.name, text)
        elif suffix in [".md", ".markdown"]:
            chunks = self._chunk_markdown(path.name, text)
        elif suffix in [".js", ".ts", ".jsx", ".tsx"]:
            chunks = self._chunk_code_blocks(path.name, text, language=suffix[1:])
        elif suffix in [".json", ".csv", ".html", ".css", ".txt"]:
            chunks = self._chunk_structured_text(path.name, text, file_type=suffix[1:])
        else:
            chunks = self._chunk_generic(path.name, text)

        # Fall back if no chunks produced
        if not chunks:
            chunks = self._chunk_generic(path.name, text)

        return chunks

    def _chunk_python(self, filename: str, code: str) -> List[Dict[str, Any]]:
        """AST-based chunker for Python code."""
        chunks = []
        try:
            tree = ast.parse(code)
            lines = code.splitlines()

            # 1. Gather module docstring / top-level imports
            imports = []
            for node in tree.body:
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    start_line = getattr(node, 'lineno', 1) - 1
                    end_line = getattr(node, 'end_lineno', start_line + 1)
                    imports.append("\n".join(lines[start_line:end_line]))
            
            if imports:
                import_block = "\n".join(imports)
                chunks.append({
                    "text": import_block,
                    "section": "Imports",
                    "symbol": "imports",
                    "type": "python",
                    "filename": filename
                })

            # 2. Iterate through Classes and Functions
            for node in tree.body:
                if isinstance(node, ast.ClassDef):
                    class_name = node.name
                    start_line = node.lineno - 1
                    end_line = getattr(node, 'end_lineno', len(lines))
                    class_code = "\n".join(lines[start_line:end_line])

                    if len(class_code) <= self.max_chunk_size:
                        chunks.append({
                            "text": class_code,
                            "section": f"Class {class_name}",
                            "symbol": class_name,
                            "type": "python",
                            "filename": filename
                        })
                    else:
                        # Chunk individual methods
                        for item in node.body:
                            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                                m_start = item.lineno - 1
                                m_end = getattr(item, 'end_lineno', m_start + 1)
                                method_code = "\n".join(lines[m_start:m_end])
                                chunks.append({
                                    "text": method_code,
                                    "section": f"Class {class_name} -> {item.name}",
                                    "symbol": f"{class_name}.{item.name}",
                                    "type": "python",
                                    "filename": filename
                                })

                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    func_name = node.name
                    start_line = node.lineno - 1
                    end_line = getattr(node, 'end_lineno', len(lines))
                    func_code = "\n".join(lines[start_line:end_line])

                    chunks.append({
                        "text": func_code,
                        "section": f"Function {func_name}",
                        "symbol": func_name,
                        "type": "python",
                        "filename": filename
                    })
        except Exception:
            # Fallback to structural line splitting
            return self._chunk_generic(filename, code, file_type="python")

        return chunks if chunks else self._chunk_generic(filename, code, file_type="python")

    def _chunk_markdown(self, filename: str, text: str) -> List[Dict[str, Any]]:
        """Heading hierarchy chunker for Markdown."""
        chunks = []
        lines = text.splitlines()
        current_heading = "Overview"
        current_lines = []

        for line in lines:
            heading_match = re.match(r'^(#{1,6})\s+(.+)$', line)
            if heading_match:
                if current_lines:
                    chunk_text = "\n".join(current_lines).strip()
                    if chunk_text:
                        chunks.append({
                            "text": chunk_text,
                            "section": current_heading,
                            "symbol": current_heading,
                            "type": "markdown",
                            "filename": filename
                        })
                current_heading = heading_match.group(2).strip()
                current_lines = [line]
            else:
                current_lines.append(line)

        if current_lines:
            chunk_text = "\n".join(current_lines).strip()
            if chunk_text:
                chunks.append({
                    "text": chunk_text,
                    "section": current_heading,
                    "symbol": current_heading,
                    "type": "markdown",
                    "filename": filename
                })

        return chunks

    def _chunk_code_blocks(self, filename: str, text: str, language: str) -> List[Dict[str, Any]]:
        """Chunk JavaScript/TypeScript/Code by functions/classes or regex blocks."""
        chunks = []
        pattern = r'((?:export\s+)?(?:async\s+)?(?:function|class|const|let|var)\s+([A-Za-z0-9_$]+)[^{]*\{)'
        matches = list(re.finditer(pattern, text))
        
        if not matches:
            return self._chunk_generic(filename, text, file_type=language)

        lines = text.splitlines()
        for i, match in enumerate(matches):
            symbol = match.group(2)
            start_char = match.start()
            end_char = matches[i+1].start() if i+1 < len(matches) else len(text)
            block_text = text[start_char:end_char].strip()
            
            if block_text:
                chunks.append({
                    "text": block_text[:self.max_chunk_size],
                    "section": f"{language.upper()} Symbol: {symbol}",
                    "symbol": symbol,
                    "type": language,
                    "filename": filename
                })
        return chunks if chunks else self._chunk_generic(filename, text, file_type=language)

    def _chunk_structured_text(self, filename: str, text: str, file_type: str) -> List[Dict[str, Any]]:
        """Chunk structured text formats (JSON, CSV, HTML, CSS, TXT)."""
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        chunks = []
        current_chunk = []
        current_len = 0

        for p in paragraphs:
            if current_len + len(p) > self.max_chunk_size and current_chunk:
                chunks.append({
                    "text": "\n\n".join(current_chunk),
                    "section": f"Section {len(chunks)+1}",
                    "symbol": f"chunk_{len(chunks)+1}",
                    "type": file_type,
                    "filename": filename
                })
                current_chunk = [p]
                current_len = len(p)
            else:
                current_chunk.append(p)
                current_len += len(p)

        if current_chunk:
            chunks.append({
                "text": "\n\n".join(current_chunk),
                "section": f"Section {len(chunks)+1}",
                "symbol": f"chunk_{len(chunks)+1}",
                "type": file_type,
                "filename": filename
            })

        return chunks

    def _chunk_generic(self, filename: str, text: str, file_type: str = "txt") -> List[Dict[str, Any]]:
        """Generic sliding window chunker."""
        chunks = []
        start = 0
        step = max(100, self.max_chunk_size - self.chunk_overlap)
        
        while start < len(text):
            end = min(start + self.max_chunk_size, len(text))
            chunk_str = text[start:end].strip()
            if chunk_str:
                chunk_id = len(chunks) + 1
                chunks.append({
                    "text": chunk_str,
                    "section": f"Block {chunk_id}",
                    "symbol": f"block_{chunk_id}",
                    "type": file_type,
                    "filename": filename
                })
            start += step
        return chunks
