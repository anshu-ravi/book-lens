"""Tests for the OpenRouter adapter. All HTTP is mocked; no test may spend money or hit the network."""

from __future__ import annotations

import httpx
import pytest

from booklens.llm.base import BudgetedLLM, FatalLLMError, Message, TransientLLMError
from booklens.llm.fake import FakeLLM
from booklens.llm.openrouter import Credits, OpenRouterProvider, get_credits


def _responder(status_code: int, json_body: dict, captured: dict | None = None):
    """Build an httpx MockTransport handler that records the request and returns a canned response."""

    def handler(request: httpx.Request) -> httpx.Response:
        if captured is not None:
            captured["request"] = request
            if request.content:
                captured["json"] = __import__("json").loads(request.content)
        return httpx.Response(status_code, json=json_body)

    return handler


def _patch_client(monkeypatch, handler) -> None:
    """Route httpx.post/httpx.get through a MockTransport so no real socket is opened."""
    transport = httpx.MockTransport(handler)

    def fake_post(url, *, headers=None, json=None, timeout=None):
        with httpx.Client(transport=transport) as client:
            return client.post(url, headers=headers, json=json)

    def fake_get(url, *, headers=None, timeout=None):
        with httpx.Client(transport=transport) as client:
            return client.get(url, headers=headers)

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr(httpx, "get", fake_get)


_SUCCESS_BODY = {
    "id": "gen-1",
    "model": "openai/gpt-5.6-luna-20260709",
    "choices": [
        {"message": {"role": "assistant", "content": "hello there"}, "finish_reason": "stop"}
    ],
    "usage": {
        "prompt_tokens": 1500,
        "completion_tokens": 12,
        "total_tokens": 1512,
        "cost": 0.000173,
        "prompt_tokens_details": {"cached_tokens": 1000, "cache_write_tokens": 200},
    },
}


def test_missing_api_key_raises_fatal_naming_the_variable(monkeypatch):
    """No OPENROUTER_API_KEY, no network call: the error names the variable and nothing else."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    provider = OpenRouterProvider()
    with pytest.raises(FatalLLMError, match="OPENROUTER_API_KEY"):
        provider.complete([Message("user", "hi")])


def test_missing_key_ignores_unrelated_env_vars(monkeypatch):
    """Setting an unrelated key (mirroring the ANTHROPIC_API_KEY shadowing trap) must not substitute silently."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-should-not-be-used")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-should-not-be-used")
    provider = OpenRouterProvider()
    with pytest.raises(FatalLLMError, match="OPENROUTER_API_KEY"):
        provider.complete([Message("user", "hi")])


def test_successful_completion_maps_every_response_field(monkeypatch):
    """A 200 response maps text, stop reason, real token counts, model, and reported cost -- no estimation."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-key")
    captured: dict = {}
    _patch_client(monkeypatch, _responder(200, _SUCCESS_BODY, captured))

    provider = OpenRouterProvider()
    response = provider.complete([Message("user", "hi")], system="be terse")

    assert response.text == "hello there"
    assert response.stop_reason == "stop"
    assert response.input_tokens == 1500
    assert response.output_tokens == 12
    assert response.model == "openai/gpt-5.6-luna-20260709"
    assert response.cost_usd == 0.000173
    assert response.cached_tokens == 1000
    assert response.cache_write_tokens == 200

    body = captured["json"]
    assert body["messages"][0] == {"role": "system", "content": "be terse"}
    assert body["messages"][1] == {"role": "user", "content": "hi"}


def test_reasoning_mode_sets_reasoning_field(monkeypatch):
    """`reasoning_mode='pro'` puts `reasoning: {mode: pro}` on the wire -- one adapter, a parameter."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-key")
    captured: dict = {}
    _patch_client(monkeypatch, _responder(200, _SUCCESS_BODY, captured))

    provider = OpenRouterProvider(reasoning_mode="pro")
    provider.complete([Message("user", "hi")])

    assert captured["json"]["reasoning"] == {"mode": "pro"}


def test_cache_breakpoint_marks_the_right_message_and_sets_explicit_mode(monkeypatch):
    """cache_breakpoint=N rewrites api_messages[N] into block form with prompt_cache_breakpoint, and sets prompt_cache_options."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-key")
    captured: dict = {}
    _patch_client(monkeypatch, _responder(200, _SUCCESS_BODY, captured))

    provider = OpenRouterProvider()
    provider.complete(
        [Message("user", "the assembled readable-set text")],
        system="you are a spoiler-free reading companion",
        cache_breakpoint=0,
    )

    body = captured["json"]
    # index 0 is the system message when `system` is given.
    marked = body["messages"][0]
    assert marked["content"] == [
        {
            "type": "text",
            "text": "you are a spoiler-free reading companion",
            "prompt_cache_breakpoint": {"mode": "explicit"},
        }
    ]
    # the user message is untouched.
    assert body["messages"][1] == {"role": "user", "content": "the assembled readable-set text"}
    assert body["prompt_cache_options"] == {"mode": "explicit", "ttl": "30m"}


def test_no_cache_breakpoint_omits_explicit_cache_options(monkeypatch):
    """Without an explicit breakpoint, the request relies on OpenRouter's automatic caching -- no options sent."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-key")
    captured: dict = {}
    _patch_client(monkeypatch, _responder(200, _SUCCESS_BODY, captured))

    provider = OpenRouterProvider()
    provider.complete([Message("user", "hi")])

    assert "prompt_cache_options" not in captured["json"]
    assert isinstance(captured["json"]["messages"][0]["content"], str)


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_client_error_statuses_are_fatal(monkeypatch, status):
    """400/401/403/404 fail identically on retry, so they must not be retried."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-key")
    _patch_client(monkeypatch, _responder(status, {"error": {"message": "bad"}}))

    provider = OpenRouterProvider()
    with pytest.raises(FatalLLMError):
        provider.complete([Message("user", "hi")])


@pytest.mark.parametrize("status", [429, 500, 502, 503])
def test_rate_limit_and_server_error_statuses_are_transient(monkeypatch, status):
    """429 and 5xx are load/outage conditions, retryable by BudgetedLLM."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-key")
    _patch_client(monkeypatch, _responder(status, {"error": {"message": "slow down"}}))

    provider = OpenRouterProvider()
    with pytest.raises(TransientLLMError):
        provider.complete([Message("user", "hi")])


def test_network_failure_is_transient(monkeypatch):
    """A transport-level failure (no response at all) must be retryable, not fatal."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-key")

    def raising_post(url, *, headers=None, json=None, timeout=None):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "post", raising_post)

    provider = OpenRouterProvider()
    with pytest.raises(TransientLLMError):
        provider.complete([Message("user", "hi")])


def test_api_key_value_never_appears_in_response_exception_or_log(monkeypatch, caplog):
    """The key value must not leak into Response, an exception message, or a log record, on success or failure."""
    secret = "sk-or-v1-do-not-leak-this-exact-string"
    monkeypatch.setenv("OPENROUTER_API_KEY", secret)
    captured: dict = {}
    _patch_client(monkeypatch, _responder(200, _SUCCESS_BODY, captured))

    provider = OpenRouterProvider()
    with caplog.at_level("DEBUG"):
        response = provider.complete([Message("user", "hi")])

    assert secret not in str(response)
    assert secret not in response.text
    for record in caplog.records:
        assert secret not in record.getMessage()

    # and on a failure path too.
    _patch_client(monkeypatch, _responder(401, {"error": {"message": "invalid key"}}))
    with caplog.at_level("DEBUG"):
        try:
            provider.complete([Message("user", "hi")])
        except FatalLLMError as exc:
            assert secret not in str(exc)
    for record in caplog.records:
        assert secret not in record.getMessage()

    # header carries it, which is expected and never inspected here -- only response/exception/log surfaces matter.
    assert captured["request"].headers["authorization"] == f"Bearer {secret}"


_CREDITS_BODY = {
    "data": {
        "label": "test-key",
        "limit": 50.0,
        "limit_remaining": 41.23,
        "usage": 8.77,
        "usage_daily": 0.42,
        "usage_weekly": 3.1,
        "usage_monthly": 8.77,
        "is_free_tier": False,
    }
}


def test_get_credits_parses_balance_fields(monkeypatch):
    """get_credits() hits GET /key and returns the balance fields as a Credits dataclass."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-key")
    captured: dict = {}
    _patch_client(monkeypatch, _responder(200, _CREDITS_BODY, captured))

    credits = get_credits()

    assert credits == Credits(
        limit=50.0,
        limit_remaining=41.23,
        usage=8.77,
        usage_daily=0.42,
        usage_weekly=3.1,
        usage_monthly=8.77,
    )
    assert captured["request"].url.path == "/api/v1/key"
    assert captured["request"].method == "GET"


def test_get_credits_missing_key_is_fatal(monkeypatch):
    """No key, no request: get_credits() must fail the same way complete() does."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(FatalLLMError, match="OPENROUTER_API_KEY"):
        get_credits()


def test_get_credits_null_limit_is_preserved(monkeypatch):
    """An unlimited key reports `limit: null`; that must come through as None, not 0 or a made-up cap."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-key")
    body = {"data": {**_CREDITS_BODY["data"], "limit": None, "limit_remaining": None}}
    _patch_client(monkeypatch, _responder(200, body))

    credits = get_credits()

    assert credits.limit is None
    assert credits.limit_remaining is None


def test_default_provider_is_fake_when_env_unset(monkeypatch):
    """An unconfigured environment must never route to OpenRouter, so it never spends money."""
    monkeypatch.delenv("BOOKLENS_LLM_PROVIDER", raising=False)
    from booklens.llm.base import get_provider
    from booklens.llm.fake import FakeLLM

    assert isinstance(get_provider(), FakeLLM)


def test_get_provider_openrouter_registers_the_adapter(monkeypatch):
    """`get_provider('openrouter')` builds an OpenRouterProvider without making any network call."""
    from booklens.llm.base import get_provider

    provider = get_provider("openrouter")
    assert isinstance(provider, OpenRouterProvider)
    assert provider.model == "openai/gpt-5.6-luna-20260709"


def test_cache_token_fields_absent_when_usage_omits_details(monkeypatch):
    """No `prompt_tokens_details` in the response body means `cached_tokens`/`cache_write_tokens` stay None, not 0."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-key")
    body = {**_SUCCESS_BODY, "usage": {"prompt_tokens": 10, "completion_tokens": 2, "cost": 0.0001}}
    _patch_client(monkeypatch, _responder(200, body))

    response = OpenRouterProvider().complete([Message("user", "hi")])

    assert response.cached_tokens is None
    assert response.cache_write_tokens is None


def test_cache_breakpoint_out_of_range_raises_clear_error(monkeypatch):
    """An index past the end of the assembled message list must fail loudly, not raise a bare IndexError."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-key")
    _patch_client(monkeypatch, _responder(200, _SUCCESS_BODY))

    provider = OpenRouterProvider()
    with pytest.raises(ValueError, match="cache_breakpoint"):
        provider.complete([Message("user", "hi")], cache_breakpoint=5)


def test_cache_breakpoint_negative_index_raises_rather_than_silently_marking_the_wrong_message(monkeypatch):
    """A negative index must not silently wrap around and mark an unintended message."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-key")
    _patch_client(monkeypatch, _responder(200, _SUCCESS_BODY))

    provider = OpenRouterProvider()
    with pytest.raises(ValueError, match="cache_breakpoint"):
        provider.complete([Message("user", "hi")], cache_breakpoint=-1)


def test_budgeted_llm_forwards_cache_breakpoint_to_the_inner_provider(monkeypatch):
    """BudgetedLLM must not silently drop cache_breakpoint -- that would turn explicit caching off unnoticed."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-key")
    captured: dict = {}
    _patch_client(monkeypatch, _responder(200, _SUCCESS_BODY, captured))

    llm = BudgetedLLM(OpenRouterProvider(), max_calls=5)
    llm.complete(
        [Message("user", "the assembled readable-set text")],
        system="you are a spoiler-free reading companion",
        cache_breakpoint=0,
    )

    body = captured["json"]
    assert body["messages"][0]["content"] == [
        {
            "type": "text",
            "text": "you are a spoiler-free reading companion",
            "prompt_cache_breakpoint": {"mode": "explicit"},
        }
    ]
    assert body["prompt_cache_options"] == {"mode": "explicit", "ttl": "30m"}


def test_budgeted_llm_without_cache_breakpoint_does_not_break_providers_that_lack_the_kwarg():
    """Providers that don't accept cache_breakpoint (fake, claude-sdk) must keep working when it's not asked for."""
    fake = FakeLLM(responses=["ok"])
    llm = BudgetedLLM(fake, max_calls=5)

    response = llm.complete([Message("user", "hi")])

    assert response.text == "ok"
