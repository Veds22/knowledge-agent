from __future__ import annotations
 
import logging
import re
from dataclasses import dataclass
from pathlib import Path
 
import aiofiles
 
from src.core.config import get_settings
 
log = logging.getLogger("knowledge-agent.chunker")
 
 
class ChunkingError(Exception):
    """Raised when a file cannot be chunked."""
    
    
@dataclass
class Chunk:
    chunk_id:    str
    text:        str
    doc_id:      str
    doc_title:   str
    section:     str
    chunk_index: int
    
def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")

def _split_into_words_chunks(text: str, chunk_size: int, overlap: int) -> list[str]:
    """ 
        Split text into chunks of approximately chunk_size words, with overlap.
    """
    
    if overlap >= chunk_size:
        log.warning(
            "CHUNK_OVERLAP (%d) >= CHUNK_SIZE (%d) — resetting overlap to chunk_size // 4.",
            overlap, chunk_size,
        )
        overlap = chunk_size // 4
        
    words  = text.split()
    if not words:
        return []
    
    chunks = []
    start  = 0
    while start < len(words):
        end = start + chunk_size
        chunks.append(" ".join(words[start:end]))
        if end >= len(words):
            break
        start = end - overlap
    return chunks

async def chunk_file(path: Path) -> list[Chunk]:
    """
        Stream-read a markdown/text file and return a list of Chunks.
        - Preserves ## headings as section metadata.
        - Never loads the entire file into memory.
        - Skips empty sections silently.
    
        Raises ChunkingError for IO or encoding problems.
    """
    settings = get_settings()
    
    if not path.exists():
        log.error("File not found: %s", path)
        raise ChunkingError(
            f"The file '{path.name}' could not be found. "
            f"It may have been deleted before processing started."
        )

    if path.stat().st_size == 0:
        log.warning("File '%s' is empty — no chunks produced.", path.name)
        return []
    
    doc_id    = _slugify(path.stem)
    doc_title = path.stem.replace("-", " ").title()
    
    current_section = "General"
    buffer: list[str] = []
    section_blocks: list[tuple[str, str]] = []

    try:
        async with aiofiles.open(path, mode='r', encoding='utf-8') as f:
            async for line in f:
                line = line.rstrip()
                heading = re.match(r"^#{1,3}\s+(.+)", line)
                if heading:
                    if buffer:
                        section_blocks.append(
                            (current_section, " ".join(buffer).strip())
                        )
                        buffer = []
                    current_section = heading.group(1).strip() or "General"
                else:
                    stripped = line.strip()
                    if stripped:
                        buffer.append(stripped)
    except UnicodeDecodeError as exc:
        log.error("Encoding error reading '%s': %s", path.name, exc)
        raise ChunkingError(
            f"'{path.name}' contains characters that could not be read as UTF-8. "
            f"Please re-save the file with UTF-8 encoding."
        ) from exc
    except OSError as exc:
        log.error("IO error reading '%s': %s", path.name, exc)
        raise ChunkingError(
            f"Could not read '{path.name}' due to a filesystem error."
        ) from exc
        
    if buffer:
        section_blocks.append((current_section, " ".join(buffer).strip()))
 
    if not section_blocks:
        log.warning("No content blocks found in '%s'.", path.name)
        return []
    
    chunks: list[Chunk] = []
    chunk_index = 0
    
    for section, text in section_blocks:
        if not text.strip():
            continue
        word_chunks = _split_into_words_chunks(
            text,
            chunk_size=settings.chunk_size,
            overlap=settings.chunk_overlap,
        )
        for wc in word_chunks:
            if not wc.strip():
                continue
            chunks.append(
                Chunk(
                    chunk_id    = f"{doc_id}__{chunk_index}",
                    text        = wc,
                    doc_id      = doc_id,
                    doc_title   = doc_title,
                    section     = section,
                    chunk_index = chunk_index,
                )
            )
            chunk_index += 1
            
    log.info(
        "Chunked '%s' → %d chunk(s) across %d section(s).",
        path.name, len(chunks), len(section_blocks),
    )
    return chunks