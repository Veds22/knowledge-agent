from __future__ import annotations

import chromadb
from src.core.job_store import JobStore, get_job_store
from src.ingestion.embedder import SentenceTransformer, get_embedder

_chroma_client:      chromadb.PersistentClient | None = None
_kb_collection:      chromadb.Collection | None       = None
_pending_collection: chromadb.Collection | None       = None
_memory_collection:  chromadb.Collection | None       = None


def init_chroma(path: str) -> chromadb.PersistentClient:
    global _chroma_client, _kb_collection, _pending_collection, _memory_collection
    _chroma_client      = chromadb.PersistentClient(path=path)
    _kb_collection      = _chroma_client.get_or_create_collection(
        "kb_collection",      metadata={"hnsw:space": "l2"},
    )
    _pending_collection = _chroma_client.get_or_create_collection(
        "pending_collection", metadata={"hnsw:space": "l2"},
    )
    _memory_collection  = _chroma_client.get_or_create_collection(
        "memory_collection",  metadata={"hnsw:space": "l2"},
    )
    return _chroma_client


def get_kb_collection() -> chromadb.Collection:
    if _kb_collection is None:
        raise RuntimeError("ChromaDB not initialised. Call init_chroma() in lifespan.")
    return _kb_collection

def get_pending_collection() -> chromadb.Collection:
    if _pending_collection is None:
        raise RuntimeError("ChromaDB not initialised.")
    return _pending_collection

def get_memory_collection() -> chromadb.Collection:
    if _memory_collection is None:
        raise RuntimeError("ChromaDB not initialised.")
    return _memory_collection


# FastAPI Depends functions
def dep_kb()      -> chromadb.Collection:    return get_kb_collection()
def dep_pending() -> chromadb.Collection:    return get_pending_collection()
def dep_memory()  -> chromadb.Collection:    return get_memory_collection()
def dep_jobs()    -> JobStore:               return get_job_store()
def dep_embedder() -> SentenceTransformer:   return get_embedder()