from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field 


### Enums ###

class ActionName(str, Enum):
    search_kb = "search_kb"
    search_web = "search_web"
    escalate_issue = "escalate_issue"
    mark_resolved = "mark_resolved"
    send_instructions = "send_instructions"
    

class StepStatus(str, Enum):
    pending = "pending"
    running = "running"
    done = "done"
    failed = "failed"
    skipped = "skipped"
    

class JobStatus(str, Enum):
    pending = "pending"
    chunking = "chunking"
    embedding = "embedding"
    scanning = "scanning"
    conflicted = "conflicted"
    ingesting = "ingesting"
    completed = "completed"
    failed = "failed"
    
class Resolution(str, Enum):
    keep_new = "keep_new"
    keep_existing = "keep_existing"
    merge = "merge"
    
    
### Plan & Trace (LangGraph) ###

class PlanStep(BaseModel):
    step_number: int
    description: str
    tool: str
    tool_input: str
    status: StepStatus = StepStatus.pending
    error: str | None = None
    result: str | None
    retries: int = 0
    correction: str | None = None
    
class PlanTrace(BaseModel):
    goal: str
    steps: list[PlanStep]
    reasoning: str | None = None
    

### KB / Memory ###

class KBChunk(BaseModel):
    chunk_id: str
    text: str
    doc_id: str
    doc_title: str
    section: str 
    chunk_index: int
    score: float 
    
class MemoryEntry(BaseModel):
    turn_id: str
    query: str
    answer: str
    action_taken: str
    timestamp: datetime
    
### Action Result ###

class ActionResult(BaseModel):
    action: ActionName
    success: str    # "executed" | "pending_approval" | "cancelled" | "failed"
    output:      dict[str, Any]
    executed_at: datetime = Field(default_factory=datetime.utcnow)
    

### Agent I/O ###

class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    session_id: str = Field(default_factory=lambda: f"sess_{uuid4().hex[:8]}")
 
class ApprovalRequest(BaseModel):
    action_id: str
    approved: bool
    
class AgentResponse(BaseModel):
    """ 
        Full structured response returned to the user — includes visible plan trace.
    """
    session_id: str
    plan: PlanTrace
    answer: str 
    action_result: ActionResult 
    confidence: float 
    chunks_used: list[KBChunk]
    memory_used: list[MemoryEntry]
    total_steps: int
    completed_steps: int
    failed_steps:  int
    skipped_steps: int
    

### Upload / Ingestion ###

class UploadResponse(BaseModel):
    job_id: str
    status: str = "accepted"
    

class ConflictItem(BaseModel):
    chunk_id: str
    new_text: str
    existing_chunk_id: str
    existing_text: str
    conflict_score: float
    conflict_summary: str
    
class JobState(BaseModel):
    job_id: str
    status: JobStatus = JobStatus.pending
    progress: int = 0
    total_chunks: int = 0
    done_chunks: int = 0
    conflicts: list[ConflictItem] = []
    upload_id: str = ""
    filename: str = ""
    error: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    

class ResolutionItem(BaseModel):
    chunk_id: str
    resolution: Resolution
    merged_text: str | None = None
    
class ResolveRequest(BaseModel):
    upload_id:   str
    resolutions: list[ResolutionItem]
    
    
### Audit Entry ###

class AuditEntry(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    session_id: str
    query: str
    action: str
    reasoning: str
    confidence: float
    approved_by: str | None = None
    status: str = "completed"
 
 
class PaginatedAuditLog(BaseModel):
    total: int
    page: int
    size: int
    entries: list[AuditEntry]