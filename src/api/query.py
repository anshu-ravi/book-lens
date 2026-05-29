"""Routes for knowledge graph Q&A."""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.api.deps import get_current_user, CurrentUser
from src.knowledge.qa import KnowledgeQA
from src.library.manager import get_series_by_id
from src.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/query", tags=["query"])


class QueryRequest(BaseModel):
    """Request to ask a question about a book series."""

    series_id: str
    question: str
    top_k: int = 5
    conversation_history: list[dict] = []
    mode: str = "default"


class QueryResponse(BaseModel):
    """Response containing the answer to a question."""

    answer: str
    sources: list[dict] = []


class PromptRequest(BaseModel):
    """Request to get a suggested question."""

    series_id: str
    book_index: int
    chapter_index: int


class PromptResponse(BaseModel):
    """Response containing a suggested question."""

    question: str


async def _get_up_to_chapter(series_id: str, user_id: str) -> int:
    """Determine the spoiler cutoff chapter for a user's reading progress.

    Returns the highest chapter index the user has read across all books in the series.
    Defaults to 0 if no progress is found.
    """
    client = get_supabase_client()
    resp = (
        client.table("books")
        .select("current_chapter_index")
        .filter("series_id", "eq", series_id)
        .filter("user_id", "eq", user_id)
        .execute()
    )

    if not resp.data:
        return 0

    # Find the max chapter across all books in the series
    chapters = [
        row.get("current_chapter_index")
        for row in resp.data
        if row.get("current_chapter_index") is not None
    ]

    return max(chapters) if chapters else 0


@router.post("", response_model=QueryResponse)
async def query_knowledge_graph(
    request: QueryRequest, user_id: CurrentUser
) -> QueryResponse:
    """Ask a question about a book series using the knowledge graph.

    The question is answered using characters, relationships, and summaries
    from chapters up to the user's current reading progress (spoiler-safe).
    """
    # Verify the series exists for this user
    series = await get_series_by_id(request.series_id, user_id)
    if series is None:
        raise HTTPException(status_code=404, detail=f"Series '{request.series_id}' not found.")

    # Determine spoiler cutoff from user's reading progress
    up_to_chapter = await _get_up_to_chapter(request.series_id, user_id)

    # Get the answer
    qa = KnowledgeQA(request.series_id)
    try:
        answer = await qa.ask(
            question=request.question,
            up_to_chapter=up_to_chapter,
            user_id=user_id,
            conversation_history=request.conversation_history,
            top_k=request.top_k,
        )
    except Exception as e:
        logger.error(f"Q&A failed for series {request.series_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to generate answer.")

    return QueryResponse(answer=answer, sources=[])


@router.post("/prompts", response_model=PromptResponse)
async def get_proactive_prompt(
    request: PromptRequest, user_id: CurrentUser
) -> PromptResponse:
    """Get a suggested question for a specific book and chapter.

    Returns a contextual question based on the chapter to help guide the reader.
    """
    # Verify the series exists for this user
    series = await get_series_by_id(request.series_id, user_id)
    if series is None:
        raise HTTPException(status_code=404, detail=f"Series '{request.series_id}' not found.")

    # For now, return a templated question
    # This can be enhanced later with LLM-generated suggestions
    suggested_question = "What have I learned about the main characters so far?"

    return PromptResponse(question=suggested_question)
