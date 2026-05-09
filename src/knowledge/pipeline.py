"""Orchestrator for full BRONZE → SILVER → GOLD pipeline."""

from io import BytesIO
from typing import Optional

from src.ingestion.epub_parser import parse_epub
from src.knowledge.deduplicator import Deduplicator
from src.knowledge.extractor import Extractor
from src.knowledge.ingestor import Ingestor


class KnowledgePipeline:
    """Run full knowledge extraction and ingestion pipeline."""

    def __init__(self, series_id: str) -> None:
        """Initialize pipeline.

        Args:
            series_id: Series identifier.
        """
        self.series_id = series_id

    def run_extraction(
        self, epub_bytes: bytes, limit: Optional[int] = None
    ) -> None:
        """Run BRONZE stage: extract knowledge from chapters.

        Args:
            epub_bytes: EPUB file contents.
            limit: If set, only extract first N chapters.
        """
        # Parse EPUB
        parsed_chapters = parse_epub(BytesIO(epub_bytes))
        chapters = [(ch.label, ch.text) for ch in parsed_chapters]

        # Extract knowledge per chapter
        extractor = Extractor()
        for idx, (label, text) in enumerate(chapters):
            if limit and idx >= limit:
                break
            print(f"Extracting chapter {idx}: {label}")
            extractor.extract(text, self.series_id, idx, label)

    def run_deduplication(self, limit: Optional[int] = None) -> None:
        """Run SILVER stage: deduplicate characters.

        Args:
            limit: If set, only deduplicate first N chapters.
        """
        print("Running deduplication...")
        deduplicator = Deduplicator(self.series_id)
        deduplicator.run(limit=limit)

    def run_ingestion(self, limit: Optional[int] = None) -> None:
        """Run GOLD stage: ingest into Neo4j.

        Args:
            limit: If set, only ingest first N chapters.
        """
        print("Running ingestion...")
        ingestor = Ingestor(self.series_id)
        ingestor.run(limit=limit)

    def run_all(self, epub_bytes: bytes, limit: Optional[int] = None) -> None:
        """Run full pipeline: BRONZE → SILVER → GOLD.

        Args:
            epub_bytes: EPUB file contents.
            limit: If set, only process first N chapters.
        """
        print(f"Starting knowledge pipeline for {self.series_id}")
        self.run_extraction(epub_bytes, limit=limit)
        self.run_deduplication(limit=limit)
        self.run_ingestion(limit=limit)
        print(f"Pipeline complete for {self.series_id}")
