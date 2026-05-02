"""Gemini implementation of LLMClient using google-genai async API."""

import time

from google import genai
from google.genai import errors, types


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

    def get_series_via_gemini(
        self, title: str, author: str, retries: int = 3, delay: int = 5
    ) -> dict:
        """Look up series information for a book using Gemini with Google Search.

        Args:
            title: The book title.
            author: The book author.
            retries: Number of retry attempts on server errors.
            delay: Seconds to wait between retries.

        Returns:
            A dict with keys: is_series (bool), series_name (str|None),
            position (float|None), book_name (str|None).
        """
        for attempt in range(retries):
            try:
                search_response = self._client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=f'Is the book "{title}" by {author} part of a series? If so, what is the book name, series name and position?',
                    config=types.GenerateContentConfig(
                        tools=[types.Tool(google_search=types.GoogleSearch())],
                        thinking_config=types.ThinkingConfig(thinking_budget=0),
                    ),
                )
                parse_response = self._client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=f"Extract the series information from this text:\n\n{search_response.text}",
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        thinking_config=types.ThinkingConfig(thinking_budget=0),
                        response_schema=types.Schema(
                            type=types.Type.OBJECT,
                            properties={
                                "is_series": types.Schema(type=types.Type.BOOLEAN),
                                "series_name": types.Schema(
                                    type=types.Type.STRING, nullable=True
                                ),
                                "position": types.Schema(
                                    type=types.Type.NUMBER, nullable=True
                                ),
                                "book_name": types.Schema(
                                    type=types.Type.STRING, nullable=True
                                ),
                            },
                            required=["is_series", "series_name", "position", "book_name"],
                        ),
                    ),
                )
                result = parse_response.parsed
                if result["is_series"] and result["position"] is None:
                    result["is_series"] = False
                    result["series_name"] = None
                return result
            except errors.ServerError:
                if attempt < retries - 1:
                    print(f"503 on attempt {attempt + 1}, retrying in {delay}s...")
                    time.sleep(delay)
                else:
                    raise
