"""
Graphiti Knowledge Graph Ingestion & Query Notebook

Loads extracted chapter JSON files and ingests them into a Neo4j-backed
knowledge graph using Graphiti. Includes sample queries to explore relationships.
"""

import asyncio
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

# --- GRAPHITI SETUP ---
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
    print("  Please add GEMINI_API_KEY to your .env file")
    exit(1)


def get_extraction_files(limit: int = 10) -> list[tuple[str, dict]]:
    """Load extracted JSON files from disk.

    Returns:
        List of (filename, data) tuples for each extracted chapter.
    """
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


async def ingest_chapters_to_graphiti(chapters: list[tuple[str, dict]]) -> dict[str, datetime]:
    """Ingest extracted chapter data into Graphiti.

    Args:
        chapters: List of (chapter_label, chapter_data) tuples.

    Returns:
        Mapping of chapter labels to their reference timestamps.
    """
    # Initialize Graphiti with Gemini LLM clients
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
        print("✓ Graphiti initialized with Gemini")
    except Exception as e:
        print(f"✗ Failed to initialize Graphiti: {e}")
        print("  Make sure Neo4j is running at", NEO4J_URI)
        print("  And GEMINI_API_KEY is valid")
        return {}

    # Ingest chapters and track timestamps
    print(f"\nIngesting {len(chapters)} chapters...")
    chapter_timestamps = {}
    for i, (label, data) in enumerate(chapters):
        try:
            # Map chapter order to temporal dates (for spoiler-safe retrieval)
            ref_time = datetime(2026, 1, 1) + timedelta(days=i)
            chapter_timestamps[label] = ref_time

            # Try passing data directly (as dict) instead of JSON string
            # Graphiti will serialize it internally
            await graphiti.add_episode(
                name=label,
                episode_body=data,
                source=EpisodeType.json,
                reference_time=ref_time,
                source_description=f"Automated extraction from: {label}",
            )
            print(f"  [{i+1}/{len(chapters)}] ✓ {label} (timestamp: {ref_time.date()})")
        except Exception as e:
            print(f"  [{i+1}/{len(chapters)}] ✗ {label}: {e}")

    # Run sample queries using Graphiti's API
    print("\n" + "="*70)
    print("SAMPLE QUERIES & RETRIEVAL")
    print("="*70)

    try:
        # Query 1: Retrieve episodes up to specific chapter timestamps
        print("\n1️⃣  Episodes Ingested (Spoiler-Safe Retrieval):")
        print("-" * 70)
        if chapter_timestamps:
            # Show example: retrieve up to chapter 2
            example_chapter = list(chapter_timestamps.keys())[1] if len(chapter_timestamps) > 1 else list(chapter_timestamps.keys())[0]
            example_timestamp = chapter_timestamps[example_chapter]

            episodes = await graphiti.retrieve_episodes(reference_time=example_timestamp)
            if episodes:
                print(f"  Retrieving up to: {example_chapter} ({example_timestamp.date()})")
                print(f"  Episodes available up to this point: {len(episodes)}")
                for i, ep in enumerate(episodes[:5], 1):
                    print(f"    {i}. {ep.name}")
            else:
                print(f"  (No episodes found up to {example_timestamp.date()})")
        else:
            print("  (No chapter timestamps available)")

        # Query 2: Get nodes and edges for first episode
        if episodes:
            print(f"\n2️⃣  Knowledge Graph Structure (First Episode):")
            print("-" * 70)
            first_episode = episodes[0]
            nodes_edges = await graphiti.get_nodes_and_edges_by_episode(first_episode.id)
            print(f"  Episode: {first_episode.name}")
            print(f"  • Nodes: {len(nodes_edges.nodes)}")
            print(f"  • Edges: {len(nodes_edges.edges)}")

            # Show sample nodes
            if nodes_edges.nodes:
                print("\n  Sample Nodes:")
                for node in nodes_edges.nodes[:5]:
                    print(f"    - {node.label}: {node.name}")

            # Show sample edges
            if nodes_edges.edges:
                print("\n  Sample Relationships:")
                for edge in nodes_edges.edges[:5]:
                    print(f"    - {edge.source_label} --[{edge.relationship_type}]--> {edge.target_label}")

        # Query 3: Search for specific entities
        print(f"\n3️⃣  Search Query (Example: 'characters'):")
        print("-" * 70)
        search_results = await graphiti.search(query="characters and relationships")
        if search_results:
            print(f"  Found {len(search_results)} results:")
            for i, result in enumerate(search_results[:3], 1):
                print(f"  {i}. {result}")
        else:
            print("  (No search results)")

        # Query 4: Graph summary
        print(f"\n4️⃣  Knowledge Graph Summary:")
        print("-" * 70)
        if episodes:
            total_episodes = len(episodes)
            total_nodes = 0
            total_edges = 0

            # Aggregate statistics
            for ep in episodes[:5]:  # Sample first 5
                nodes_edges = await graphiti.get_nodes_and_edges_by_episode(ep.id)
                total_nodes += len(nodes_edges.nodes)
                total_edges += len(nodes_edges.edges)

            print(f"  Total Episodes Ingested: {total_episodes}")
            print(f"  Sample Stats (first 5 episodes):")
            print(f"    • Total Nodes: {total_nodes}")
            print(f"    • Total Relationships: {total_edges}")
            print(f"    • Avg Nodes/Episode: {total_nodes / min(5, total_episodes):.1f}")
            print(f"    • Avg Edges/Episode: {total_edges / min(5, total_episodes):.1f}")

    except Exception as e:
        print(f"✗ Query error: {e}")

    # Close connection
    await graphiti.close()
    print("\n" + "="*70)
    print("✓ Ingestion complete")
    print("="*70)

    # Return timestamp mapping for future spoiler-safe queries
    return chapter_timestamps


async def main(num_chapters: int = 10) -> None:
    """Main workflow.

    Args:
        num_chapters: Number of chapters to ingest (default: 10)
    """
    print(f"Loading up to {num_chapters} extracted chapters...")

    # Load extraction files
    chapters = get_extraction_files(limit=num_chapters)
    if not chapters:
        print("✗ No extracted chapters found in", EXTRACTIONS_DIR)
        return

    print(f"\n✓ Loaded {len(chapters)} chapters\n")

    # Ingest into Graphiti and get chapter timestamps
    chapter_timestamps = await ingest_chapters_to_graphiti(chapters)

    # Save timestamp mapping for future use
    if chapter_timestamps:
        timestamp_file = "./notebooks/chapter_timestamps.json"
        with open(timestamp_file, "w") as f:
            # Convert datetime to ISO format for JSON serialization
            json.dump(
                {k: v.isoformat() for k, v in chapter_timestamps.items()},
                f,
                indent=2
            )
        print(f"\n✓ Saved chapter timestamps to {timestamp_file}")
        print(f"  Use this for spoiler-safe queries based on reading progress")


if __name__ == "__main__":
    import sys

    num_chapters = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    asyncio.run(main(num_chapters))
