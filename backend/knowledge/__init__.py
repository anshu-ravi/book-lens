"""Knowledge extraction and query engine."""

from backend.knowledge.deduplicator import Deduplicator
from backend.knowledge.embedder import Embedder
from backend.knowledge.extractor import Extractor
from backend.knowledge.ingestor import Ingestor
from backend.knowledge.neo4j_client import close_driver, get_driver
from backend.knowledge.pipeline import KnowledgePipeline
from backend.knowledge.query import KnowledgeQueryEngine

__all__ = [
    "Deduplicator",
    "Embedder",
    "Extractor",
    "Ingestor",
    "KnowledgePipeline",
    "KnowledgeQueryEngine",
    "get_driver",
    "close_driver",
]
