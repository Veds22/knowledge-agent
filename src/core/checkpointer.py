"""
    SQLite-backed LangGraph checkpointer for:
    1. HITL pause-and-resume (escalation approval gate)
    2. Long context management via state trimming before each node    
"""

from __future__ import annotations

import logging

import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from src.core.config import get_settings

log = logging.getLogger("knowledge-agent.checkpointer")
 
_connection: aiosqlite.Connection | None = None
_checkpointer: AsyncSqliteSaver | None = None

async def init_checkpointer() -> AsyncSqliteSaver:
    """
        Initialise the SQLite checkpointer. Called once in FastAPI lifespan.
        DB file lives in the configured checkpoint directory.
    """
    global _checkpointer, _connection
    settings = get_settings()
    db_path = settings.checkpoint_dir / "checkpoints.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        _connection = await aiosqlite.connect(str(db_path))
        _checkpointer = AsyncSqliteSaver(conn=_connection)
        log.info("Checkpointer initialised at '%s'.", db_path)
        return _checkpointer
    except Exception as exc:
        log.critical("Failed to initialise checkpointer at '%s': %s", db_path, exc)
        raise RuntimeError(
            f"Checkpointer could not be initialised. "
            f"Ensure the directory '{db_path.parent}' is writable."
        ) from exc
        

async def close_checkpointer() -> None:
    global _checkpointer, _connection

    if _connection is not None:
        await _connection.close()
    _connection = None
    _checkpointer = None


def get_checkpointer() -> AsyncSqliteSaver:
    if _checkpointer is None:
        raise RuntimeError(
            "Checkpointer not initialised. "
            "Call init_checkpointer() during application startup."
        )
    return _checkpointer

 
_MAX_STEP_RESULTS_CHARS = 8_000   
_MAX_ERRORS_KEPT = 5       
 
def trim_state_context(state: dict) -> dict:
    """
        Trim long-running context fields before they bloat the LLM prompt.
        Called at the start of each node that sends state to the LLM.
    
        Trims:
        - step_results: cap total chars, keep most recent results
        - errors: keep last N only
        - chunks: keep top-3 by score (rest already summarised in step_results)
    """
    
    trimmed = dict(state)
    # Trim Results
    results = list(trimmed.get("step_results", []))
    if results:
        total = sum(len(r) for r in results)
        while total > _MAX_STEP_RESULTS_CHARS and len(results) > 1:
            removed = results.pop(0)
            total  -= len(removed)
            log.debug("Context trim: dropped oldest step_result (%d chars).", len(removed))
        trimmed["step_results"] = results
    # Trim Errors
    errors = list(trimmed.get("errors", []))
    if len(errors) > _MAX_ERRORS_KEPT:
        dropped = len(errors) - _MAX_ERRORS_KEPT
        trimmed["errors"] = errors[-_MAX_ERRORS_KEPT:]
        log.debug("Context trim: dropped %d old error(s).", dropped)
 
    # Trim Chunks
    chunks = list(trimmed.get("chunks", []))
    if len(chunks) > 3:
        trimmed["chunks"] = sorted(chunks, key=lambda c: c.score, reverse=True)[:3]
        log.debug("Context trim: kept top 3 KB chunks from %d.", len(chunks))
 
    return trimmed
