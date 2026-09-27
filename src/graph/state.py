from __future__ import annotations
 
from typing import Annotated
from typing_extensions import TypedDict
 
import operator
 
from src.core.schemas import (
    ActionResult, KBChunk, MemoryEntry, PlanStep, PlanTrace,
)


class AgentState(TypedDict):
    """
        LangGraph state — passed between every node in the graph.
        Uses Annotated[list, operator.add] for fields that nodes append to,
        so parallel nodes can safely extend lists without overwriting each other.
    """
    
    # Input
    goal:str 
    session_id:str
    
    # Memory & Retreival
    memory: list[MemoryEntry]
    chunks: list[KBChunk]
    
    # Plan & Trace
    plan: PlanTrace | None
    current_step: int 
    
    # Execution State
    step_results: Annotated[list[ActionResult], operator.add]
    errors: Annotated[list[str], operator.add]
    
    # Pending Approval 
    hitl_approved:    bool    
    hitl_approved_by: str
    
    # Final Output
    answer: str | None
    action_result: ActionResult | None
    confidence: float 
    
    # Control Flags
    should_abort: bool
    
