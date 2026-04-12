"""Vector store abstraction layer."""

from src.vector_store.base import SearchResult, VectorStore
from src.vector_store.qdrant_store import QdrantVectorStore

__all__ = ["VectorStore", "SearchResult", "QdrantVectorStore"]
