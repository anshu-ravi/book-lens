# %%
# %load_ext autoreload
# %autoreload 2

#%%
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

os.environ["NEO4J_ENV"] = "dev"
os.environ["NEO4J_URI"] = "bolt://localhost:7688"

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
assert ANTHROPIC_API_KEY, "ANTHROPIC_API_KEY not set in .env"

import anthropic as anthropic_sdk

from rag_pipeline.config import (
    BOOK_PATH,
    BOOK_ID,
    CACHE_DIR,
    CHAPTERS_TO_PROCESS,
    GENERATION_MODEL,
    SERIES_ID,
    USER_ID,
)
from rag_pipeline.chunking import build_nodes, summarize_node_tree
from rag_pipeline.embedder import embed_and_summarize, load_chapter_summaries
from rag_pipeline.node_store import NodeStore
from rag_pipeline.parsing import load_documents
from rag_pipeline.retriever import retrieve
from src.knowledge.neo4j_client import close_driver, get_driver
from src.knowledge.query import KnowledgeQueryEngine
from src.supabase_client import get_supabase_client

# %% ── Step 1: Parse EPUB ─────────────────────────────────────────────────────
documents = load_documents(BOOK_PATH, limit=CHAPTERS_TO_PROCESS, book_title="Red Rising")

print(f"Loaded {len(documents)} chapters")
for doc in documents:
    m = doc.metadata
    print(f"  [{m['chapter_index']:2d}] {m['chapter_label']:<35} {len(doc.text.split()):,} words")

# %% ── Step 2: Hierarchical Chunking ─────────────────────────────────────────
all_nodes, leaf_nodes = build_nodes(documents, series_id=SERIES_ID, book_id=BOOK_ID)
summarize_node_tree(all_nodes, leaf_nodes)

# %% ── Step 3: Embed + Summarise (disk-cached) ────────────────────────────────
# Summaries come from the gold layer (deduped_chapters.json in Supabase Storage)
# — no Anthropic API calls needed. Embeddings are batched via HuggingFace.
# Subsequent runs load both from disk cache — zero API or model calls.
supabase = get_supabase_client()
chapter_summaries = load_chapter_summaries(supabase, USER_ID, SERIES_ID, BOOK_ID)
print(f"[runner] Loaded {len(chapter_summaries)} chapter summaries from gold layer")

leaf_nodes = embed_and_summarize(
    leaf_nodes,
    anthropic_api_key=ANTHROPIC_API_KEY,
    cache_path=CACHE_DIR / "embed_cache.json",
    chapter_summaries=chapter_summaries,
)

# %% ── Step 4: Persist to Supabase — only new nodes ──────────────────────────
store = NodeStore(supabase, series_id=SERIES_ID, book_id=BOOK_ID)

existing_ids = store.get_existing_node_ids()
new_nodes = [n for n in all_nodes if n.node_id not in existing_ids]
new_leaves = [n for n in leaf_nodes if n.node_id not in existing_ids]

print(f"[store] {len(existing_ids)} nodes already stored — "
      f"writing {len(new_nodes)} new nodes, {len(new_leaves)} new embeddings")

if new_nodes:
    store.upsert_nodes(new_nodes)
if new_leaves:
    store.upsert_embeddings(new_leaves)

# %% ── Step 5: Hybrid retrieval (vector + graph) ─────────────────────────────
READER_CHAPTER = 3

# Vector path — pgvector ANN search + auto-merging
vector_results = retrieve(
    query="What is Darrow's relationship with Eo?",
    node_store=store,
    reader_chapter=READER_CHAPTER,
    top_k=6,
    merge_threshold=2,
)

print(f"\nVector results ({len(vector_results)} nodes):")
for node in vector_results:
    ch = node.metadata.get("chapter_index", "?")
    label = node.metadata.get("chapter_label", "")
    print(f"  [Ch {ch}] {label}: {node.text[:100]}...")

# Graph path — src/knowledge/query.py, spoiler-gated
close_driver()  # reset singleton so env overrides take effect
kg = KnowledgeQueryEngine(series_id=SERIES_ID, driver=get_driver())
graph_context = kg.get_graph_context("Darrow Eo relationship", up_to_chapter=READER_CHAPTER)

print(f"\nGraph context:\n{graph_context}")

# %% ── Step 6: Answer generation ──────────────────────────────────────────────
_GENERATION_PROMPT = """\
You are a reading companion for "Red Rising" by Pierce Brown. \
Think of yourself as a friend who has read the book and is talking with someone who is reading it now. \
Answer their question naturally, the way you would explain something to a friend over coffee — \
no bullet points, no headers, no structured lists unless the question is genuinely asking you \
to compare or list multiple distinct things. Just talk to them.

Match your answer length to the question. Default to short — two or three sentences for most questions. \
Only go longer if the person is explicitly asking you to explain something in depth, \
walk through an event, or explore a theme. If they ask "who is X" or "what is X", \
give them the essential answer and stop. They'll ask follow-up questions if they want more.

Draw on the facts and passages below to make your answer accurate, \
but weave them in naturally rather than citing them mechanically. \
If a chapter detail matters, mention it in passing ("early on..." or "right from the start..."). \
If the context doesn't give you enough to answer well, say so plainly.


=== GRAPH FACTS ===
{graph_context}

=== NARRATIVE PASSAGES ===
{vector_context}

=== QUESTION ===
{query}
"""


def answer_question(query: str, reader_chapter: int) -> str:
    v_nodes = retrieve(query, store, reader_chapter=reader_chapter)

    vector_context = "\n\n---\n\n".join(n.text[:600] for n in v_nodes)
    graph_context = kg.get_graph_context(query, up_to_chapter=reader_chapter)

    prompt = _GENERATION_PROMPT.format(
        graph_context=graph_context or "No graph facts found.",
        vector_context=vector_context or "No passages found.",
        query=query,
    )

    client = anthropic_sdk.Anthropic(api_key=ANTHROPIC_API_KEY)
    response = client.messages.create(
        model=GENERATION_MODEL,
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text.strip()


READER_CHAPTER = 3
questions = [
    "Who is Eo?",
    "What is Darrow's job?",
    "What is the Society?",
]

for q in questions:
    print(f"\nQ: {q}")
    print(f"A: {answer_question(q, reader_chapter=READER_CHAPTER)}")
    print("-" * 60)

# %%
