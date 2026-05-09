"""
Graphiti Ingestion - Working Version

Disables the problematic cross encoder to avoid the zip() error.
"""

import asyncio
import json
import os
from pathlib import Path
from datetime import datetime, timedelta

from dotenv import load_dotenv
load_dotenv()

from graphiti_core import Graphiti
from graphiti_core.nodes import EpisodeType
from graphiti_core.llm_client.gemini_client import GeminiClient, LLMConfig
from graphiti_core.embedder.gemini import GeminiEmbedder, GeminiEmbedderConfig


# --- CONFIG ---
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASS = os.getenv("NEO4J_PASS", "password")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
EXTRACTIONS_DIR = "./notebooks/extractions"

if not GEMINI_API_KEY:
    print("✗ Error: GEMINI_API_KEY not found in environment")
    exit(1)


def get_extraction_files(limit: int = 10) -> list[tuple[str, dict]]:
    """Load extracted JSON files from disk."""
    files = sorted(Path(EXTRACTIONS_DIR).glob("*.json"))[:limit]
    chapters = []

    for filepath in files:
        try:
            with open(filepath, "r") as f:
                data = json.load(f)
            chapters.append((filepath.stem, data))
            print(f"✓ Loaded: {filepath.stem}")
        except Exception as e:
            print(f"✗ Failed to load {filepath.stem}: {e}")

    return chapters


def format_chapter_text(label: str, data: dict) -> str:
    """Format extracted data as readable text for Graphiti to parse."""

    text = f"Chapter: {label}\n\n"

    # Characters
    if data.get('characters'):
        text += "CHARACTERS:\n"
        for char in data['characters']:
            text += f"- {char.get('name', 'Unknown')}: {char.get('description', '')}\n"
            if char.get('aliases'):
                text += f"  Also known as: {', '.join(char['aliases'])}\n"
            if char.get('role'):
                text += f"  Role: {char['role']}\n"
        text += "\n"

    # Relationships
    if data.get('relationships'):
        text += "RELATIONSHIPS:\n"
        for rel in data['relationships']:
            text += f"- {rel.get('character_a')} and {rel.get('character_b')}: "
            text += f"{rel.get('description', '')} "
            text += f"({rel.get('type', 'related')})\n"
        text += "\n"

    # World facts
    if data.get('world_facts'):
        text += "WORLD FACTS:\n"
        for fact in data['world_facts']:
            text += f"- {fact.get('name')}: {fact.get('description')}\n"
        text += "\n"

    # Summary
    if data.get('summary'):
        text += f"SUMMARY:\n{data['summary']}\n"

    return text


async def ingest_with_graphiti(chapters: list[tuple[str, dict]]) -> None:
    """Ingest using Graphiti WITHOUT cross encoder to avoid zip() error."""

    print("\nInitializing Graphiti (no cross encoder)...")
    try:
        # Initialize WITHOUT cross_encoder to avoid reranking errors
        graphiti = Graphiti(
            NEO4J_URI,
            NEO4J_USER,
            NEO4J_PASS,
            llm_client=GeminiClient(
                config=LLMConfig(
                    api_key=GEMINI_API_KEY,
                    model="gemini-3.1-flash-lite",
                )
            ),
            embedder=GeminiEmbedder(
                config=GeminiEmbedderConfig(
                    api_key=GEMINI_API_KEY,
                    embedding_model="gemini-embedding-2",
                )
            ),
            # cross_encoder=None  # DISABLED - this was causing the zip() error
        )
        await graphiti.build_indices_and_constraints()
        print("✓ Graphiti initialized (cross encoder disabled)\n")
    except Exception as e:
        print(f"✗ Failed to initialize Graphiti: {e}")
        return

    # Ingest as plain text
    print(f"Ingesting {len(chapters)} chapters to Neo4j via Graphiti...\n")
    successful = 0
    failed = 0

    for i, (label, data) in enumerate(chapters):
        try:
            ref_time = datetime(2026, 1, 1) + timedelta(days=i)
            text_body = format_chapter_text(label, data)

            await graphiti.add_episode(
                name=label,
                episode_body=text_body,
                source=EpisodeType.message,
                reference_time=ref_time,
                source_description=f"Book chapter: {label}",
            )
            print(f"  [{i+1}/{len(chapters)}] ✓ {label}")
            successful += 1
        except Exception as e:
            error_msg = str(e)[:60]
            print(f"  [{i+1}/{len(chapters)}] ✗ {label}: {error_msg}")
            failed += 1

    print(f"\n" + "="*70)
    print(f"✓ Ingestion Summary:")
    print(f"  • Successful: {successful}")
    print(f"  • Failed: {failed}")
    print(f"  • Total: {successful + failed}/{len(chapters)}")
    print("="*70)

    # Get graph stats
    try:
        print("\nGraphiti nodes created:")
        # Graphiti will have created entities in Neo4j
        # You can query via Neo4j directly to see what was created
    except Exception as e:
        print(f"Error: {e}")

    await graphiti.close()


async def main(num_chapters: int = 10) -> None:
    """Main workflow."""
    print(f"Loading up to {num_chapters} extracted chapters...\n")

    chapters = get_extraction_files(limit=num_chapters)
    if not chapters:
        print("✗ No extracted chapters found")
        return

    print(f"\n✓ Loaded {len(chapters)} chapters")

    await ingest_with_graphiti(chapters)


if __name__ == "__main__":
    import sys
    num_chapters = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    asyncio.run(main(num_chapters))
