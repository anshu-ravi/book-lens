#!/usr/bin/env python3
"""SILVER + GOLD stages: Deduplicate and ingest into Neo4j."""

import argparse
import sys

from dotenv import load_dotenv

from backend.knowledge.deduplicator import Deduplicator
from backend.knowledge.ingestor import Ingestor


def main() -> None:
    """Run deduplication and ingestion."""
    parser = argparse.ArgumentParser(description="Deduplicate and ingest knowledge")
    parser.add_argument("--series", required=True, help="Series identifier")
    parser.add_argument("--limit", type=int, help="Limit chapters to process")
    args = parser.parse_args()

    # Load environment
    load_dotenv()

    print(f"Running deduplication for {args.series}...")
    deduplicator = Deduplicator(args.series)
    deduplicator.run(limit=args.limit)

    print(f"Running ingestion for {args.series}...")
    ingestor = Ingestor(args.series)
    ingestor.run(limit=args.limit)

    print("Deduplication and ingestion complete")


if __name__ == "__main__":
    main()
