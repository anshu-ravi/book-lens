"""Summarisation + embedding for leaf nodes with two independent disk caches.

Summaries and embeddings are cached separately so the embedding format can be
changed (and the embed cache cleared) without re-running any LLM calls.

Cache files (both under CACHE_DIR):
  summary_cache.json  — {node_id: str}           never invalidated
  embed_cache.json    — {node_id: list[float]}    safe to delete and regenerate

Embedding format: "<book_title> | <chapter_label>\\n\\n<summary>\\n\\n<raw text>"

Performance:
  - Embeddings: batched via get_text_embedding_batch() — all nodes in one pass
  - Summaries: parallelised via ThreadPoolExecutor (default 8 workers)
"""

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import TYPE_CHECKING

import anthropic as anthropic_sdk
from llama_index.core.schema import BaseNode
from llama_index.embeddings.huggingface import HuggingFaceEmbedding

from backend.rag.config import EMBED_MODEL_NAME, EXTRACTION_MODEL, OVERWRITE

if TYPE_CHECKING:
    from supabase import Client

_SUMMARY_PROMPT = (
    "Summarise the following passage in 2–3 sentences. "
    "Be concise and focus on the key events or ideas.\n\n{text}"
)
_SUMMARY_WORKERS = 8


def load_chapter_summaries(
    client: "Client",
    user_id: str,
    series_id: str,
    book_id: str,
) -> dict[int, str]:
    """Load chapter-level summaries from the gold layer in Supabase Storage.

    Returns a mapping of chapter_index → summary string. Used to populate
    the summary cache without making any LLM calls.

    Args:
        client: Supabase client.
        user_id: Owner of the extraction.
        series_id: Series slug matching the Storage path.
        book_id: Book UUID matching the Storage path.

    Returns:
        {chapter_index: summary} for every chapter that has a summary.
    """
    path = f"extractions/{user_id}/{series_id}/{book_id}/deduped_chapters.json"
    response = client.storage.from_("extractions").download(path)
    data = json.loads(response)
    return {
        int(idx): chapter["extraction"]["summary"]
        for idx, chapter in data.items()
        if chapter.get("extraction", {}).get("summary")
    }


def embed_and_summarize(
    leaf_nodes: list[BaseNode],
    anthropic_api_key: str,
    cache_path: Path,
    overwrite: bool = OVERWRITE,
    chapter_summaries: dict[int, str] | None = None,
) -> list[BaseNode]:
    """Add summaries and embeddings to leaf nodes using two independent caches.

    Summary resolution order:
      1. Disk cache (summary_cache.json) — free, always checked first
      2. chapter_summaries dict (gold layer) — free, no LLM calls
      3. Parallel Anthropic Haiku calls — fallback when no gold layer available

    Embedding cache miss → HuggingFace batched forward pass.

    The enriched nodes are returned with:
      - node.metadata["section_summary"] set
      - node.embedding set (list[float], 384-dim)

    Args:
        leaf_nodes: Paragraph-level nodes from chunking.build_nodes().
        anthropic_api_key: Used only when chapter_summaries is None and cache misses.
        cache_path: Base path — summary_cache.json and embed_cache.json sit alongside.
        overwrite: If True, ignore both caches and recompute everything.
        chapter_summaries: Optional {chapter_index: summary} from gold layer.
                           When provided, no LLM calls are made for summaries.

    Returns:
        The same list of nodes, mutated in-place with summaries and embeddings.
    """
    summary_cache_path = cache_path.parent / "summary_cache.json"
    embed_cache_path   = cache_path.parent / "embed_cache.json"

    summary_cache = _load_cache(summary_cache_path, overwrite)
    embed_cache   = _load_cache(embed_cache_path, overwrite)

    # ── summaries ─────────────────────────────────────────────────────────────
    summary_misses = [n for n in leaf_nodes if n.node_id not in summary_cache]
    print(f"[embedder] summaries: {len(leaf_nodes) - len(summary_misses)} cached, "
          f"{len(summary_misses)} to fetch")

    if summary_misses:
        if chapter_summaries is not None:
            # Use gold layer chapter summaries — no LLM calls
            for node in summary_misses:
                ch = node.metadata.get("chapter_index", -1)
                summary_cache[node.node_id] = chapter_summaries.get(ch, "")
        else:
            # Fallback: parallel Haiku calls
            llm_client = anthropic_sdk.Anthropic(api_key=anthropic_api_key)
            new_summaries = _summarize_batch(summary_misses, llm_client)
            for node, summary in zip(summary_misses, new_summaries):
                summary_cache[node.node_id] = summary
        _save_cache(summary_cache, summary_cache_path)

    # ── embeddings ────────────────────────────────────────────────────────────
    embed_misses = [n for n in leaf_nodes if n.node_id not in embed_cache]
    print(f"[embedder] embeddings: {len(leaf_nodes) - len(embed_misses)} cached, "
          f"{len(embed_misses)} to compute")

    if embed_misses:
        embed_model = HuggingFaceEmbedding(model_name=EMBED_MODEL_NAME)
        embed_texts = [
            _build_embed_text(n, summary_cache[n.node_id])
            for n in embed_misses
        ]
        new_embeddings = embed_model.get_text_embedding_batch(embed_texts, show_progress=True)
        for node, embedding in zip(embed_misses, new_embeddings):
            embed_cache[node.node_id] = embedding
        _save_cache(embed_cache, embed_cache_path)

    # ── attach to nodes ───────────────────────────────────────────────────────
    for node in leaf_nodes:
        node.metadata["section_summary"] = summary_cache[node.node_id]
        node.embedding = embed_cache[node.node_id]

    return leaf_nodes


def _summarize_batch(
    nodes: list[BaseNode],
    client: anthropic_sdk.Anthropic,
) -> list[str]:
    """Fetch summaries for all nodes in parallel, preserving order."""
    summaries: dict[int, str] = {}
    with ThreadPoolExecutor(max_workers=_SUMMARY_WORKERS) as pool:
        futures = {
            pool.submit(_summarize, node.text, client): i
            for i, node in enumerate(nodes)
        }
        done = 0
        for future in as_completed(futures):
            idx = futures[future]
            summaries[idx] = future.result()
            done += 1
            if done % 20 == 0:
                print(f"[embedder] summaries {done}/{len(nodes)}")
    return [summaries[i] for i in range(len(nodes))]


def _build_embed_text(node: BaseNode, summary: str) -> str:
    title = node.metadata.get("book_title", "")
    chapter = node.metadata.get("chapter_label", "")
    header = f"{title} | {chapter}" if title or chapter else ""
    parts = [p for p in [header, summary, node.text] if p]
    return "\n\n".join(parts)


def _summarize(text: str, client: anthropic_sdk.Anthropic) -> str:
    response = client.messages.create(
        model=EXTRACTION_MODEL,
        max_tokens=256,
        messages=[{"role": "user", "content": _SUMMARY_PROMPT.format(text=text)}],
    )
    return response.content[0].text.strip()


def _load_cache(path: Path, overwrite: bool) -> dict:
    if not overwrite and path.exists():
        return json.loads(path.read_text())
    return {}


def _save_cache(cache: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache))
    print(f"[embedder] saved {path.name} ({len(cache)} entries)")
