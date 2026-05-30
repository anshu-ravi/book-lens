-- RAG pipeline node hash store
-- Stores content hashes for each node, used by LlamaIndex IngestionPipeline
-- to skip re-processing nodes that haven't changed between runs.
-- Scoped per (series_id, book_id), mirrors book_rag_nodes structure.

create table if not exists book_rag_node_hashes (
    node_id     text    not null,
    series_id   text    not null,
    book_id     text    not null,
    hash        text    not null,
    primary key (node_id, series_id, book_id)
);

create index if not exists book_rag_node_hashes_series_book_idx
    on book_rag_node_hashes (series_id, book_id);
