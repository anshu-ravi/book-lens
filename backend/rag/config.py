"""RAG pipeline constants — book identity is passed at call-time, not hardcoded here."""

from pathlib import Path

# ── Caching ───────────────────────────────────────────────────────────────────
CACHE_DIR = Path("local/.rag_cache")

# ── Models ────────────────────────────────────────────────────────────────────
EXTRACTION_MODEL = "claude-haiku-4-5"   # summaries (fallback when no gold layer)
EMBED_MODEL_NAME = "BAAI/bge-small-en-v1.5"  # 384-dim, fast local

# ── Chunking ──────────────────────────────────────────────────────────────────
# Three-level hierarchy: large context → scene → paragraph
CHUNK_SIZES = [2048, 512, 128]

# ── Pipeline control ──────────────────────────────────────────────────────────
OVERWRITE = False          # True → re-run all LLM calls, rebuild cache
