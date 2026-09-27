import asyncio 
import logging
from datetime import datetime, timedelta
from uuid import uuid4
 
from src.core.config import get_settings
from src.core.schemas import ConflictItem, JobState, JobStatus


log = logging.getLogger("knowledge-agent.job_store")
 
 
class JobStoreError(Exception):
    """Raised when a JobStore operation fails."""
    
    
class JobNotFoundError(JobStoreError):
    """Raised when a job is not found in the store."""
    def __init__(self, job_id: str):
        super().__init__(f"Job '{job_id}' not found.")
        self.job_id = job_id
        
class JobStore:
    """
        In-memory job state store with async lock for concurrent safety.
        Interface is designed to be swappable to Redis without changes.
    """
    def __init__(self):
        self._jobs: dict[str, JobState] = {}
        self._lock = asyncio.Lock()
        
    async def create(self, filename: str) -> JobState:
        """Create a new job in the store."""
        job_id    = f"job_{uuid4().hex[:10]}"
        upload_id = f"upload_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:6]}"
        state     = JobState(job_id=job_id, upload_id=upload_id, filename=filename)
        
        try:
            async with self._lock:
               self._jobs[job_id] = state
            log.info("Job created: job_id=%s upload_id=%s filename=%s", job_id, upload_id, filename)
            return state   
        except Exception as exc:
            log.exception("Failed to create job for file '%s': %s", filename, exc)
            raise JobStoreError(f"Could not create job for '{filename}'.") from exc 
        
    async def get(self, job_id: str) -> JobState | None:
        try:
            async with self._lock:
                return self._jobs.get(job_id)
        except Exception as exc:
            log.exception("Failed to retrieve job '%s': %s", job_id, exc)
            return None    
        
    async def get_or_raise(self, job_id: str) -> JobState:
        job = await self.get(job_id)
        if job is None:
            log.warning("Job not found: %s", job_id)
            raise JobNotFoundError(job_id)
        return job 
    
    async def update(self, job_id: str, **kwargs) -> JobState:
        try:
            async with self._lock:
                job = self._jobs.get(job_id)
                if job is None:
                    raise JobNotFoundError(job_id)
                updated = job.model_copy(update={**kwargs, "updated_at": datetime.utcnow()})
                self._jobs[job_id] = updated
                return updated
        except JobNotFoundError:
            raise
        except Exception as exc:
            log.exception("Failed to update job '%s': %s", job_id, exc)
            raise JobStoreError(f"Could not update job '{job_id}'.") from exc
    
    async def set_status(
        self,
        job_id:   str,
        status:   JobStatus,
        progress: int | None = None,
    ) -> None:
        kwargs: dict = {"status": status}
        if progress is not None:
            if not (0 <= progress <= 100):
                log.warning("Invalid progress value %d for job %s — clamping.", progress, job_id)
                progress = max(0, min(100, progress))
            kwargs["progress"] = progress
        try:
            await self.update(job_id, **kwargs)
            log.debug("Job %s → status=%s progress=%s", job_id, status, progress)
        except JobNotFoundError:
            log.error("Cannot set status: job '%s' not found.", job_id)

    async def add_conflicts(self, job_id: str, conflicts: list[ConflictItem]) -> None:
        if not conflicts:
            return
        try:
            async with self._lock:
                job = self._jobs.get(job_id)
                if job is None:
                    raise JobNotFoundError(job_id)
                merged = list(job.conflicts) + conflicts
                self._jobs[job_id] = job.model_copy(
                    update={"conflicts": merged, "updated_at": datetime.utcnow()}
                )
            log.info("Added %d conflict(s) to job %s.", len(conflicts), job_id)
        except JobNotFoundError:
            log.error("Cannot add conflicts: job '%s' not found.", job_id)
        except Exception as exc:
            log.exception("Failed to add conflicts to job '%s': %s", job_id, exc)
            raise JobStoreError(f"Could not add conflicts to job '{job_id}'.") from exc
        
    async def set_error(self, job_id: str, error: str) -> None:
        try:
            await self.update(job_id, status=JobStatus.failed, error=error)
            log.error("Job %s marked as failed: %s", job_id, error)
        except JobNotFoundError:
            log.error("Cannot mark error: job '%s' not found. Original error: %s", job_id, error)
 
    async def expire_old_jobs(self) -> int:
        """Remove jobs older than JOB_TTL_SECONDS. Returns count removed."""
        settings  = get_settings()
        cutoff    = datetime.utcnow() - timedelta(seconds=settings.job_ttl_seconds)
        to_delete = []
        try:
            async with self._lock:
                for job_id, job in self._jobs.items():
                    if job.created_at < cutoff:
                        to_delete.append(job_id)
                for job_id in to_delete:
                    del self._jobs[job_id]
            if to_delete:
                log.info("Expired %d stale job(s).", len(to_delete))
            return len(to_delete)
        except Exception as exc:
            log.exception("Error during job expiry: %s", exc)
            return 0
    
    async def all(self) -> list[JobState]:
        try:
            async with self._lock:
                return list(self._jobs.values())
        except Exception as exc:
            log.exception("Failed to list all jobs: %s", exc)
            return []
        
    
### Singleton ###
 
_job_store: JobStore | None = None
 
 
def init_job_store() -> JobStore:
    global _job_store
    _job_store = JobStore()
    log.info("JobStore initialised.")
    return _job_store
 
 
def get_job_store() -> JobStore:
    if _job_store is None:
        raise RuntimeError(
            "JobStore has not been initialised. "
            "Ensure init_job_store() is called in the FastAPI lifespan."
        )
    return _job_store