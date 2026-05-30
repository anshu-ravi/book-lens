"""Central configuration — change values here, nothing else needs to touch constants."""

from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────
BOOK_PATH = Path("../uploads/red-rising/book_0.epub")
CACHE_DIR = Path("rag_pipeline/.cache")

# ── Book identity — shared between RAG and KG pipelines ──────────────────────
# Must match the Supabase Storage path used by the KG pipeline:
#   extractions/{USER_ID}/{SERIES_ID}/{BOOK_ID}/deduped_chapters.json
USER_ID   = "d5203e02-a3d8-4b9b-ba4e-1b08c8ebdc46"
SERIES_ID = "the-red-rising-saga"
BOOK_ID   = "7af3a69a-1d3a-4899-881d-a33eceaa69a9"

# ── Models ────────────────────────────────────────────────────────────────────
EXTRACTION_MODEL = "claude-haiku-4-5"   # summaries (fallback when no gold layer)
GENERATION_MODEL = "claude-haiku-4-5"   # final answer generation
EMBED_MODEL_NAME = "BAAI/bge-small-en-v1.5"  # 384-dim, fast local

# ── Chunking ──────────────────────────────────────────────────────────────────
# Three-level hierarchy: large context → scene → paragraph
CHUNK_SIZES = [2048, 512, 128]

# ── Pipeline control ──────────────────────────────────────────────────────────
OVERWRITE = False          # True → re-run all LLM calls, rebuild cache
CHAPTERS_TO_PROCESS = None  # None = full book; set to int to limit
