# LLM Provider Wrapper — Design Spec

**Date:** 2026-04-26
**Status:** Approved

## Goal

Replace all direct Anthropic SDK calls with a provider-agnostic `LLMClient` wrapper. Default provider switches to Gemini. Provider and model are configurable via `config.toml` without touching code.

---

## Config

### `config.toml` (project root, committed)

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

- Switching providers: change `provider` and restart.
- Switching models: change the model string under the provider block.
- API keys stay in `.env` — never in `config.toml`.

### `src/config.py` changes

Load `config.toml` with `tomllib` (Python 3.11 stdlib) at module level. Derive `llm_model`, `extraction_model`, and the active API key from the TOML + env:

```python
import tomllib

def _load_toml() -> dict:
    try:
        with open("config.toml", "rb") as f:
            return tomllib.load(f)
    except FileNotFoundError:
        return {}

_toml = _load_toml()
_llm = _toml.get("llm", {})
_provider = _llm.get("provider", "anthropic")
_provider_cfg = _llm.get(_provider, {})

class Settings(BaseSettings):
    # existing fields ...
    anthropic_api_key: str = ""
    gemini_api_key: str = ""

    llm_provider: str = _provider
    llm_model: str = _provider_cfg.get("model", "claude-haiku-4-5-20251001")
    extraction_model: str = _provider_cfg.get("extraction_model", "claude-haiku-4-5-20251001")
```

Env vars (e.g. `LLM_MODEL`) still override TOML values thanks to pydantic-settings precedence.

---

## Wrapper Architecture

### New package: `src/llm/`

```
src/llm/
  __init__.py       # re-exports LLMClient, create_llm_client
  client.py         # Protocol definition + factory
  anthropic.py      # AnthropicLLMClient
  gemini.py         # GeminiLLMClient
```

### `src/llm/client.py`

```python
class LLMClient(Protocol):
    async def generate(
        self,
        messages: list[dict],   # [{"role": "user"|"assistant", "content": str}]
        max_tokens: int,
    ) -> str: ...

    async def extract_structured(
        self,
        messages: list[dict],
        tool_name: str,
        tool_schema: dict,      # JSON Schema (OpenAPI style)
        max_tokens: int,
    ) -> dict: ...

def create_llm_client() -> LLMClient:
    """Read settings and instantiate the right implementation."""
    provider = settings.llm_provider
    if provider == "gemini":
        return GeminiLLMClient(api_key=settings.gemini_api_key, model=settings.llm_model, extraction_model=settings.extraction_model)
    return AnthropicLLMClient(api_key=settings.anthropic_api_key, model=settings.llm_model, extraction_model=settings.extraction_model)
```

### `src/llm/anthropic.py` — `AnthropicLLMClient`

- `generate`: calls `client.messages.create(model, max_tokens, messages)`, returns `response.content[0].text`.
- `extract_structured`: wraps schema as Anthropic tool (`{"name": tool_name, "input_schema": tool_schema}`), calls `messages.create(tools=..., tool_choice={"type": "tool", "name": tool_name})`, returns `response.content[0].input` (already a dict).

### `src/llm/gemini.py` — `GeminiLLMClient`

- Uses `google-genai` async client (`google.genai.Client(api_key=...)`).
- `generate`: calls `client.aio.models.generate_content(model, contents=prompt_text)`, returns `response.text`.
- `extract_structured`: wraps schema as Gemini `FunctionDeclaration` (`{"name": tool_name, "parameters": tool_schema}`), calls with `tool_config` set to `ANY` mode restricted to `tool_name`, returns `dict(response.candidates[0].content.parts[0].function_call.args)`.

### Tool schema common format

Both implementations receive a standard JSON Schema dict:

```python
{
    "type": "object",
    "properties": {
        "field": {"type": "string", "description": "..."},
        ...
    },
    "required": ["field", ...]
}
```

Each implementation converts this internally to its provider's native format. No translation logic leaks into call sites.

---

## Call Site Changes

| File | Change |
|------|--------|
| `src/knowledge/extractor.py` | `client: anthropic.AsyncAnthropic` → `client: LLMClient`; `messages.create(tools=...)` → `client.extract_structured(...)` |
| `src/knowledge/pipeline.py` | Type hint only: `anthropic.AsyncAnthropic` → `LLMClient` |
| `src/graph/digest.py` | `client: anthropic.AsyncAnthropic` → `client: LLMClient`; `messages.create(...)` → `client.generate(...)` |
| `src/main.py` | Lifespan: `AnthropicClient(...)` → `create_llm_client()`; store as `app.state.llm_client`; two inline `messages.create` calls → `llm_client.generate(...)` |

---

## New Dependency

```toml
# pyproject.toml
google-genai = "^1.0"
```

`anthropic` package stays (still needed when provider = "anthropic").

---

## What Does Not Change

- Vector store, Supabase, chunking, epub parsing — untouched.
- `settings.llm_model` and `settings.extraction_model` remain the single source of truth for model strings; only their *source* changes (TOML instead of hardcoded defaults).
- Frontend — no changes.
- Existing `.env` structure — `ANTHROPIC_API_KEY` stays; `GEMINI_API_KEY` is added.

---

## Out of Scope

- Streaming responses
- Token counting / cost tracking
- Retry / rate-limit handling (callers handle this already via `asyncio.Semaphore`)
- Adding more providers (OpenAI, etc.) — the Protocol makes this straightforward later
