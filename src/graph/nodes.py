"""
    LangGraph node functions.
    Each node receives AgentState, performs one unit of work, and returns
    a partial state dict — LangGraph merges it back automatically.
"""

from __future__ import annotations
 
import json
import logging
from datetime import datetime
from uuid import uuid4
 
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage, AIMessage
from langchain_groq import ChatGroq
from langgraph.prebuilt import ToolNode

 
from src.core.config import get_settings
from src.core.schemas import ActionResult, PlanStep, PlanTrace, StepStatus
from src.graph.state import AgentState
from src.graph.tools import ALL_TOOLS, TOOL_DESCRIPTIONS, TOOL_NAMES
 
log = logging.getLogger("knowledge-agent.nodes")
 
def _get_llm(temperature: float = 0.2) -> ChatGroq:
    s = get_settings()
    return ChatGroq(
        api_key=s.groq_api_key,
        model=s.groq_model,
        temperature=temperature,
        max_tokens=2048,
    )
    
### Node: Planner ###

PLANNER_SYSTEM = """
You are a planning AI for an IT Helpdesk agent.
Given a user's goal and any prior context, produce a step-by-step plan.
 
Available tools:
{tool_descriptions}
 
Rules:
- Each step must use exactly one tool from the list above.
- Maximum {max_steps} steps.
- search_kb must be the first step if any knowledge retrieval is needed.
- Only use escalate_issue for genuine P1/P2 incidents (data loss, security breach, full outage).
- End with either send_instructions, mark_resolved, create_ticket, or escalate_issue.
 
Respond with ONLY a valid JSON object:
{{
  "reasoning": "<why you chose this plan>",
  "steps": [
    {{
      "step_number": 1,
      "description": "<what this step does in plain English>",
      "tool": "<tool_name>",
      "tool_input": "<exact input string to pass to the tool>"
    }}
  ]
}}"""

async def planner_node(state: AgentState) -> dict:
    """
        Produces a PlanTrace from the user's goal.
    """
    settings = get_settings()
    log.info("[planner] Planning for goal: '%s…'", state["goal"][:80])
    
    memory_context = ""
    if state.get("memory"):
        pairs = [f"Q: {m.query[:80]}\nA: {m.response[:150]}" for m in state['memory:3']]
        memory_context = "Prior context from memory:\n" + "\n\n".join(pairs) + "\n"
        
    system_prompt = PLANNER_SYSTEM.format(
        tool_descriptions=TOOL_DESCRIPTIONS,
        max_steps=settings.max_plan_steps,
    )
    
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"User goal: {state['goal']}\n\n {memory_context}"),
    ]
    
    try:
        llm = _get_llm(temperature=0.1)
        response =  await llm.ainvoke(messages)
        raw = response.content.strip()
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        log.error("[planner] Failed to parse LLM response: %s", exc)
        data = {
            "reasoning": "Fallback plan due to planner error.",
            "steps": [{
                "step_number": 1,
                "description": "Search the knowledge base for relevant information.",
                "tool":        "search_kb",
                "tool_input":  state["goal"],
            }],
        }
    except Exception as exc:
        log.error("[planner] LLM invocation failed: %s", exc)
        data = {
            "reasoning": f"Planner failed: {exc}",
            "steps": [{
                "step_number": 1,
                "description": "Search the knowledge base.",
                "tool":        "search_kb",
                "tool_input":  state["goal"],
            }],
        }
    
    steps = [
        PlanStep(
            step_number  = s.get("step_number", i + 1),
            description  = s.get("description", ""),
            tool         = s.get("tool", "search_kb"),
            tool_input   = s.get("tool_input", state["goal"]),
        )
        for i, s in enumerate(data.get("steps", []))
        if s.get("tool") in TOOL_NAMES          
    ]
    
    if not steps:
        log.warning("[planner] No valid steps produced — using fallback.")
        steps = [PlanStep(
            step_number=1, description="Search the knowledge base.",
            tool="search_kb", tool_input=state["goal"],
        )]
    
    plan = PlanTrace(
        goal      = state["goal"],
        reasoning = data.get("reasoning", ""),
        steps     = steps,
    )
    
    log.info("[planner] Plan produced: %d step(s).", len(steps))
    return {"plan": plan, "current_step": 0}


### Node: Tool Executor ###

_tool_node = ToolNode(
    tools=ALL_TOOLS,
)
 
async def tool_executor_node(state: AgentState) -> dict:
    """
        Executes the current plan step using LLM-native tool binding.
        The LLM emits a tool_call message; ToolNode intercepts and runs it.
        Makes tool invocation explicit and visible in the trace.
    """
    plan = state["plan"]
    idx  = state["current_step"]
 
    if idx >= len(plan.steps):
        log.warning("[executor] current_step=%d out of range — skipping.", idx)
        return {"current_step": idx + 1}
 
    step = plan.steps[idx]
    step.status = StepStatus.running
    log.info(
        "[executor] Step %d/%d — tool=%s input='%s…'",
        idx + 1, len(plan.steps), step.tool, step.tool_input[:60],
    )
 
    llm_with_tools = _get_llm().bind_tools(ALL_TOOLS, tool_choice=step.tool)
 
    messages = [
        SystemMessage(content=(
            f"You are executing step {idx + 1} of a plan.\n"
            f"Step: {step.description}\n"
            f"You must call the tool '{step.tool}' with the following input:\n"
            f"{step.tool_input}\n"
            f"Call the tool now — do not add commentary."
        )),
        HumanMessage(content=step.tool_input),
    ]
 
    try:
        ai_msg: AIMessage = await llm_with_tools.ainvoke(messages)
 
        if not ai_msg.tool_calls:
            raise ValueError(
                f"LLM did not emit a tool call for step {idx + 1} "
                f"(tool={step.tool}). Response: {ai_msg.content[:200]}"
            )
 
        # ToolNode executes the tool call and returns a ToolMessage
        tool_result = await _tool_node.ainvoke({"messages": [ai_msg]})
        tool_message: ToolMessage = tool_result["messages"][-1]
        result_text = tool_message.content
 
        log.info(
            "[executor] Step %d tool_call_id=%s result='%s…'",
            idx + 1,
            ai_msg.tool_calls[0].get("id", "?"),
            result_text[:80],
        )
 
        step.status = StepStatus.done
        step.result = result_text
 
        return {
            "plan":         plan,
            "current_step": idx + 1,
            "step_results": [result_text],
        }
 
    except Exception as exc:
        err = f"Step {idx + 1} ({step.tool}) failed: {exc}"
        log.error("[executor] %s", err)
        step.status = StepStatus.failed
        step.error  = str(exc)
        return {
            "plan":         plan,
            "current_step": idx + 1,
            "errors":       [err],
        }
    

### Node: Self Corrector ###

CORRECTOR_SYSTEM = """You are a self-correction module for an IT Helpdesk AI agent.
A tool execution step just failed. Decide what to do next.
 
Respond with ONLY a valid JSON object:
{{
  "decision": "<retry|skip|abort>",
  "reasoning": "<why>",
  "new_input": "<revised tool input if decision is retry, else empty string>"
}}
 
- retry: the step can succeed with a different input (max {max_retries} retries per step)
- skip: the step is not essential; continue with the remaining plan
- abort: the failure is unrecoverable; stop and report the error to the user"""

async def self_corrector_node(state: AgentState) -> dict:
    """
    Called when the previous step failed.
    Decides: retry with new input | skip | abort.
    """
    settings  = get_settings()
    plan      = state["plan"]
    idx       = state["current_step"] - 1   
    step      = plan.steps[idx] if idx < len(plan.steps) else None
 
    if step is None:
        return {"should_abort": True}
 
    if step.retries >= settings.max_tool_retries:
        log.warning(
            "[corrector] Step %d exceeded max retries (%d) — skipping.",
            idx + 1, settings.max_tool_retries,
        )
        step.status = StepStatus.skipped
        return {"plan": plan, "should_abort": False}
 
    messages = [
        SystemMessage(content=CORRECTOR_SYSTEM.format(max_retries=settings.max_tool_retries)),
        HumanMessage(content=(
            f"Goal: {state['goal']}\n"
            f"Failed step: {step.description}\n"
            f"Tool: {step.tool}\n"
            f"Input used: {step.tool_input}\n"
            f"Error: {step.error}\n"
            f"Retries so far: {step.retries}"
        )),
    ]
    
    try:
        llm  = _get_llm(temperature=0.0)
        response = await llm.ainvoke(messages)
        data = json.loads(response.content.strip())
    except Exception as exc:
        log.error("[corrector] LLM call failed: %s — defaulting to skip.", exc)
        data = {"decision": "skip", "reasoning": str(exc), "new_input": ""}
    
    decision   = data.get("decision", "skip")
    reasoning  = data.get("reasoning", "")
    new_input  = data.get("new_input", "")
    
    log.info("[corrector] Step %d: decision=%s reasoning='%s…'", idx + 1, decision, reasoning[:80])
    
    if decision == "retry" and new_input:
        step.retries += 1
        step.tool_input = new_input
        step.status = StepStatus.pending
        step.correction = reasoning
        return {
            "plan": plan,
            "current_step": idx,        
            "should_abort": False,
        }
        
    elif decision == "abort":
        step.status = StepStatus.failed
        return {"plan": plan, "should_abort": True}
 
    else:
        step.status = StepStatus.skipped
        step.correction = reasoning
        return {"plan": plan, "should_abort": False}
    
    
### Node 4: Synthesizer ###

SYNTHESIZER_SYSTEM = """You are a synthesis AI for an IT Helpdesk agent.
Given a user's goal and the results of each executed step, produce a final response.
 
Respond with ONLY a valid JSON object:
{{
  "answer": "<complete, helpful response to the user>",
  "action": "<primary action taken: send_instructions|create_ticket|escalate_issue|mark_resolved>",
  "confidence": <float 0.0-1.0>,
  "reasoning": "<brief explanation of your conclusion>"
}}"""
 
 
async def synthesizer_node(state: AgentState) -> dict:
    """
        Reads all step results and produces the final structured answer.
        Detects escalation requests from tool outputs.
    """
    plan         = state["plan"]
    step_results = state.get("step_results", [])
    errors       = state.get("errors", [])
 
    for result in step_results:
        if result.startswith("ESCALATION_REQUESTED::"):
            reason = result.split("::", 1)[1]
            log.warning("[synthesizer] Escalation requested — flagging for approval.")
            return {
                "answer": (
                    f"This issue has been flagged for P1 escalation. "
                    f"Reason: {reason}\n\n"
                    f"A senior IT engineer will be notified pending your approval."
                ),
                "action_result": ActionResult(
                    action="escalate_issue",
                    status="pending_approval",
                    output={
                        "message": "Escalation requires your approval. Please confirm.",
                        "reason":  reason,
                    },
                ),
                "confidence": 0.95,
            }
            
    results_block = "\n\n".join(
        f"Step {i+1} result:\n{r}" for i, r in enumerate(step_results)
    ) or "No results were collected."
 
    errors_block = (
        "\n".join(f"- {e}" for e in errors)
        if errors else "None."
    )
    
    messages = [
        SystemMessage(content=SYNTHESIZER_SYSTEM),
        HumanMessage(content=(
            f"User goal: {state['goal']}\n\n"
            f"Step results:\n{results_block}\n\n"
            f"Errors encountered:\n{errors_block}"
        )),
    ]
    
    try:
        llm = _get_llm(temperature=0.2)
        response = await llm.ainvoke(messages)
        data = json.loads(response.content.strip())
    except Exception as exc:
        log.error("[synthesizer] LLM call failed: %s", exc)
        data = {
            "answer": "I was unable to produce a complete answer due to an internal error.",
            "action": "mark_resolved",
            "confidence": 0.0,
            "reasoning":  str(exc),
        }
        
    action_name = data.get("action", "mark_resolved")
    log.info(
        "[synthesizer] Final answer produced — action=%s confidence=%.2f",
        action_name, float(data.get("confidence", 0.5)),
    )
    
    return {
        "answer": data.get("answer", "No answer produced."),
        "action_result": ActionResult(
            action = action_name,
            status = "executed",
            output = {"answer": data.get("answer", ""), "reasoning": data.get("reasoning", "")},
        ),
        "confidence": max(0.0, min(1.0, float(data.get("confidence", 0.5)))),
    }
    

### Node: HITL Approval ###

async def hitl_approval_node(state: AgentState) -> dict:
    """ 
        Runs AFTER user approval is received (graph was interrupted before this).
        Reads approval decision from state["hitl_approved"] and builds ActionResult.
    """
    import aiofiles
    approved    = state.get("hitl_approved", False)
    approved_by = state.get("hitl_approved_by", "user")
    
    escalation_reason = ""
    for result in state.get("step_results", []):
        if str(result).startswith("ESCALATION_REQUESTED::"):
            escalation_reason = result.split("::", 1)[1]
            break
        
    if not approved:
        log.info("[hitl] Escalation rejected by user.")
        return {
            "action_result": ActionResult(
                action = "escalate_issue",
                status = "cancelled",
                output = {"message": "Escalation cancelled by user. No action taken."},
            ),
            "answer": "The escalation request was reviewed and cancelled. No further action has been taken.",
        }
    
    settings      = get_settings()
    escalation_id = f"ESC-{uuid4().hex[:6].upper()}"
    record = {
        "escalation_id": escalation_id,
        "session_id":    state.get("session_id", ""),
        "escalated_at":  datetime.utcnow().isoformat(),
        "reason":        escalation_reason,
        "approved_by":   approved_by,
        "severity":      "P1",
        "status":        "escalated",
    }
    
    try:
        with aiofiles.open(settings.tickets_path, "a") as f:
            f.write(json.dumps(record) + "\n")
        log.warning("[hitl] Escalation executed: %s approved_by=%s", escalation_id, approved_by)
    except OSError as exc:
        log.error("[hitl] Failed to write escalation record: %s", exc)
        return {
            "action_result": ActionResult(
                action = "escalate_issue",
                status = "failed",
                output = {"message": "Escalation approved but could not be logged. Contact IT directly."},
            ),
            "answer": "Escalation was approved but a storage error occurred. Please contact IT support directly.",
        }
        
    return {
        "action_result": ActionResult(
            action = "escalate_issue",
            status = "executed",
            output = {
                "escalation_id": escalation_id,
                "message":       f"Issue escalated ({escalation_id}). Senior IT engineer notified — ETA 30 min.",
                "approved_by":   approved_by,
            },
        ),
        "answer": (
            f"Your issue has been escalated to senior IT engineering ({escalation_id}). "
            f"A response is expected within 30 minutes."
        ),
    }