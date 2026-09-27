from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from src.api.deps import init_chroma, get_kb_collection
from src.api.routes import audit, query, resolve, upload
from src.api.routes.approve import router as approve_router
from src.core.checkpointer import init_checkpointer, close_checkpointer
from src.core.config import configure_langsmith, get_settings
from src.core.job_store import init_job_store
from src.graph.graph import init_graph
from src.graph.tools import init_tools
from src.ingestion.embedder import load_embedder

log = logging.getLogger("knowledge-agent.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_langsmith(settings)
    settings.ensure_dirs()

    log.info("══════════════════════════════════════")
    log.info("  Knowledge Agent — starting up")
    log.info("══════════════════════════════════════")

    try:
        load_embedder()
    except RuntimeError as exc:
        log.critical("Embedding model failed: %s", exc); sys.exit(1)

    try:
        init_chroma(str(settings.chroma_path))
    except Exception as exc:
        log.critical("ChromaDB failed: %s", exc); sys.exit(1)

    try:
        init_job_store()
    except Exception as exc:
        log.critical("JobStore failed: %s", exc); sys.exit(1)

    try:
        await init_checkpointer()
    except RuntimeError as exc:
        log.critical("Checkpointer failed: %s", exc); sys.exit(1)
    try:
        init_tools(get_kb_collection())
        log.info("Tools initialised.")
    except Exception as exc:
        log.critical("Tool init failed: %s", exc); sys.exit(1)

    try:
        init_graph()
        log.info("LangGraph agent compiled with SQLite checkpointer.")
    except Exception as exc:
        log.critical("Graph build failed: %s", exc); sys.exit(1)

    log.info("══════════════════════════════════════")
    log.info("  Ready → http://%s:%d", settings.host, settings.port)
    log.info("══════════════════════════════════════")
    try:
        yield
    finally:
        await close_checkpointer()
        log.info("Shutting down.")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Autonomous Knowledge Execution Agent", version="0.1.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(Exception)
    async def global_handler(request: Request, exc: Exception):
        log.exception("Unhandled exception %s %s: %s", request.method, request.url.path, exc)
        return JSONResponse(status_code=500, content={
            "error": "internal_server_error",
            "message": "An unexpected error occurred. Please try again.",
        })

    app.include_router(query.router,   tags=["Agent"])
    app.include_router(approve_router, tags=["Agent"])
    app.include_router(upload.router,  tags=["Ingestion"])
    app.include_router(resolve.router, tags=["Ingestion"])
    app.include_router(audit.router,   tags=["Audit"])

    app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
    return app


app = create_app()