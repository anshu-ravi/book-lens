-- RAG pipeline embedding store
-- Stores pgvector embeddings for leaf nodes only (paragraph-level chunks).
-- Separated from book_rag_nodes so the node table stays uniform (all nodes,
-- leaves + parents) while this table is purpose-built for ANN search.
--
-- Schema:
--   book_rag_nodes     — ALL nodes (leaves + parents), text + metadata JSONB
--   book_rag_embeddings — leaf nodes only, vector(384) for similarity search

create extension if not exists vector;

create table if not exists book_rag_embeddings (
    node_id       text        not null,
    series_id     text        not null,
    book_id       text        not null,
    chapter_index integer     not null,
    embedding     vector(384) not null,
    primary key (node_id, series_id, book_id),
    foreign key (node_id, series_id, book_id)
        references book_rag_nodes (node_id, series_id, book_id)
        on delete cascade
);

-- HNSW index: fast ANN search with no vacuuming requirement
create index if not exists book_rag_embeddings_hnsw_idx
    on book_rag_embeddings
    using hnsw (embedding vector_cosine_ops);

-- Composite index for spoiler gate + series/book scoping
create index if not exists book_rag_embeddings_lookup_idx
    on book_rag_embeddings (series_id, book_id, chapter_index);

-- RPC function for pgvector search — called via supabase.rpc("search_rag_nodes", {...})
-- Returns top_k leaf nodes closest to query_embedding, gated by reader_chapter.
--
-- Uses plpgsql + SET LOCAL hnsw.ef_search to work around HNSW pre-filtering:
-- HNSW fetches global top-k THEN applies WHERE, so early chapters get silently
-- dropped when the global nearest neighbours are all from later chapters.
-- ef_search=400 makes the index scan 400 candidates before the WHERE filter runs.
create or replace function search_rag_nodes(
    query_embedding  vector(384),
    p_series_id      text,
    p_book_id        text,
    p_reader_chapter integer,
    p_top_k          integer default 6
)
returns table (
    node_id       text,
    chapter_index integer,
    distance      double precision
)
language plpgsql volatile
as $$
begin
    set local hnsw.ef_search = 400;
    return query
    select
        e.node_id,
        e.chapter_index,
        (e.embedding <=> query_embedding)::double precision as distance
    from book_rag_embeddings e
    where e.series_id     = p_series_id
      and e.book_id       = p_book_id
      and e.chapter_index <= p_reader_chapter
    order by e.embedding <=> query_embedding
    limit p_top_k;
end;
$$;
