"""Q&A engine: route questions to graph/vector retrieval, then generate answers with Gemini."""

import os

from google import genai
from google.genai import types

from src.config import ModelConfig
from src.knowledge.retriever import Retriever


class KnowledgeQA:
    """Answer questions about a book series using hybrid retrieval + LLM generation."""

    def __init__(self, series_id: str) -> None:
        """Initialize Q&A engine.

        Args:
            series_id: Series identifier (e.g., 'red-rising').
        """
        self.series_id = series_id
        self.retriever = Retriever(series_id)

        api_key = os.environ.get("GOOGLE_API_KEY", "")
        self.gemini_client = genai.Client(api_key=api_key)

    async def ask(
        self,
        question: str,
        up_to_chapter: int,
        user_id: str,
        conversation_history: list[dict] | None = None,
        top_k: int = 5,
    ) -> str:
        """Answer a question using the knowledge graph and/or prose passages.

        Args:
            question: The question to answer.
            up_to_chapter: Spoiler cutoff — only use info up to this chapter.
            user_id: User identifier for vector store scoping.
            conversation_history: Prior conversation turns as role/content dicts.
            top_k: Number of results to retrieve per source.

        Returns:
            Answer string from Gemini.
        """
        history = conversation_history or []

        # Retrieve context via smart routing (graph / vector / hybrid)
        result = self.retriever.retrieve(
            question=question,
            user_id=user_id,
            up_to_chapter=up_to_chapter,
            conversation_history=history,
            top_k=top_k,
        )

        # Build combined context block
        context_parts = []
        if result.graph_context:
            context_parts.append(result.graph_context)
        if result.vector_context:
            context_parts.append(result.vector_context)
        context = "\n\n".join(context_parts)

        # System instruction with spoiler scope
        system_instruction = (
            f"You are a knowledgeable reading companion for the book series '{self.series_id}'.\n"
            f"Answer questions based ONLY on the provided context from the story.\n"
            f"Only include information from chapters the reader has reached (up to chapter {up_to_chapter}).\n"
            f"If the context does not contain enough information to answer, say so — do not speculate.\n\n"
            f"Context:\n{context}"
        )

        # Build multi-turn contents: prior history + current question
        contents: list[dict] = []
        for turn in history[-6:]:  # last 3 exchanges
            role = turn.get("role", "user")
            content = turn.get("content", "")
            # Gemini uses "model" not "assistant"
            gemini_role = "model" if role == "assistant" else "user"
            contents.append({"role": gemini_role, "parts": [{"text": content}]})

        contents.append({"role": "user", "parts": [{"text": question}]})

        qa_model = ModelConfig.get_model("qa")
        response = await self.gemini_client.aio.models.generate_content(
            model=qa_model,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                max_output_tokens=1024,
            ),
        )

        return response.text if response.text else "No answer generated."
