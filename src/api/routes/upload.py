from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import aiofiles
import chromadb
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse

from src.api.deps import dep_kb, dep_pending, dep_jobs
from src.core.config import get_settings
from src.core.job_store import JobStore
from src.core.schemas import JobState, UploadResponse
from src.ingestion.pipeline import run_ingestion_pipeline

router = APIRouter()
log    = logging.getLogger("knowledge-agent.routes.upload")

ALLOWED_EXTENSIONS = {".md", ".txt"}
MAX_FILE_SIZE_MB   = 10
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024


@router.post("/upload", response_model=UploadResponse, status_code=202)
async def upload_document(
    background_tasks:   BackgroundTasks,
    file:               UploadFile      = File(...),
    kb_collection:      chromadb.Collection = Depends(dep_kb),
    pending_collection: chromadb.Collection = Depends(dep_pending),
    job_store:          JobStore            = Depends(dep_jobs),
):
    # ── Validate filename ─────────────────────────────────────────────────────
    if not file.filename:
        raise HTTPException(
            status_code=422,
            detail={
                "error":   "missing_filename",
                "message": "The uploaded file has no filename. Please upload a named file.",
            },
        )

    suffix = Path(file.filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=422,
            detail={
                "error":   "unsupported_file_type",
                "message": (
                    f"'{suffix}' files are not supported. "
                    f"Please upload a Markdown (.md) or plain text (.txt) file."
                ),
            },
        )

    # ── Read and size-check ───────────────────────────────────────────────────
    try:
        content = await file.read()
    except Exception as exc:
        log.error("Failed to read uploaded file '%s': %s", file.filename, exc)
        raise HTTPException(
            status_code=400,
            detail={
                "error":   "file_read_error",
                "message": "The file could not be read. It may be corrupted. Please try again.",
            },
        )

    if len(content) == 0:
        raise HTTPException(
            status_code=422,
            detail={
                "error":   "empty_file",
                "message": f"'{file.filename}' is empty. Please upload a file with content.",
            },
        )

    if len(content) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail={
                "error":   "file_too_large",
                "message": (
                    f"'{file.filename}' exceeds the {MAX_FILE_SIZE_MB} MB size limit "
                    f"({len(content) / 1024 / 1024:.1f} MB uploaded). "
                    f"Please split the file and upload in parts."
                ),
            },
        )

    settings = get_settings()

    # ── Create job ────────────────────────────────────────────────────────────
    try:
        job = await job_store.create(filename=file.filename)
    except Exception as exc:
        log.exception("Failed to create job for '%s': %s", file.filename, exc)
        raise HTTPException(
            status_code=500,
            detail={
                "error":   "job_creation_failed",
                "message": "Could not initialise the upload job. Please try again.",
            },
        )

    # ── Save file to disk ─────────────────────────────────────────────────────
    dest = settings.upload_dir / f"{job.upload_id}{suffix}"
    try:
        async with aiofiles.open(dest, "wb") as f_out:
            await f_out.write(content)
        log.info(
            "File saved: '%s' → %s (%.1f KB, job=%s)",
            file.filename, dest, len(content) / 1024, job.job_id,
        )
    except OSError as exc:
        log.error("Failed to save uploaded file to '%s': %s", dest, exc)
        await job_store.set_error(job.job_id, "File could not be saved to disk.")
        raise HTTPException(
            status_code=500,
            detail={
                "error":   "file_save_error",
                "message": "The file was received but could not be saved. Please try again.",
            },
        )

    # ── Queue background pipeline ─────────────────────────────────────────────
    background_tasks.add_task(
        run_ingestion_pipeline,
        file_path          = dest,
        job_id             = job.job_id,
        job_store          = job_store,
        kb_collection      = kb_collection,
        pending_collection = pending_collection,
    )

    log.info("Pipeline queued for job=%s file='%s'.", job.job_id, file.filename)
    return UploadResponse(job_id=job.job_id)


@router.get("/jobs/{job_id}/status")
async def job_status(
    job_id:    str,
    job_store: JobStore = Depends(dep_jobs),
):
    """
    SSE stream of upload job progress.
    Client connects once and receives events until status is terminal.
    """
    # Verify job exists before opening the stream
    job = await job_store.get(job_id)
    if job is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error":   "job_not_found",
                "message": f"Job '{job_id}' does not exist or has expired.",
            },
        )

    async def event_stream():
        terminal = {"completed", "conflicted", "failed"}
        consecutive_errors = 0

        while True:
            try:
                job: JobState | None = await job_store.get(job_id)

                if job is None:
                    yield f"data: {json.dumps({'error': 'job_not_found', 'message': f'Job {job_id} has expired.'})}\n\n"
                    break

                yield f"data: {job.model_dump_json()}\n\n"
                consecutive_errors = 0

                if job.status in terminal:
                    log.debug("SSE stream closing for job=%s (status=%s).", job_id, job.status)
                    break

            except Exception as exc:
                consecutive_errors += 1
                log.warning(
                    "SSE stream error for job=%s (attempt %d): %s",
                    job_id, consecutive_errors, exc,
                )
                if consecutive_errors >= 3:
                    yield f"data: {json.dumps({'error': 'stream_error', 'message': 'Job status stream failed repeatedly. Please refresh.'})}\n\n"
                    break

            await asyncio.sleep(0.5)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # disable nginx buffering
        },
    )