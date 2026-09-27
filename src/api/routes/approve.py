"""
POST /approve  — resume a graph interrupted at hitl_approval.
Kept as a separate route file to avoid cluttering resolve.py.
"""
from __future__ import annotations

import logging

import chromadb
from fastapi import APIRouter, Depends, HTTPException

from src.agent.runner import RunnerError, resume_agent
from src.api.deps import dep_memory
from src.core.logger import append_audit
from src.core.schemas import ApprovalRequest, AuditEntry

router = APIRouter()
log    = logging.getLogger("knowledge-agent.routes.approve")


@router.post("/approve")
async def approve_escalation(
    req:               ApprovalRequest,
    memory_collection: chromadb.Collection = Depends(dep_memory),
):
    """
    Resume a graph paused at the hitl_approval interrupt.
    session_id in ApprovalRequest.action_id is the thread_id used to
    locate the checkpoint.
    """
    if not req.action_id or not req.action_id.strip():
        raise HTTPException(
            status_code=422,
            detail={"error": "missing_session_id", "message": "action_id (session_id) is required."},
        )

    log.info("Approval received — session=%s approved=%s", req.action_id, req.approved)

    try:
        response = await resume_agent(
            session_id        = req.action_id,   # action_id carries the session_id
            approved          = req.approved,
            approved_by       = "user",
            memory_collection = memory_collection,
        )
    except RunnerError as exc:
        log.error("Resume failed session=%s: %s", req.action_id, exc)
        raise HTTPException(
            status_code=503,
            detail={"error": "resume_failed", "message": str(exc)},
        )
    except Exception as exc:
        log.exception("Unexpected error on /approve session=%s: %s", req.action_id, exc)
        raise HTTPException(
            status_code=500,
            detail={"error": "internal_error", "message": "An unexpected error occurred."},
        )

    await append_audit(AuditEntry(
        session_id  = req.action_id,
        query       = f"HITL approval: approved={req.approved}",
        action      = response.action_result.action,
        reasoning   = "User decision via POST /approve.",
        confidence  = response.confidence,
        answer      = response.answer,
        approved_by = "user",
        status      = response.action_result.status,
    ))

    return response