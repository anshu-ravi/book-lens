"""Query router: classify questions to determine the best retrieval strategy."""

import json
import logging
import os
from typing import Literal

from google import genai
from google.genai import types
from pydantic import BaseModel

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a query router for a book series Q&A system.

The system has two retrieval sources:

1. GRAPH — A knowledge graph with structured entity data:
   - Character profiles (name, aliases, role, faction, description)
   - Character relationships (ALLY, ENEMY, FAMILY, ROMANCE, MENTOR, RIVAL)
   - Chapter summaries
   - World facts (magic systems, locations, factions, lore)
   - Identity reveals (who is secretly who)

2. VECTOR — Semantic search over the actual book prose passages:
   - Raw narrative text from the chapters
   - Specific scenes, dialogue, action sequences
   - Thematic or tonal descriptions
   - World-building prose and magic system mechanics as described on the page

Routing rules:
- Use GRAPH for: "Who is X?", "What is X's relationship with Y?", "What happens in chapter N?",
  "List characters in faction Z", "When is X's identity revealed?", "What are the world facts about X?"
- Use VECTOR for: "How is X described?", "Find where X says/does Y", "What does the city look like?",
  "What themes run through the story?", "How does the magic system work mechanically?",
  "Walk me through the battle scene", "Find the passage where..."
- Use HYBRID for: complex character analysis requiring both profile + supporting passages,
  theory-crafting questions, comparative analysis of two characters, "What motivates X and how does
  it show in the story?", "Could X still be alive — build a case"

Output JSON only: {"strategy": "graph"|"vector"|"hybrid", "reasoning": "<one sentence>"}
"""

_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "strategy": {"type": "string", "enum": ["graph", "vector", "hybrid"]},
        "reasoning": {"type": "string"},
    },
    "required": ["strategy", "reasoning"],
}


class RouteDecision(BaseModel):
    """Routing decision for a query."""

    strategy: Literal["graph", "vector", "hybrid"]
    reasoning: str


def route_query(question: str, conversation_history: list[dict]) -> RouteDecision:
    """Classify a question to select the retrieval strategy.

    Args:
        question: The user's question.
        conversation_history: Recent conversation turns (list of role/content dicts).

    Returns:
        RouteDecision with strategy and one-line reasoning.
    """
    api_key = os.environ.get("GOOGLE_API_KEY", os.environ.get("GEMINI_API_KEY", ""))
    client = genai.Client(api_key=api_key)

    # Include up to last 2 exchanges for follow-up awareness
    recent = conversation_history[-4:]
    history_str = ""
    if recent:
        lines = [f"{t['role'].upper()}: {t['content']}" for t in recent]
        history_str = "\n\nRecent conversation:\n" + "\n".join(lines)

    prompt = f"Question: {question}{history_str}"

    try:
        response = client.models.generate_content(
            model="gemini-3.1-flash-lite",
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=_SYSTEM_PROMPT,
                response_mime_type="application/json",
                response_schema=_RESPONSE_SCHEMA,
                max_output_tokens=128,
            ),
        )
        data = json.loads(response.text or "{}")
        return RouteDecision(
            strategy=data.get("strategy", "hybrid"),
            reasoning=data.get("reasoning", ""),
        )
    except Exception as e:
        logger.warning(f"Router failed, defaulting to hybrid: {e}")
        return RouteDecision(strategy="hybrid", reasoning="fallback due to router error")
