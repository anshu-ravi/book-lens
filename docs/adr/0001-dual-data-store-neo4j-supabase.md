# Dual data store: Neo4j for the Knowledge Graph, Supabase for everything else

The system uses two data stores: Neo4j holds the per-series Knowledge Graph (characters, relationships, world facts, chapter summaries, identity reveals), and Supabase holds everything else (auth, library state, prose embeddings, book covers, file storage).

Neo4j was chosen for the Knowledge Graph because it is the leading graph database, offers Cypher as a well-supported query language, and has a managed cloud offering (AuraDB) for production deployment. Supabase was already in use for auth; since it provides Postgres, pgvector, and Storage in one service, it was the natural home for all non-graph data rather than introducing a third system.

## Considered options

- **Supabase only** — model the Knowledge Graph as relational tables (characters + junction tables for relationships). Simpler operational footprint, but loses Cypher's expressiveness for graph traversal and would require significant schema design effort for what is naturally graph-shaped data.
- **Neo4j only** — move auth, library, and vector search into Neo4j or a companion service. Rejected because Supabase auth and Storage are deeply integrated into the frontend and upload flow.
