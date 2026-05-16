"""Application settings from environment variables."""

from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings from environment variables."""

    supabase_url: str
    supabase_key: str
    supabase_anon_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    gemini_api_key: Optional[str] = None
    # tavily_api_key: Optional[str] = None
    admin_user_id: Optional[str] = None
    enable_extraction: bool = True
    enable_graph: bool = True

    class Config:
        env_file = ".env"
        case_sensitive = False
        extra = "ignore"
