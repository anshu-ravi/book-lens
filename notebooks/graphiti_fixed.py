"""
Graphiti Ingestion - Fixed Version

Uses simpler data format and proper string encoding.
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
from graphiti_core.cross_encoder.gemini_reranker_client import GeminiRerankerClient


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


async def ingest_with_graphiti(chapters: list[tuple[str, dict]]) -> None:
    """Ingest using Graphiti with TEXT format instead of JSON."""

    print("\nInitializing Graphiti with Google Gemini...")
    try:
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
            cross_encoder=GeminiRerankerClient(
                config=LLMConfig(
                    api_key=GEMINI_API_KEY,
                    model="gemini-3.1-flash-lite",
                )
            ),
        )
        await graphiti.build_indices_and_constraints()
        print("✓ Graphiti initialized\n")
    except Exception as e:
        print(f"✗ Failed to initialize Graphiti: {e}")
        return

    # Ingest as plain text (let Graphiti parse it)
    print(f"Ingesting {len(chapters)} chapters...\n")
    for i, (label, data) in enumerate(chapters):
        try:
            ref_time = datetime(2026, 1, 1) + timedelta(days=i)

            # Convert to formatted text (not JSON)
            text_body = format_chapter_text(label, data)

            await graphiti.add_episode(
                name=label,
                episode_body=text_body,
                source=EpisodeType.message,  # Plain text
                reference_time=ref_time,
                source_description=f"Book chapter: {label}",
            )
            print(f"  [{i+1}/{len(chapters)}] ✓ {label}")
        except Exception as e:
            print(f"  [{i+1}/{len(chapters)}] ✗ {label}: {str(e)[:80]}")

    await graphiti.close()
    print("\n✓ Graphiti ingestion complete")


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
