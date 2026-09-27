from __future__ import annotations
 
import asyncio
import logging
 
import chromadb
 
from src.core.config import get_settings
from src.core.schemas import ConflictItem
from src.ingestion.chunker import Chunk
 
log = logging.getLogger("knowledge-agent.conflict")
 
 
class ConflictDetectionError(Exception):
    """Raised when conflict detection cannot be completed."""
 
async def _check_single_chunk(
    chunk: Chunk,
    embedding: list[float],
    kb_collection: chromadb.Collection,
    threshold: float,
) -> ConflictItem | None:
    """
        Query kb_collection with a single chunk embedding.
        Returns a ConflictItem if cosine similarity exceeds threshold, else None.
        Errors are logged and treated as no-conflict (fail-open) to avoid
        blocking an entire upload because of one bad vector query.
    """
    loop = asyncio.get_running_loop()
    
    def _query() -> dict:
        return kb_collection.query(
            query_embeddings=[embedding],
            n_results=1,
            include=["documents", "metadatas", "distances"],
        )
    
    try:
        result = await loop.run_in_executor(None, _query)
    except Exception as exc:
        log.error(
            "Conflict query failed for chunk '%s' — treating as no conflict. Error: %s",
            chunk.chunk_id, exc,
        )
        return None
    
    if not result["ids"] or not result["ids"][0]:
        log.debug("No existing chunks in KB — skipping conflict check for '%s'.", chunk.chunk_id)
        return None
    
    distance   = result["distances"][0][0]
    similarity = round(1.0 - (distance / 2.0), 4)
    
    if similarity < threshold:
        log.debug(
            "Chunk '%s': similarity=%.4f < threshold=%.2f — no conflict.",
            chunk.chunk_id, similarity, threshold,
        )
        return None
 
    existing_id = result["ids"][0][0]
    existing_text = result["documents"][0][0]
    meta = result["metadatas"][0][0] if result["metadatas"][0] else {} 
    conflict_summary = (
        f"New content from '{chunk.doc_title}' (section: '{chunk.section}') "
        f"conflicts with existing chunk '{existing_id}' "
        f"(doc: '{meta.get('doc_title', 'unknown')}', section: '{meta.get('section', 'unknown')}') "
        f"— similarity {similarity:.2%}."
    )
 
    log.warning(
        "Conflict detected: new='%s' ↔ existing='%s' (similarity=%.4f).",
        chunk.chunk_id, existing_id, similarity,
    )
    
    return ConflictItem(
        chunk_id           = chunk.chunk_id,
        new_text           = chunk.text,
        existing_chunk_id  = existing_id,
        existing_text      = existing_text,
        conflict_score     = similarity,
        conflict_summary   = conflict_summary,
    )
     
async def detect_conflicts(
    chunks: list[Chunk],
    embeddings: list[list[float]],
    kb_collection: chromadb.Collection,
) -> tuple[list[ConflictItem], list[int]]:
    """
        Run conflict detection for all chunks concurrently via asyncio.gather().
    
        Returns:
            conflicts      — ConflictItems for chunks that exceed the threshold
            clean_indices  — indices of conflict-free chunks (safe to ingest directly)
    
        Raises ConflictDetectionError only for unrecoverable setup failures.
        Individual chunk failures are fail-open (logged, treated as clean).
    """
    
    if len(chunks) != len(embeddings):
        msg = (
            f"Mismatch: {len(chunks)} chunks but {len(embeddings)} embeddings. "
            f"Cannot perform conflict detection."
        )
        log.error(msg)
        raise ConflictDetectionError(msg)
    
    if not chunks:
        log.debug("detect_conflicts called with empty chunk list.")
        return [], []
 
    settings = get_settings()
    log.info(
        "Starting parallel conflict scan for %d chunk(s) "
        "(threshold=%.2f) …", len(chunks), settings.conflict_threshold,
    )
    
    tasks = [
        _check_single_chunk(chunk, embedding, kb_collection, settings.conflict_threshold)
        for chunk, embedding in zip(chunks, embeddings)
    ]
 
    try:
        results: list[ConflictItem | None] = await asyncio.gather(*tasks)
    except Exception as exc:
        log.exception("Conflict detection gather failed unexpectedly: %s", exc)
        raise ConflictDetectionError(
            "Conflict detection could not be completed due to an unexpected error. "
            "The upload has been paused — please try again."
        ) from exc
        
    conflicts:     list[ConflictItem] = []
    clean_indices: list[int]          = []
 
    for idx, result in enumerate(results):
        if result is not None:
            conflicts.append(result)
        else:
            clean_indices.append(idx)
 
    log.info(
        "Conflict scan complete: %d conflict(s), %d clean chunk(s).",
        len(conflicts), len(clean_indices),
    )
    return conflicts, clean_indices