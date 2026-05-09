"""LLM model configuration for different purposes."""

import os
from typing import Optional


class ModelConfig:
    """Centralized model configuration for different use cases."""

    # BRONZE stage: Extract structured knowledge from chapter text
    EXTRACTION_MODEL: str = os.environ.get(
        "MODEL_EXTRACTION",
        "gemini-3.1-flash-lite",
    )

    # SILVER/GOLD: Knowledge graph Q&A
    QA_GENERATION_MODEL: str = os.environ.get(
        "MODEL_QA_GENERATION",
        "gemini-3.1-flash-lite",
    )

    # Series lookup: Determine if a book is part of a series
    SERIES_LOOKUP_MODEL: str = os.environ.get(
        "MODEL_SERIES_LOOKUP",
        "gemini-3.1-flash-lite",
    )

    # Default fallback for any other LLM tasks
    DEFAULT_MODEL: str = os.environ.get(
        "MODEL_DEFAULT",
        "gemini-3.1-flash-lite",
    )

    @classmethod
    def get_model(cls, purpose: str) -> str:
        """Get the model for a specific purpose.

        Args:
            purpose: One of: extraction, qa, series_lookup, default

        Returns:
            Model name string.

        Raises:
            ValueError: If purpose is not recognized.
        """
        purpose_lower = purpose.lower().strip()

        if purpose_lower == "extraction":
            return cls.EXTRACTION_MODEL
        elif purpose_lower == "qa":
            return cls.QA_GENERATION_MODEL
        elif purpose_lower == "series_lookup":
            return cls.SERIES_LOOKUP_MODEL
        elif purpose_lower == "default":
            return cls.DEFAULT_MODEL
        else:
            raise ValueError(
                f"Unknown purpose: {purpose}. "
                f"Valid options: extraction, qa, series_lookup, default"
            )

    @classmethod
    def set_model(cls, purpose: str, model: str) -> None:
        """Dynamically set a model for a specific purpose.

        Useful for testing or runtime configuration.

        Args:
            purpose: One of: extraction, qa, series_lookup, default
            model: Model name string.

        Raises:
            ValueError: If purpose is not recognized.
        """
        purpose_lower = purpose.lower().strip()

        if purpose_lower == "extraction":
            cls.EXTRACTION_MODEL = model
        elif purpose_lower == "qa":
            cls.QA_GENERATION_MODEL = model
        elif purpose_lower == "series_lookup":
            cls.SERIES_LOOKUP_MODEL = model
        elif purpose_lower == "default":
            cls.DEFAULT_MODEL = model
        else:
            raise ValueError(
                f"Unknown purpose: {purpose}. "
                f"Valid options: extraction, qa, series_lookup, default"
            )

    @classmethod
    def to_dict(cls) -> dict[str, str]:
        """Return current configuration as dict.

        Returns:
            Dict of purpose -> model mappings.
        """
        return {
            "extraction": cls.EXTRACTION_MODEL,
            "qa": cls.QA_GENERATION_MODEL,
            "series_lookup": cls.SERIES_LOOKUP_MODEL,
            "default": cls.DEFAULT_MODEL,
        }
