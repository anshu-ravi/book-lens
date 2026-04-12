# Prompt Engineering Notes

Learnings from Phase 5 prompt design for spoiler-safe Q&A.

---

## Prompt Structure

```
You are a spoiler-safe reading companion for the "{series.name}" series.

Your job is to answer questions based ONLY on the context passages provided below.
Do not use any knowledge beyond what is in these passages.
If the answer cannot be found in the passages, say:
"I don't have enough information from your reading so far to answer that."

Reading progress:
{reading_summary}

Context passages:
[1] (chapter_label, book N): {text}
[2] (chapter_label, book N): {text}
...

Question: {question}
```

---

## What Works

- **"ONLY on the context passages"** — explicit instruction to ignore model knowledge prevents hallucination about content the user hasn't read
- **Reading progress summary** — helps Claude contextualise which books/chapters are relevant without exposing what's ahead
- **Numbered passages with chapter labels** — gives Claude clear attribution anchors; tested well for factual questions
- **Fallback phrase in the prompt** — instructing Claude exactly what to say when it can't answer keeps the UX consistent

## What to Watch

- **Embedding quality limits retrieval** — `all-MiniLM-L6-v2` is small. Character/relationship questions work well; nuanced thematic questions may retrieve tangentially related chunks. Consider a larger model in Phase 7+.
- **Top-k tuning** — default `top_k=5` is a reasonable starting point. More context = better answers but longer prompts and slower responses.
- **Chapter label mismatch** — some epubs produce generic labels (e.g. "Section 46") which look odd in the prompt. Epub parsing improvements can clean this up.

## Spoiler Prevention Strategy

Spoilers are prevented at the **retrieval layer**, not the prompt layer:

1. `build_qdrant_filter()` constructs a Qdrant filter from `BookStatus` before any search happens
2. Chunks from NOT_STARTED books never reach the prompt
3. READING books are filtered to `chapter_index <= current_chapter_index`

This is more robust than relying on Claude to self-censor — the model never sees the spoiler content at all.

## Model Choice

`claude-haiku-4-5` (configured as `settings.llm_model`):
- Fast and cheap for a personal reading companion
- Handles structured context-grounded Q&A well
- Upgrade to Sonnet if answer quality feels insufficient for complex multi-book questions
