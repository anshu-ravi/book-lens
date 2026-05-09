#!/usr/bin/env python3
"""Query the knowledge graph for testing."""

import argparse
import sys

from dotenv import load_dotenv

from src.knowledge.query import KnowledgeQueryEngine


def main() -> None:
    """Run semantic search query."""
    parser = argparse.ArgumentParser(description="Query knowledge graph")
    parser.add_argument("--series", required=True, help="Series identifier")
    parser.add_argument("--chapter", type=int, required=True, help="Up to chapter (spoiler cutoff)")
    parser.add_argument("--search", required=True, help="Search query")
    parser.add_argument("--top-k", type=int, default=10, help="Number of results")
    args = parser.parse_args()

    # Load environment
    load_dotenv()

    # Create query engine
    engine = KnowledgeQueryEngine(args.series)

    # Run semantic search
    results = engine.semantic_search(args.search, args.chapter, top_k=args.top_k)

    print(f"Search results for '{args.search}' up to chapter {args.chapter}:")
    for result in results:
        print(f"  - {result['name']}: {result['description'][:100]}... (score: {result['score']:.3f})")


if __name__ == "__main__":
    main()
