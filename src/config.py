"""Application configuration and settings."""

from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # API Keys
    anthropic_api_key: str
    supabase_url: str
    supabase_key: str  # This can be the service_role key for backend bypass
    supabase_anon_key: Optional[str] = None  # Public key for frontend

    # Model Configuration
    embedding_model: str = "all-MiniLM-L6-v2"
    llm_model: str = "claude-haiku-4-5-20251001"
    extraction_model: str = "claude-haiku-4-5-20251001"

    # Chunking Parameters
    chunk_size: int = 400  # words
    chunk_overlap: int = 50  # words

    class Config:
        """Pydantic configuration."""

        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()  # type: ignore[call-arg]
