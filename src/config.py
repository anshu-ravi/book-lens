"""Application configuration and settings."""

from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # API Keys
    anthropic_api_key: str
    qdrant_url: str
    qdrant_api_key: str

    # Application Paths
    library_path: Path = Path("./library.json")
    upload_dir: Path = Path("./uploads")

    # Model Configuration
    embedding_model: str = "all-MiniLM-L6-v2"
    llm_model: str = "claude-haiku-4-5"

    # Chunking Parameters
    chunk_size: int = 400  # words
    chunk_overlap: int = 50  # words

    class Config:
        """Pydantic configuration."""

        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()  # type: ignore[call-arg]
