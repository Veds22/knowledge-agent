import asyncio
import json
import logging
from datetime import datetime
from uuid import uuid4
 
import aiofiles
 
from src.core.config import get_settings
from src.core.schemas import ActionName, ActionResult, AgentOutput
from src.actions.registry import register
 
log = logging.getLogger("knowledge-agent.actions.create_ticket")
_lock = asyncio.Lock()
 
@register(
    ActionName.create_ticket,
    is_critical=False,
    description="Log a support ticket for issues requiring hands-on IT support.",
)
async def handle_create_ticket(
    output:     AgentOutput,
    session_id: str = "",
    **kwargs,
) -> ActionResult:
    settings  = get_settings()
    ticket_id = f"TKT-{uuid4().hex[:6].upper()}"
    
    ticket = {
        "ticket_id":  ticket_id,
        "session_id": session_id,
        "created_at": datetime.utcnow().isoformat(),
        "summary":    output.answer[:300],
        "reasoning":  output.reasoning,
        "status":     "open",
        "priority":   "medium",
    }
 
    try:
        async with _lock:
            async with aiofiles.open(settings.tickets_path, mode="a") as f:
                await f.write(json.dumps(ticket) + "\n")
        log.info("Ticket created: %s (session=%s)", ticket_id, session_id)
    except OSError as exc:
        log.error("Failed to write ticket '%s' to disk: %s", ticket_id, exc)
        return ActionResult(
            action="create_ticket",
            status="failed",
            output={
                "message": (
                    "Your support request was received but could not be saved due to a "
                    "storage error. Please contact IT support directly and quote your "
                    f"session ID: {session_id}."
                )
            },
        )
    except Exception as exc:
        log.exception("Unexpected error creating ticket '%s': %s", ticket_id, exc)
        return ActionResult(
            action="create_ticket",
            status="failed",
            output={
                "message": (
                    "An unexpected error occurred while creating your ticket. "
                    f"Please contact IT support directly (session: {session_id})."
                )
            },
        )
        
    return ActionResult(
        action="create_ticket",
        status="executed",
        output={
            "ticket_id":       ticket_id,
            "message":         f"Support ticket {ticket_id} has been created. The IT team will respond within 4 business hours.",
            "estimated_time":  "4 business hours",
        },
    )