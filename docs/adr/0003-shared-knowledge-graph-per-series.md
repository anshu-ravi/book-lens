# Knowledge Graph is shared per series, not isolated per reader

The Knowledge Graph in Neo4j is scoped by `series_id` only — all readers of the same series share one graph. The Prose Index in Supabase is scoped by both `series_id` and `user_id`, so each reader has their own copy.

Per-reader KG isolation was considered but deferred. The app serves a small, trusted circle of users (not the public), so the risk of cross-user data leakage is low and the operational cost of per-user graph isolation is not justified. If the user base grows or isolation becomes a requirement, `user_id` can be added as a scope to the Neo4j queries and ingestion pipeline.
