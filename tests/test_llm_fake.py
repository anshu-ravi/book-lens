"""Tests for the deterministic fake LLM provider."""

from __future__ import annotations

import pytest

from booklens.llm.base import Message
from booklens.llm.fake import FakeLLM


def test_scripted_responses_returned_in_order():
    """Consecutive calls return the scripted responses in sequence."""
    fake = FakeLLM(responses=["first", "second"])
    assert fake.complete([Message("user", "a")]).text == "first"
    assert fake.complete([Message("user", "b")]).text == "second"


def test_scripted_responses_repeat_last_once_exhausted():
    """Calling past the end of the script keeps returning the final response."""
    fake = FakeLLM(responses=["only"])
    fake.complete([Message("user", "a")])
    second = fake.complete([Message("user", "b")])
    assert second.text == "only"


def test_responder_callable_receives_messages_and_system():
    """A callable responder lets a test assert on exactly what the model was asked."""
    seen = {}

    def responder(messages, system):
        seen["messages"] = messages
        seen["system"] = system
        return "computed"

    fake = FakeLLM(responder=responder)
    response = fake.complete([Message("user", "hello")], system="be terse")
    assert response.text == "computed"
    assert seen["system"] == "be terse"
    assert seen["messages"][0].content == "hello"


def test_calls_are_recorded_for_inspection():
    """Every call is recorded with its messages, system prompt, and max_tokens."""
    fake = FakeLLM(responses=["ok"])
    fake.complete([Message("user", "hi")], system="sys", max_tokens=100)
    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call.messages[0].content == "hi"
    assert call.system == "sys"
    assert call.max_tokens == 100


def test_deterministic_by_default():
    """Same input, same output: no randomness without an explicit seed source."""
    fake1 = FakeLLM(responses=["x", "y"])
    fake2 = FakeLLM(responses=["x", "y"])
    r1 = [fake1.complete([Message("user", "q")]).text for _ in range(2)]
    r2 = [fake2.complete([Message("user", "q")]).text for _ in range(2)]
    assert r1 == r2


def test_raise_on_nth_call():
    """A configured exception fires on the exact call number, not before or after."""
    boom = ValueError("boom")
    fake = FakeLLM(responses=["ok", "ok", "ok"], raise_on_call={2: boom})
    fake.complete([Message("user", "1")])
    with pytest.raises(ValueError, match="boom"):
        fake.complete([Message("user", "2")])
    # the call was still recorded before raising
    assert len(fake.calls) == 2
    third = fake.complete([Message("user", "3")])
    assert third.text == "ok"


def test_response_token_counts_are_populated():
    """input_tokens and output_tokens are always integers, never None, for the fake."""
    fake = FakeLLM(responses=["two words"])
    response = fake.complete([Message("user", "one two three")])
    assert response.input_tokens == 3
    assert response.output_tokens == 2
    assert response.model == "fake-model"
