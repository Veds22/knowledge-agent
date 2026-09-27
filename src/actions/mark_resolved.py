import logging
from src.core.schemas import ActionName, ActionResult, AgentOutput
from src.actions.registry import register

log = logging.getLogger("knowledge-agent.actions.mark_resolved")


@register(
    ActionName.mark_resolved,
    is_critical=False,
    description="Mark the query as resolved — informational only, no further action needed.",
)
async def handle_mark_resolved(output: AgentOutput, **kwargs) -> ActionResult:
    log.info("Query marked as resolved (confidence=%.2f).", output.confidence)
    return ActionResult(
        action="mark_resolved",
        status="executed",
        output={
            "message": "Your query has been answered. No further action is required.",
            "answer":  output.answer,
        },
    )