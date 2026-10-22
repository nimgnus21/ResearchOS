"""Application settings. All secrets come from environment variables / .env — never from source."""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(BACKEND_DIR / ".env"), extra="ignore")

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/researchos"
    storage_dir: Path = BACKEND_DIR.parent / "data" / "storage"
    max_upload_mb: int = 50
    ingest_sync: bool = False
    ingest_stale_minutes: int = 30  # a 'processing' job older than this is considered abandoned  # True: process uploads inline (tests); False: background thread pool

    # Chunking
    chunk_target_chars: int = 700
    chunk_overlap_chars: int = 120

    # Embeddings: "hash" (offline lexical feature hashing) | "openai" (OpenAI-compatible /embeddings)
    embedding_provider: str = "hash"
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 384
    embedding_api_key: str | None = None
    embedding_base_url: str = "https://api.openai.com/v1"

    # LLM: "none" | "anthropic" | "openai" (OpenAI-compatible /chat/completions)
    llm_provider: str = "none"
    llm_model: str = "claude-opus-5-5"
    llm_api_key: str | None = None
    llm_base_url: str | None = None
    llm_effort: str = "medium"  # Anthropic output_config.effort
    llm_fallbacks: str = "default"  # Anthropic server-side refusal fallbacks: "default" | "off"
    llm_max_tokens: int = 16000
    llm_timeout_s: float = 300.0

    # Retrieval
    retrieval_top_k: int = 8
    retrieval_candidates: int = 30
    retrieval_min_term_coverage: float = 0.5  # share of query content terms that must appear in a chunk
    retrieval_min_vector_sim: float = 0.55  # vector similarity that alone counts as strong evidence
    retrieval_max_evidence: int = 6
    # Per-document retrieval for comparison/report sections: documents phrase the same topic
    # differently ("真正原因" vs "根本原因"), so a lower, separately configurable bar is used.
    retrieval_compare_min_term_coverage: float = 0.3


@lru_cache
def get_settings() -> Settings:
    return Settings()
