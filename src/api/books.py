"""Routes for book operations: metadata extraction, covers."""

import os
import tempfile
from typing import Optional

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from src.supabase_client import get_supabase_client

router = APIRouter(prefix="/books", tags=["books"])


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

    Reads epub metadata locally and returns basic information.
    """
    from ebooklib import epub

    if not file.filename or not file.filename.endswith(".epub"):
        raise HTTPException(status_code=400, detail="File must be an .epub.")

    book_bytes = await file.read()

    # Write to a temp file since ebooklib requires a file path.
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

    return ExtractMetadataResponse(
        title=title,
        author=author,
    )
