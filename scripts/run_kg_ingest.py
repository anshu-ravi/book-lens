"""Ingest gold layer into dev Neo4j, bypassing the async extraction gate.

Calls IngestionService directly. Targets the dev Neo4j instance (port 7688).

Usage:
    NEO4J_ENV=dev poetry run python scripts/run_kg_ingest.py \\
        --series the-red-rising-saga \\
        --book-id 7af3a69a-1d3a-4899-881d-a33eceaa69a9 \\
        --user-id d5203e02-a3d8-4b9b-ba4e-1b08c8ebdc46
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

# Must be set before any backend.knowledge imports so neo4j_client picks up dev URI
os.environ.setdefault("NEO4J_ENV", "dev")

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()

from backend.knowledge.ingestion_service import IngestionService


async def main(series_id: str, book_id: str, user_id: str) -> None:
    print(f"Ingesting {series_id} / {book_id} into dev Neo4j...")
    service = IngestionService(user_id=user_id, book_id=book_id, series_id=series_id)
    await service.ingest_book()
    print("Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest gold layer into dev Neo4j")
    parser.add_argument("--series", required=True, help="Series slug")
    parser.add_argument("--book-id", required=True, help="Book UUID")
    parser.add_argument("--user-id", required=True, help="Supabase user UUID")
    args = parser.parse_args()
    asyncio.run(main(args.series, args.book_id, args.user_id))
