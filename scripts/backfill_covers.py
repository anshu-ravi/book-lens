"""Backfill cover images for books already uploaded before cover extraction was added.

Scans uploads/ for epubs without a corresponding cover file, runs extraction,
saves the cover, and updates library.json. Safe to re-run — skips books that
already have a cover file on disk.

Usage:
    poetry run python scripts/backfill_covers.py
"""

import json
import sys
from pathlib import Path

# Allow imports from src/
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.config import settings
from backend.ingestion.cover_extractor import extract_cover, fetch_cover_open_library


def main() -> None:
    if not settings.library_path.exists():
        print("library.json not found — nothing to do.")
        return

    library = json.loads(settings.library_path.read_text(encoding="utf-8"))
    patched = 0
    skipped = 0
    failed = 0

    for series in library["series"]:
        sid = series["id"]
        for book in series["books"]:
            idx = book["index"]
            title = book["title"]

            # Already has a cover file on disk — skip
            cover_exists = any(
                (settings.upload_dir / sid / f"cover_{idx}{ext}").exists()
                for ext in [".jpg", ".jpeg", ".png", ".webp", ".gif"]
            )
            if cover_exists:
                book["has_cover"] = True
                skipped += 1
                continue

            epub_path = settings.upload_dir / sid / f"book_{idx}.epub"
            if not epub_path.exists():
                print(f"  [{sid}] book {idx} '{title}': no epub found, skipping")
                skipped += 1
                continue

            print(f"  [{sid}] book {idx} '{title}': extracting...", end=" ", flush=True)
            try:
                result = extract_cover(epub_path)
                if result is None:
                    print("not in epub, trying Open Library...", end=" ", flush=True)
                    result = fetch_cover_open_library(title, epub_path)
                if result is None:
                    print("not found")
                    skipped += 1
                    continue
                cover_bytes, ext = result
                cover_path = settings.upload_dir / sid / f"cover_{idx}{ext}"
                cover_path.write_bytes(cover_bytes)
                book["has_cover"] = True
                patched += 1
                print(f"saved ({len(cover_bytes) // 1024} KB{ext})")
            except Exception as e:
                print(f"ERROR: {e}")
                failed += 1

    settings.library_path.write_text(
        json.dumps(library, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\nDone — {patched} extracted, {skipped} skipped, {failed} failed")


if __name__ == "__main__":
    main()
