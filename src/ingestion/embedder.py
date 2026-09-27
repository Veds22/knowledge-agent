import asyncio
import logging
 
from sentence_transformers import SentenceTransformer
 
from src.core.config import get_settings

log = logging.getLogger("knowledge-agent.embedder")

_model: SentenceTransformer | None = None

class EmbedderNotLoadedError(Exception):
    """Raised when the embedder model is not loaded."""
    def __init__(self):
        super().__init__(
            "Embedding model has not been loaded. "
            "Ensure load_embedder() is called during application startup."
        )
    
class EmbeddingError(Exception):
    """Raised when embedding fails for recoverable reasons."""
 
 
def load_embedder() -> SentenceTransformer:
    """
        Load the sentence-transformers model into memory.
        Called once in FastAPI lifespan — subsequent calls are no-ops.
        Raises RuntimeError with a clear message if the model name is invalid.
    """
    global _model
    
    if _model is not None:
        log.debug("Embedder model already loaded, skipping.")
        return _model

    settings = get_settings()
    log.info("Loading embedding model: %s ... ", settings.embed_model)
    try:
        _model = SentenceTransformer(settings.embed_model)
        log.info("Embedding model %s loaded successfully.", settings.embed_model)
        return _model
    except Exception as exc:
        log.critical(
            "Failed to load embedding model '%s'. "
            "Check EMBED_MODEL in .env and ensure sentence-transformers is installed. Error: %s",
            settings.embed_model, exc,
        )
        raise RuntimeError(
            f"Could not load embedding model '{settings.embed_model}'. "
            f"Verify the model name and your internet connection."
        ) from exc
        

def get_embedder() -> SentenceTransformer:
    if _model is None:
        raise EmbedderNotLoadedError()
    return _model
 
 
async def embed_batch(texts: list[str]) -> list[list[float]]:
    """
        Embed a batch of texts asynchronously.
        Processes in batches of EMBED_BATCH_SIZE for memory efficiency.
    
        Raises EmbeddingError on failure so callers can handle gracefully.
    """
    if not texts:
        log.debug("embed_batch called with empty list — returning [].")
        return []
    
    settings = get_settings()
    model    = get_embedder()
    loop     = asyncio.get_running_loop()
    
    log.debug("Embedding %d text(s) with batch_size=%d …", len(texts), settings.embed_batch_size)
    
    def _encode() -> list[list[float]]:
        vectors = model.encode(
            texts,
            batch_size=settings.embed_batch_size,
            show_progress_bar=False,
            normalize_embeddings=True,  # cosine sim == dot product after normalisation
        )
        return vectors.tolist()
    
    try:
        embeddings = await loop.run_in_executor(None, _encode)
        log.debug("Embedded %d text(s) successfully.", len(texts))
        return embeddings
    except EmbedderNotLoadedError:
        raise
    except Exception as exc:
        log.error("Embedding failed for batch of %d texts: %s", len(texts), exc)
        raise EmbeddingError(
            f"Failed to generate embeddings for {len(texts)} text(s). "
            f"The embedding model may be unavailable."
        ) from exc
        
        
async def embed_single(text: str) -> list[float]:
    """Convenience wrapper for embedding a single string."""
    if not text or not text.strip():
        log.warning("embed_single called with empty or whitespace-only text.")
        raise EmbeddingError("Cannot embed empty text.")
    results = await embed_batch([text])
    return results[0]