#!/usr/bin/env python3
"""Ask questions about a book series using its knowledge graph."""

import argparse
import asyncio
import sys

from dotenv import load_dotenv

from src.knowledge.qa import KnowledgeQA


async def main() -> None:
    """Run Q&A."""
    parser = argparse.ArgumentParser(description="Ask questions about a book series")
    parser.add_argument("--series", required=True, help="Series identifier")
    parser.add_argument("--chapter", type=int, required=True, help="Up to chapter (spoiler cutoff)")
    parser.add_argument("--question", required=True, help="Question to ask")
    parser.add_argument("--top-k", type=int, default=5, help="Top K characters to include")
    args = parser.parse_args()

    # Load environment
    load_dotenv()

    # Create Q&A engine
    qa = KnowledgeQA(args.series)

    # Ask question
    print(f"Asking: {args.question}")
    print(f"Context: {args.series} up to chapter {args.chapter}")
    print("=" * 80)

    answer = await qa.ask(args.question, args.chapter, top_k=args.top_k)
    print(answer)


if __name__ == "__main__":
    asyncio.run(main())
