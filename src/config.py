"""Application configuration and settings."""

import tomllib
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


def _load_toml() -> dict:
    """Load config.toml from the project root (next to pyproject.toml)."""
    path = Path(__file__).parent.parent / "config.toml"
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except FileNotFoundError:
        return {}


_toml = _load_toml()
_llm = _toml.get("llm", {})
_provider = _llm.get("provider", "anthropic")
_provider_cfg = _llm.get(_provider, {})


class Settings(BaseSettings):
    """Application settings.

    LLM provider and model are read from config.toml.
    API keys and infrastructure settings come from .env.
    Env vars override TOML values (pydantic-settings precedence).
    """

    # Infrastructure
    supabase_url: str
    supabase_key: str
    supabase_anon_key: Optional[str] = None

    # API keys (stay in .env, never in config.toml)
    anthropic_api_key: str = ""
    gemini_api_key: str = ""
    google_api_key: Optional[str] = None  # Legacy support

    # LLM provider — derived from config.toml, overridable by env var
    llm_provider: str = _provider
    llm_model: str = _provider_cfg.get("model", "claude-haiku-4-5-20251001")
    extraction_model: str = _provider_cfg.get("extraction_model", "claude-haiku-4-5-20251001")

    # Embeddings + chunking (unchanged)
    embedding_model: str = "all-MiniLM-L6-v2"
    chunk_size: int = 400
    chunk_overlap: int = 50

    # Admin features
    admin_user_id: Optional[str] = None

    # Feature flags
    enable_extraction: bool = False  # Extract entities, summaries, character arcs, etc.
    enable_graph: bool = False  # Build and serve knowledge graphs

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="allow",  # Allow extra fields from .env
    )


settings = Settings()
