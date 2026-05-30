"""Standalone script: ingest gold layer into dev Neo4j.

Calls IngestionService directly, bypassing the status gate in
ExtractionService._trigger_downstream_stages(). Routes to the dev Neo4j
instance (port 7688) via NEO4J_ENV=dev.

Usage:
    NEO4J_ENV=dev poetry run python rag_pipeline/ingest_kg.py
"""

import asyncio
import os

# Must be set before any src.knowledge imports so neo4j_client picks up dev URI
os.environ.setdefault("NEO4J_ENV", "dev")

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()

from rag_pipeline.config import BOOK_ID, SERIES_ID, USER_ID
from src.knowledge.ingestion_service import IngestionService


async def main() -> None:
    print(f"Ingesting {SERIES_ID} / {BOOK_ID} into dev Neo4j...")
    service = IngestionService(
        user_id=USER_ID,
        book_id=BOOK_ID,
        series_id=SERIES_ID,
    )
    await service.ingest_book()
    print("Done.")


asyncio.run(main())
