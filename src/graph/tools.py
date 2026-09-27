""" 
    LangGraph tool definitions.
    Each @tool is a named callable the planner can reference by name.
    Side-effect actions (ticket writes, escalation records) delegate
    to src/actions/ handlers to keep IO logic in one place.
"""

from __future__ import annotations
 
import asyncio
import logging
from typing import Annotated
 
import chromadb
from langchain_core.tools import tool
 
from src.core.config import get_settings
from src.ingestion.embedder import embed_single, EmbeddingError
 
 
log = logging.getLogger("knowledge-agent.tools")

_kb_collection: chromadb.Collection | None = None


def init_tools(kb_collection: chromadb.Collection) -> None:
    global _kb_collection
    _kb_collection = kb_collection
    log.info("Tools Inititalised with KB Collection: %s", kb_collection.name)
    
def _get_kb() -> chromadb.Collection:
    if _kb_collection is None:
        raise RuntimeError(
            "Tools are not initalised. Call init_tools(kb_collection) in the FastAPI lifespan."
        )
    return _kb_collection


### Tool: search_kb ###

@tool
def search_kb(query: Annotated[str, "The search query to look up in the knowledge base"]) -> str:
    """
        Search the internal IT knowledge base for relevant information.
        Returns the top matching chunks as formatted text.
        Use this for any question about IT policies, procedures, or troubleshooting steps.
    """
    if not query or not query.strip():
        return "Error: search query cannot be empty."
 
    settings = get_settings()
    kb = _get_kb()
    
    try:
        loop = asyncio.new_event_loop()
        embedding = loop.run_until_complete(embed_single(query))
        loop.close()
    except EmbeddingError as exc:
        log.error("search_kb: Failed to embed query '%s': %s", query[:60], exc)
        return f"Error: Could not process the search_query. {exc}"
    
    try:
        result = kb.query(
            query_embeddings=[embedding],
            n_results=settings.top_k,
            include=["documents", "metadatas", "distances"],
        )
    except Exception as exc: 
        log.error("search_kb ChromaDB query failed %s", exc)
        return "Error: the knowldege base could not query right now. Please try again later."
    
    if not result["ids"] or not result["ids"][0]:
        return "No relevant information found in the knowledge base for this query."
    
    parts = []
    for doc, meta, dist in zip(
        result["documents"][0],
        result["metadatas"][0],
        result["distances"][0],
    ):
        score = round(1.0 - dist/2.0, 3)
        title = meta.get("doc_title", "Unknown")
        section = meta.get("section", "")
        parts.append(f"Title: {title}\nSection: {section}\nScore: {score}\nContent: {doc}\n")
    
    log.info("search_kb returned %d chunk(s) for query '%s'", len(parts), query[:60])
    return "\n\n---\n\n".join(parts)

### Tool: create_ticket ###
@tool
def create_ticket(
    summary: Annotated[str, "Brief summary of the issue to be logged in the ticket requiring IT support"],
) -> str:
    """
        Create a support ticket for issues that require hands-on IT intervention.
        Use when the issue cannot be resolved with instructions alone.
        Returns the ticket ID and a confirmation message.
    """
    
    import json
    from datetime import datetime
    from uuid import uuid4
    
    if not summary or not summary.strip():
        return "Error: ticket summary cannot be empty."
    
    settings  = get_settings()
    ticket_id = f"TKT-{uuid4().hex[:6].upper()}"
    record    = {
        "ticket_id":  ticket_id,
        "created_at": datetime.utcnow().isoformat(),
        "summary":    summary[:400],
        "status":     "open",
        "priority":   "medium",
    }
    try:
        with open(settings.tickets_path, "a") as f:
            f.write(json.dumps(record) + "\n")
        log.info("Ticket created: %s", ticket_id)
        return (
            f"Support ticket {ticket_id} created successfully. "
        )
    except Exception as exc:
        log.error("Failed to write ticket to disk: ", exc)
        return (
            "Ticket could not be saved due to a storage error. "
            "Please contact IT support directly."
        )
        
### Tool: escalate_issue ###

@tool
def escalate_issue(
    reason: Annotated[str, "Why this issue requires P1/P2 escalation to senior IT"],
) -> str:
    """
        Escalate a critical incident (P1/P2) to senior IT engineering.
        Use ONLY for: data loss, security breaches, full system outages.
        This action is flagged as CRITICAL and will require user approval before execution.
    """
    # Returns a sentinel string — the graph's self_corrector / synthesizer
    # detects this and routes to the approval gate
    log.warning("escalate_issue tool called — flagging for human approval. Reason: %s", reason[:100])
    return f"ESCALATION_REQUESTED::{reason}"


### Tool: get_ticket_status ###

@tool
def get_ticket_status(
    ticket_id: Annotated[str, "The ID of the ticket to check the status of"],
) -> str:
    """
        Get the status of a support ticket.
        Returns the current status of the ticket.
    """
    import json
    settings = get_settings()
    try:
        with open(settings.tickets_path, "r") as f:
            for line in f:
                record = json.loads(line)
                if record["ticket_id"] == ticket_id:
                    return f"Ticket {ticket_id} is currently {record['status']}."
        return f"Ticket {ticket_id} not found."
    except Exception as exc:
        log.error("Failed to read ticket status: %s", exc)
        return "Error: could not retrieve the ticket status. Please try again later."
    
    
### Tool: mark_resolved ###

@tool
def mark_resolved(
    summary: Annotated[str, "Brief summary of how the query was resolved"],
) -> str:
    """
        Mark the query as resolved — use for purely informational queries
        that have been answered fully and require no further action.
    """
    log.info("Query marked resolved: %s", summary[:80])
    return f"Resolved: {summary}"
 

### Tool: send_instructions ###

@tool
def send_instructions(
    instructions: Annotated[str, "The step-by-step instructions to send to the user"],
) -> str:
    """
        Format and deliver step-by-step instructions to the user.
        Use after retrieving relevant steps from the knowledge base.
    """
    if not instructions or not instructions.strip():
        return "Error: instructions cannot be empty."
    log.info("Instructions prepared (%d chars).", len(instructions))
    return f"INSTRUCTIONS::{instructions}"
 
 
ALL_TOOLS = [
    search_kb,
    create_ticket,
    escalate_issue,
    mark_resolved,
    get_ticket_status,
    send_instructions,
]
 
TOOL_NAMES = [t.name for t in ALL_TOOLS]
TOOL_DESCRIPTIONS = "\n".join(
    f"- {t.name}: {t.description.strip().splitlines()[0]}"
    for t in ALL_TOOLS
)