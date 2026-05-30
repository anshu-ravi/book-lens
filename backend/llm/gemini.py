"""Gemini implementation of LLMClient using google-genai async API."""

import time

from google import genai
from google.genai import errors, types

from backend.config import ModelConfig


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
        """Use Gemini's JSON schema mode to return structured data."""
        import logging
        logger = logging.getLogger(__name__)

        def json_schema_to_gemini_schema(schema: dict) -> types.Schema:
            """Recursively convert JSON Schema dict to Gemini Schema."""
            if "type" not in schema:
                raise ValueError(f"Schema must have 'type': {schema}")

            schema_type = schema["type"]

            type_map = {
                "object": types.Type.OBJECT,
                "array": types.Type.ARRAY,
                "string": types.Type.STRING,
                "number": types.Type.NUMBER,
                "integer": types.Type.INTEGER,
                "boolean": types.Type.BOOLEAN,
            }

            gemini_type = type_map.get(schema_type)
            if not gemini_type:
                raise ValueError(f"Unsupported schema type: {schema_type}")

            kwargs = {"type": gemini_type}
            if "description" in schema:
                kwargs["description"] = schema["description"]

            if schema_type == "object" and "properties" in schema:
                kwargs["properties"] = {
                    prop_name: json_schema_to_gemini_schema(prop_schema)
                    for prop_name, prop_schema in schema["properties"].items()
                }
                if "required" in schema:
                    kwargs["required"] = schema["required"]

            if schema_type == "array" and "items" in schema:
                kwargs["items"] = json_schema_to_gemini_schema(schema["items"])

            if "enum" in schema:
                kwargs["enum"] = schema["enum"]

            if schema.get("nullable"):
                kwargs["nullable"] = True

            return types.Schema(**kwargs)

        gemini_schema = json_schema_to_gemini_schema(tool_schema)

        logger.debug(f"Using Gemini JSON schema mode for extraction")

        contents = []
        for msg in messages:
            role = "model" if msg["role"] == "assistant" else "user"
            contents.append(
                types.Content(role=role, parts=[types.Part(text=msg["content"])])
            )

        response = await self._client.aio.models.generate_content(
            model=self._extraction_model,
            contents=contents,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=gemini_schema,
                max_output_tokens=max_tokens,
            ),
        )

        # Check for response errors
        if response is None:
            raise RuntimeError("Gemini API returned None response. Check API key and quota.")

        if not response.candidates:
            raise RuntimeError(f"Gemini API returned no candidates. Prompt feedback: {response.prompt_feedback if hasattr(response, 'prompt_feedback') else 'unknown'}")

        candidate = response.candidates[0]

        if not candidate.content:
            finish_reason = candidate.finish_reason if hasattr(candidate, 'finish_reason') else 'unknown'
            logger.error(f"Empty content from Gemini. Finish reason: {finish_reason}")
            raise RuntimeError(f"Gemini API returned empty content. Finish reason: {finish_reason}")

        # Use response.parsed if available (SDK handles JSON decoding + schema coercion)
        if response.parsed is not None:
            return dict(response.parsed)

        # Fallback: parse text manually
        import json
        text_content = candidate.content.parts[0].text if candidate.content.parts else None
        if not text_content:
            raise RuntimeError("Gemini returned no text content")
        try:
            return json.loads(text_content)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Gemini JSON response: {text_content[:500]}")
            raise RuntimeError(f"Gemini returned invalid JSON: {e}")

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
                series_model = ModelConfig.get_model("series_lookup")
                search_response = self._client.models.generate_content(
                    model=series_model,
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
