"""Manual smoke tests for LLMClient implementations.

Run with: poetry run pytest tests/manual/test_llm_client.py -v
Requires real API keys in .env. Hits live APIs.
"""

import asyncio

import pytest

from src.llm import create_llm_client

# Minimal JSON Schema for a simple structured output test
_TEST_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string", "description": "A one-word answer."},
    },
    "required": ["answer"],
}


def test_generate_returns_string() -> None:
    """create_llm_client().generate() returns a non-empty string."""
    client = create_llm_client()
    result = asyncio.run(
        client.generate(
            messages=[{"role": "user", "content": "Reply with the single word: hello"}],
            max_tokens=20,
        )
    )
    assert isinstance(result, str)
    assert len(result.strip()) > 0


def test_extract_structured_returns_dict() -> None:
    """create_llm_client().extract_structured() returns a dict matching the schema."""
    client = create_llm_client()
    result = asyncio.run(
        client.extract_structured(
            messages=[
                {
                    "role": "user",
                    "content": "What is 2 + 2? Use the tool to record your answer.",
                }
            ],
            tool_name="record_answer",
            tool_description="Record a one-word answer.",
            tool_schema=_TEST_SCHEMA,
            max_tokens=100,
        )
    )
    assert isinstance(result, dict)
    assert "answer" in result
    assert isinstance(result["answer"], str)
