"""Shared fixtures.

`BOOKLENS_DATA_DIR` is forced to a temp directory for the whole test session so a
test can never write to, or read from, the real `data/`.
"""

import os
import pytest

CORPUS = {
    "red-rising": "Red Rising Trilogy - 01 - Red Rising.epub",
    "golden-son": "Red Rising Trilogy - 02 - Golden Son.epub",
    "final-empire": "Mistborn Trilogy - 01 - The Final Empire.epub",
    "well-of-ascension": "Mistborn Trilogy - 02 - Well of Ascension.epub",
    "hero-of-ages": "Mistborn Trilogy - 03 - Hero of the Ages.epub",
    "morning-star": "Red Rising Trilogy - 03 - Morning Star.epub",
}


@pytest.fixture(scope="session")
def uploads_dir():
    from pathlib import Path

    d = Path(__file__).resolve().parent.parent / "uploads"
    if not d.is_dir():
        pytest.skip("dev corpus not present")
    return d


@pytest.fixture(scope="session")
def corpus(uploads_dir):
    """slug -> Path for each dev-corpus EPUB that is actually present."""
    return {
        slug: uploads_dir / name
        for slug, name in CORPUS.items()
        if (uploads_dir / name).is_file()
    }


@pytest.fixture(autouse=True, scope="session")
def _isolate_data_dir(tmp_path_factory):
    prev = os.environ.get("BOOKLENS_DATA_DIR")
    os.environ["BOOKLENS_DATA_DIR"] = str(tmp_path_factory.mktemp("booklens-data"))
    yield
    if prev is None:
        os.environ.pop("BOOKLENS_DATA_DIR", None)
    else:
        os.environ["BOOKLENS_DATA_DIR"] = prev
