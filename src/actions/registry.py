"""
Action registry — single source of truth for action metadata.
The @register decorator marks each handler with its name, criticality flag,
and description. Used by:
  - dispatcher (legacy reference — now graph routes via ToolNode)
  - audit logging (action metadata lookup)
  - startup validation (confirm all actions loaded)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Coroutine

log = logging.getLogger("knowledge-agent.actions.registry")


@dataclass
class ActionDefinition:
    name:        str
    handler:     Callable[..., Coroutine[Any, Any, Any]]
    is_critical: bool
    description: str


# Populated at import time via @register decorators on each action handler
ACTION_REGISTRY: dict[str, ActionDefinition] = {}


def register(
    name:        str,
    is_critical: bool = False,
    description: str  = "",
) -> Callable:
    """
    Decorator that registers an async action handler into ACTION_REGISTRY.

    Usage:
        @register("create_ticket", is_critical=False, description="...")
        async def handle_create_ticket(...): ...
    """
    def decorator(fn: Callable) -> Callable:
        if name in ACTION_REGISTRY:
            log.warning(
                "Action '%s' already registered — overwriting with '%s'.",
                name, fn.__name__,
            )
        ACTION_REGISTRY[name] = ActionDefinition(
            name        = name,
            handler     = fn,
            is_critical = is_critical,
            description = description,
        )
        log.debug("Action registered: name=%s is_critical=%s", name, is_critical)
        return fn
    return decorator


def get_action(name: str) -> ActionDefinition:
    if name not in ACTION_REGISTRY:
        raise KeyError(
            f"Action '{name}' is not registered. "
            f"Registered actions: {list(ACTION_REGISTRY.keys())}"
        )
    return ACTION_REGISTRY[name]


def is_critical(name: str) -> bool:
    entry = ACTION_REGISTRY.get(name)
    return entry.is_critical if entry else False


def list_actions() -> list[str]:
    return list(ACTION_REGISTRY.keys())