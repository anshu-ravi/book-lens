# Gemini as the primary LLM for answer generation and extraction

Status: accepted — pragmatic choice, expected to change as model pricing and rate limits evolve.

Gemini is used for both answer generation (query time) and knowledge extraction (ingestion). It was chosen over Claude and OpenAI because, for this workload, it is the cheapest, fastest, and most permissive on rate limits. The use case — retrieval-augmented Q&A over structured context — does not require the highest-quality model available, so cost and throughput are the deciding factors.

Claude Haiku is used as a narrow fallback for chapter summarisation during ingestion only, when no pre-extracted summary exists. Local sentence-transformers handle all embedding to avoid the cost and latency of a hosted embedding API.

The model choice is explicitly not permanent. If a cheaper or faster model with better rate limits emerges, it should replace Gemini. The `backend/llm/` module exists to keep model-specific code isolated so swaps are contained.
