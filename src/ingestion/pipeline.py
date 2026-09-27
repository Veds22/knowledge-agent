from __future__ import annotations
 
import logging
from datetime import datetime
from pathlib import Path
 
import chromadb
 
from src.core.job_store import JobStore
from src.core.schemas import JobStatus
from src.ingestion.chunker import ChunkingError, Chunk, chunk_file
from src.ingestion.conflict import ConflictDetectionError, detect_conflicts
from src.ingestion.embedder import EmbeddingError, embed_batch
 
log = logging.getLogger("knowledge-agent.pipeline")
 
def _build_kb_metadata(chunk: Chunk, upload_id: str) -> dict:
    return {
        "doc_id": chunk.doc_id,
        "chunk_id": chunk.chunk_id,
        "doc_title": chunk.doc_title,
        "section": chunk.section,
        "chunk_index": chunk.chunk_index,
        "ingested_at": datetime.utcnow().isoformat(),
        "ingested_by":  f"user:{upload_id}",
        "version": 1,
        "conflict_resolved": True,
        "resolved_from": "",
    }
    
def _build_pending_metadata(chunk: Chunk, upload_id: str, conflict_chunk_id: str, score: float, summary: str) -> dict:
    return {
        "upload_id": upload_id,
        "doc_id": chunk.doc_id,
        "chunk_id": chunk.chunk_id,
        "doc_title": chunk.doc_title,
        "section": chunk.section,
        "chunk_index": chunk.chunk_index,
        "uploaded_at": datetime.utcnow().isoformat(),
        "has_conflict": True,
        "conflict_with": conflict_chunk_id,
        "conflict_score": score,
        "conflict_summary": summary,
        "resolution": "",
        "resolved_at": "",
    }
 
async def run_ingestion_pipeline(
    file_path: Path,
    job_id: str,
    job_store: JobStore,
    kb_collection: chromadb.Collection,
    pending_collection: chromadb.Collection,
) -> None:
    """
        Full async ingestion pipeline: chunk → embed → conflict scan → store.
        Updates JobStore at every stage for SSE progress streaming.
    
        All exceptions are caught here — the pipeline never propagates to the
        FastAPI BackgroundTask caller, which has no way to surface errors to the user.
        Instead, errors are written to JobStore so the SSE stream can report them.
    """
    
    job = await job_store.get(job_id)
    if job is None:
        log.error("Pipeline started for unknown job_id '%s' — aborting.", job_id)
        return
 
    upload_id = job.upload_id
    log.info("[%s] Pipeline started for file '%s'.", job_id, file_path.name)
    
    
    # Chunking
    try:
        await job_store.set_status(job_id, JobStatus.chunking, progress=5)
        chunks = await chunk_file(file_path)
    except ChunkingError as exc:
        log.error("[%s] Chunking failed: %s", job_id, exc)
        await job_store.set_error(
            job_id,
            f"We could not read '{file_path.name}': {exc} "
            f"Please check the file and try again."
        )
        return
    except Exception as exc:
        log.exception("[%s] Unexpected error during chunking: %s", job_id, exc)
        await job_store.set_error(
            job_id,
            "An unexpected error occurred while reading the file. Please try again."
        )
        return
    
    if not chunks:
        log.warning("[%s] File '%s' produced no chunks.", job_id, file_path.name)
        await job_store.set_error(
            job_id,
            f"'{file_path.name}' appears to be empty or contains no readable text. "
            f"Please add content and re-upload."
        )
        return
 
    await job_store.update(job_id, total_chunks=len(chunks), done_chunks=0)
    log.info("[%s] Chunking complete: %d chunk(s).", job_id, len(chunks))
    
    # Embedding
    try:
        await job_store.set_status(job_id, JobStatus.embedding, progress=20)
        log.info("[%s] Embedding %d chunk(s) …", job_id, len(chunks))
        embeddings = await embed_batch([c.text for c in chunks])
    except EmbeddingError as exc:
        log.error("[%s] Embedding failed: %s", job_id, exc)
        await job_store.set_error(
            job_id,
            f"Could not generate embeddings for '{file_path.name}': {exc} "
            f"The embedding model may be temporarily unavailable."
        )
        return
    except Exception as exc:
        log.exception("[%s] Unexpected error during embedding: %s", job_id, exc)
        await job_store.set_error(
            job_id,
            "An unexpected error occurred during embedding. Please try again."
        )
        return
    
    # Conflict Detection
    try:
        await job_store.set_status(job_id, JobStatus.scanning, progress=45)
        log.info("[%s] Running parallel conflict scan …", job_id)
        conflicts, clean_indices = await detect_conflicts(chunks, embeddings, kb_collection)
    except ConflictDetectionError as exc:
        log.error("[%s] Conflict detection failed: %s", job_id, exc)
        await job_store.set_error(job_id, str(exc))
        return
    except Exception as exc:
        log.exception("[%s] Unexpected error during conflict detection: %s", job_id, exc)
        await job_store.set_error(
            job_id,
            "An unexpected error occurred during conflict detection. Please try again."
        )
        return
    
    # Ingest clean chunks directly into KB
    await job_store.set_status(job_id, JobStatus.ingesting, progress=65)
 
    if clean_indices:
        try:
            clean_ids   = [chunks[i].chunk_id for i in clean_indices]
            clean_texts = [chunks[i].text      for i in clean_indices]
            clean_embs  = [embeddings[i]        for i in clean_indices]
            clean_metas = [_build_kb_metadata(chunks[i], upload_id) for i in clean_indices]
 
            kb_collection.upsert(
                ids=clean_ids,
                documents=clean_texts,
                embeddings=clean_embs,
                metadatas=clean_metas,
            )
            log.info("[%s] Ingested %d clean chunk(s) into KB.", job_id, len(clean_indices))
        except Exception as exc:
            log.exception("[%s] Failed to upsert clean chunks into KB: %s", job_id, exc)
            await job_store.set_error(
                job_id,
                "Clean chunks were processed but could not be saved to the knowledge base. "
                "Please try the upload again."
            )
            return
        
    # Store Conflicted chunks in Pending collection for HITL resolution
    if conflicts:
        conflict_map = {c.chunk_id: c for c in conflicts}
        try:
            pend_ids, pend_texts, pend_embs, pend_metas = [], [], [], []
            for chunk, emb in zip(chunks, embeddings):
                if chunk.chunk_id not in conflict_map:
                    continue
                ci = conflict_map[chunk.chunk_id]
                pending_id = f"{upload_id}__{chunk.chunk_id}"
                pend_ids.append(pending_id)
                pend_texts.append(chunk.text)
                pend_embs.append(emb)
                pend_metas.append(
                    _build_pending_metadata(
                        chunk, upload_id,
                        ci.existing_chunk_id,
                        ci.conflict_score,
                        ci.conflict_summary,
                    )
                )
            pending_collection.upsert(
                ids=pend_ids,
                documents=pend_texts,
                embeddings=pend_embs,
                metadatas=pend_metas,
            )
            await job_store.add_conflicts(job_id, conflicts)
            log.info(
                "[%s] %d conflicted chunk(s) stored in pending — awaiting user resolution.",
                job_id, len(conflicts),
            )
        except Exception as exc:
            log.exception("[%s] Failed to store conflicted chunks in pending: %s", job_id, exc)
            await job_store.set_error(
                job_id,
                f"{len(conflicts)} chunk(s) had conflicts but could not be staged for review. "
                f"Please try the upload again."
            )
            return
        
    # Finalise
    final_status = JobStatus.conflicted if conflicts else JobStatus.completed
    await job_store.update(
        job_id,
        status      = final_status,
        progress    = 100,
        done_chunks = len(chunks),
    )
    log.info(
        "[%s] Pipeline complete — status=%s, clean=%d, conflicts=%d.",
        job_id, final_status, len(clean_indices), len(conflicts),
    )