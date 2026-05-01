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
