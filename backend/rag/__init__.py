"""RAG pipeline — hierarchical chunking, pgvector retrieval, and EPUB ingestion."""

from backend.rag.ingest import ingest_book
from backend.rag.node_store import NodeStore
from backend.rag.retriever import retrieve

__all__ = ["ingest_book", "NodeStore", "retrieve"]
