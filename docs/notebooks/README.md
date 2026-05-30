# Archived Notebooks

These notebooks were used for early exploration and are **not maintained**. They document design thinking but may have stale imports and hardcoded paths.

| Notebook | What it was for |
|----------|----------------|
| `booklens_timeline.ipynb` | Timeline visualisation experiments — character arcs and event ordering across chapters. |
| `hybrid_rag_pipeline.ipynb` | Early RAG pipeline design: tested LlamaIndex auto-merging retriever with Supabase pgvector before the pipeline was ported to `backend/rag/`. |

The production implementation is in `backend/rag/`. For ingestion, use `scripts/run_rag_ingest.py`.
