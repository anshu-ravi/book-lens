"""Tests for the Claude Agent SDK adapter, entirely against a mocked SDK module.

No test here may perform real network I/O or import the real `claude_agent_sdk` package,
except the conformance test, which imports it only if installed and never calls it.
"""

from __future__ import annotations

import inspect
import sys
import types

import pytest

from booklens.llm.base import FatalLLMError, Message, TransientLLMError
from booklens.llm.claude_sdk import ClaudeSDKProvider


class TextBlock:
    """Stand-in for `claude_agent_sdk.types.TextBlock`."""

    def __init__(self, text):
        self.text = text


class AssistantMessage:
    """Stand-in for `claude_agent_sdk.types.AssistantMessage`."""

    def __init__(self, content, model=None, stop_reason=None, usage=None):
        self.content = content
        self.model = model
        self.stop_reason = stop_reason
        self.usage = usage


class ResultMessage:
    """Stand-in for `claude_agent_sdk.types.ResultMessage`."""

    def __init__(self, usage=None, total_cost_usd=None, is_error=False, stop_reason=None, result=None):
        self.usage = usage
        self.total_cost_usd = total_cost_usd
        self.is_error = is_error
        self.stop_reason = stop_reason
        self.result = result


class ClaudeAgentOptions:
    """Stand-in for `claude_agent_sdk.ClaudeAgentOptions`; just captures whatever kwargs it's given."""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def _install_fake_sdk_module(monkeypatch, messages=(), raises: Exception | None = None):
    """Inject a fake `claude_agent_sdk` (+ `.types`) into sys.modules, shaped like the real package."""
    captured = {}

    async def fake_query(*, prompt, options=None, transport=None):
        captured["prompt"] = prompt
        captured["options"] = options
        if raises is not None:
            raise raises
        for m in messages:
            yield m

    types_mod = types.ModuleType("claude_agent_sdk.types")
    types_mod.TextBlock = TextBlock
    types_mod.AssistantMessage = AssistantMessage
    types_mod.ResultMessage = ResultMessage

    sdk_mod = types.ModuleType("claude_agent_sdk")
    sdk_mod.query = fake_query
    sdk_mod.ClaudeAgentOptions = ClaudeAgentOptions
    sdk_mod.types = types_mod

    monkeypatch.setitem(sys.modules, "claude_agent_sdk", sdk_mod)
    monkeypatch.setitem(sys.modules, "claude_agent_sdk.types", types_mod)

    return captured


def test_import_booklens_llm_succeeds_without_the_sdk_installed():
    """The package must import cleanly even though claude_agent_sdk is absent in this venv."""
    import booklens.llm  # noqa: F401
    import booklens.llm.claude_sdk  # noqa: F401


def test_missing_sdk_raises_clear_actionable_error():
    """Selecting claude-sdk without the package installed names the extra to install."""
    with pytest.raises(FatalLLMError, match="pip install"):
        ClaudeSDKProvider()


def test_api_key_is_removed_before_reaching_the_sdk(monkeypatch):
    """A dummy ANTHROPIC_API_KEY must never reach the SDK options, and a warning is emitted."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-dummy-should-not-be-used")
    captured = _install_fake_sdk_module(
        monkeypatch,
        [AssistantMessage(content=[TextBlock("hi")], model="m", stop_reason="end_turn", usage=None)],
    )

    provider = ClaudeSDKProvider()
    provider.complete([Message("user", "hello")])

    assert "ANTHROPIC_API_KEY" not in captured["options"].env
    import os

    assert os.environ.get("ANTHROPIC_API_KEY") == "sk-ant-dummy-should-not-be-used"


def test_api_key_removal_logs_a_warning(monkeypatch, caplog):
    """When ANTHROPIC_API_KEY was present, a one-line warning explains why it was stripped."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-dummy")
    _captured = _install_fake_sdk_module(
        monkeypatch, [AssistantMessage(content=[TextBlock("hi")], model="m", stop_reason="end_turn")]
    )

    provider = ClaudeSDKProvider()
    with caplog.at_level("WARNING"):
        provider.complete([Message("user", "hello")])

    assert any("ANTHROPIC_API_KEY" in record.message for record in caplog.records)


def test_no_warning_when_api_key_absent(monkeypatch, caplog):
    """No key set, no warning: the log stays quiet in the normal subscription-only case."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    _captured = _install_fake_sdk_module(
        monkeypatch, [AssistantMessage(content=[TextBlock("hi")], model="m", stop_reason="end_turn")]
    )

    provider = ClaudeSDKProvider()
    with caplog.at_level("WARNING"):
        provider.complete([Message("user", "hello")])

    assert not any("ANTHROPIC_API_KEY" in record.message for record in caplog.records)


def test_completion_shuts_down_the_agent_loop(monkeypatch):
    """The adapter must never let the model run tools, read files, or take more than one turn."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    captured = _install_fake_sdk_module(
        monkeypatch, [AssistantMessage(content=[TextBlock("hi")], model="m", stop_reason="end_turn")]
    )

    provider = ClaudeSDKProvider()
    provider.complete([Message("user", "hello")])

    options = captured["options"]
    assert options.allowed_tools == []
    assert options.max_turns == 1
    # [] means isolation; None would mean "load everything" (CLI default) - the opposite intent.
    assert options.setting_sources == []
    assert options.skills == []


def test_successful_completion_concatenates_text_blocks_and_reads_usage(monkeypatch):
    """Text blocks from AssistantMessage concatenate in order; usage comes off ResultMessage."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    captured = _install_fake_sdk_module(
        monkeypatch,
        [
            AssistantMessage(
                content=[TextBlock("hi "), TextBlock("there")],
                model="claude-sonnet",
                stop_reason="end_turn",
                usage=None,
            ),
            ResultMessage(usage={"input_tokens": 5, "output_tokens": 3}, stop_reason="end_turn"),
        ],
    )

    provider = ClaudeSDKProvider()
    response = provider.complete([Message("user", "hello")], system="be terse")

    assert response.text == "hi there"
    assert response.stop_reason == "end_turn"
    assert response.input_tokens == 5
    assert response.output_tokens == 3
    assert response.model == "claude-sonnet"
    assert captured["options"].system_prompt == "be terse"
    assert captured["prompt"] == "hello"


def test_usage_absent_yields_none_token_counts_not_invented_numbers(monkeypatch):
    """If neither message carries a usage dict, token counts stay None rather than being guessed."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    _captured = _install_fake_sdk_module(
        monkeypatch, [AssistantMessage(content=[TextBlock("hi")], model="m", stop_reason="end_turn", usage=None)]
    )

    provider = ClaudeSDKProvider()
    response = provider.complete([Message("user", "hello")])

    assert response.input_tokens is None
    assert response.output_tokens is None


def test_non_default_max_tokens_or_temperature_logs_a_warning(monkeypatch, caplog):
    """This backend cannot honour max_tokens/temperature; silently accepting them would hide that."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    _captured = _install_fake_sdk_module(
        monkeypatch, [AssistantMessage(content=[TextBlock("hi")], model="m", stop_reason="end_turn")]
    )

    provider = ClaudeSDKProvider()
    with caplog.at_level("WARNING"):
        provider.complete([Message("user", "hello")], max_tokens=999, temperature=0.7)

    assert any("ignores max_tokens" in record.message for record in caplog.records)


def test_auth_error_from_sdk_is_classified_fatal_and_not_retried(monkeypatch):
    """An auth-shaped exception from the SDK becomes FatalLLMError, so BudgetedLLM won't retry it."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    class AuthenticationError(Exception):
        pass

    _install_fake_sdk_module(monkeypatch, messages=[], raises=AuthenticationError("invalid credentials"))

    provider = ClaudeSDKProvider()
    with pytest.raises(FatalLLMError):
        provider.complete([Message("user", "hello")])


def test_rate_limit_error_from_sdk_is_classified_transient(monkeypatch):
    """A rate-limit-shaped exception from the SDK becomes TransientLLMError, so it is retryable."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    class RateLimitError(Exception):
        pass

    _install_fake_sdk_module(monkeypatch, messages=[], raises=RateLimitError("slow down"))

    provider = ClaudeSDKProvider()
    with pytest.raises(TransientLLMError):
        provider.complete([Message("user", "hello")])


def test_multi_message_prompt_is_flattened_with_role_labels(monkeypatch):
    """query() takes one prompt string, not a turn list, so multi-message input gets flattened."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    captured = _install_fake_sdk_module(
        monkeypatch, [AssistantMessage(content=[TextBlock("ok")], model="m", stop_reason="end_turn")]
    )

    provider = ClaudeSDKProvider()
    provider.complete([Message("user", "first"), Message("assistant", "second")])

    assert captured["prompt"] == "user: first\n\nassistant: second"


def test_conformance_real_sdk_signatures_match_what_the_adapter_assumes():
    """If claude-agent-sdk is ever installed, this fails loudly the moment its real API drifts."""
    claude_agent_sdk = pytest.importorskip("claude_agent_sdk")

    query_params = inspect.signature(claude_agent_sdk.query).parameters
    assert "prompt" in query_params
    assert "options" in query_params

    options_params = inspect.signature(claude_agent_sdk.ClaudeAgentOptions).parameters
    for field in ("env", "system_prompt", "model", "allowed_tools", "max_turns", "setting_sources", "skills"):
        assert field in options_params
