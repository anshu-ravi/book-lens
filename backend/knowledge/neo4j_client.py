"""Neo4j driver singleton and schema initialization."""

import os
from typing import Optional

from neo4j import Driver, GraphDatabase


_driver: Optional[Driver] = None


def get_driver() -> Driver:
    """Get or create Neo4j driver singleton."""
    global _driver
    if _driver is not None:
        return _driver

    env = os.environ.get("NEO4J_ENV", "prod")
    default_uri = "bolt://localhost:7688" if env == "dev" else "bolt://localhost:7687"
    uri = os.environ.get("NEO4J_URI", default_uri)
    user = os.environ.get("NEO4J_USER", "neo4j")
    password = os.environ.get("NEO4J_PASS", "password")

    _driver = GraphDatabase.driver(uri, auth=(user, password))
    _initialize_schema(_driver)
    return _driver


def _initialize_schema(driver: Driver) -> None:
    """Create constraints and indexes on database."""
    with driver.session() as session:
        # Create unique constraints for Character and Chapter
        session.run(
            "CREATE CONSTRAINT character_unique IF NOT EXISTS "
            "FOR (c:Character) REQUIRE (c.name, c.series_id) IS UNIQUE"
        )
        session.run(
            "CREATE CONSTRAINT chapter_unique IF NOT EXISTS "
            "FOR (ch:Chapter) REQUIRE (ch.name, ch.series_id) IS UNIQUE"
        )

        # Create vector index for semantic search
        try:
            session.run(
                "CREATE VECTOR INDEX character_embeddings IF NOT EXISTS "
                "FOR (c:Character) ON (c.embedding) "
                "OPTIONS {indexConfig: {`vector.dimensions`: 384, `vector.similarity_function`: 'cosine'}}"
            )
        except Exception as e:
            # Vector index creation might fail in some Neo4j versions; log and continue
            print(f"Warning: Could not create vector index: {e}")


def close_driver() -> None:
    """Close the Neo4j driver."""
    global _driver
    if _driver is not None:
        _driver.close()
        _driver = None
