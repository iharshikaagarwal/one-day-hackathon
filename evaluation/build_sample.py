from __future__ import annotations

from pathlib import Path

import pymupdf as fitz

from evaluation.agreement_text import PAGES

SAMPLE_PATH = Path(__file__).resolve().parent / "test_agreements" / "karthik_agreement.pdf"


def build_pdf_bytes(pages: list[str] | None = None) -> bytes:
    pages = pages or PAGES
    document = fitz.open()
    font_path = Path(r"C:\Windows\Fonts\arial.ttf")
    use_custom = font_path.exists()
    try:
        for index, text in enumerate(pages, start=1):
            page = document.new_page(width=595, height=842)
            fontname = "helv"
            body = text
            if use_custom:
                page.insert_font(fontname="body", fontfile=str(font_path))
                fontname = "body"
            else:
                body = text.replace("₹", "Rs. ")
            footer = f"\n\nPage {index} of {len(pages)}"
            rect = fitz.Rect(54, 54, 541, 788)
            leftover = page.insert_textbox(rect, body + footer, fontsize=11, fontname=fontname)
            if leftover < 0:
                raise RuntimeError(f"Page {index} overflowed. Shorten the sample text.")
        return document.tobytes()
    finally:
        document.close()


def write_sample(path: Path | None = None) -> Path:
    target = path or SAMPLE_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(build_pdf_bytes())
    return target


if __name__ == "__main__":
    print(write_sample())
