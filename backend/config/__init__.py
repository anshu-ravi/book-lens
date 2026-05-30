"""Configuration module for BookLens."""

from backend.config.models import ModelConfig
from backend.config.settings import Settings

settings = Settings()

__all__ = ["ModelConfig", "Settings", "settings"]
