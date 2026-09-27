from __future__ import annotations
 
import asyncio
import logging
from datetime import datetime
from uuid import uuid4
 
import chromadb
 
from src.core.schemas import ActionName, MemoryEntry
from src.ingestion.embedder import EmbeddingError, embed_single
 
log = logging.getLogger("knowledge-agent.memory")
 
_TOP_K_MEMORY = 3


async def get_relevant_memory(
    query: str,
    memory_collection: chromadb.Collection,
) -> list[MemoryEntry]:
    """
        Retrieve the most relevant past Q&A turns for the current query.
        Returns an empty list on any failure — memory is best-effort and
        should never block the main agent flow.
    """
    if not query or not query.strip():
        log.debug("get_relevant_memory called with empty query — returning [].")
        return []
    
    try:
        embedding = await embed_single(query)
    except EmbeddingError as exc:
        log.warning("Could not embed query for memory retrieval — skipping memory: %s", exc)
        return []
 
    loop = asyncio.get_running_loop()
 
    def _query() -> dict:
        return memory_collection.query(
            query_embeddings=[embedding],
            n_results=_TOP_K_MEMORY,
            include=["documents", "metadatas", "distances"],
        )
        
    try:
        result = await loop.run_in_executor(None, _query)
    except Exception as exc:
        log.warning("Memory collection query failed — proceeding without memory context: %s", exc)
        return []
    
    entries: list[MemoryEntry] = []
 
    if not result.get("ids") or not result["ids"][0]:
        log.debug("No memory entries found for query: '%s…'", query[:60])
        return entries
 
    for meta in result["metadatas"][0]:
        try:
            entries.append(
                MemoryEntry(
                    turn_id      = meta["turn_id"],
                    query        = meta["query"],
                    answer       = meta["answer"],
                    action_taken = ActionName(meta["action_taken"]),
                    timestamp    = datetime.fromisoformat(meta["timestamp"]),
                )
            )
        except KeyError as exc:
            log.warning("Skipping memory entry with missing field '%s'.", exc)
        except ValueError as exc:
            log.warning("Skipping memory entry with invalid value: %s", exc)
        except Exception as exc:
            log.warning("Skipping malformed memory entry: %s", exc)
 
    log.debug("Retrieved %d memory entry/entries for context.", len(entries))
    return entries

async def store_turn(
    session_id:  str,
    query: str,
    answer: str,
    action: ActionName,
    memory_collection: chromadb.Collection,
) -> None:
    """
        Embed and store a completed Q&A turn in memory_collection.
        Failures are logged but not raised — memory write must not affect the response.
    """
    if not query or not query.strip():
        log.warning("store_turn called with empty query — skipping memory write.")
        return
    
    try:
        embedding = await embed_single(query)
    except EmbeddingError as exc:
        log.warning("Could not embed query for memory storage — skipping: %s", exc)
        return
 
    turn_id = f"{session_id}__{uuid4().hex[:6]}"
    meta    = {
        "turn_id":      turn_id,
        "session_id":   session_id,
        "query":        query[:500],         # cap to avoid oversized metadata
        "answer":       answer[:500],
        "action_taken": action.value,
        "timestamp":    datetime.utcnow().isoformat(),
    }
    
    loop = asyncio.get_running_loop()
 
    def _upsert() -> None:
        memory_collection.upsert(
            ids        = [turn_id],
            documents  = [query],
            embeddings = [embedding],
            metadatas  = [meta],
        )
 
    try:
        await loop.run_in_executor(None, _upsert)
        log.debug("Memory turn stored: turn_id=%s session=%s action=%s", turn_id, session_id, action.value)
    except Exception as exc:
        log.warning(
            "Failed to store memory turn '%s' for session '%s': %s — continuing without saving.",
            turn_id, session_id, exc,
        )