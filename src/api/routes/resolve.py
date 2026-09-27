from __future__ import annotations

import asyncio
import logging
from datetime import datetime

import chromadb
from fastapi import APIRouter, Depends, HTTPException

from src.agent.dispatcher import approve_action
from src.api.deps import dep_kb, dep_pending, dep_jobs
from src.core.logger import append_audit
from src.core.schemas import (
    ActionName, ActionResult, ApprovalRequest,
    AuditEntry, Resolution, ResolveRequest,
)
from src.core.job_store import JobStore
from src.ingestion.embedder import EmbeddingError, embed_single

router = APIRouter()
log    = logging.getLogger("knowledge-agent.routes.resolve")


@router.post("/resolve")
async def resolve_conflicts(
    req:                ResolveRequest,
    kb_collection:      chromadb.Collection = Depends(dep_kb),
    pending_collection: chromadb.Collection = Depends(dep_pending),
    job_store:          JobStore            = Depends(dep_jobs),
):
    """
    Process user resolutions for conflicted upload chunks.
    Processes each resolution independently — one failure does not block others.
    """
    if not req.resolutions:
        raise HTTPException(
            status_code=422,
            detail={
                "error":   "empty_resolutions",
                "message": "No resolutions were provided. Please resolve at least one conflict.",
            },
        )

    loop            = asyncio.get_running_loop()
    resolved_count  = 0
    discarded_count = 0
    failed_count    = 0
    failed_ids: list[str] = []

    for item in req.resolutions:
        pending_id = f"{req.upload_id}__{item.chunk_id}"

        # ── Fetch from pending collection ─────────────────────────────────────
        try:
            def _get(pid=pending_id):
                return pending_collection.get(
                    ids=[pid],
                    include=["documents", "metadatas", "embeddings"],
                )
            result = await loop.run_in_executor(None, _get)
        except Exception as exc:
            log.error("Failed to fetch pending chunk '%s': %s", pending_id, exc)
            failed_count += 1
            failed_ids.append(item.chunk_id)
            continue

        if not result["ids"]:
            log.warning(
                "Pending chunk '%s' not found — it may have already been resolved or expired.",
                pending_id,
            )
            failed_count += 1
            failed_ids.append(item.chunk_id)
            continue

        text              = result["documents"][0]
        meta              = result["metadatas"][0]
        existing_embedding = result["embeddings"][0] if result.get("embeddings") else None

        # ── keep_existing: discard the new chunk ──────────────────────────────
        if item.resolution == Resolution.keep_existing:
            try:
                def _del(pid=pending_id):
                    pending_collection.delete(ids=[pid])
                await loop.run_in_executor(None, _del)
                discarded_count += 1
                log.info("Chunk '%s' discarded — keeping existing KB content.", item.chunk_id)
            except Exception as exc:
                log.error("Failed to delete pending chunk '%s': %s", pending_id, exc)
                failed_count += 1
                failed_ids.append(item.chunk_id)
            continue

        # ── merge: validate merged_text is provided ───────────────────────────
        if item.resolution == Resolution.merge:
            if not item.merged_text or not item.merged_text.strip():
                log.warning("merge resolution for chunk '%s' has no merged_text.", item.chunk_id)
                raise HTTPException(
                    status_code=422,
                    detail={
                        "error":    "missing_merged_text",
                        "message":  (
                            f"A merged text is required for chunk '{item.chunk_id}' "
                            f"when resolution is 'merge'. Please provide the merged content."
                        ),
                    },
                )

        # ── keep_new / merge: upsert into KB ──────────────────────────────────
        final_text = item.merged_text if item.resolution == Resolution.merge else text

        # Re-embed only if text changed
        if item.resolution == Resolution.merge:
            try:
                embedding = await embed_single(final_text)
            except EmbeddingError as exc:
                log.error("Failed to embed merged text for chunk '%s': %s", item.chunk_id, exc)
                failed_count += 1
                failed_ids.append(item.chunk_id)
                continue
        else:
            if existing_embedding is None:
                log.warning("No stored embedding for '%s' — re-embedding.", item.chunk_id)
                try:
                    embedding = await embed_single(final_text)
                except EmbeddingError as exc:
                    log.error("Re-embedding failed for chunk '%s': %s", item.chunk_id, exc)
                    failed_count += 1
                    failed_ids.append(item.chunk_id)
                    continue
            else:
                embedding = existing_embedding

        kb_meta = {
            **{
                k: v for k, v in meta.items()
                if k not in {
                    "upload_id", "has_conflict", "conflict_with",
                    "conflict_score", "conflict_summary",
                    "resolution", "resolved_at", "uploaded_at",
                }
            },
            "ingested_at":       datetime.utcnow().isoformat(),
            "ingested_by":       f"user:{req.upload_id}",
            "conflict_resolved": True,
            "resolved_from":     pending_id,
            "version":           int(meta.get("version", 1)) + 1,
        }

        try:
            def _upsert(cid=item.chunk_id, ft=final_text, emb=embedding, km=kb_meta):
                kb_collection.upsert(
                    ids=[cid], documents=[ft], embeddings=[emb], metadatas=[km],
                )
            await loop.run_in_executor(None, _upsert)

            def _del(pid=pending_id):
                pending_collection.delete(ids=[pid])
            await loop.run_in_executor(None, _del)

            resolved_count += 1
            log.info(
                "Chunk '%s' resolved (%s) → ingested into KB.",
                item.chunk_id, item.resolution,
            )
        except Exception as exc:
            log.error(
                "Failed to upsert resolved chunk '%s' into KB: %s",
                item.chunk_id, exc,
            )
            failed_count += 1
            failed_ids.append(item.chunk_id)

    log.info(
        "Conflict resolution complete — resolved=%d discarded=%d failed=%d (upload_id=%s).",
        resolved_count, discarded_count, failed_count, req.upload_id,
    )

    response = {
        "status":           "resolved" if failed_count == 0 else "partial",
        "upload_id":        req.upload_id,
        "resolved_chunks":  resolved_count,
        "discarded_chunks": discarded_count,
        "failed_chunks":    failed_count,
    }

    if failed_ids:
        response["failed_chunk_ids"] = failed_ids
        response["message"] = (
            f"{failed_count} chunk(s) could not be processed: {', '.join(failed_ids)}. "
            f"Please retry the upload for these chunks."
        )
    else:
        response["message"] = (
            f"All conflicts resolved. "
            f"{resolved_count} chunk(s) added to the knowledge base, "
            f"{discarded_count} discarded."
        )

    return response


@router.post("/approve")
async def approve(req: ApprovalRequest):
    """Approve or cancel a pending critical action (e.g. escalate_issue)."""
    if not req.action_id or not req.action_id.strip():
        raise HTTPException(
            status_code=422,
            detail={
                "error":   "missing_action_id",
                "message": "action_id is required.",
            },
        )

    log.info(
        "Approval request received — action_id=%s approved=%s",
        req.action_id, req.approved,
    )

    result: ActionResult = await approve_action(req.action_id, req.approved)

    if result.status == "not_found":
        raise HTTPException(
            status_code=404,
            detail={
                "error":   "action_not_found",
                "message": result.output.get("message", "Action not found."),
            },
        )

    # Audit the approval decision
    if req.approved and result.status == "executed":
        await append_audit(AuditEntry(
            session_id  = "approval-endpoint",
            query       = f"Manual approval for action_id={req.action_id}",
            action      = ActionName.escalate_issue,
            reasoning   = "Approved by user via POST /approve.",
            confidence  = 1.0,
            approved_by = "user",
            status      = "executed",
        ))

    log.info(
        "Approval outcome — action_id=%s approved=%s status=%s",
        req.action_id, req.approved, result.status,
    )
    return result