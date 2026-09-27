"""
Streamlit frontend for the Autonomous Knowledge Execution Agent.
Tabs: Chat | Upload KB | Audit Log
"""
import json
import time
from datetime import datetime

import requests
import streamlit as st

API = "http://localhost:8000"

st.set_page_config(
    page_title  = "IT Helpdesk Agent",
    page_icon   = "🤖",
    layout      = "wide",
    initial_sidebar_state = "expanded",
)

# ── Session state defaults ────────────────────────────────────────────────────
if "session_id"      not in st.session_state: st.session_state.session_id      = f"sess_{int(time.time())}"
if "messages"        not in st.session_state: st.session_state.messages        = []
if "pending_action"  not in st.session_state: st.session_state.pending_action  = None   # action_id awaiting approval
if "last_plan"       not in st.session_state: st.session_state.last_plan       = None


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("🤖 IT Helpdesk Agent")
    st.caption("Autonomous Knowledge Execution Agent")
    st.divider()

    st.markdown("**Session**")
    st.code(st.session_state.session_id, language=None)
    if st.button("🔄 New Session", use_container_width=True):
        st.session_state.session_id     = f"sess_{int(time.time())}"
        st.session_state.messages       = []
        st.session_state.pending_action = None
        st.session_state.last_plan      = None
        st.rerun()

    st.divider()
    st.markdown("**Sample Queries**")
    samples = [
        "How do I set up VPN on macOS?",
        "My VPN keeps disconnecting.",
        "I forgot my password and am locked out.",
        "What software can I install without approval?",
        "Company-wide network outage for 30 minutes.",
        "What should I do on my first day?",
    ]
    for s in samples:
        if st.button(s, use_container_width=True, key=f"sample_{s[:20]}"):
            st.session_state._prefill = s

    st.divider()
    try:
        r = requests.get(f"{API}/health", timeout=2)
        if r.status_code == 200:
            st.success("● API online", icon="✅")
        else:
            st.error("● API error")
    except Exception:
        st.error("● API offline — start the FastAPI server")


# ── Tabs ──────────────────────────────────────────────────────────────────────
tab_chat, tab_upload, tab_audit = st.tabs(["💬 Chat", "📁 Upload Document", "📋 Audit Log"])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — CHAT
# ══════════════════════════════════════════════════════════════════════════════
with tab_chat:

    # Approval gate banner (shown when a critical action is pending)
    if st.session_state.pending_action:
        st.warning(
            "⚠️ **Critical Action Pending Approval**\n\n"
            "The agent wants to escalate this issue to senior IT. "
            "Please review and approve or reject below.",
            icon="🚨",
        )
        col_approve, col_reject = st.columns(2)
        with col_approve:
            if st.button("✅ Approve Escalation", type="primary", use_container_width=True):
                with st.spinner("Resuming agent…"):
                    try:
                        r = requests.post(f"{API}/approve", json={
                            "action_id": st.session_state.pending_action,
                            "approved":  True,
                        }, timeout=60)
                        if r.status_code == 200:
                            data = r.json()
                            st.session_state.messages.append({
                                "role":    "assistant",
                                "content": data.get("answer", "Escalation executed."),
                                "data":    data,
                            })
                            st.session_state.pending_action = None
                            st.rerun()
                        else:
                            st.error(f"Approval failed: {r.json().get('detail', {}).get('message', r.text)}")
                    except Exception as e:
                        st.error(f"Could not reach API: {e}")
        with col_reject:
            if st.button("❌ Reject", use_container_width=True):
                with st.spinner("Cancelling…"):
                    try:
                        r = requests.post(f"{API}/approve", json={
                            "action_id": st.session_state.pending_action,
                            "approved":  False,
                        }, timeout=30)
                        st.session_state.messages.append({
                            "role":    "assistant",
                            "content": "Escalation cancelled — no action taken.",
                            "data":    {},
                        })
                        st.session_state.pending_action = None
                        st.rerun()
                    except Exception as e:
                        st.error(f"Could not reach API: {e}")
        st.divider()

    # Chat history
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

            # Show plan trace for assistant messages
            if msg["role"] == "assistant" and msg.get("data"):
                data = msg["data"]
                plan = data.get("plan")
                if plan and plan.get("steps"):
                    with st.expander("🗺️ Planning Trace", expanded=False):
                        st.markdown(f"**Goal:** {plan.get('goal', '')}")
                        st.markdown(f"**Reasoning:** {plan.get('reasoning', '')}")
                        st.divider()
                        for step in plan["steps"]:
                            status_icon = {
                                "done":    "✅",
                                "failed":  "❌",
                                "skipped": "⏭️",
                                "running": "⏳",
                                "pending": "⏸️",
                            }.get(step.get("status", ""), "❓")
                            st.markdown(
                                f"{status_icon} **Step {step['step_number']}** — `{step['tool']}`\n\n"
                                f"{step['description']}"
                            )
                            if step.get("result"):
                                st.caption(f"Result: {step['result'][:200]}")
                            if step.get("error"):
                                st.caption(f"⚠️ Error: {step['error']}")
                            if step.get("correction"):
                                st.caption(f"🔧 Correction: {step['correction']}")

                action_result = data.get("action_result", {})
                cols = st.columns(3)
                cols[0].metric("Action", action_result.get("action", "—"))
                cols[1].metric("Confidence", f"{data.get('confidence', 0):.0%}")
                cols[2].metric(
                    "Steps",
                    f"{data.get('completed_steps', 0)}/{data.get('total_steps', 0)} done"
                    + (f" · {data.get('failed_steps', 0)} failed" if data.get("failed_steps") else ""),
                )

    # Prefill from sidebar sample click
    prefill = st.session_state.pop("_prefill", "")

    # Chat input
    user_input = st.chat_input("Ask the IT Helpdesk agent…") or prefill
    if user_input and not st.session_state.pending_action:
        st.session_state.messages.append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.markdown(user_input)

        with st.chat_message("assistant"):
            with st.spinner("Agent thinking…"):
                try:
                    r = requests.post(f"{API}/query", json={
                        "query":      user_input,
                        "session_id": st.session_state.session_id,
                    }, timeout=120)

                    if r.status_code == 200:
                        data           = r.json()
                        answer         = data.get("answer", "No answer produced.")
                        action_result  = data.get("action_result", {})
                        action_status  = action_result.get("status", "")

                        st.markdown(answer)

                        # HITL interrupt detected
                        if action_status == "pending_approval":
                            st.session_state.pending_action = st.session_state.session_id
                            st.warning("⚠️ Critical action requires your approval — see banner above.")

                        st.session_state.messages.append({
                            "role":    "assistant",
                            "content": answer,
                            "data":    data,
                        })
                        st.rerun()

                    else:
                        detail = r.json().get("detail", {})
                        err    = detail.get("message", r.text) if isinstance(detail, dict) else str(detail)
                        st.error(f"Agent error: {err}")

                except requests.exceptions.ConnectionError:
                    st.error("Cannot reach the API. Is `uvicorn src.api.main:app` running?")
                except requests.exceptions.Timeout:
                    st.error("Request timed out. The agent may be processing a complex query — try again.")
                except Exception as e:
                    st.error(f"Unexpected error: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — UPLOAD DOCUMENT
# ══════════════════════════════════════════════════════════════════════════════
with tab_upload:
    st.header("📁 Upload Document to Knowledge Base")
    st.caption("Upload a Markdown (.md) or plain text (.txt) file. The agent will detect conflicts with existing KB content and ask you to resolve them before ingestion.")

    uploaded = st.file_uploader("Choose a file", type=["md", "txt"])

    if uploaded:
        if st.button("Upload & Process", type="primary"):
            with st.spinner("Uploading…"):
                try:
                    r = requests.post(
                        f"{API}/upload",
                        files={"file": (uploaded.name, uploaded.getvalue(), "text/plain")},
                        timeout=30,
                    )
                    if r.status_code == 202:
                        job_id = r.json()["job_id"]
                        st.success(f"Upload accepted. Job ID: `{job_id}`")

                        # Poll SSE via regular polling (Streamlit doesn't support SSE natively)
                        progress_bar = st.progress(0, text="Starting…")
                        status_text  = st.empty()
                        conflicts_placeholder = st.empty()
                        job_done = False

                        for _ in range(120):   # max 60 seconds polling
                            time.sleep(0.5)
                            try:
                                jr = requests.get(f"{API}/jobs/{job_id}/status", stream=True, timeout=5)
                                for line in jr.iter_lines():
                                    if line and line.startswith(b"data: "):
                                        job = json.loads(line[6:])
                                        pct    = job.get("progress", 0)
                                        status = job.get("status", "")
                                        progress_bar.progress(pct / 100, text=f"{status} ({pct}%)")
                                        status_text.markdown(f"**Status:** `{status}`")

                                        if status == "completed":
                                            st.success("✅ Document ingested into knowledge base successfully!")
                                            job_done = True
                                            break

                                        if status == "conflicted":
                                            conflicts = job.get("conflicts", [])
                                            conflicts_placeholder.warning(
                                                f"⚠️ {len(conflicts)} conflict(s) detected — resolve below."
                                            )
                                            st.session_state["_conflicts"] = conflicts
                                            st.session_state["_upload_id"] = job.get("upload_id", "")
                                            job_done = True
                                            break

                                        if status == "failed":
                                            st.error(f"❌ Ingestion failed: {job.get('error', 'Unknown error')}")
                                            job_done = True
                                            break
                                if job_done:
                                    break
                            except Exception:
                                pass

                    else:
                        detail = r.json().get("detail", {})
                        err    = detail.get("message", r.text) if isinstance(detail, dict) else str(detail)
                        st.error(f"Upload failed: {err}")

                except requests.exceptions.ConnectionError:
                    st.error("Cannot reach the API.")
                except Exception as e:
                    st.error(f"Error: {e}")

    # ── Conflict resolution UI ─────────────────────────────────────────────────
    if st.session_state.get("_conflicts"):
        st.divider()
        st.subheader("🔀 Conflict Resolution")
        st.caption("For each conflict, choose how to resolve it before the document is added to the KB.")

        conflicts  = st.session_state["_conflicts"]
        upload_id  = st.session_state.get("_upload_id", "")
        resolutions = []

        for i, c in enumerate(conflicts):
            with st.expander(
                f"Conflict {i+1}: `{c['chunk_id']}` — similarity {c['conflict_score']:.0%}",
                expanded=True,
            ):
                st.markdown(f"**Summary:** {c['conflict_summary']}")
                col_new, col_existing = st.columns(2)
                with col_new:
                    st.markdown("**New content (uploaded)**")
                    st.text_area("", c["new_text"], height=150, key=f"new_{i}", disabled=True)
                with col_existing:
                    st.markdown("**Existing KB content**")
                    st.text_area("", c["existing_text"], height=150, key=f"existing_{i}", disabled=True)

                choice = st.radio(
                    "Resolution",
                    ["Keep new", "Keep existing", "Merge"],
                    key=f"choice_{i}",
                    horizontal=True,
                )
                merged_text = None
                if choice == "Merge":
                    merged_text = st.text_area(
                        "Merged content (edit as needed)",
                        value=c["new_text"] + "\n\n" + c["existing_text"],
                        height=150,
                        key=f"merge_{i}",
                    )

                resolutions.append({
                    "chunk_id":    c["chunk_id"],
                    "resolution":  {"Keep new": "keep_new", "Keep existing": "keep_existing", "Merge": "merge"}[choice],
                    "merged_text": merged_text,
                })

        if st.button("Submit Resolutions", type="primary"):
            with st.spinner("Applying resolutions…"):
                try:
                    r = requests.post(f"{API}/resolve", json={
                        "upload_id":   upload_id,
                        "resolutions": resolutions,
                    }, timeout=60)
                    if r.status_code == 200:
                        result = r.json()
                        st.success(result.get("message", "Resolved."))
                        del st.session_state["_conflicts"]
                        del st.session_state["_upload_id"]
                        st.rerun()
                    else:
                        detail = r.json().get("detail", {})
                        err    = detail.get("message", r.text) if isinstance(detail, dict) else str(detail)
                        st.error(f"Resolution failed: {err}")
                except Exception as e:
                    st.error(f"Error: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — AUDIT LOG
# ══════════════════════════════════════════════════════════════════════════════
with tab_audit:
    st.header("📋 Audit Log")

    col_filter, col_size, col_refresh = st.columns([2, 1, 1])
    with col_filter:
        action_filter = st.selectbox(
            "Filter by action",
            ["All", "search_kb", "create_ticket", "escalate_issue", "mark_resolved", "send_instructions"],
        )
    with col_size:
        page_size = st.selectbox("Per page", [10, 20, 50], index=1)
    with col_refresh:
        st.markdown("<br>", unsafe_allow_html=True)
        refresh = st.button("🔄 Refresh", use_container_width=True)

    if refresh or True:
        params = {"page": 1, "size": page_size}
        if action_filter != "All":
            params["action"] = action_filter
        try:
            r = requests.get(f"{API}/audit-log", params=params, timeout=10)
            if r.status_code == 200:
                log_data = r.json()
                entries  = log_data.get("entries", [])
                total    = log_data.get("total", 0)

                st.caption(f"{total} total entries")

                if not entries:
                    st.info("No audit entries yet. Submit a query to see logs here.")
                else:
                    for entry in entries:
                        ts     = entry.get("timestamp", "")[:19].replace("T", " ")
                        action = entry.get("action", "")
                        status = entry.get("status", "")
                        conf   = entry.get("confidence", 0)
                        query  = entry.get("query", "")[:80]

                        status_icon = {
                            "executed":         "✅",
                            "pending_approval":  "⏳",
                            "cancelled":         "🚫",
                            "failed":            "❌",
                        }.get(status, "❓")

                        with st.expander(f"{status_icon} `{action}` — {ts} — {query}…"):
                            cols = st.columns(3)
                            cols[0].metric("Action", action)
                            cols[1].metric("Status", status)
                            cols[2].metric("Confidence", f"{conf:.0%}")
                            st.markdown(f"**Query:** {entry.get('query', '')}")
                            st.markdown(f"**Reasoning:** {entry.get('reasoning', '')}")
                            if entry.get("approved_by"):
                                st.markdown(f"**Approved by:** {entry['approved_by']}")
            else:
                st.error(f"Could not load audit log: {r.status_code}")
        except requests.exceptions.ConnectionError:
            st.error("Cannot reach the API.")
        except Exception as e:
            st.error(f"Error loading audit log: {e}")