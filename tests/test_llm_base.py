"""Tests for the provider protocol, budget guard, retry, and provider selection."""

from __future__ import annotations

import os

import pytest

from booklens.llm.base import (
    BudgetedLLM,
    BudgetExceeded,
    FatalLLMError,
    Message,
    Response,
    TransientLLMError,
    get_provider,
)
from booklens.llm.fake import FakeLLM


def test_get_provider_defaults_to_fake_with_no_configuration(monkeypatch):
    """An unconfigured environment must never accidentally start spending real quota."""
    monkeypatch.delenv("BOOKLENS_LLM_PROVIDER", raising=False)
    provider = get_provider()
    assert isinstance(provider, FakeLLM)


def test_get_provider_reads_env_var(monkeypatch):
    """BOOKLENS_LLM_PROVIDER selects the provider when name is not passed explicitly."""
    monkeypatch.setenv("BOOKLENS_LLM_PROVIDER", "fake")
    provider = get_provider()
    assert isinstance(provider, FakeLLM)


def test_get_provider_unknown_name_raises():
    """An unrecognised provider name fails loudly rather than silently falling back."""
    with pytest.raises(ValueError, match="unknown LLM provider"):
        get_provider("not-a-real-provider")


def test_budget_guard_allows_calls_up_to_max():
    """A budget of N calls permits exactly N completions."""
    fake = FakeLLM(responses=["ok"] * 5)
    budgeted = BudgetedLLM(fake, max_calls=3)
    for _ in range(3):
        budgeted.complete([Message("user", "hi")])
    assert budgeted.calls_made == 3


def test_budget_guard_raises_at_the_right_call():
    """The call that would exceed the budget raises before reaching the provider."""
    fake = FakeLLM(responses=["ok"] * 5)
    budgeted = BudgetedLLM(fake, max_calls=2)
    budgeted.complete([Message("user", "hi")])
    budgeted.complete([Message("user", "hi")])
    with pytest.raises(BudgetExceeded):
        budgeted.complete([Message("user", "hi")])
    assert budgeted.calls_made == 2
    assert len(fake.calls) == 2


def test_budget_guard_tracks_tokens_used():
    """tokens_used accumulates input + output tokens across calls."""
    fake = FakeLLM(responses=["one two three"])
    budgeted = BudgetedLLM(fake, max_calls=5)
    budgeted.complete([Message("user", "a b")])
    assert budgeted.tokens_used == 2 + 3


def test_retry_on_transient_error_eventually_succeeds():
    """A transient failure retries with backoff and succeeds once the provider recovers."""
    fake = FakeLLM(
        responses=["recovered"],
        raise_on_call={1: TransientLLMError("rate limited"), 2: TransientLLMError("overloaded")},
    )
    sleeps = []
    budgeted = BudgetedLLM(fake, max_calls=10, max_retries=3, sleep_fn=sleeps.append)
    response = budgeted.complete([Message("user", "hi")])
    assert response.text == "recovered"
    assert len(fake.calls) == 3
    assert len(sleeps) == 2
    # exponential backoff: second sleep is longer than the first
    assert sleeps[1] > sleeps[0]


def test_retry_gives_up_after_max_retries():
    """Persistent transient errors exhaust retries and re-raise."""
    fake = FakeLLM(raise_on_call={i: TransientLLMError("down") for i in range(1, 10)})
    budgeted = BudgetedLLM(fake, max_calls=10, max_retries=2, sleep_fn=lambda s: None)
    with pytest.raises(TransientLLMError):
        budgeted.complete([Message("user", "hi")])
    # 1 initial + 2 retries = 3 attempts
    assert len(fake.calls) == 3


def test_retries_count_against_the_budget():
    """Each retry attempt is still a call to the provider and consumes budget."""
    fake = FakeLLM(raise_on_call={1: TransientLLMError("down"), 2: TransientLLMError("down")}, responses=["ok"])
    budgeted = BudgetedLLM(fake, max_calls=3, max_retries=2, sleep_fn=lambda s: None)
    budgeted.complete([Message("user", "hi")])
    assert budgeted.calls_made == 3
    assert len(fake.calls) == 3


def test_fatal_error_does_not_retry():
    """Auth and malformed-request errors never succeed on retry, so they must not be retried."""
    fake = FakeLLM(raise_on_call={1: FatalLLMError("bad api key")})
    budgeted = BudgetedLLM(fake, max_calls=10, max_retries=5, sleep_fn=lambda s: None)
    with pytest.raises(FatalLLMError):
        budgeted.complete([Message("user", "hi")])
    assert len(fake.calls) == 1
    assert budgeted.calls_made == 1
