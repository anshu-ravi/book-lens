"""Query engine: spoiler-safe retrieval and prompt assembly."""

from src.query.prompt_builder import build_prompt, build_reading_summary
from src.query.retriever import retrieve_chunks

__all__ = [
    "retrieve_chunks",
    "build_reading_summary",
    "build_prompt",
]
