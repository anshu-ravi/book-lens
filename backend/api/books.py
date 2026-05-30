"""Routes for book operations: metadata extraction, covers."""

import logging
import os
import tempfile
from typing import Optional

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

router = APIRouter(prefix="/books", tags=["books"])

logger = logging.getLogger(__name__)


class ExtractMetadataResponse(BaseModel):
    """Response returned after extracting metadata from an epub."""

    title: str
    author: Optional[str] = None
    book_name: Optional[str] = None
    series_name: Optional[str] = None
    series_position: Optional[float] = None
    is_series: bool = False


@router.post("/extract-metadata", response_model=ExtractMetadataResponse)
async def extract_metadata_endpoint(file: UploadFile = File(...)) -> ExtractMetadataResponse:
    """Extract title, author, and series info from an epub.

    Reads epub metadata from the file, then queries Gemini to determine
    whether the book is part of a series and what its position is.
    """
    from ebooklib import epub

    if not file.filename or not file.filename.endswith(".epub"):
        raise HTTPException(status_code=400, detail="File must be an .epub.")

    book_bytes = await file.read()

    with tempfile.NamedTemporaryFile(suffix=".epub", delete=False) as tmp:
        tmp.write(book_bytes)
        tmp_path = tmp.name

    try:
        book = epub.read_epub(tmp_path)
        title_meta = book.get_metadata("DC", "title")
        author_meta = book.get_metadata("DC", "creator")
        title: str = title_meta[0][0] if title_meta else (file.filename or "Unknown")
        author: Optional[str] = author_meta[0][0] if author_meta else None
    finally:
        os.unlink(tmp_path)

    # Look up series information via Gemini + Google Search
    series_info: dict = {"is_series": False, "series_name": None, "position": None, "book_name": None}
    if author:
        try:
            from backend.llm.gemini import GeminiLLMClient

            api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY", "")
            gemini = GeminiLLMClient(api_key=api_key, model="", extraction_model="")
            series_info = gemini.get_series_via_gemini(title, author)
        except Exception as e:
            logger.warning(f"Series lookup failed for '{title}': {e}")

    return ExtractMetadataResponse(
        title=title,
        author=author,
        book_name=series_info.get("book_name") or title,
        series_name=series_info.get("series_name"),
        series_position=series_info.get("position"),
        is_series=series_info.get("is_series", False),
    )
