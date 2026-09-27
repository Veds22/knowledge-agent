from functools import lru_cache
import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )
    
    # LLM Settings
    groq_api_key:str
    groq_model: str = "llama-3.3-70b-versatile"
    
    # Path Settings
    chroma_path: Path = Path("./chroma_db")
    kb_path: Path = Path("./data/kb")
    upload_dir: Path = Path("./uploads")
    audit_log_path: Path = Path("./audit_log.jsonl")
    tickets_path: Path = Path("./tickets.jsonl")
    
    # Retreival Settings
    top_k: int = 5
    max_reasoning_hops: int = 3
    
    # Ingestion Settings
    embed_batch_size: int = 64
    chunk_size: int = 300
    chunk_overlap: int = 50
    embed_model: str = "all-MiniLM-L6-v2"
    
    # Conflict Detection Settings
    conflict_threshold: float = 0.82
    pending_ttl_hours: int = 24
    
    # Jobs
    max_concurrent_jobs: int = 10
    job_ttl_seconds: int = 3600
    
    # Langgraph  Settings
    max_plan_steps: int = 6
    max_tool_retries: int = 2
    max_graph_iterations: int = 20
    min_confidence: float = 0.4
    llm_timeout_seconds: float = 90.0
    agent_timeout_seconds: float = 110.0

    # LangSmith Settings
    langsmith_tracing: bool = False
    langsmith_endpoint: str = "https://api.smith.langchain.com"
    langsmith_api_key: str | None = None
    langsmith_project: str = "knowledge-agent"
    
    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:5500"]
    
    def ensure_dirs(self) -> None:
        """Create all required directories on startup."""
        for path in [self.chroma_path, self.upload_dir, self.kb_path]:
            path.mkdir(parents=True, exist_ok=True)
           
            
@lru_cache
def get_settings() -> Settings:
    return Settings()


def configure_langsmith(settings: Settings | None = None) -> None:
    """Expose LangSmith settings to LangChain's process-level tracer."""
    settings = settings or get_settings()
    os.environ["LANGSMITH_TRACING"] = str(settings.langsmith_tracing).lower()
    os.environ["LANGSMITH_ENDPOINT"] = settings.langsmith_endpoint
    os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project

    if settings.langsmith_api_key:
        os.environ["LANGSMITH_API_KEY"] = settings.langsmith_api_key