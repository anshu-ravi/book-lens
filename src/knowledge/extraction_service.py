"""Service to orchestrate extraction and save to Supabase."""

import json
import logging
from datetime import datetime
from io import BytesIO
from typing import Optional

from src.ingestion.epub_parser import parse_epub
from src.knowledge.extractor import Extractor
from src.models import Chapter
from src.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)


class ExtractionService:
    """Handle extraction workflow: extract chapters, save to storage, update metadata."""

    def __init__(self, user_id: str, book_id: str, series_id: str) -> None:
        """Initialize extraction service.

        Args:
            user_id: User identifier.
            book_id: Book identifier.
            series_id: Series identifier.
        """
        self.user_id = user_id
        self.book_id = book_id
        self.series_id = series_id
        self.client = get_supabase_client()
        self.extractor = Extractor()

    async def extract_book(
        self,
        epub_bytes: bytes,
        chapters: list[Chapter],
        limit: Optional[int] = None,
        series_id: Optional[str] = None,
        refresh_mode: str = "skip",
        refresh_chapters: Optional[list[int]] = None,
    ) -> None:
        """Extract knowledge from chapters and save to Supabase.

        Args:
            epub_bytes: EPUB file contents.
            chapters: List of Chapter metadata from the books table.
            limit: If set, only process first N chapters.
            series_id: Series identifier for Neo4j coreference (optional).
            refresh_mode: "skip" (default), "all", or "specific".
            refresh_chapters: List of chapter indices to refresh (for "specific" mode).
        """
        try:
            # Update status to in_progress
            await self._update_extraction_status("in_progress")

            # Parse EPUB
            parsed_chapters = parse_epub(BytesIO(epub_bytes))

            # Get already-extracted chapters
            already_extracted = await self._get_extracted_indices()
            logger.info(f"Already extracted chapters: {already_extracted}")

            # Determine which chapters to extract
            chapters_to_extract = self._filter_chapters_to_extract(
                total_chapters=len(parsed_chapters),
                already_extracted=already_extracted,
                refresh_mode=refresh_mode,
                refresh_chapters=refresh_chapters,
                limit=limit,
            )
            logger.info(f"Chapters to extract: {chapters_to_extract}")

            # Load existing extractions from storage (if any)
            all_extractions = await self._load_existing_extractions()

            # Extract per chapter
            total_chapters = len(parsed_chapters)
            extracted_indices = list(already_extracted)

            for idx in chapters_to_extract:
                if idx >= total_chapters:
                    break

                parsed_ch = parsed_chapters[idx]
                logger.info(f"Extracting chapter {idx}: {parsed_ch.label}")

                try:
                    extraction = self.extractor.extract(
                        chapter_text=parsed_ch.text,
                        user_id=self.user_id,
                        book_id=self.book_id,
                        chapter_index=idx,
                        chapter_label=parsed_ch.label,
                        series_id=series_id,
                    )

                    all_extractions[str(idx)] = {
                        "chapter_index": idx,
                        "chapter_label": parsed_ch.label,
                        "extraction": extraction,
                    }

                    extracted_indices.append(idx)

                    # Update progress
                    await self._update_progress(
                        total_chapters, len(extracted_indices), extracted_indices
                    )

                except Exception as e:
                    logger.error(f"Failed to extract chapter {idx}: {e}", exc_info=True)
                    continue

            # Upload all extractions to Supabase Storage
            await self._upload_to_storage(all_extractions)

            # Mark extraction as completed
            await self._update_extraction_status("completed")
            logger.info(
                f"Extraction complete: {len(extracted_indices)}/{total_chapters} chapters"
            )

            # Trigger deduplication and ingestion
            await self._trigger_downstream_stages()

        except Exception as e:
            logger.error(f"Extraction failed for book {self.book_id}: {e}", exc_info=True)
            await self._update_extraction_status("failed", error_message=str(e))

    async def _upload_to_storage(self, extractions: dict) -> None:
        """Upload extraction JSON to Supabase Storage.

        Args:
            extractions: Dict of chapter extractions.
        """
        file_path = f"extractions/{self.user_id}/{self.series_id}/{self.book_id}/chapters.json"

        try:
            # Delete existing file if it exists
            try:
                self.client.storage.from_("extractions").remove([file_path])
            except Exception:
                pass  # File doesn't exist, that's fine

            # Upload new file
            json_bytes = json.dumps(extractions, indent=2).encode("utf-8")
            self.client.storage.from_("extractions").upload(
                path=file_path,
                file=json_bytes,
                file_options={"content-type": "application/json"},
            )
            logger.info(f"Uploaded extractions to {file_path}")
        except Exception as e:
            logger.error(f"Failed to upload extractions to storage: {e}", exc_info=True)
            raise

    async def _update_extraction_status(
        self, status: str, error_message: Optional[str] = None
    ) -> None:
        """Update book_extractions table with status.

        Args:
            status: Extraction status ('not_started', 'in_progress', 'completed', 'failed').
            error_message: Optional error message if status is 'failed'.
        """
        try:
            file_path = f"extractions/{self.user_id}/{self.series_id}/{self.book_id}/chapters.json"

            # Upsert: insert if not exists, update if does
            self.client.table("book_extractions").upsert(
                {
                    "user_id": self.user_id,
                    "book_id": self.book_id,
                    "extraction_file_path": file_path,
                    "extraction_status": status,
                    "updated_at": datetime.utcnow().isoformat() + "Z",
                },
                on_conflict="user_id,book_id",
            ).execute()

        except Exception as e:
            logger.error(
                f"Failed to update extraction status for {self.book_id}: {e}",
                exc_info=True,
            )

    async def _update_progress(
        self, total_chapters: int, extracted_chapters: int, extracted_indices: list[int]
    ) -> None:
        """Update progress in book_extractions table.

        Args:
            total_chapters: Total number of chapters in the book.
            extracted_chapters: Number of chapters extracted so far.
            extracted_indices: List of chapter indices that have been extracted.
        """
        try:
            # Deduplicate and sort indices
            unique_indices = sorted(set(extracted_indices))
            progress = {
                "total_chapters": total_chapters,
                "extracted_chapters": len(unique_indices),
                "extracted_indices": unique_indices,
                "last_extracted_at": datetime.utcnow().isoformat() + "Z",
            }

            self.client.table("book_extractions").update(
                {"progress": progress, "updated_at": datetime.utcnow().isoformat() + "Z"}
            ).filter("book_id", "eq", self.book_id).filter(
                "user_id", "eq", self.user_id
            ).execute()

        except Exception as e:
            logger.warning(f"Failed to update progress: {e}")

    async def _get_extracted_indices(self) -> set[int]:
        """Get list of already-extracted chapter indices.

        Returns:
            Set of chapter indices that have been extracted.
        """
        try:
            resp = (
                self.client.table("book_extractions")
                .select("progress")
                .filter("book_id", "eq", self.book_id)
                .filter("user_id", "eq", self.user_id)
                .execute()
            )

            if resp.data and resp.data[0].get("progress"):
                indices = resp.data[0]["progress"].get("extracted_indices", [])
                return set(indices)
            return set()
        except Exception as e:
            logger.warning(f"Failed to get extracted indices: {e}")
            return set()

    def _filter_chapters_to_extract(
        self,
        total_chapters: int,
        already_extracted: set[int],
        refresh_mode: str,
        refresh_chapters: Optional[list[int]],
        limit: Optional[int],
    ) -> list[int]:
        """Determine which chapters to extract based on refresh mode.

        Args:
            total_chapters: Total chapters in the book.
            already_extracted: Set of chapter indices already extracted.
            refresh_mode: "skip", "all", or "specific".
            refresh_chapters: List of indices to refresh (for "specific" mode).
            limit: Extract up to this chapter index (e.g., limit=15 means chapters 0-15).

        Returns:
            List of chapter indices to extract.
        """
        if refresh_mode == "all":
            chapters = list(range(total_chapters))
        elif refresh_mode == "specific":
            chapters = refresh_chapters or []
        else:  # "skip" (default)
            chapters = [i for i in range(total_chapters) if i not in already_extracted]

        # Apply limit as an absolute chapter index, not a count
        if limit is not None:
            chapters = [ch for ch in chapters if ch <= limit]

        return chapters

    async def _load_existing_extractions(self) -> dict:
        """Load existing extractions from storage.

        Returns:
            Dict of existing chapter extractions, or empty dict if none exist.
        """
        try:
            file_path = f"extractions/{self.user_id}/{self.series_id}/{self.book_id}/chapters.json"
            content = self.client.storage.from_("extractions").download(file_path)
            return json.loads(content)
        except Exception:
            return {}

    async def _trigger_downstream_stages(self) -> None:
        """Trigger deduplication and ingestion after extraction completes."""
        try:
            from src.knowledge.deduplication_service import DeduplicationService
            from src.knowledge.ingestion_service import IngestionService

            logger.info("Starting deduplication...")
            dedup_service = DeduplicationService(self.user_id, self.book_id, self.series_id)
            await dedup_service.deduplicate_book()

            logger.info("Starting ingestion...")
            ingest_service = IngestionService(self.user_id, self.book_id, self.series_id)
            await ingest_service.ingest_book()

        except Exception as e:
            logger.error(f"Downstream pipeline failed: {e}", exc_info=True)
