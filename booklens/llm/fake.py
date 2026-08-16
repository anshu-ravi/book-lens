"""A deterministic LLM provider for tests and for exercising the pipeline without spending anything."""

from __future__ import annotations

from typing import Callable

from booklens.llm.base import FatalLLMError, Message, Response, TransientLLMError


class RecordedCall:
    """One call made to `FakeLLM`, kept for test introspection."""

    def __init__(
        self,
        messages: list[Message],
        system: str | None,
        max_tokens: int,
        temperature: float,
        cache_breakpoint: int | None = None,
    ):
        self.messages = messages
        self.system = system
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.cache_breakpoint = cache_breakpoint


class FakeLLM:
    """Scriptable, deterministic stand-in for a real LLM. Never touches the network."""

    def __init__(
        self,
        responses: list[str] | None = None,
        responder: Callable[[list[Message], str | None], str] | None = None,
        raise_on_call: dict[int, Exception] | None = None,
        model: str = "fake-model",
    ):
        self.responses = responses or []
        self.responder = responder
        self.raise_on_call = raise_on_call or {}
        self.model = model
        self.calls: list[RecordedCall] = []

    def complete(
        self,
        messages: list[Message],
        *,
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        cache_breakpoint: int | None = None,
    ) -> Response:
        """Return the next scripted response, recording the call for later inspection.

        Accepts `cache_breakpoint` for signature-compatibility with providers that support
        explicit prompt caching (see `booklens/llm/openrouter.py`) and simply records it --
        `FakeLLM` never sends anything over the wire, so there is nothing to cache.
        """
        call_number = len(self.calls) + 1
        self.calls.append(RecordedCall(messages, system, max_tokens, temperature, cache_breakpoint))
        if call_number in self.raise_on_call:
            raise self.raise_on_call[call_number]

        if self.responder is not None:
            text = self.responder(messages, system)
        elif self.responses:
            index = min(call_number - 1, len(self.responses) - 1)
            text = self.responses[index]
        else:
            text = ""

        return Response(
            text=text,
            stop_reason="end_turn",
            input_tokens=sum(len(m.content.split()) for m in messages),
            output_tokens=len(text.split()),
            model=self.model,
            cost_usd=None,
        )


__all__ = ["FakeLLM", "RecordedCall", "TransientLLMError", "FatalLLMError"]
