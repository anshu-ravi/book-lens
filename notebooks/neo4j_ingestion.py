"""
Direct Neo4j Knowledge Graph Ingestion with Spoiler-Safe Filtering

Ingests extracted chapter data into Neo4j with timestamp-based spoiler filtering.
Allows querying knowledge "up to" a specific chapter without revealing future events.
"""

import json
import os
from pathlib import Path
from datetime import datetime, timedelta

from neo4j import GraphDatabase


# --- CONFIG ---
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASS = os.getenv("NEO4J_PASS", "password")
EXTRACTIONS_DIR = "./notebooks/extractions"


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


def ingest_chapters_to_neo4j(chapters: list[tuple[str, dict]]) -> dict[str, dict]:
    """Ingest extracted chapter data directly into Neo4j with timestamps.

    Args:
        chapters: List of (chapter_label, chapter_data) tuples.

    Returns:
        Mapping of chapter names to their metadata (index, timestamp).
    """
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
    chapter_metadata = {}

    print("\nIngesting chapters into Neo4j...")
    for i, (label, data) in enumerate(chapters):
        try:
            # Calculate timestamp for this chapter (for spoiler filtering)
            ref_time = datetime(2026, 1, 1) + timedelta(days=i)
            chapter_metadata[label] = {
                "index": i,
                "timestamp": ref_time.isoformat(),
            }

            with driver.session() as session:
                # Create or merge chapter/episode node with timestamp
                session.run(
                    """
                    MERGE (ep:Chapter {name: $name})
                    SET ep.label = $label,
                        ep.summary = $summary,
                        ep.chapter_index = $chapter_index,
                        ep.reference_time = $reference_time,
                        ep.extracted_at = $extracted_at
                    """,
                    {
                        "name": label,
                        "label": label,
                        "summary": data.get("summary", ""),
                        "chapter_index": i,
                        "reference_time": ref_time.isoformat(),
                        "extracted_at": datetime.now().isoformat(),
                    },
                )

                # Create or merge character nodes
                for char in data.get("characters", []):
                    session.run(
                        """
                        MERGE (c:Character {name: $name})
                        ON CREATE SET c.first_appearance = $chapter_index
                        SET c.faction = $faction,
                            c.role = $role,
                            c.description = $description,
                            c.aliases = $aliases
                        """,
                        {
                            "name": char.get("name"),
                            "chapter_index": i,
                            "faction": char.get("faction"),
                            "role": char.get("role"),
                            "description": char.get("description"),
                            "aliases": char.get("aliases", []),
                        },
                    )

                    # Link character to chapter (with introduction timestamp)
                    session.run(
                        """
                        MATCH (c:Character {name: $char_name})
                        MATCH (ep:Chapter {name: $chapter_name})
                        MERGE (c)-[r:APPEARS_IN]->(ep)
                        SET r.chapter_index = $chapter_index,
                            r.reference_time = $reference_time
                        """,
                        {
                            "char_name": char.get("name"),
                            "chapter_name": label,
                            "chapter_index": i,
                            "reference_time": ref_time.isoformat(),
                        },
                    )

                # Create relationship edges between characters
                for rel in data.get("relationships", []):
                    char_a = rel.get("character_a")
                    char_b = rel.get("character_b")

                    if char_a and char_b:
                        rel_type = rel.get("type", "RELATED_TO").upper().replace(
                            " ", "_"
                        )
                        session.run(
                            f"""
                            MATCH (a:Character {{name: $char_a}})
                            MATCH (b:Character {{name: $char_b}})
                            MERGE (a)-[r:{rel_type}]->(b)
                            SET r.description = $description,
                                r.moments = $moments,
                                r.introduced_in_chapter = $chapter_name,
                                r.chapter_index = $chapter_index,
                                r.reference_time = $reference_time
                            """,
                            {
                                "char_a": char_a,
                                "char_b": char_b,
                                "description": rel.get("description"),
                                "moments": rel.get("moments", []),
                                "chapter_name": label,
                                "chapter_index": i,
                                "reference_time": ref_time.isoformat(),
                            },
                        )

                # Create world fact nodes
                for fact in data.get("world_facts", []):
                    session.run(
                        """
                        MERGE (wf:WorldFact {name: $name})
                        SET wf.category = $category,
                            wf.description = $description
                        """,
                        {
                            "name": fact.get("name"),
                            "category": fact.get("category"),
                            "description": fact.get("description"),
                        },
                    )

                    # Link fact to chapter with timestamp
                    session.run(
                        """
                        MATCH (wf:WorldFact {name: $fact_name})
                        MATCH (ep:Chapter {name: $chapter_name})
                        MERGE (wf)-[r:INTRODUCED_IN]->(ep)
                        SET r.chapter_index = $chapter_index,
                            r.reference_time = $reference_time
                        """,
                        {
                            "fact_name": fact.get("name"),
                            "chapter_name": label,
                            "chapter_index": i,
                            "reference_time": ref_time.isoformat(),
                        },
                    )

            print(f"  [{i+1}/{len(chapters)}] ✓ {label} (ts: {ref_time.date()})")
        except Exception as e:
            print(f"  [{i+1}/{len(chapters)}] ✗ {label}: {e}")

    # Print summary
    print("\n" + "="*70)
    print("KNOWLEDGE GRAPH SUMMARY")
    print("="*70)

    try:
        with driver.session() as session:
            # Count nodes
            result = session.run("MATCH (c:Character) RETURN COUNT(c) as count")
            char_count = result.single()["count"]

            result = session.run("MATCH (wf:WorldFact) RETURN COUNT(wf) as count")
            fact_count = result.single()["count"]

            result = session.run("MATCH (ep:Chapter) RETURN COUNT(ep) as count")
            chapter_count = result.single()["count"]

            # Count character relationships (exclude APPEARS_IN and INTRODUCED_IN)
            result = session.run(
                "MATCH ()-[r]->() WHERE type(r) <> 'APPEARS_IN' AND type(r) <> 'INTRODUCED_IN' RETURN COUNT(r) as count"
            )
            rel_count = result.single()["count"]

            print(f"\nNodes Created:")
            print(f"  • Characters: {char_count}")
            print(f"  • World Facts: {fact_count}")
            print(f"  • Chapters: {chapter_count}")
            print(f"  • Character Relationships: {rel_count}")

            # Sample characters
            print(f"\nTop Characters:")
            result = session.run(
                "MATCH (c:Character) RETURN c.name, c.role, c.faction ORDER BY c.name LIMIT 5"
            )
            for record in result:
                print(f"  • {record[0]:<20} {record[1]:<15} ({record[2]})")

            # Sample relationships
            print(f"\nSample Relationships:")
            result = session.run(
                "MATCH (a:Character)-[r]->(b:Character) WHERE type(r) <> 'APPEARS_IN' AND type(r) <> 'INTRODUCED_IN' RETURN a.name, type(r), b.name, r.description LIMIT 5"
            )
            for record in result:
                desc = (
                    record[3][:40] + "..." if record[3] and len(record[3]) > 40 else record[3]
                )
                print(f"  • {record[0]} --[{record[1]}]--> {record[2]}")
                if desc:
                    print(f"    └─ {desc}")

            # Show spoiler-safe query example
            print(f"\nSpoiler-Safe Query Example:")
            print(f"  To get all knowledge up to Chapter 2:")
            print(f"  MATCH (c:Character)-[r]->(ep:Chapter)")
            print(f"  WHERE ep.chapter_index <= 1")
            print(f"  RETURN DISTINCT c.name, c.role")

    except Exception as e:
        print(f"Error generating summary: {e}")

    driver.close()
    print("\n" + "="*70)
    print("✓ Ingestion complete")
    print("="*70)

    # Save metadata for reference
    metadata_file = "./notebooks/chapter_metadata.json"
    with open(metadata_file, "w") as f:
        json.dump(chapter_metadata, f, indent=2)
    print(f"\n✓ Saved chapter metadata to {metadata_file}")

    return chapter_metadata


def main(num_chapters: int = 10) -> None:
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

    # Ingest into Neo4j
    ingest_chapters_to_neo4j(chapters)


if __name__ == "__main__":
    import sys

    num_chapters = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    main(num_chapters)
