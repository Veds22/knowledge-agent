"""
    Called once at startup (already done in main.py via load_all_actions).
    Kept separate so tools.py can import handler functions without
    circular imports through the graph layer.
"""
from src.actions.create_ticket     import handle_create_ticket      # noqa: F401
from src.actions.escalate          import handle_escalate           # noqa: F401
from src.actions.mark_resolved     import handle_mark_resolved      # noqa: F401
from src.actions.send_instructions import handle_send_instructions  # noqa: F401


def load_all_actions() -> None:
    """
       Importing the handlers above triggers @register on each one,
       Explicit loader called in FastAPI lifespan (main.py).
       populating ACTION_REGISTRY. This function confirms they loaded.
    """
    import logging
    from src.actions.registry import list_actions
    log = logging.getLogger("knowledge-agent.actions")
    registered = list_actions()
    if not registered:
        raise RuntimeError("No actions were registered — check action handler imports.")
    log.info("Actions registered: %s", registered)