# %% Imports
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from fpdf import FPDF
from src.ingestion.epub_parser import parse_epub

# Common typographic Unicode → ASCII substitutions
_UNICODE_MAP = str.maketrans(
    {
        "—": "--",   # em dash
        "–": "-",    # en dash
        "‘": "'",    # left single quote
        "’": "'",    # right single quote / apostrophe
        "“": '"',    # left double quote
        "”": '"',    # right double quote
        "…": "...",  # ellipsis
        " ": " ",    # non-breaking space
        "•": "*",    # bullet
        "·": "*",    # middle dot
    }
)


def _sanitize(text: str) -> str:
    """Replace common typographic chars then drop anything still outside latin-1."""
    text = text.translate(_UNICODE_MAP)
    # Normalize accented characters (e.g. é → e) before stripping the rest
    text = unicodedata.normalize("NFKD", text)
    return text.encode("latin-1", errors="ignore").decode("latin-1")

# %% Parameters — edit these
EPUB_PATH = Path("/Users/aravi/Documents/Workspace/Projects/book-lens/uploads/The City of Brass_ A Novel (The Daevabad Trilogy) -- Chakraborty, S_ A.epub")
STOP_BEFORE_CHAPTER = 14  
OUTPUT_PDF = Path(f"chapters_1_to_{STOP_BEFORE_CHAPTER - 1}.pdf")


# %% Parse book
chapters = parse_epub(EPUB_PATH)
print(f"Total chapters parsed: {len(chapters)}")
for ch in chapters:
    print(f"  [{ch.index:>3}] {ch.label}")

# %% Filter to requested range
# STOP_BEFORE_CHAPTER is 1-based human chapter number, index is 0-based
target_chapters = [ch for ch in chapters if ch.index < STOP_BEFORE_CHAPTER - 1]
print(f"\nExporting {len(target_chapters)} chapter(s) (up to and including chapter {STOP_BEFORE_CHAPTER - 1}):")
for ch in target_chapters:
    print(f"  [{ch.index:>3}] {ch.label}")


# %% Generate PDF
class BookPDF(FPDF):
    def header(self) -> None:
        pass

    def footer(self) -> None:
        self.set_y(-12)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(150)
        self.cell(0, 10, f"Page {self.page_no()}", align="C")


pdf = BookPDF()
pdf.set_auto_page_break(auto=True, margin=20)
pdf.set_margins(25, 20, 25)

for ch in target_chapters:
    pdf.add_page()

    # Chapter title
    pdf.set_font("Helvetica", "B", 16)
    pdf.set_text_color(0)
    pdf.multi_cell(0, 10, _sanitize(ch.label), align="C")
    pdf.ln(8)

    # Chapter body
    pdf.set_font("Helvetica", size=11)
    pdf.set_text_color(30)
    for paragraph in ch.text.split("\n\n"):
        paragraph = paragraph.strip()
        if paragraph:
            pdf.multi_cell(0, 6, _sanitize(paragraph))
            pdf.ln(3)

pdf.output(str(OUTPUT_PDF))
print(f"\nPDF saved to: {OUTPUT_PDF.resolve()}")

# %%
