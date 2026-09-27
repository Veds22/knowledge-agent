from __future__ import annotations

import asyncio
import logging
from uuid import uuid4

from src.actions.registry import ACTION_REGISTRY, get_action
from src.core.schemas import ActionName, ActionResult, AgentOutput

log = logging.getLogger("knowledge-agent.dispatcher")


class DispatchError(Exception):
    """Raised when an action cannot be dispatched."""


class ActionNotFoundError(DispatchError):
    def __init__(self, action: ActionName):
        super().__init__(f"No handler registered for action '{action}'.")
        self.action = action


# Pending critical actions awaiting human approval: action_id → (output, kwargs)
_pending: dict[str, tuple[AgentOutput, dict]] = {}
_pending_lock = asyncio.Lock()


async def dispatch(
    output:     AgentOutput,
    session_id: str = "",
) -> tuple[ActionResult, str | None]:
    """
    Route AgentOutput to the correct registered action handler.

    Critical actions are held in _pending and returned with status='pending_approval'.
    The frontend uses the returned action_id to call POST /approve.

    Returns: (ActionResult, action_id | None)
    Raises DispatchError if the action is not registered or the handler fails.
    """
    try:
        action_def = get_action(output.action)
    except KeyError as exc:
        log.error("Dispatch failed — unregistered action '%s': %s", output.action, exc)
        raise ActionNotFoundError(output.action) from exc

    # ── Critical action: hold for approval ────────────────────────────────────
    if action_def.is_critical:
        action_id = f"act_{uuid4().hex[:8]}"
        async with _pending_lock:
            _pending[action_id] = (output, {"session_id": session_id})

        log.warning(
            "Critical action '%s' queued — action_id=%s session=%s. "
            "Awaiting human approval.",
            output.action, action_id, session_id,
        )
        return (
            ActionResult(
                action = output.action,
                status = "pending_approval",
                output = {
                    "action_id": action_id,
                    "message":   (
                        f"This action ({output.action}) has been flagged as critical "
                        f"and requires your approval before it is executed. "
                        f"Please review the reasoning and confirm."
                    ),
                },
            ),
            action_id,
        )

    # ── Non-critical action: execute immediately ───────────────────────────────
    try:
        result = await action_def.handler(output, session_id=session_id)
        log.info(
            "Action '%s' executed — status=%s session=%s",
            output.action, result.status, session_id,
        )
        return result, None
    except Exception as exc:
        log.exception(
            "Handler for action '%s' raised an unexpected error (session=%s): %s",
            output.action, session_id, exc,
        )
        raise DispatchError(
            f"The action '{output.action}' could not be completed due to an internal error. "
            f"Please try again or contact support."
        ) from exc


async def dispatch_parallel(
    outputs:    list[AgentOutput],
    session_id: str = "",
) -> list[tuple[ActionResult, str | None]]:
    """
    Execute multiple independent actions concurrently via asyncio.gather().
    Individual failures do not cancel sibling actions — errors are caught
    per-action and returned as failed ActionResults.
    """
    if not outputs:
        log.debug("dispatch_parallel called with empty outputs list.")
        return []

    async def _safe_dispatch(o: AgentOutput) -> tuple[ActionResult, str | None]:
        try:
            return await dispatch(o, session_id)
        except DispatchError as exc:
            log.error("Parallel dispatch failed for action '%s': %s", o.action, exc)
            return (
                ActionResult(
                    action = o.action,
                    status = "failed",
                    output = {"error": str(exc)},
                ),
                None,
            )

    log.info("Dispatching %d action(s) in parallel.", len(outputs))
    results = await asyncio.gather(*[_safe_dispatch(o) for o in outputs])
    return list(results)


async def approve_action(
    action_id:   str,
    approved:    bool,
    approved_by: str = "user",
) -> ActionResult:
    """
    Resume or cancel a pending critical action.
    Called from POST /approve.

    Never raises — returns a descriptive ActionResult for all outcomes.
    """
    async with _pending_lock:
        entry = _pending.pop(action_id, None)

    if entry is None:
        log.warning(
            "Approval request for unknown or already-resolved action_id '%s'.", action_id,
        )
        return ActionResult(
            action = ActionName.escalate_issue,
            status = "not_found",
            output = {
                "message": (
                    f"Action '{action_id}' was not found. "
                    f"It may have already been resolved or expired."
                )
            },
        )

    output, kwargs = entry

    if not approved:
        log.info(
            "Critical action '%s' (action_id=%s) cancelled by '%s'.",
            output.action, action_id, approved_by,
        )
        return ActionResult(
            action = output.action,
            status = "cancelled",
            output = {"message": "Action was cancelled. No changes have been made."},
        )

    try:
        action_def = get_action(output.action)
        result     = await action_def.handler(
            output, approved_by=approved_by, **kwargs
        )
        log.info(
            "Critical action '%s' (action_id=%s) executed after approval by '%s'.",
            output.action, action_id, approved_by,
        )
        return result
    except Exception as exc:
        log.exception(
            "Critical action '%s' (action_id=%s) failed after approval: %s",
            output.action, action_id, exc,
        )
        return ActionResult(
            action = output.action,
            status = "failed",
            output = {
                "message": (
                    f"The action was approved but could not be executed due to an internal error. "
                    f"Please contact support with action ID: {action_id}."
                )
            },
        )