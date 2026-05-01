# LLM Provider Wrapper — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace all direct Anthropic SDK calls with a provider-agnostic `LLMClient` wrapper; make Gemini the default provider; keep both providers switchable via `config.toml`.

**Architecture:** A `Protocol`-based `LLMClient` with `generate()` and `extract_structured()` methods. `AnthropicLLMClient` and `GeminiLLMClient` each implement it. A factory reads `config.toml` and returns the right one. All call sites receive `LLMClient` — they never know which provider is active.

**Tech Stack:** Python 3.11, FastAPI, `google-genai` (Gemini async SDK), `anthropic` (kept for fallback), `tomllib` (stdlib), Poetry

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `config.toml` | Create | Provider + model selection (committed, no secrets) |
| `src/config.py` | Modify | Load TOML; derive `llm_provider`, `llm_model`, `extraction_model` from it |
| `pyproject.toml` | Modify | Add `google-genai ^1.0` dependency |
| `src/llm/__init__.py` | Create | Re-export `LLMClient`, `create_llm_client` |
| `src/llm/client.py` | Create | `LLMClient` Protocol + `create_llm_client` factory |
| `src/llm/anthropic.py` | Create | `AnthropicLLMClient` — wraps `anthropic.AsyncAnthropic` |
| `src/llm/gemini.py` | Create | `GeminiLLMClient` — wraps `google.genai.Client` async API |
| `src/knowledge/extractor.py` | Modify | Replace `anthropic.AsyncAnthropic` with `LLMClient`; `messages.create(tools=...)` → `extract_structured(...)` |
| `src/knowledge/pipeline.py` | Modify | Type hint only: `anthropic.AsyncAnthropic` → `LLMClient` |
| `src/graph/digest.py` | Modify | `anthropic.AsyncAnthropic` → `LLMClient`; `messages.create` → `generate()` |
| `src/main.py` | Modify | Lifespan creates `LLMClient` via factory; two inline `messages.create` → `generate()` |
| `tests/manual/test_llm_client.py` | Create | Smoke tests hitting real APIs |

---

## Task 1: Config — `config.toml` + `src/config.py` + dependency

**Files:**
- Create: `config.toml`
- Modify: `src/config.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: Add `google-genai` to pyproject.toml**

Run:
```bash
cd /path/to/book-lens && poetry add "google-genai>=1.0"
```
Expected: resolves and installs without error. `pyproject.toml` gains a `google-genai` entry.

- [ ] **Step 2: Create `config.toml` at the project root**

```toml
[llm]
provider = "gemini"   # "gemini" or "anthropic"

[llm.gemini]
model = "gemini-2.0-flash"
extraction_model = "gemini-2.0-flash"

[llm.anthropic]
model = "claude-haiku-4-5-20251001"
extraction_model = "claude-haiku-4-5-20251001"
```

- [ ] **Step 3: Rewrite `src/config.py`**

Replace the entire file:

```python
"""Application configuration and settings."""

import tomllib
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings


def _load_toml() -> dict:
    """Load config.toml from the project root (next to pyproject.toml)."""
    path = Path(__file__).parent.parent / "config.toml"
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except FileNotFoundError:
        return {}


_toml = _load_toml()
_llm = _toml.get("llm", {})
_provider = _llm.get("provider", "anthropic")
_provider_cfg = _llm.get(_provider, {})


class Settings(BaseSettings):
    """Application settings.

    LLM provider and model are read from config.toml.
    API keys and infrastructure settings come from .env.
    Env vars override TOML values (pydantic-settings precedence).
    """

    # Infrastructure
    supabase_url: str
    supabase_key: str
    supabase_anon_key: Optional[str] = None

    # API keys (stay in .env, never in config.toml)
    anthropic_api_key: str = ""
    gemini_api_key: str = ""

    # LLM provider — derived from config.toml, overridable by env var
    llm_provider: str = _provider
    llm_model: str = _provider_cfg.get("model", "claude-haiku-4-5-20251001")
    extraction_model: str = _provider_cfg.get("extraction_model", "claude-haiku-4-5-20251001")

    # Embeddings + chunking (unchanged)
    embedding_model: str = "all-MiniLM-L6-v2"
    chunk_size: int = 400
    chunk_overlap: int = 50

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()  # type: ignore[call-arg]
```

- [ ] **Step 4: Verify import and TOML loading**

```bash
poetry run python -c "
from src.config import settings
print('provider:', settings.llm_provider)
print('llm_model:', settings.llm_model)
print('extraction_model:', settings.extraction_model)
"
```
Expected:
```
provider: gemini
llm_model: gemini-2.0-flash
extraction_model: gemini-2.0-flash
```

- [ ] **Step 5: Add `GEMINI_API_KEY` to `.env.example`**

Open `.env.example` and add (do NOT read or modify `.env`):
```
GEMINI_API_KEY=your-gemini-api-key-here
```

---

## Task 2: `LLMClient` Protocol + factory

**Files:**
- Create: `src/llm/__init__.py`
- Create: `src/llm/client.py`

- [ ] **Step 1: Create `src/llm/__init__.py`**

```python
from src.llm.client import LLMClient, create_llm_client

__all__ = ["LLMClient", "create_llm_client"]
```

- [ ] **Step 2: Create `src/llm/client.py`**

```python
"""Provider-agnostic LLM client protocol and factory."""

from typing import Protocol, runtime_checkable

from src.config import settings


@runtime_checkable
class LLMClient(Protocol):
    """Minimal async LLM interface used throughout BookLens.

    Implementations: AnthropicLLMClient, GeminiLLMClient.
    """

    async def generate(
        self,
        messages: list[dict],
        max_tokens: int,
    ) -> str:
        """Send a chat conversation and return the assistant's text reply.

        Args:
            messages: List of {"role": "user"|"assistant", "content": str} dicts.
            max_tokens: Maximum tokens in the reply.

        Returns:
            Assistant reply as a plain string.
        """
        ...

    async def extract_structured(
        self,
        messages: list[dict],
        tool_name: str,
        tool_description: str,
        tool_schema: dict,
        max_tokens: int,
    ) -> dict:
        """Force the model to call a named function and return its arguments.

        The tool_schema is standard JSON Schema (OpenAPI style):
            {"type": "object", "properties": {...}, "required": [...]}

        Each implementation translates this to its provider's native format.

        Args:
            messages: Conversation so far (typically a single user message).
            tool_name: Name of the function the model must call.
            tool_description: What the function does (used by Gemini).
            tool_schema: JSON Schema describing the function's parameters.
            max_tokens: Maximum tokens in the reply.

        Returns:
            Dict matching the tool_schema — the model's structured output.
        """
        ...


def create_llm_client() -> LLMClient:
    """Instantiate the LLMClient configured in config.toml.

    Reads settings.llm_provider and returns the matching implementation.
    """
    provider = settings.llm_provider
    if provider == "gemini":
        from src.llm.gemini import GeminiLLMClient
        return GeminiLLMClient(
            api_key=settings.gemini_api_key,
            model=settings.llm_model,
            extraction_model=settings.extraction_model,
        )
    if provider == "anthropic":
        from src.llm.anthropic import AnthropicLLMClient
        return AnthropicLLMClient(
            api_key=settings.anthropic_api_key,
            model=settings.llm_model,
            extraction_model=settings.extraction_model,
        )
    raise ValueError(f"Unknown LLM provider: {provider!r}. Choose 'gemini' or 'anthropic'.")
```

- [ ] **Step 3: Verify import**

```bash
poetry run python -c "from src.llm import LLMClient, create_llm_client; print('OK')"
```
Expected: `OK`

---

## Task 3: `AnthropicLLMClient`

**Files:**
- Create: `src/llm/anthropic.py`

- [ ] **Step 1: Create `src/llm/anthropic.py`**

```python
"""Anthropic implementation of LLMClient."""

import anthropic


class AnthropicLLMClient:
    """LLMClient backed by Anthropic's Claude models."""

    def __init__(self, api_key: str, model: str, extraction_model: str) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model
        self._extraction_model = extraction_model

    async def generate(self, messages: list[dict], max_tokens: int) -> str:
        """Send messages and return the assistant's text reply."""
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            messages=messages,
        )
        return response.content[0].text

    async def extract_structured(
        self,
        messages: list[dict],
        tool_name: str,
        tool_description: str,
        tool_schema: dict,
        max_tokens: int,
    ) -> dict:
        """Force Claude to call tool_name and return its input dict."""
        tool_def = {
            "name": tool_name,
            "description": tool_description,
            "input_schema": tool_schema,
        }
        response = await self._client.messages.create(
            model=self._extraction_model,
            max_tokens=max_tokens,
            tools=[tool_def],
            tool_choice={"type": "tool", "name": tool_name},
            messages=messages,
        )
        tool_block = response.content[0]
        if tool_block.type != "tool_use":
            raise RuntimeError(
                f"Anthropic: expected tool_use block, got {tool_block.type!r}"
            )
        return tool_block.input  # type: ignore[return-value]
```

- [ ] **Step 2: Verify import**

```bash
poetry run python -c "from src.llm.anthropic import AnthropicLLMClient; print('OK')"
```
Expected: `OK`

---

## Task 4: `GeminiLLMClient`

**Files:**
- Create: `src/llm/gemini.py`

- [ ] **Step 1: Create `src/llm/gemini.py`**

```python
"""Gemini implementation of LLMClient using google-genai async API."""

from google import genai
from google.genai import types


class GeminiLLMClient:
    """LLMClient backed by Google's Gemini models."""

    def __init__(self, api_key: str, model: str, extraction_model: str) -> None:
        self._client = genai.Client(api_key=api_key)
        self._model = model
        self._extraction_model = extraction_model

    async def generate(self, messages: list[dict], max_tokens: int) -> str:
        """Send messages and return the assistant's text reply.

        Converts the OpenAI-style messages list to Gemini's Content format.
        Gemini uses "model" where OpenAI/Anthropic use "assistant".
        """
        contents = []
        for msg in messages:
            role = "model" if msg["role"] == "assistant" else "user"
            contents.append(
                types.Content(role=role, parts=[types.Part(text=msg["content"])])
            )

        response = await self._client.aio.models.generate_content(
            model=self._model,
            contents=contents,
            config=types.GenerateContentConfig(max_output_tokens=max_tokens),
        )
        return response.text

    async def extract_structured(
        self,
        messages: list[dict],
        tool_name: str,
        tool_description: str,
        tool_schema: dict,
        max_tokens: int,
    ) -> dict:
        """Force Gemini to call tool_name via function calling and return its args."""
        # Gemini function declarations use "parameters" (same JSON Schema shape).
        func_decl = types.FunctionDeclaration(
            name=tool_name,
            description=tool_description,
            parameters=tool_schema,
        )
        tool = types.Tool(function_declarations=[func_decl])
        tool_config = types.ToolConfig(
            function_calling_config=types.FunctionCallingConfig(
                mode="ANY",
                allowed_function_names=[tool_name],
            )
        )

        # Extraction is always a single user message.
        prompt = messages[0]["content"] if messages else ""

        response = await self._client.aio.models.generate_content(
            model=self._extraction_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[tool],
                tool_config=tool_config,
                max_output_tokens=max_tokens,
            ),
        )

        part = response.candidates[0].content.parts[0]
        if not part.function_call:
            raise RuntimeError(
                f"Gemini: expected function_call in response, got: {part!r}"
            )
        return dict(part.function_call.args)
```

- [ ] **Step 2: Verify import**

```bash
poetry run python -c "from src.llm.gemini import GeminiLLMClient; print('OK')"
```
Expected: `OK`

---

## Task 5: Smoke tests for both implementations

**Files:**
- Create: `tests/manual/test_llm_client.py`

- [ ] **Step 1: Create `tests/manual/test_llm_client.py`**

```python
"""Manual smoke tests for LLMClient implementations.

Run with: poetry run pytest tests/manual/test_llm_client.py -v
Requires real API keys in .env. Hits live APIs.
"""

import asyncio
import pytest
from src.llm import create_llm_client

# Minimal JSON Schema for a simple structured output test
_TEST_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string", "description": "A one-word answer."},
    },
    "required": ["answer"],
}


def test_generate_returns_string():
    """create_llm_client().generate() returns a non-empty string."""
    client = create_llm_client()
    result = asyncio.run(
        client.generate(
            messages=[{"role": "user", "content": "Reply with the single word: hello"}],
            max_tokens=20,
        )
    )
    assert isinstance(result, str)
    assert len(result.strip()) > 0


def test_extract_structured_returns_dict():
    """create_llm_client().extract_structured() returns a dict matching the schema."""
    client = create_llm_client()
    result = asyncio.run(
        client.extract_structured(
            messages=[{"role": "user", "content": "What is 2 + 2? Use the tool to record your answer."}],
            tool_name="record_answer",
            tool_description="Record a one-word answer.",
            tool_schema=_TEST_SCHEMA,
            max_tokens=100,
        )
    )
    assert isinstance(result, dict)
    assert "answer" in result
    assert isinstance(result["answer"], str)
```

- [ ] **Step 2: Run smoke tests**

```bash
poetry run pytest tests/manual/test_llm_client.py -v
```
Expected: 2 passed (both tests make live API calls).

If Gemini is the active provider and `gemini_api_key` is not set in `.env`, add it first.

---

## Task 6: Update `src/knowledge/extractor.py`

**Files:**
- Modify: `src/knowledge/extractor.py`

The current code uses `client: anthropic.AsyncAnthropic` and calls `client.messages.create(tools=..., tool_choice=...)`. Replace with `LLMClient.extract_structured()`.

The `_EXTRACTION_TOOL` dict currently has Anthropic's format:
```python
{"name": "...", "description": "...", "input_schema": {...}}
```
Split it into separate constants: `_TOOL_NAME`, `_TOOL_DESCRIPTION`, `_TOOL_SCHEMA`.

- [ ] **Step 1: Replace the `_EXTRACTION_TOOL` definition**

Read `src/knowledge/extractor.py` first. The `_EXTRACTION_TOOL` dict has this structure:

```python
_EXTRACTION_TOOL: Any = {
    "name": "record_chapter_knowledge",
    "description": (...),
    "input_schema": {
        ...many lines...
    },
}   # <-- this outer closing brace is the one to remove
```

Make two edits:

**Edit A** — replace the opening three lines:
```python
_EXTRACTION_TOOL: Any = {
    "name": "record_chapter_knowledge",
    "description": (
        "Record all structured knowledge extracted from this fiction chapter: "
        "characters, relationships between them, world-building facts, and a summary."
    ),
    "input_schema": {
```
with:
```python
_TOOL_NAME = "record_chapter_knowledge"
_TOOL_DESCRIPTION = (
    "Record all structured knowledge extracted from this fiction chapter: "
    "characters, relationships between them, world-building facts, and a summary."
)
_TOOL_SCHEMA: dict = {
```

**Edit B** — the `_EXTRACTION_TOOL` dict ends with two closing lines that look like:
```
    },
}
```
where the `},` closes `"input_schema"` and the bare `}` closes `_EXTRACTION_TOOL`. After Edit A, `_TOOL_SCHEMA` wraps only what was `input_schema`, so remove the trailing bare `}`. The result should end with just:
```
    },
```
(closing the last property inside the schema, then the schema itself closes with `}`).

Verify by running: `poetry run python -c "from src.knowledge.extractor import _TOOL_NAME, _TOOL_SCHEMA; print(_TOOL_NAME)"` — should print `record_chapter_knowledge`.

- [ ] **Step 2: Update the import and `extract_chapter` signature**

Find:
```python
import anthropic
```
Replace with:
```python
from src.llm import LLMClient
```

Find:
```python
async def extract_chapter(
    chapter: ParsedChapter,
    book_index: int,
    kb: KnowledgeBase,
    client: anthropic.AsyncAnthropic,
    extraction_model: str,
) -> ChapterExtraction:
    """Extract structured knowledge from a single chapter using Claude tool_use."""
```
Replace with:
```python
async def extract_chapter(
    chapter: ParsedChapter,
    book_index: int,
    kb: KnowledgeBase,
    client: LLMClient,
    extraction_model: str,
) -> ChapterExtraction:
    """Extract structured knowledge from a single chapter using the configured LLM."""
```

Note: `extraction_model` parameter is kept for signature compatibility but the LLMClient now owns the model choice internally. It is unused — leave it in place to avoid changing all callers in this task.

- [ ] **Step 3: Replace the `client.messages.create` call**

Find:
```python
    response = await client.messages.create(
        model=extraction_model,
        max_tokens=4096,
        tools=[_EXTRACTION_TOOL],
        tool_choice={"type": "tool", "name": "record_chapter_knowledge"},
        messages=[{"role": "user", "content": prompt}],
    )

    tool_block = response.content[0]
    if tool_block.type != "tool_use":
        raise RuntimeError(
            f"Expected tool_use block from Claude, got: {tool_block.type!r}"
        )

    input_data: dict = tool_block.input  # type: ignore[assignment]
```
Replace with:
```python
    input_data: dict = await client.extract_structured(
        messages=[{"role": "user", "content": prompt}],
        tool_name=_TOOL_NAME,
        tool_description=_TOOL_DESCRIPTION,
        tool_schema=_TOOL_SCHEMA,
        max_tokens=4096,
    )
```

- [ ] **Step 4: Remove unused `Any` import if it was only used for `_EXTRACTION_TOOL`**

Check the top of the file. If `from typing import Any` was only used for `_EXTRACTION_TOOL: Any`, remove `Any` from the import. Otherwise leave it.

- [ ] **Step 5: Import check**

```bash
poetry run python -c "from src.knowledge.extractor import extract_chapter; print('OK')"
```
Expected: `OK`

---

## Task 7: Update `src/knowledge/pipeline.py` and `src/graph/digest.py`

**Files:**
- Modify: `src/knowledge/pipeline.py`
- Modify: `src/graph/digest.py`

### pipeline.py

- [ ] **Step 1: Update import and type hint in pipeline.py**

Find:
```python
import anthropic
```
Replace with:
```python
from src.llm import LLMClient
```

Find:
```python
    client: anthropic.AsyncAnthropic,
```
Replace with:
```python
    client: LLMClient,
```

Find in the docstring:
```python
        client: Anthropic async client.
```
Replace with:
```python
        client: LLM client (provider-agnostic).
```

- [ ] **Step 2: Import check for pipeline**

```bash
poetry run python -c "from src.knowledge.pipeline import extract_book_knowledge; print('OK')"
```
Expected: `OK`

### digest.py

- [ ] **Step 3: Update import and signature in digest.py**

Find:
```python
import anthropic
```
Replace with:
```python
from src.llm import LLMClient
```

Find:
```python
    client: anthropic.AsyncAnthropic,
```
Replace with:
```python
    client: LLMClient,
```

Find in the docstring:
```python
        client: AsyncAnthropic client from app state.
```
Replace with:
```python
        client: LLM client (provider-agnostic).
```

- [ ] **Step 4: Replace `client.messages.create` in digest.py**

Find:
```python
    message = await client.messages.create(
        model=model,
        max_tokens=800,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text
```
Replace with:
```python
    return await client.generate(
        messages=[{"role": "user", "content": prompt}],
        max_tokens=800,
    )
```

The `model` parameter stays in `generate_digest`'s signature for compatibility but is now unused (the client owns the model). Leave it.

- [ ] **Step 5: Import check for digest**

```bash
poetry run python -c "from src.graph.digest import generate_digest; print('OK')"
```
Expected: `OK`

---

## Task 8: Update `src/main.py`

**Files:**
- Modify: `src/main.py`

Four changes: import, lifespan, proactive prompt endpoint, query endpoint.

- [ ] **Step 1: Update imports**

Find:
```python
import anthropic
```
Replace with:
```python
from src.llm import LLMClient, create_llm_client
```

- [ ] **Step 2: Update lifespan**

Find:
```python
    app.state.anthropic_client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
```
Replace with:
```python
    app.state.llm_client = create_llm_client()
```

- [ ] **Step 3: Update `_run_extraction_background`**

Find:
```python
    anthropic_client: anthropic.AsyncAnthropic,
```
Replace with:
```python
    llm_client: LLMClient,
```

Find:
```python
        await extract_book_knowledge(
            chapters=parsed_chapters,
            canonical_series_id=canonical_series_id,
            book_index=book_index,
            client=anthropic_client,
            extraction_model=settings.extraction_model,
        )
```
Replace with:
```python
        await extract_book_knowledge(
            chapters=parsed_chapters,
            canonical_series_id=canonical_series_id,
            book_index=book_index,
            client=llm_client,
            extraction_model=settings.extraction_model,
        )
```

- [ ] **Step 4: Update all callers that pass `request.app.state.anthropic_client`**

There are several places in `main.py` that pass `request.app.state.anthropic_client` — to `_run_extraction_background`, `generate_digest`, and direct `messages.create` calls. Replace every occurrence:

```
request.app.state.anthropic_client  →  request.app.state.llm_client
```

Use find-and-replace across the file.

- [ ] **Step 5: Replace the inline `messages.create` call in the proactive prompt endpoint**

Find (in `generate_proactive_prompt_endpoint`):
```python
    anthropic_client: anthropic.AsyncAnthropic = request.app.state.anthropic_client
    message = await anthropic_client.messages.create(
        model=settings.llm_model,
        max_tokens=150,
        messages=[{"role": "user", "content": prompt}],
    )
    return ProactivePromptResponse(question=message.content[0].text)
```
Replace with:
```python
    llm_client: LLMClient = request.app.state.llm_client
    answer = await llm_client.generate(
        messages=[{"role": "user", "content": prompt}],
        max_tokens=150,
    )
    return ProactivePromptResponse(question=answer)
```

- [ ] **Step 6: Replace the inline `messages.create` call in `query_endpoint`**

Find (in `query_endpoint`):
```python
    anthropic_client: anthropic.AsyncAnthropic = request.app.state.anthropic_client
    message = await anthropic_client.messages.create(
        model=settings.llm_model,
        max_tokens=1024,
        messages=[
            *history,
            {"role": "user", "content": prompt},
        ],
    )
    answer = message.content[0].text
```
Replace with:
```python
    llm_client: LLMClient = request.app.state.llm_client
    answer = await llm_client.generate(
        messages=[
            *history,
            {"role": "user", "content": prompt},
        ],
        max_tokens=1024,
    )
```

- [ ] **Step 7: Update the `generate_digest` call**

Find (in the graph digest endpoint):
```python
    anthropic_client: anthropic.AsyncAnthropic = request.app.state.anthropic_client
    digest = await generate_digest(
        kb, from_book, from_chapter, to_book, to_chapter,
        client=anthropic_client,
        model=settings.llm_model,
    )
```
Replace with:
```python
    llm_client: LLMClient = request.app.state.llm_client
    digest = await generate_digest(
        kb, from_book, from_chapter, to_book, to_chapter,
        client=llm_client,
        model=settings.llm_model,
    )
```

- [ ] **Step 8: Full import check**

```bash
poetry run python -c "from src.main import app; print('OK')"
```
Expected: `OK`

---

## Self-Review Checklist (for implementer)

After completing all tasks, verify:

- [ ] `poetry run python -c "from src.main import app; print('OK')"` passes
- [ ] `poetry run pytest tests/manual/test_llm_client.py -v` — both tests pass against the active provider
- [ ] No remaining `anthropic.AsyncAnthropic` references in non-llm src files: `grep -r "AsyncAnthropic" src/ --include="*.py"` should only show `src/llm/anthropic.py`
- [ ] No remaining `client.messages.create` calls outside `src/llm/`: `grep -r "messages.create" src/ --include="*.py"` should be empty
- [ ] `config.toml` is in `.gitignore`? No — it should be **committed** (no secrets in it). Confirm `.env` is gitignored and `config.toml` is not.
