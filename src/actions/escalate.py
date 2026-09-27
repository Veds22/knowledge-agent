calate · PY
import asyncio
import json
import logging
from datetime import datetime
from uuid import uuid4
 
import aiofiles
 
from src.core.config import get_settings
from src.core.schemas import ActionName, ActionResult, AgentOutput
from src.actions.registry import register
 
log   = logging.getLogger("knowledge-agent.actions.escalate")
_lock = asyncio.Lock()
 
 
@register(
    ActionName.escalate_issue,
    is_critical=True,
    description="Escalate a P1/P2 incident to senior IT. CRITICAL — requires human approval.",
)

async def handle_escalate(
    output:      AgentOutput,
    session_id:  str = "",
    approved_by: str = "user",
    **kwargs,
) -> ActionResult:
    settings      = get_settings()
    escalation_id = f"ESC-{uuid4().hex[:6].upper()}"
 
    record = {
        "escalation_id": escalation_id,
        "session_id":    session_id,
        "escalated_at":  datetime.utcnow().isoformat(),
        "summary":       output.answer[:300],
        "reasoning":     output.reasoning,
        "approved_by":   approved_by,
        "severity":      "P1",
        "status":        "escalated",
    }
    
    try:
        async with _lock:
            async with aiofiles.open(settings.tickets_path, mode="a") as f:
                await f.write(json.dumps(record) + "\n")
        log.warning(
            "Issue escalated: %s (severity=P1, approved_by=%s, session=%s)",
            escalation_id, approved_by, session_id,
        )
    except OSError as exc:
        log.error("Failed to write escalation record '%s': %s", escalation_id, exc)
        return ActionResult(
            action="escalate_issue",
            status="failed",
            output={
                "message": (
                    "The escalation was approved but could not be logged due to a storage error. "
                    f"Please contact your IT manager directly and quote session ID: {session_id}."
                )
            },
        )
        
    except Exception as exc:
        log.exception("Unexpected error writing escalation record '%s': %s", escalation_id, exc)
        return ActionResult(
            action="escalate_issue",
            status="failed",
            output={
                "message": (
                    "An unexpected error occurred while logging the escalation. "
                    f"Please contact IT support directly (session: {session_id})."
                )
            },
        )
 
    return ActionResult(
        action="escalate_issue",
        status="executed",
        output={
            "escalation_id": escalation_id,
            "message":       (
                f"Issue escalated ({escalation_id}). "
                f"A senior IT engineer has been notified and will respond within 30 minutes."
            ),
            "severity":      "P1",
            "approved_by":   approved_by,
        },
    )