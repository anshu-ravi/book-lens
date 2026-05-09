"""Knowledge extraction and query engine."""

from src.knowledge.deduplicator import Deduplicator
from src.knowledge.embedder import Embedder
from src.knowledge.extractor import Extractor
from src.knowledge.ingestor import Ingestor
from src.knowledge.neo4j_client import close_driver, get_driver
from src.knowledge.pipeline import KnowledgePipeline
from src.knowledge.query import KnowledgeQueryEngine

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
