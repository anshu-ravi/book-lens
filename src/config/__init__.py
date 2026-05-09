"""Configuration module for BookLens."""

from src.config.models import ModelConfig
from src.config.settings import Settings

settings = Settings()

__all__ = ["ModelConfig", "Settings", "settings"]
