"""Adapter over `claude-agent-sdk`, drawing on the user's Claude subscription rather than API credits."""

from __future__ import annotations

import asyncio
import logging
import os

from booklens.llm.base import FatalLLMError, Message, Response, TransientLLMError

logger = logging.getLogger(__name__)

_INSTALL_HINT = (
    "claude-agent-sdk is not installed. Install it with: pip install 'booklens[llm]'"
)
_DEFAULT_MAX_TOKENS = 4096
_DEFAULT_TEMPERATURE = 0.0


class ClaudeSDKProvider:
    """LLM provider backed by the Claude Agent SDK's `query()`, driven as a single-turn, tool-free call.

    `max_tokens` and `temperature` are accepted for protocol compatibility but ignored:
    Claude Code's `query()` does not expose either knob.
    """

    def __init__(self, model: str | None = None):
        self.model = model
        self._import_sdk()

    def _import_sdk(self) -> None:
        """Import claude_agent_sdk lazily so the package stays optional."""
        try:
            from claude_agent_sdk import ClaudeAgentOptions, query
            from claude_agent_sdk.types import AssistantMessage, ResultMessage, TextBlock
        except ImportError as exc:
            raise FatalLLMError(_INSTALL_HINT) from exc
        self._query = query
        self._options_cls = ClaudeAgentOptions
        self._AssistantMessage = AssistantMessage
        self._ResultMessage = ResultMessage
        self._TextBlock = TextBlock

    def _clean_env(self) -> dict[str, str]:
        """Copy the process environment with ANTHROPIC_API_KEY removed, warning if it was set."""
        env = dict(os.environ)
        if env.pop("ANTHROPIC_API_KEY", None) is not None:
            logger.warning(
                "ANTHROPIC_API_KEY was set in the environment and has been removed before "
                "calling the Claude Agent SDK, so the call uses subscription OAuth, not API billing."
            )
        return env

    def _flatten_prompt(self, messages: list[Message]) -> str:
        """Collapse the message list into one prompt string, since query() takes a prompt, not a turn list."""
        if len(messages) == 1:
            return messages[0].content
        return "\n\n".join(f"{m.role}: {m.content}" for m in messages)

    def complete(
        self,
        messages: list[Message],
        *,
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> Response:
        """Run a single-turn, tool-free completion through the Claude Agent SDK."""
        if max_tokens != _DEFAULT_MAX_TOKENS or temperature != _DEFAULT_TEMPERATURE:
            logger.warning(
                "ClaudeSDKProvider ignores max_tokens/temperature (got %r, %r); "
                "Claude Code's query() does not expose either.",
                max_tokens,
                temperature,
            )
        env = self._clean_env()
        prompt = self._flatten_prompt(messages)
        # setting_sources/skills: [] means isolation (no filesystem settings/CLAUDE.md/skills loaded).
        # None means "load everything" (CLI default) - the opposite of what a reproducible prompt needs.
        options = self._options_cls(
            env=env,
            system_prompt=system,
            model=self.model,
            allowed_tools=[],
            max_turns=1,
            setting_sources=[],
            skills=[],
        )
        try:
            text, stop_reason, usage, model_used = asyncio.run(self._run(prompt, options))
        except Exception as exc:
            if self._is_fatal(exc):
                raise FatalLLMError(str(exc)) from exc
            raise TransientLLMError(str(exc)) from exc

        input_tokens, output_tokens = self._extract_token_counts(usage)
        return Response(
            text=text,
            stop_reason=stop_reason,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model=model_used or self.model,
        )

    async def _run(self, prompt: str, options) -> tuple[str, str | None, dict | None, str | None]:
        """Drive query() to completion, concatenating assistant text and taking the last usage seen."""
        text_parts: list[str] = []
        usage = None
        stop_reason = None
        model_used = None
        async for message in self._query(prompt=prompt, options=options):
            if isinstance(message, self._AssistantMessage):
                for block in message.content:
                    if isinstance(block, self._TextBlock):
                        text_parts.append(block.text)
                usage = message.usage or usage
                stop_reason = message.stop_reason or stop_reason
                model_used = message.model or model_used
            elif isinstance(message, self._ResultMessage):
                usage = message.usage or usage
                stop_reason = message.stop_reason or stop_reason
        return "".join(text_parts), stop_reason, usage, model_used

    def _extract_token_counts(self, usage: dict | None) -> tuple[int | None, int | None]:
        """Read token counts out of the SDK's usage dict defensively; never invent a number."""
        if not usage:
            return None, None
        return usage.get("input_tokens"), usage.get("output_tokens")

    def _is_fatal(self, exc: Exception) -> bool:
        """Auth and malformed-request errors never succeed on retry; classify them fatal."""
        name = type(exc).__name__.lower()
        return "auth" in name or "invalid" in name or "malformed" in name
