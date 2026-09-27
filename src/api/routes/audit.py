import logging
from fastapi import APIRouter, HTTPException, Query
from src.core.logger import read_audit_log
from src.core.schemas import PaginatedAuditLog

router = APIRouter()
log    = logging.getLogger("knowledge-agent.routes.audit")


@router.get("/audit-log", response_model=PaginatedAuditLog)
async def get_audit_log(
    page:   int        = Query(default=1,  ge=1,              description="Page number (1-based)"),
    size:   int        = Query(default=20, ge=1,   le=100,    description="Entries per page"),
    action: str | None = Query(default=None,                  description="Filter by action name"),
):
    try:
        total, entries = await read_audit_log(page=page, size=size, action_filter=action)
    except Exception as exc:
        log.exception("Failed to read audit log: %s", exc)
        raise HTTPException(
            status_code=500,
            detail={
                "error":   "audit_log_read_error",
                "message": "The audit log could not be read. Please try again.",
            },
        )

    log.debug("Audit log served — page=%d size=%d total=%d filter=%s", page, size, total, action)
    return PaginatedAuditLog(total=total, page=page, size=size, entries=entries)


@router.get("/health")
async def health():
    return {"status": "ok"}