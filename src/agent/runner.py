"""
    Orchestration wrapper around the LangGraph agent graph.
    
    Two entry points:
    run_agent()    — start a new graph run for a user query
    resume_agent() — resume a graph interrupted at hitl_approval node
"""
from __future__ import annotations
 
import asyncio
import logging
 
import chromadb
 
from src.agent.memory import get_relevant_memory, store_turn
from src.core.config import get_settings
from src.core.schemas import (
    ActionResult, AgentResponse, PlanTrace, QueryRequest, StepStatus,
)
from src.graph.graph import get_graph, init_graph
from src.graph.state import AgentState
 
log = logging.getLogger("knowledge-agent.runner")

class RunnerError(Exception):
    """Raised when the graph fails to produce a usable response."""
 
 
def _thread_config(session_id: str) -> dict:
    """
        LangGraph thread config — thread_id scopes the checkpoint to this session.
        All checkpointed state (plan, steps, results) is stored under this key.
    """
    return {
        "configurable": {"thread_id": session_id},
        "recursion_limit": get_settings().max_graph_iterations,
    }
 
def _build_response(session_id: str, final_state: AgentState, memory: list) -> AgentResponse:
    """Extract AgentResponse from final graph state."""
    plan: PlanTrace = final_state.get("plan") or PlanTrace(
        goal="", reasoning="Plan unavailable.", steps=[]
    )
    answer = final_state.get("answer") or "No answer was produced."
    action_result = final_state.get("action_result") or ActionResult(
        action="mark_resolved",
        status="failed",
        output={"message": "No action result available."},
    )
    confidence = final_state.get("confidence", 0.0)
    steps      = plan.steps
    

    return AgentResponse(
            session_id      = session_id,
            plan            = plan,
            answer          = answer,
            action_result   = action_result,
            confidence      = confidence,
            chunks_used     = final_state.get("chunks", []),
            memory_used     = memory,
            total_steps     = len(steps),
            completed_steps = sum(1 for s in steps if s.status == StepStatus.done),
            failed_steps    = sum(1 for s in steps if s.status == StepStatus.failed),
            skipped_steps   = sum(1 for s in steps if s.status == StepStatus.skipped),
        )
 
 
async def run_agent(
    req: QueryRequest,
    kb_collection: chromadb.Collection,
    memory_collection: chromadb.Collection,
) -> AgentResponse:
    """
        Start a new agent run.
    
        - thread_id = session_id → graph state checkpointed under this key
        - If graph hits interrupt_before=["hitl_approval"], ainvoke() returns
        with action_result.status == "pending_approval"
        - Caller checks for this and tells the frontend to hit POST /approve
    """
    
    log.info("Agent run — session=%s goal='%s…'", req.session_id, req.query[:80])
 
    log.info("Memory retrieval started — session=%s", req.session_id)
    memory = await get_relevant_memory(req.query, req.session_id, memory_collection)
    log.info("Memory retrieval complete — session=%s entries=%d", req.session_id, len(memory))
 
 
    initial_state: AgentState = {
        "goal": req.query,
        "session_id": req.session_id,
        "memory": memory,
        "chunks": [],
        "plan": None,
        "current_step": 0,
        "step_results": [],
        "errors": [],
        "hitl_approved": False,
        "hitl_approved_by": "",
        "answer": None,
        "action_result": None,
        "confidence": 0.0,
        "should_abort": False,
    }
    
    try:
        graph = get_graph()
        if graph is None:
            log.info("Initialising LangGraph agent graph…")
            graph = init_graph()
    except Exception as exc:
        log.error("Failed to initialise LangGraph agent graph: %s", exc)
        raise RunnerError(
            "The agent is not available at this time. Please try again later."
        ) from exc
            
    config = _thread_config(req.session_id)
 
    try:
        timeout = get_settings().agent_timeout_seconds
        log.info("Graph execution started — session=%s timeout=%ss", req.session_id, timeout)
        final_state: AgentState = await asyncio.wait_for(
            graph.ainvoke(initial_state, config=config),
            timeout=timeout,
        )
    except asyncio.TimeoutError as exc:
        log.error("Graph execution timed out session=%s after %ss", req.session_id, timeout)
        raise RunnerError(
            "The agent took too long to respond. Please try again."
        ) from exc
    except Exception as exc:
        log.exception("Graph execution failed session=%s: %s", req.session_id, exc)
        raise RunnerError(
            "The agent encountered an unexpected error. Please try again."
        ) from exc
        
    current_node = await _get_next_node(graph, config)
    if current_node == "hitl_approval":
        log.info("Graph interrupted at hitl_approval — awaiting user decision.")
        
        plan = final_state.get("plan") or PlanTrace(goal=req.query, reasoning="", steps=[])
        return AgentResponse(
            session_id      = req.session_id,
            plan            = plan,
            answer          = "This action requires your approval before it can proceed.",
            action_result   = ActionResult(
                action = "escalate_issue",
                status = "pending_approval",
                output = {
                    "message":    "A critical action requires your approval. Use POST /approve to proceed.",
                    "session_id": req.session_id,
                },
            ),
            confidence      = 0.9,
            chunks_used     = final_state.get("chunks", []),
            memory_used     = memory,
            total_steps     = len(plan.steps),
            completed_steps = 0,
            failed_steps    = 0,
            skipped_steps   = 0,
        )
        
    response = _build_response(req.session_id, final_state, memory)
 
    if response.action_result.status == "executed":
        await store_turn(
            req.session_id, req.query,
            response.answer, response.action_result.action,
            memory_collection,
        )
 
    log.info(
        "Run complete — session=%s action=%s status=%s steps=%d",
        req.session_id, response.action_result.action,
        response.action_result.status, response.total_steps,
    )
    return response


async def resume_agent(
    session_id: str,
    approved: bool,
    approved_by: str,
    memory_collection: chromadb.Collection,
) -> AgentResponse:
    """
        Resume a graph that was interrupted at hitl_approval.
    
        LangGraph resumes from the exact checkpoint — no re-planning,
        no re-execution of already-completed steps.
    
        Passing None as input tells LangGraph to use the checkpointed state;
        we only inject the HITL approval fields as an update.
    """
    log.info(
        "Resuming graph — session=%s approved=%s by=%s",
        session_id, approved, approved_by,
    )
    
    graph  = get_graph()
    config = _thread_config(session_id)
    
    try:
        await graph.aupdate_state(
            config,
            {
                "hitl_approved":    approved,
                "hitl_approved_by": approved_by,
            },
        )
    except Exception as exc:
        log.error("Failed to update checkpoint state for session=%s: %s", session_id, exc)
        raise RunnerError(
            "Could not apply your decision to the paused agent. "
            "The session may have expired. Please start a new query."
        ) from exc
        
    try:
        final_state: AgentState = await graph.ainvoke(None, config=config)
    except Exception as exc:
        log.exception("Graph resume failed session=%s: %s", session_id, exc)
        raise RunnerError(
            "The agent failed to resume after your decision. Please try again."
        ) from exc
        
    response = _build_response(session_id, final_state, [])
 
    if response.action_result.status == "executed":
        await store_turn(
            session_id,
            f"[HITL resume] approved={approved}",
            response.answer,
            response.action_result.action,
            memory_collection,
        )
 
    log.info(
        "Resume complete — session=%s action=%s status=%s",
        session_id, response.action_result.action, response.action_result.status,
    )
    return response

async def _get_next_node(graph, config: dict) -> str | None:
    """
        Check which node the graph will run next (None if graph finished).
        Used to detect the hitl_approval interrupt after ainvoke returns.
    """
    try:
        snapshot = await graph.aget_state(config)
        nexts    = snapshot.next
        return nexts[0] if nexts else None
    except Exception as exc:
        log.warning("Could not read graph state snapshot: %s", exc)
        return None
    
    