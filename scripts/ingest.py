"""
    One-time seed script — ingests all markdown files from data/kb/ into kb_collection.
    Run: uv run python scripts/ingest.py
"""

from __future__ import annotations

import asyncio
import logging 
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import chromadb

from src.core.config import get_settings
from src.core.logger import log 
from src.ingestion.embedder import embed_batch, load_embedder
from src.ingestion.chunker import chunk_file 

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")


async def ingest_all() -> None:
    """Ingest all markdown files from data/kb/ into kb_collection."""
    
    settings = get_settings()
    settings.ensure_dirs
    
    load_embedder()
    
    client = chromadb.PersistentClient(path=str(settings.chroma_path))
    kb = client.get_or_create_collection(
        name="kb_collection",
        metadata={"hnsw:space": "l2"}
    )
    
    md_files = sorted(settings.kb_path.glob('*.md'))
    
    if not md_files:
        log.warning("No .md files found in %s", settings.kb_path)
        return
    
    log.info("Found %d .md files in %s", len(md_files), settings.kb_path)
    total_chunks = 0
    
    for path in md_files:
        log.info("Processing: %s", path.name)
        chunks = await chunk_file(path)
        
        if not chunks:
            log.warning(f"{path.name}  -> No chunks produced, skipping ingestion.")
            continue
        texts = [c.text for c in chunks]
        embeddings = await embed_batch(texts)
        
        ids = [c.chunk_id for c in chunks]
        metas = [
            {
                "doc_id":            c.doc_id,
                "chunk_id":          c.chunk_id,
                "doc_title":         c.doc_title,
                "section":           c.section,
                "chunk_index":       c.chunk_index,
                "total_chunks":      len(chunks),
                "ingested_at":       __import__("datetime").datetime.utcnow().isoformat(),
                "ingested_by":       "system",
                "version":           1,
                "conflict_resolved": True,
                "resolved_from":     "",
            }
            for c in chunks
        ]
        
        kb.upsert(ids=ids, documents=texts, embeddings=embeddings, metadatas=metas)
        log.info(f" -> {len(chunks)} chunks ingested into kb_collection.")
        total_chunks += len(chunks)
        log.info(f"Ingestion complete. Total chunks in KB: {total_chunks}.")
        
        count  = kb.count()
        log.info("ChromaDB kb_collection count: %d", count)
        
if __name__ == "__main__":
    asyncio.run(ingest_all()) 