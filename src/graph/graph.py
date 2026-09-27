"""
    LangGraph StateGraph definition.
    Defines nodes, edges, and conditional routing.
    Compiled once at startup and reused across all requests.
"""

from __future__ import annotations
 
import logging
 
from langgraph.graph import END, START, StateGraph
 
from src.core.config import get_settings
from src.core.checkpointer import get_checkpointer
from src.graph import state
from src.graph.nodes import (
    planner_node,
    self_corrector_node,
    synthesizer_node,
    hitl_approval_node,
    tool_executor_node,
)
from src.graph.state import AgentState
 
log = logging.getLogger("knowledge-agent.graph")
 
_graph = None

def _route_after_executor(state: AgentState) -> str:
    """
        Conditional edge after tool_executor_node.
        Decides: run next step | self-correct | synthesize.
    """
    plan  = state.get("plan")
    idx   = state.get("current_step", 0)
    
    if plan is None:
        log.warning("[router] No plan in state — routing to synthesizer.")
        return "synthesizer"
    
    prev_idx = idx - 1
    if 0 <= prev_idx < len(plan.steps):
        prev_step = plan.steps[prev_idx]
 
        # Escalation detected — route to HITL node (graph will interrupt here)
        if getattr(prev_step, "result", "") and \
           str(prev_step.result).startswith("ESCALATION_REQUESTED::"):
            log.info("[router] Escalation detected → hitl_approval.")
            return "hitl_approval"
 
        if prev_step.status.value == "failed":
            log.info("[router] Step %d failed → self_corrector.", prev_idx + 1)
            return "self_corrector"
        
    if idx >= len(plan.steps):
        log.info("[router] All steps complete → synthesizer.")
        return "synthesizer"
 
    log.info("[router] Step %d/%d next → tool_executor.", idx + 1, len(plan.steps))
    return "tool_executor"


def _route_after_corrector(state: AgentState) -> str:
    """
        Conditional edge after self_corrector_node.
        Decides: retry step | continue to next | abort.
    """
    if state.get("should_abort", False):
        log.warning("[router] Abort flag set → synthesizer.")
        return "synthesizer"
 
    plan = state.get("plan")
    idx  = state.get("current_step", 0)
    
    if plan and 0 <= idx < len(plan.steps):
        step = plan.steps[idx]
        if step.status.value == "pending":
            log.info("[router] Retry step %d → tool_executor.", idx + 1)
            return "tool_executor"
 
    # Step was skipped or abort not set — check if more steps remain
    if idx >= len(plan.steps if plan else []):
        return "synthesizer"
 
    return "tool_executor"


def build_graph():
    """
        Build and compile the LangGraph StateGraph.
        Called once at startup.
    """
    settings = get_settings()
    builder  = StateGraph(AgentState)
    checkpointer = get_checkpointer()
    
    # Add Nodes 
    builder.add_node("planner", planner_node)
    builder.add_node("tool_executor", tool_executor_node)
    builder.add_node("self_corrector", self_corrector_node)
    builder.add_node("synthesizer", synthesizer_node)
    builder.add_node("hitl_approval",  hitl_approval_node) 
    
    # Add Edges
    builder.add_edge(START, "planner")
    builder.add_edge("planner", "tool_executor")
    builder.add_edge("synthesizer", END)
    builder.add_edge("hitl_approval", END)
    
    # Add conditional edges after tool_executor
    builder.add_conditional_edges(
        "tool_executor",
        _route_after_executor,
        {
            "tool_executor":  "tool_executor",
            "self_corrector": "self_corrector",
            "hitl_approval":  "hitl_approval",
            "synthesizer":    "synthesizer",
        },
    )
    builder.add_conditional_edges(
        "self_corrector",
        _route_after_corrector,
        {
            "tool_executor": "tool_executor",
            "synthesizer":   "synthesizer",
        },
    )
    compiled = builder.compile(
        checkpointer = checkpointer,
        interrupt_before = ["hitl_approval"],
    )
    log.info(
        "LangGraph compiled — max_iterations=%d max_retries_per_step=%d.",
        settings.max_graph_iterations,
        settings.max_tool_retries,
    )
    return compiled

def get_graph():
    global _graph
    if _graph is None:
        raise RuntimeError(
            "Agent graph not built. Call build_graph() during application startup."
        )
    return _graph
 
def init_graph():
    global _graph
    _graph = build_graph()
    log.info("Agent graph initialised.")
    return _graph  