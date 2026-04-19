---
name: Enhanced Query Engine
description: Query engine extended with question type classification and entity-aware context assembly
type: project
---

Two new modules added to `src/query/`:

**`classifier.py`**: `classify_question(question)` → `QuestionType` enum. Heuristic regex patterns (no LLM call). Types: CHARACTER, CHARACTER_ARC, RELATIONSHIP, RECAP, WORLD_BUILDING, CAUSAL, DETAIL. Also `extract_entity_mentions(question, alias_registry)` — longest-match-first scan returning canonical names.

**`context_builder.py`**: `build_entity_context(question_type, entity_mentions, kb, max_tokens=2500)` — assembles structured knowledge from `KnowledgeBase` (characters, relationships, summaries, world facts) tailored to the question type. Token budget: rough `len(text.split()) * 1.4` estimate; drops sections from the end when over budget.

**`QueryRequest`** now includes `conversation_history: list[dict]` and `mode: str`. The ask view sends full conversation history; backend filters out error messages before forwarding to Claude.

**`ProactivePromptRequest/Response`**: New endpoint for proactive check-in questions after reading a chapter.

**Why:** Pure RAG wasn't enough for complex character/relationship questions. The knowledge graph (Phase 7) needed a routing layer to surface the right structured data per question type.
