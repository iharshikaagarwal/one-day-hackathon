from __future__ import annotations

import pymupdf as fitz

from models.schemas import PageText
from utils.errors import UserFacingError

MAX_PAGES = 40
MAX_CHARS = 150_000
MIN_CHARS = 40


def _clean_extracted_text(text: str) -> str:
    return (
        text.replace("\xa0", " ")
        .replace("\u202f", " ")
        .replace("\u2009", " ")
        .replace("\u200b", "")
        .replace("\u00ad", "-")
    )


def parse_pdf(data: bytes) -> list[PageText]:
    if not data:
        raise UserFacingError("The uploaded file is empty.")
    try:
        document = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise UserFacingError("This file could not be read as a PDF.") from exc

    if document.needs_pass:
        document.close()
        raise UserFacingError("This PDF is password protected. Upload an unprotected text-based PDF.")
    if document.page_count == 0:
        document.close()
        raise UserFacingError("The PDF has no pages.")
    if document.page_count > MAX_PAGES:
        count = document.page_count
        document.close()
        raise UserFacingError(
            f"This PDF has {count} pages. ClauseLens analyzes agreements of up to {MAX_PAGES} pages."
        )

    pages: list[PageText] = []
    for index, page in enumerate(document, start=1):
        text = _clean_extracted_text(page.get_text("text") or "")
        pages.append(PageText(page=index, text=text))
    document.close()

    total = sum(len(page.text.strip()) for page in pages)
    if total < MIN_CHARS:
        raise UserFacingError(
            "This PDF has no extractable text. Scanned image-only PDFs are not supported. Export a text-based PDF and try again."
        )
    if total > MAX_CHARS:
        raise UserFacingError(
            "This PDF has too much text for one review. Split it into a shorter agreement and try again."
        )
    return pages
