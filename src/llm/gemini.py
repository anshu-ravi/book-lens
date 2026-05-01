"""Gemini implementation of LLMClient using google-genai async API."""

from google import genai
from google.genai import types


class GeminiLLMClient:
    """LLMClient backed by Google's Gemini models."""

    def __init__(self, api_key: str, model: str, extraction_model: str) -> None:
        self._client = genai.Client(api_key=api_key)
        self._model = model
        self._extraction_model = extraction_model

    async def generate(self, messages: list[dict], max_tokens: int) -> str:
        """Send messages and return the assistant's text reply.

        Converts the OpenAI-style messages list to Gemini's Content format.
        Gemini uses "model" where OpenAI/Anthropic use "assistant".
        """
        contents = []
        for msg in messages:
            role = "model" if msg["role"] == "assistant" else "user"
            contents.append(
                types.Content(role=role, parts=[types.Part(text=msg["content"])])
            )

        response = await self._client.aio.models.generate_content(
            model=self._model,
            contents=contents,
            config=types.GenerateContentConfig(max_output_tokens=max_tokens),
        )
        return response.text

    async def extract_structured(
        self,
        messages: list[dict],
        tool_name: str,
        tool_description: str,
        tool_schema: dict,
        max_tokens: int,
    ) -> dict:
        """Force Gemini to call tool_name via function calling and return its args."""
        # Gemini function declarations use "parameters" (same JSON Schema shape).
        func_decl = types.FunctionDeclaration(
            name=tool_name,
            description=tool_description,
            parameters=tool_schema,
        )
        tool = types.Tool(function_declarations=[func_decl])
        tool_config = types.ToolConfig(
            function_calling_config=types.FunctionCallingConfig(
                mode="ANY",
                allowed_function_names=[tool_name],
            )
        )

        # Extraction is always a single user message.
        prompt = messages[0]["content"] if messages else ""

        response = await self._client.aio.models.generate_content(
            model=self._extraction_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[tool],
                tool_config=tool_config,
                max_output_tokens=max_tokens,
            ),
        )

        part = response.candidates[0].content.parts[0]
        if not part.function_call:
            raise RuntimeError(
                f"Gemini: expected function_call in response, got: {part!r}"
            )
        return dict(part.function_call.args)
