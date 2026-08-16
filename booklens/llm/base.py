"""Provider-agnostic LLM protocol, response types, and the budget guard.

Providers differ most at the tool-calling boundary (see DECISIONS.md section 13),
so `complete` is shaped to grow a `tools` parameter later without breaking callers.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Callable, Protocol


@dataclass(frozen=True)
class Message:
    """One turn in a conversation handed to an LLM."""

    role: str
    content: str


@dataclass(frozen=True)
class Response:
    """The result of a single completion call."""

    text: str
    stop_reason: str | None
    input_tokens: int | None
    output_tokens: int | None
    model: str | None
    cost_usd: float | None = None


class LLM(Protocol):
    """A single-shot text completion provider."""

    def complete(
        self,
        messages: list[Message],
        *,
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> Response:
        """Send messages to the model and return its completion."""
        ...


class BudgetExceeded(Exception):
    """Raised when a call would push a `BudgetedLLM` past its call budget."""


class TransientLLMError(Exception):
    """A retryable failure: network, rate limit, or overload."""


class FatalLLMError(Exception):
    """A non-retryable failure: bad auth or a malformed request."""


class BudgetedLLM:
    """Wraps any LLM and refuses to exceed a call budget, with bounded retry on transient errors."""

    def __init__(
        self,
        inner: LLM,
        *,
        max_calls: int,
        max_retries: int = 3,
        backoff_base_seconds: float = 0.1,
        sleep_fn: Callable[[float], None] = time.sleep,
    ):
        self.inner = inner
        self.max_calls = max_calls
        self.max_retries = max_retries
        self.backoff_base_seconds = backoff_base_seconds
        self.sleep_fn = sleep_fn
        self.calls_made = 0
        self.tokens_used = 0
        self.cost_usd = 0.0

    def complete(
        self,
        messages: list[Message],
        *,
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> Response:
        """Call the wrapped provider, retrying transient failures, never exceeding the budget."""
        attempt = 0
        while True:
            if self.calls_made >= self.max_calls:
                raise BudgetExceeded(
                    f"budget of {self.max_calls} calls exhausted "
                    f"({self.calls_made} made, tokens_used={self.tokens_used})"
                )
            self.calls_made += 1
            try:
                response = self.inner.complete(
                    messages, system=system, max_tokens=max_tokens, temperature=temperature
                )
            except FatalLLMError:
                raise
            except TransientLLMError:
                attempt += 1
                if attempt > self.max_retries:
                    raise
                self.sleep_fn(self.backoff_base_seconds * (2 ** (attempt - 1)))
                continue
            self.tokens_used += (response.input_tokens or 0) + (response.output_tokens or 0)
            self.cost_usd += response.cost_usd or 0.0
            return response


def get_provider(name: str | None = None, **kwargs) -> LLM:
    """Build an LLM provider by name, defaulting to the fake so an unconfigured env never spends."""
    if name is None:
        name = os.environ.get("BOOKLENS_LLM_PROVIDER", "fake")
    if name == "fake":
        from booklens.llm.fake import FakeLLM

        return FakeLLM(**kwargs)
    if name == "claude-sdk":
        from booklens.llm.claude_sdk import ClaudeSDKProvider

        return ClaudeSDKProvider(**kwargs)
    raise ValueError(f"unknown LLM provider: {name!r} (valid: 'fake', 'claude-sdk')")
