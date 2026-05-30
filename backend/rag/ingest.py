"""EPUB → hierarchical nodes → embeddings → Supabase.

Entry point: ingest_book(). Idempotent — only writes nodes not already stored.
"""

from pathlib import Path
from typing import Optional

from supabase import Client

from backend.rag.chunking import build_nodes, summarize_node_tree
from backend.rag.config import CACHE_DIR
from backend.rag.embedder import embed_and_summarize, load_chapter_summaries
from backend.rag.node_store import NodeStore
from backend.rag.parsing import load_documents


def ingest_book(
    epub_path: Path,
    series_id: str,
    book_id: str,
    user_id: str,
    supabase: Client,
    anthropic_api_key: str,
    book_title: str = "",
    chapters_limit: Optional[int] = None,
) -> dict[str, int]:
    """Parse, chunk, embed, and persist a book into Supabase.

    Args:
        epub_path: Path to the source .epub file.
        series_id: Series slug (e.g. "the-red-rising-saga").
        book_id: Book UUID from the Supabase books table.
        user_id: Owner's Supabase user ID (needed for the gold-layer path).
        supabase: Authenticated Supabase client.
        anthropic_api_key: API key — only used when no gold-layer summaries exist.
        book_title: Used in embedding context window (e.g. "Red Rising").
        chapters_limit: Cap ingestion at N chapters (useful for testing).

    Returns:
        {"new_nodes": int, "new_embeddings": int} — counts of rows written.
    """
    cache_path = CACHE_DIR / series_id / book_id / "embed_cache.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    documents = load_documents(epub_path, limit=chapters_limit, book_title=book_title)

    all_nodes, leaf_nodes = build_nodes(documents, series_id=series_id, book_id=book_id)
    summarize_node_tree(all_nodes, leaf_nodes)

    chapter_summaries = load_chapter_summaries(supabase, user_id, series_id, book_id)

    leaf_nodes = embed_and_summarize(
        leaf_nodes,
        anthropic_api_key=anthropic_api_key,
        cache_path=cache_path,
        chapter_summaries=chapter_summaries,
    )

    store = NodeStore(supabase, series_id=series_id, book_id=book_id)
    existing_ids = store.get_existing_node_ids()

    new_nodes = [n for n in all_nodes if n.node_id not in existing_ids]
    new_leaves = [n for n in leaf_nodes if n.node_id not in existing_ids]

    if new_nodes:
        store.upsert_nodes(new_nodes)
    if new_leaves:
        store.upsert_embeddings(new_leaves)

    return {"new_nodes": len(new_nodes), "new_embeddings": len(new_leaves)}
