# Autonomous Knowledge Execution Agent

An autonomous AI agent that retrieves information from an internal IT Helpdesk knowledge base, reasons over it using a LangGraph planning loop, selects and executes appropriate actions, and explains every decision. Supports dynamic knowledge base expansion with conflict detection and human-in-the-loop approval for critical actions.

## Architecture

```
User Query
    │
    ▼
┌─────────────────────────────────────────────────┐
│              FastAPI Backend                     │
│                                                 │
│  POST /query → Runner → LangGraph Graph         │
│                              │                  │
│              ┌───────────────┼─────────────┐    │
│              ▼               ▼             ▼    │
│          planner_node  tool_executor  synthesizer│
│              │         (ToolNode +   │           │
│              │          bind_tools)  │           │
│              └──── self_corrector ───┘           │
│                    (retry/skip/abort)            │
│                                                 │
│  SQLite Checkpointer → HITL pause/resume        │
│  ChromaDB → kb / pending / memory collections  │
│  Groq LLaMA 3.3 70B → all LLM calls (free)     │
└─────────────────────────────────────────────────┘
    │
    ▼
Streamlit Frontend
(Chat + Plan trace + Conflict resolver + Audit log)
```

## Setup

### 1. Clone and install

```bash
git clone https://github.com/Veds22/knowledge-agent
cd knowledge-agent
cp .env.example .env
```

Edit `.env` and set `GROQ_API_KEY` — get a free key at [console.groq.com](https://console.groq.com).

```bash
uv sync
```

### 2. Seed the knowledge base

```bash
uv run python scripts/ingest.py
```

This embeds all 10 markdown files in `data/kb/` into ChromaDB. Run once.

### 3. Start the backend

```bash
uv run uvicorn src.api.main:app --reload --host 0.0.0.0 --port 8000
```

### 4. Start the frontend

```bash
uv run streamlit run frontend/app.py
```

Open `http://localhost:8501`.

---

## Features

### Core (Assignment Requirements)
| Feature | Implementation |
|---|---|
| Natural language goal input | `POST /query` — plain text |
| Visible planning trace | `planner_node` produces `PlanTrace` with steps before execution |
| Tool use (≥2 tools) | `search_kb`, `create_ticket`, `escalate_issue`, `mark_resolved`, `send_instructions` |
| Self-correction on failure | `self_corrector_node` — retry with new input / skip / abort |
| Structured output | `AgentResponse` JSON with plan, answer, action, confidence, step counts |

### Bonus
| Feature | Implementation |
|---|---|
| Human-in-the-loop | `interrupt_before=["hitl_approval"]` — graph pauses, resumes via `POST /approve` |
| Long-term memory | `memory_collection` in ChromaDB — past Q&A retrieved as context |
| Audit log | Append-only `audit_log.jsonl` — every action recorded |
| Parallel actions | `asyncio.gather()` in dispatcher |
| Conflict-aware doc upload | Upload pipeline: chunk → embed → parallel conflict scan → user resolution |
| Real-time upload progress | SSE stream on `GET /jobs/{job_id}/status` |

---

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/query` | Submit a query to the agent |
| `POST` | `/approve` | Approve or reject a pending critical action |
| `POST` | `/upload` | Upload a new document to the KB |
| `GET` | `/jobs/{job_id}/status` | SSE stream of upload progress |
| `POST` | `/resolve` | Resolve upload conflicts |
| `GET` | `/audit-log` | Paginated audit log |
| `GET` | `/health` | Health check |
| `GET` | `/docs` | Interactive Swagger UI |

---

## Sample Queries

```
"How do I set up VPN on macOS?"
"My VPN keeps disconnecting every 10 minutes."
"I forgot my password and my account is locked."
"What software am I allowed to install without approval?"
"We've had a company-wide network outage for the past 30 minutes."  ← triggers P1 escalation
"What do I need to do on my first day?"
"How do I set up my email on my phone?"
```

---

## Project Structure

```
knowledge-agent/
├── data/kb/              # 10 seed IT Helpdesk markdown files
├── scripts/ingest.py     # One-time KB ingestion script
├── frontend/app.py       # Streamlit UI
├── src/
│   ├── core/             # config, schemas, logger, job_store, checkpointer
│   ├── graph/            # LangGraph: state, tools, nodes, graph
│   ├── agent/            # memory, runner (graph entry point)
│   ├── actions/          # side-effect handlers + register.py
│   ├── ingestion/        # chunker, embedder, conflict detector, pipeline
│   └── api/              # FastAPI app, routes, deps
├── chroma_db/            # ChromaDB persistent storage (auto-created)
├── checkpoints.db        # LangGraph SQLite checkpoints (auto-created)
├── audit_log.jsonl       # Append-only action audit trail
└── tickets.jsonl         # Created tickets and escalation records
```

---

## Design Decisions

**LangGraph over raw loops** — gives us a proper state machine with conditional edges, built-in checkpointing for HITL, and crash recovery without building retry/resume infrastructure from scratch.

**Groq free tier** — `llama-3.3-70b-versatile` at ~500 tok/s handles three distinct LLM roles (planner, self-corrector, synthesizer) at different temperatures without hitting rate limits for demo traffic.

**SQLite checkpointer** — keeps HITL simple: `interrupt_before` pauses the graph, state persists to disk, `ainvoke(None, thread_id=...)` resumes exactly where it stopped. No Redis dependency.

**Three ChromaDB collections** — `kb_collection` (KB chunks), `pending_collection` (conflict-staged uploads), `memory_collection` (past Q&A) — kept separate to avoid contaminating retrieval with unresolved or conversational content.

**Conflict threshold 0.82** — cosine similarity above this means the chunks are semantically contradictory, not just related. Tunable via `CONFLICT_THRESHOLD` in `.env`.

## Limitations

- Confidence scores are LLM-generated (not calibrated) — treat as relative signal, not absolute probability.
- `search_kb` tool is synchronous inside `ToolNode` — the embedding call uses `asyncio.new_event_loop()` as a workaround since LangChain tools are sync-first.
- No authentication — all endpoints are open. Add OAuth2/API key middleware before production use.
- Checkpoints are per `session_id` (thread_id) — sessions sharing an ID will share state.

## What I'd Do Differently With More Time

- Replace the per-node Groq calls with a single streaming response and stream tokens to the frontend via SSE.
- Add Jev for routing decisions at conditional edges — typed `Choice` outputs with calibrated probabilities instead of LLM JSON.
- Add pytest coverage for each node with mock LLM responses.
- Containerise with Docker Compose (FastAPI + Streamlit + ChromaDB volume).
- Add PDF/DOCX parsing to the ingestion pipeline (currently markdown/txt only).