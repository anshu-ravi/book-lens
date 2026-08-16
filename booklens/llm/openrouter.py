"""Adapter over OpenRouter's chat completions API, the default provider (see DECISIONS.md section 13)."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import httpx

from booklens.llm.base import FatalLLMError, Message, Response, TransientLLMError

logger = logging.getLogger(__name__)

_API_BASE = "https://openrouter.ai/api/v1"
_DEFAULT_MODEL = "openai/gpt-5.6-luna-20260709"
_DEFAULT_TIMEOUT_SECONDS = 120.0
_CACHE_TTL = "30m"
# 400/401/403/404 fail identically on retry (bad request, bad auth, bad route); 429 and 5xx are load/outage.
_FATAL_STATUS_CODES = {400, 401, 403, 404}


class OpenRouterProvider:
    """LLM provider backed by OpenRouter's OpenAI-compatible `/chat/completions` endpoint.

    `reasoning_mode` selects `reasoning.mode` on the wire (e.g. `"pro"` for Luna Pro) --
    per DECISIONS.md section 13 this is a parameter on one model, not a second adapter.
    """

    def __init__(
        self,
        model: str = _DEFAULT_MODEL,
        reasoning_mode: str | None = None,
        timeout: float = _DEFAULT_TIMEOUT_SECONDS,
    ):
        self.model = model
        self.reasoning_mode = reasoning_mode
        self._timeout = timeout

    def complete(
        self,
        messages: list[Message],
        *,
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        cache_breakpoint: int | None = None,
    ) -> Response:
        """Send a chat completion to OpenRouter and map its usage accounting straight into `Response`.

        `cache_breakpoint` is the index into the assembled API message list (the system
        message occupies index 0 when `system` is given) whose content ends the reusable
        prefix -- see DECISIONS.md section 7 for why that boundary sits at the reading ceiling.
        """
        api_key = _read_api_key()
        api_messages = _build_messages(messages, system, cache_breakpoint)
        payload: dict = {
            "model": self.model,
            "messages": api_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if cache_breakpoint is not None:
            payload["prompt_cache_options"] = {"mode": "explicit", "ttl": _CACHE_TTL}
        if self.reasoning_mode:
            payload["reasoning"] = {"mode": self.reasoning_mode}

        data = _post(f"{_API_BASE}/chat/completions", api_key, payload, self._timeout)
        return _to_response(data, self.model)


def _read_api_key() -> str:
    """Read the key from the process environment at call time; never cached, never logged, no fallback chain."""
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise FatalLLMError("OPENROUTER_API_KEY is not set")
    return key


def _build_messages(
    messages: list[Message], system: str | None, cache_breakpoint: int | None
) -> list[dict]:
    """Flatten `system` + `messages` into the OpenAI-compatible message array, marking the breakpoint if given."""
    api_messages: list[dict] = []
    if system:
        api_messages.append({"role": "system", "content": system})
    api_messages.extend({"role": m.role, "content": m.content} for m in messages)
    if cache_breakpoint is not None:
        if not (0 <= cache_breakpoint < len(api_messages)):
            raise ValueError(
                f"cache_breakpoint={cache_breakpoint!r} is out of range for "
                f"{len(api_messages)} message(s) (valid: 0..{len(api_messages) - 1})"
            )
        api_messages[cache_breakpoint] = _mark_cache_breakpoint(api_messages[cache_breakpoint])
    return api_messages


def _mark_cache_breakpoint(message: dict) -> dict:
    """Rewrite a message's content into block form carrying OpenAI's explicit cache breakpoint.

    Per https://openrouter.ai/docs/features/prompt-caching, GPT-5.6+ takes `prompt_cache_breakpoint`
    on a text content block to mark the end of a reusable, cacheable prefix (Chat Completions API).
    """
    return {
        **message,
        "content": [
            {
                "type": "text",
                "text": message["content"],
                "prompt_cache_breakpoint": {"mode": "explicit"},
            }
        ],
    }


def _post(url: str, api_key: str, payload: dict, timeout: float) -> dict:
    """POST to OpenRouter, mapping transport failures and HTTP status codes to the LLM error taxonomy."""
    try:
        resp = httpx.post(
            url,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=timeout,
        )
    except httpx.HTTPError as exc:
        raise TransientLLMError(f"OpenRouter request failed: {type(exc).__name__}") from exc
    if resp.status_code >= 400:
        _raise_for_status(resp)
    return resp.json()


def _get(url: str, api_key: str, timeout: float) -> dict:
    """GET from OpenRouter, mapping transport failures and HTTP status codes the same way as `_post`."""
    try:
        resp = httpx.get(url, headers={"Authorization": f"Bearer {api_key}"}, timeout=timeout)
    except httpx.HTTPError as exc:
        raise TransientLLMError(f"OpenRouter request failed: {type(exc).__name__}") from exc
    if resp.status_code >= 400:
        _raise_for_status(resp)
    return resp.json()


def _raise_for_status(resp: httpx.Response) -> None:
    """400/401/403/404 are fatal (will recur on retry); 429 and 5xx are transient (load or outage)."""
    message = f"OpenRouter returned status {resp.status_code}"
    try:
        detail = resp.json().get("error", {}).get("message")
    except Exception:
        detail = None
    if detail:
        message = f"{message}: {detail}"
    if resp.status_code in _FATAL_STATUS_CODES:
        raise FatalLLMError(message)
    raise TransientLLMError(message)


def _to_response(data: dict, requested_model: str) -> Response:
    """Map an OpenRouter chat completion body to `Response`, reading cost and cache hit/write straight off usage.

    `prompt_tokens_details.cached_tokens`/`cache_write_tokens` are how the debug output tells
    whether the explicit breakpoint is actually engaging, not just being sent.
    """
    choice = (data.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    usage = data.get("usage") or {}
    prompt_details = usage.get("prompt_tokens_details") or {}
    return Response(
        text=message.get("content") or "",
        stop_reason=choice.get("finish_reason"),
        input_tokens=usage.get("prompt_tokens"),
        output_tokens=usage.get("completion_tokens"),
        model=data.get("model") or requested_model,
        cost_usd=usage.get("cost"),
        cached_tokens=prompt_details.get("cached_tokens"),
        cache_write_tokens=prompt_details.get("cache_write_tokens"),
    )


@dataclass(frozen=True)
class Credits:
    """Remaining balance and usage for the configured OpenRouter API key."""

    limit: float | None
    limit_remaining: float | None
    usage: float
    usage_daily: float
    usage_weekly: float
    usage_monthly: float


def get_credits(timeout: float = _DEFAULT_TIMEOUT_SECONDS) -> Credits:
    """Query OpenRouter's key-info endpoint (`GET /key`) for the configured key's remaining balance."""
    api_key = _read_api_key()
    data = _get(f"{_API_BASE}/key", api_key, timeout).get("data") or {}
    return Credits(
        limit=data.get("limit"),
        limit_remaining=data.get("limit_remaining"),
        usage=data.get("usage", 0.0),
        usage_daily=data.get("usage_daily", 0.0),
        usage_weekly=data.get("usage_weekly", 0.0),
        usage_monthly=data.get("usage_monthly", 0.0),
    )
