"""pgvector search + auto-merging retriever.

Replaces LlamaIndex's VectorStoreIndex + AutoMergingRetriever with direct
Supabase queries and ~30 lines of merge logic.

Auto-merge rule (same as LlamaIndex's AutoMergingRetriever):
  If >= merge_threshold leaf nodes from the same parent are retrieved,
  replace them with the parent (scene-level) node.

No StorageContext, no VectorStoreIndex, no framework magic.
"""

from collections import defaultdict

from llama_index.core.schema import BaseNode, NodeRelationship
from llama_index.core.storage.docstore.utils import json_to_doc
from llama_index.embeddings.huggingface import HuggingFaceEmbedding

from rag_pipeline.config import EMBED_MODEL_NAME
from rag_pipeline.node_store import NodeStore

_embed_model: HuggingFaceEmbedding | None = None


def _get_embed_model() -> HuggingFaceEmbedding:
    global _embed_model
    if _embed_model is None:
        _embed_model = HuggingFaceEmbedding(model_name=EMBED_MODEL_NAME)
    return _embed_model


def embed_query(query: str) -> list[float]:
    """Embed a query string using the same model as the stored leaf nodes."""
    return _get_embed_model().get_text_embedding(query)


def retrieve(
    query: str,
    node_store: NodeStore,
    reader_chapter: int,
    top_k: int = 6,
    merge_threshold: int = 2,
) -> list[BaseNode]:
    """Retrieve nodes for a query, with spoiler safety and auto-merging.

    Args:
        query: Natural language question.
        node_store: NodeStore scoped to the target series/book.
        reader_chapter: Only chunks from chapters <= this are considered.
        top_k: Number of leaf nodes to retrieve before merging.
        merge_threshold: Min siblings from the same parent to trigger a merge.

    Returns:
        List of BaseNode objects (leaf or merged parent).
    """
    query_embedding = embed_query(query)
    hits = node_store.search_nodes(query_embedding, reader_chapter, top_k)
    if not hits:
        return []
    return _auto_merge(hits, node_store, merge_threshold)


def _auto_merge(
    hits: list[dict],
    node_store: NodeStore,
    merge_threshold: int,
) -> list[BaseNode]:
    """Replace leaf groups with their parent when >= merge_threshold siblings hit."""
    # Fetch full node data for all hits
    hit_ids = [h["node_id"] for h in hits]
    node_data = node_store.get_nodes_by_ids(hit_ids)

    # Deserialise and group by parent
    nodes = {nid: json_to_doc(data) for nid, data in node_data.items()}
    parent_groups: dict[str, list[BaseNode]] = defaultdict(list)
    no_parent: list[BaseNode] = []

    for node in nodes.values():
        parent_info = node.relationships.get(NodeRelationship.PARENT)
        if parent_info:
            parent_groups[parent_info.node_id].append(node)
        else:
            no_parent.append(node)

    results: list[BaseNode] = list(no_parent)
    parent_ids_to_fetch: list[str] = []

    for parent_id, children in parent_groups.items():
        if len(children) >= merge_threshold:
            parent_ids_to_fetch.append(parent_id)
        else:
            results.extend(children)

    # Fetch and substitute parent nodes
    if parent_ids_to_fetch:
        parent_data = node_store.get_nodes_by_ids(parent_ids_to_fetch)
        for parent_id, data in parent_data.items():
            results.append(json_to_doc(data))
        # Remaining parents not found — fall back to leaves
        missing = set(parent_ids_to_fetch) - set(parent_data)
        for parent_id in missing:
            results.extend(parent_groups[parent_id])

    return results
