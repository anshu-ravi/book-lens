-- RAG pipeline node store
-- Stores serialized LlamaIndex nodes (text, metadata, parent/child relationships)
-- scoped per (series_id, book_id). Used by SupabaseDocumentStore as the
-- persistent backend for AutoMergingRetriever.
--
-- Naming convention: {entity}_{qualifier}
-- Matches: books, book_chunks, book_extractions

create table if not exists book_rag_nodes (
    node_id     text    not null,
    series_id   text    not null,
    book_id     text    not null,
    data        jsonb   not null,
    primary key (node_id, series_id, book_id)
);

-- Fast scoped lookups by series + book (used on every retrieval)
create index if not exists book_rag_nodes_series_book_idx
    on book_rag_nodes (series_id, book_id);
