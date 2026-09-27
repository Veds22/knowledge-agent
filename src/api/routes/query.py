from __future__ import annotations

import logging

import chromadb
from fastapi import APIRouter, Depends, HTTPException

from src.agent.runner import RunnerError, run_agent
from src.api.deps import dep_kb, dep_memory
from src.core.logger import append_audit
from src.core.schemas import AgentResponse, AuditEntry, QueryRequest

router = APIRouter()
log    = logging.getLogger("knowledge-agent.routes.query")


@router.post("/query", response_model=AgentResponse)
async def handle_query(
    req:               QueryRequest,
    kb_collection:     chromadb.Collection = Depends(dep_kb),
    memory_collection: chromadb.Collection = Depends(dep_memory),
):
    log.info("Query — session=%s query='%s…'", req.session_id, req.query[:80])

    try:
        response = await run_agent(req, kb_collection, memory_collection)
    except RunnerError as exc:
        log.error("Runner failed for session=%s: %s", req.session_id, exc)
        raise HTTPException(
            status_code=503,
            detail={"error": "agent_error", "message": str(exc)},
        )
    except Exception as exc:
        log.exception("Unexpected error in query route session=%s: %s", req.session_id, exc)
        raise HTTPException(
            status_code=500,
            detail={
                "error":   "internal_error",
                "message": "An unexpected error occurred. Please try again.",
            },
        )

    # Audit log — fail-open
    await append_audit(AuditEntry(
        session_id  = req.session_id,
        query       = req.query,
        action      = response.action_result.action,
        reasoning   = response.plan.reasoning,
        confidence  = response.confidence,
        answer      = response.answer,
        approved_by = (
            "pending" if response.action_result.status == "pending_approval" else None
        ),
        status      = response.action_result.status,
    ))

    log.info(
        "Query complete — session=%s action=%s status=%s steps=%d",
        req.session_id,
        response.action_result.action,
        response.action_result.status,
        response.total_steps,
    )
    return response