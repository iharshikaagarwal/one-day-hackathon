from __future__ import annotations

import re

from models.schemas import Agreement, AgreementClause, DocumentChunk, PageText

_HEADING = re.compile(r"^(\d+\.\d+)\s+(\S.*?)\s*$")
_SECTION = re.compile(r"^(\d+)\.\s+([A-Z][A-Z0-9 /,'()\-]{2,})\s*$")
_FOOTER = re.compile(r"^Page\s+\d+\s+of\s+\d+$", re.IGNORECASE)


def build_document(filename: str, pages: list[PageText]) -> Agreement:
    clauses: list[AgreementClause] = []
    chunks: list[DocumentChunk] = []
    for page in pages:
        lines = page.text.splitlines()
        preamble: list[str] = []
        current_number = ""
        current_title = ""
        body: list[str] = []
        chunk_index = 0

        def flush_clause() -> None:
            nonlocal chunk_index, current_number, current_title, body
            if not current_number:
                return
            chunk_index += 1
            text = "\n".join([f"{current_number} {current_title}", *body]).strip()
            chunk_id = f"page_{page.page}_chunk_{chunk_index}"
            clauses.append(
                AgreementClause(
                    clause_id=f"{current_number}",
                    clause_number=current_number,
                    title=current_title.strip(),
                    category="other",
                    text=text,
                    page=page.page,
                    chunk_id=chunk_id,
                    category_source="unassigned",
                )
            )
            chunks.append(DocumentChunk(chunk_id=chunk_id, page=page.page, text=text, section=current_number))
            current_number = ""
            current_title = ""
            body = []

        for raw_line in lines:
            line = raw_line.strip()
            if not line or _FOOTER.match(line):
                if current_number and line == "":
                    body.append("")
                continue
            match = _HEADING.match(line)
            if match:
                flush_clause()
                current_number = match.group(1)
                current_title = match.group(2).strip()
                body = []
                continue
            if current_number and _SECTION.match(line):
                flush_clause()
                preamble.append(line)
                continue
            if current_number:
                body.append(line)
            else:
                preamble.append(line)
        flush_clause()
        if preamble:
            chunk_index += 1
            chunks.append(
                DocumentChunk(
                    chunk_id=f"page_{page.page}_chunk_{chunk_index}",
                    page=page.page,
                    text="\n".join(preamble).strip(),
                    section="",
                )
            )

    full_text = "\n".join(page.text for page in pages)
    return Agreement(
        filename=filename,
        page_count=len(pages),
        pages=pages,
        chunks=chunks,
        clauses=clauses,
        full_text=full_text,
    )
