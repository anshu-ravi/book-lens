"""Provider-agnostic LLM client protocol and factory."""

from typing import Protocol, runtime_checkable

from src.config import settings


@runtime_checkable
class LLMClient(Protocol):
    """Minimal async LLM interface used throughout BookLens.

    Implementations: AnthropicLLMClient, GeminiLLMClient.
    """

    async def generate(
        self,
        messages: list[dict],
        max_tokens: int,
    ) -> str:
        """Send a chat conversation and return the assistant's text reply.

        Args:
            messages: List of {"role": "user"|"assistant", "content": str} dicts.
            max_tokens: Maximum tokens in the reply.

        Returns:
            Assistant reply as a plain string.
        """
        ...

    async def extract_structured(
        self,
        messages: list[dict],
        tool_name: str,
        tool_description: str,
        tool_schema: dict,
        max_tokens: int,
    ) -> dict:
        """Force the model to call a named function and return its arguments.

        The tool_schema is standard JSON Schema (OpenAPI style):
            {"type": "object", "properties": {...}, "required": [...]}

        Each implementation translates this to its provider's native format.

        Args:
            messages: Conversation so far (typically a single user message).
            tool_name: Name of the function the model must call.
            tool_description: What the function does (used by Gemini).
            tool_schema: JSON Schema describing the function's parameters.
            max_tokens: Maximum tokens in the reply.

        Returns:
            Dict matching the tool_schema — the model's structured output.
        """
        ...


def create_llm_client() -> LLMClient:
    """Instantiate the LLMClient configured in config.toml.

    Reads settings.llm_provider and returns the matching implementation.
    """
    provider = settings.llm_provider
    if provider == "gemini":
        from src.llm.gemini import GeminiLLMClient

        return GeminiLLMClient(
            api_key=settings.gemini_api_key,
            model=settings.llm_model,
            extraction_model=settings.extraction_model,
        )
    if provider == "anthropic":
        from src.llm.anthropic import AnthropicLLMClient

        return AnthropicLLMClient(
            api_key=settings.anthropic_api_key,
            model=settings.llm_model,
            extraction_model=settings.extraction_model,
        )
    raise ValueError(f"Unknown LLM provider: {provider!r}. Choose 'gemini' or 'anthropic'.")
