# Architecture Decision Records

This directory contains Architecture Decision Records (ADRs) documenting key technical choices made during development.

## Format
Each decision follows this structure:
- **Context**: What prompted this decision
- **Options Considered**: Alternatives evaluated
- **Decision**: What we chose
- **Rationale**: Why we chose it
- **Consequences**: Trade-offs and implications

## Records
- `decisions.md` - Running log of all architectural decisions

Example decisions:
- Why Qdrant over Pinecone/Weaviate/Chroma
- Why sentence-transformers over OpenAI embeddings
- Why JSON file over SQLite for library state
- Why single-file frontend over React/Vue
