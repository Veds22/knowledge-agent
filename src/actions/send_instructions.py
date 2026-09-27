import logging
from src.core.schemas import ActionName, ActionResult, AgentOutput
from src.actions.registry import register

log = logging.getLogger("knowledge-agent.actions.send_instructions")


@register(
    ActionName.send_instructions,
    is_critical=False,
    description="Return formatted step-by-step instructions from the knowledge base.",
)
async def handle_send_instructions(output: AgentOutput, **kwargs) -> ActionResult:
    if not output.answer or not output.answer.strip():
        log.warning("send_instructions called with empty answer — returning fallback message.")
        return ActionResult(
            action="send_instructions",
            status="executed",
            output={
                "message":      "Instructions could not be retrieved.",
                "instructions": "No relevant instructions were found in the knowledge base for your query.",
            },
        )

    log.info("Sending instructions (confidence=%.2f).", output.confidence)
    return ActionResult(
        action="send_instructions",
        status="executed",
        output={
            "message":      "Instructions retrieved from the knowledge base.",
            "instructions": output.answer,
        },
    )