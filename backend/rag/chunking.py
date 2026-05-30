"""Hierarchical chunking via LlamaIndex HierarchicalNodeParser.

Produces a three-level tree per document:
  Level 0 (root)  — ~2048 tokens,
  Level 1         — ~512 tokens, 
  Level 2 (leaf)  — ~128 tokens, paragraph-sized, what gets embedded

Only leaf nodes are embedded and stored in the vector index. Parent nodes are
kept in the docstore so AutoMergingRetriever can promote leaves back to their
scene when enough of the same scene is retrieved.
"""

import uuid

from llama_index.core import Document
from llama_index.core.node_parser import (
    HierarchicalNodeParser,
    get_leaf_nodes,
    get_root_nodes,
)
from llama_index.core.schema import BaseNode

from backend.rag.config import CHUNK_SIZES

_NAMESPACE = uuid.UUID("b00c1e05-0000-0000-0000-000000000000")


def _assign_deterministic_ids(
    nodes: list[BaseNode], series_id: str, book_id: str
) -> None:
    """Replace random UUIDs with stable uuid5 hashes so reruns never create duplicates.

    Also remaps all parent/child relationship references so AutoMergingRetriever
    can still walk up the tree after IDs are changed.
    """
    old_to_new: dict[str, str] = {}
    for i, node in enumerate(nodes):
        new_id = str(uuid.uuid5(_NAMESPACE, f"{series_id}:{book_id}:{i}"))
        old_to_new[node.node_id] = new_id
        node.id_ = new_id

    # Remap relationship node_id references so parent↔child links stay consistent.
    # Values can be a single RelatedNodeInfo (PARENT/PREV/NEXT) or a list (CHILD).
    for node in nodes:
        for rel_info in node.relationships.values():
            items = rel_info if isinstance(rel_info, list) else [rel_info]
            for item in items:
                if item.node_id in old_to_new:
                    item.node_id = old_to_new[item.node_id]


def build_nodes(
    documents: list[Document],
    series_id: str,
    book_id: str,
) -> tuple[list[BaseNode], list[BaseNode]]:
    """Parse documents into a hierarchy and return (all_nodes, leaf_nodes).

    Node IDs are deterministic (uuid5) so the same chapters always produce
    the same IDs — safe to re-index without duplicates in Supabase or Neo4j.

    Args:
        documents: LlamaIndex Document objects (one per chapter).
        series_id: Series slug (e.g. "red-rising") — scopes node IDs.
        book_id: Book slug (e.g. "book_0") — scopes node IDs.

    Returns:
        all_nodes: Every node at every level — needed for the docstore.
        leaf_nodes: Only paragraph-level nodes — these get embedded.
    """
    parser = HierarchicalNodeParser.from_defaults(chunk_sizes=CHUNK_SIZES)
    all_nodes = parser.get_nodes_from_documents(documents)
    _assign_deterministic_ids(all_nodes, series_id, book_id)
    leaf_nodes = get_leaf_nodes(all_nodes)
    return all_nodes, leaf_nodes


def summarize_node_tree(all_nodes: list[BaseNode], leaf_nodes: list[BaseNode]) -> None:
    """Print a quick breakdown of the node tree for inspection."""
    root_nodes = get_root_nodes(all_nodes)
    mid_nodes  = [n for n in all_nodes if n not in leaf_nodes and n not in root_nodes]

    print(f"Total nodes : {len(all_nodes)}")
    print(f"  Root  (ch): {len(root_nodes)}")
    print(f"  Mid (scene): {len(mid_nodes)}")
    print(f"  Leaf (para): {len(leaf_nodes)}")
