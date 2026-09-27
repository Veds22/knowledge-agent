import asyncio
import json
import logging
import sys
from pathlib import Path
 
import aiofiles
 
from src.core.config import get_settings
from src.core.schemas import AuditEntry


def setup_logging() -> None:
    """
        Configure root logger with structured format. Call once at start up.
    """
    
    fmt = "%(asctime)s | %(levelname)-8s | %(name)-35s | %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"
    
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(fmt, datefmt))
    
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    
    for noisy in ("chromadb", "httpx", "httpcore", "sentence_transformers", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
 
    if not root.handlers:
        root.addHandler(handler)
        
setup_logging()
log = logging.getLogger("knowledge-agent.logger")


_write_lock = asyncio.Lock()

async def append_audit(entry: AuditEntry) -> None:
    """
        Async, lock-guarded append to audit_log.jsonl. 
        Append an audit entry to the audit log file in JSONL format.
    """
    
    settings = get_settings()
    line = entry.model_dump_json() + "\n"
    
    try:
        async with _write_lock:
            async with aiofiles.open(settings.audit_log_path, mode="a", encoding="utf-8") as f:
                await f.write(line)
        log.debug("Audit entry written: action=%s session=%s", entry.action, entry.session_id)
    except OSError as e:
        log.error(
            f"Failed to write audit log entry [action={entry.action} session={entry.session_id}]: {e}",
        )
        
    except Exception as e:
        log.exception("Unexpected error writing audit log: %s", e)
        

async def read_audit_log(
    page: int = 1,
    size: int = 20,
    action_filter: str | None = None,
) -> tuple[int, list[AuditEntry]]:
    """
        Read and paginate audit_log.jsonl.
        Skips malformed lines with a warning rather than failing entirely.
        Returns (total_count, page_entries).
    """
    
    settings = get_settings()
    path: Path = settings.audit_log_path 
    
    if not path.exists():
        log.warning("Audit log file does not exist: %s", path)
        return 0, []
    
    entries: list[AuditEntry] = []
    skipped = 0
    
    try:
        async with aiofiles.open(path, mode="r", encoding="utf-8") as f:
            async for line_num, line in _enumerate_lines(f):
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    entry = AuditEntry(**data)
                    
                    if action_filter and entry.action != action_filter:
                        continue
                    
                    entries.append(entry)
                except json.JSONDecodeError as exc:
                    log.warning("Skipping malformed JSON on line %d of audit log: %s", line_num, exc)
                    skipped += 1
                except Exception as exc:
                    skipped += 1
                    log.warning("Skipping invalid audit entry on line %d: %s", line_num, exc)
    except OSError as exc:
        log.error("Cannot read audit log at %s: %s", path, exc)
        return 0, []
 
    if skipped:
        log.warning("Skipped %d malformed lines in audit log.", skipped)
        
    entries.sort(key=lambda e: e.timestamp, reverse=True)
    total = len(entries)
    start = (page - 1) * size
    log.debug("Audit log read: %d total entries, returning page %d (size %d).", total, page, size)
    return total, entries[start : start + size]

async def _enumerate_lines(f):
    """Async line iterator that yields (line_number, line)."""
    n = 0
    async for line in f:
        n += 1
        yield n, line