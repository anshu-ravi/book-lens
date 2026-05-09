"""BRONZE stage: Extract knowledge from chapter text using Gemini."""

import json
import os
from pathlib import Path
from typing import Optional

from google import genai
from google.genai import types

from src.knowledge.neo4j_client import get_driver


EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "characters": {
            "type": "array",
            "description": "Characters introduced or appearing in this chapter",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Primary name"},
                    "aliases": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Other names or nicknames",
                    },
                    "faction": {
                        "type": "string",
                        "nullable": True,
                        "description": "Faction or group affiliation",
                    },
                    "role": {
                        "type": "string",
                        "nullable": True,
                        "description": "Primary role (protagonist, antagonist, etc.)",
                    },
                    "description": {
                        "type": "string",
                        "description": "Physical description, personality, key traits",
                    },
                    "key_events": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Key events this character participates in",
                    },
                },
                "required": ["name", "aliases", "description", "key_events"],
            },
        },
        "relationships": {
            "type": "array",
            "description": "Relationships between characters",
            "items": {
                "type": "object",
                "properties": {
                    "character_a": {"type": "string"},
                    "character_b": {"type": "string"},
                    "type": {
                        "type": "string",
                        "enum": ["ALLY", "ENEMY", "FAMILY", "ROMANCE", "MENTOR", "RIVAL", "OTHER"],
                    },
                    "description": {"type": "string"},
                    "moments": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Specific moments showing this relationship",
                    },
                },
                "required": ["character_a", "character_b", "type", "description", "moments"],
            },
        },
        "world_facts": {
            "type": "array",
            "description": "World-building facts, locations, rules, magic systems",
            "items": {
                "type": "object",
                "properties": {
                    "category": {"type": "string"},
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["category", "name", "description"],
            },
        },
        "identity_reveals": {
            "type": "array",
            "description": "When one character is revealed to be another (e.g., secret identity, fake death)",
            "items": {
                "type": "object",
                "properties": {
                    "character_a": {"type": "string"},
                    "character_b": {"type": "string"},
                    "reveal_type": {
                        "type": "string",
                        "enum": ["SAME_PERSON", "DISGUISE", "CLONE", "RESURRECTION"],
                    },
                    "context": {"type": "string"},
                },
                "required": ["character_a", "character_b", "reveal_type", "context"],
            },
        },
        "summary": {
            "type": "string",
            "description": "200-300 word chapter summary",
        },
    },
    "required": [
        "characters",
        "relationships",
        "world_facts",
        "identity_reveals",
        "summary",
    ],
}


class Extractor:
    """Extract structured knowledge from chapter text using Gemini."""

    def __init__(self, api_key: Optional[str] = None) -> None:
        """Initialize Gemini client.

        Args:
            api_key: Google Gemini API key. If None, reads from GOOGLE_API_KEY env var.
        """
        if api_key is None:
            api_key = os.environ.get("GOOGLE_API_KEY", "")
        self.client = genai.Client(api_key=api_key)

    def extract(
        self,
        chapter_text: str,
        series_id: str,
        chapter_index: int,
        chapter_label: str,
    ) -> dict:
        """Extract knowledge from chapter text.

        Args:
            chapter_text: Full text of the chapter.
            series_id: Series identifier (e.g., 'red-rising').
            chapter_index: Chapter number (0-indexed).
            chapter_label: Chapter title/label.

        Returns:
            Extracted knowledge dict matching EXTRACTION_SCHEMA.
        """
        # Check if extraction already exists
        output_dir = Path("data/extractions") / series_id
        output_file = (
            output_dir / f"{chapter_index:03d}_{chapter_label.replace(' ', '_')}.json"
        )

        if output_file.exists():
            with open(output_file) as f:
                return json.load(f)

        # Get known characters from Neo4j for coreference resolution
        driver = get_driver()
        known_characters = self._get_known_characters(driver, series_id)

        # Build extraction prompt
        prompt = self._build_prompt(chapter_text, known_characters, chapter_label)

        # Call Gemini with structured output
        response = self.client.models.generate_content(
            model="gemini-3.1-flash-lite",
            contents=[types.Content(role="user", parts=[types.Part(text=prompt)])],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        k: self._json_schema_to_gemini_schema(v)
                        for k, v in EXTRACTION_SCHEMA["properties"].items()
                    },
                    required=EXTRACTION_SCHEMA["required"],
                ),
                max_output_tokens=4000,
            ),
        )

        # Parse response
        extraction = dict(response.parsed)

        # Save extraction
        output_dir.mkdir(parents=True, exist_ok=True)
        with open(output_file, "w") as f:
            json.dump(extraction, f, indent=2)

        return extraction

    def _get_known_characters(self, driver, series_id: str) -> list[str]:
        """Get list of known character names in series from Neo4j.

        Args:
            driver: Neo4j driver.
            series_id: Series identifier.

        Returns:
            List of character names.
        """
        with driver.session() as session:
            result = session.run(
                "MATCH (c:Character {series_id: $series_id}) RETURN c.name",
                series_id=series_id,
            )
            return [record["c.name"] for record in result]

    def _build_prompt(
        self, chapter_text: str, known_characters: list[str], chapter_label: str
    ) -> str:
        """Build extraction prompt with context.

        Args:
            chapter_text: Chapter text.
            known_characters: List of known character names for coreference.
            chapter_label: Chapter title.

        Returns:
            Formatted prompt.
        """
        known_chars_str = ", ".join(known_characters) if known_characters else "None"

        return f"""Extract structured knowledge from this chapter of a novel.

Chapter: {chapter_label}

Known characters in this series (for coreference resolution):
{known_chars_str}

Text:
{chapter_text}

Important instructions:
1. For character names, use the names as they appear in the text first time they're introduced
2. If a character has aliases or nicknames, list them in the aliases field
3. For identity_reveals, ONLY include if the text EXPLICITLY reveals that two characters are the same person. Do not speculate.
4. Relationships should capture meaningful interactions shown in the chapter
5. Include relevant world-building facts that advance the plot or setting
6. Summary should be 200-300 words capturing key events and revelations"""

    @staticmethod
    def _json_schema_to_gemini_schema(schema: dict) -> types.Schema:
        """Recursively convert JSON Schema dict to Gemini Schema.

        Args:
            schema: JSON schema dict.

        Returns:
            Gemini Schema object.
        """
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
                prop_name: Extractor._json_schema_to_gemini_schema(prop_schema)
                for prop_name, prop_schema in schema["properties"].items()
            }
            if "required" in schema:
                kwargs["required"] = schema["required"]

        if schema_type == "array" and "items" in schema:
            kwargs["items"] = Extractor._json_schema_to_gemini_schema(schema["items"])

        if "enum" in schema:
            kwargs["enum"] = schema["enum"]

        if schema.get("nullable"):
            kwargs["nullable"] = True

        return types.Schema(**kwargs)
