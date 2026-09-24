from __future__ import annotations

from models.schemas import (
    Agreement,
    AgreementClause,
    ClauseComparison,
    MissingClause,
    PatternLibrary,
    StandardClause,
    StandardLibrary,
)


def find_unusual(
    clauses: list[AgreementClause],
    library: StandardLibrary,
    patterns: PatternLibrary,
) -> list[ClauseComparison]:
    generic_ids = set(library.generic_standard_ids)
    skip_categories = set(library.generic_skip_categories)
    by_clause: dict[str, list[ClauseComparison]] = {}
    for clause in clauses:
        for entry in library.entries:
            if entry.standard_id in generic_ids and clause.category in skip_categories:
                continue
            indicators = _matching_indicators(entry, clause.text)
            if not indicators:
                continue
            missing = _missing_element_descriptions(entry, clause.text)
            pattern_notes = _pattern_notes(patterns, entry.standard_id, clause.text, absent=False)
            by_clause.setdefault(clause.clause_number, []).append(
                ClauseComparison(
                    comparison_id=f"{clause.clause_number}:{entry.standard_id}",
                    clause_number=clause.clause_number,
                    clause_title=clause.title,
                    category=clause.category,
                    page=clause.page,
                    agreement_text=clause.text,
                    standard_id=entry.standard_id,
                    standard_title=entry.title,
                    standard_version=entry.version,
                    standard_expectation=entry.standard_expectation,
                    difference=_difference(clause.text, entry, indicators, missing),
                    reason=_reason(entry, pattern_notes),
                    matched_indicators=indicators,
                    missing_elements=missing,
                    pattern_notes=pattern_notes,
                    financial_basis=entry.financial_basis,
                    suggested_revision=entry.suggested_revision,
                    negotiation_goal=entry.negotiation_goal,
                    why_it_matters=entry.why_it_matters,
                )
            )
    chosen: list[ClauseComparison] = []
    for items in by_clause.values():
        specific = [item for item in items if item.standard_id not in generic_ids]
        chosen.extend(specific or items[:1])
    return chosen


def find_missing(
    document: Agreement,
    clauses: list[AgreementClause],
    library: StandardLibrary,
    patterns: PatternLibrary,
) -> list[MissingClause]:
    present_categories = {clause.category for clause in clauses}
    text = document.full_text
    page_span = f"1–{document.page_count}" if document.page_count else "0"
    missing: list[MissingClause] = []
    for entry in library.entries:
        if not entry.report_if_absent:
            continue
        if entry.category in present_categories:
            continue
        if _indicators_present(entry.presence_indicators, text):
            continue
        searched = ", ".join(f'"{item}"' for item in entry.presence_indicators) or "the standard's expected elements"
        evidence = (
            f"Not found in the extracted text of pages {page_span}. "
            f"Searched for: {searched}."
        )
        notes = _pattern_notes(patterns, entry.standard_id, text, absent=True)
        missing.append(
            MissingClause(
                standard_id=entry.standard_id,
                title=entry.title,
                category=entry.category,
                why_it_matters=entry.why_it_matters,
                standard_expectation=entry.standard_expectation,
                absence_evidence=evidence,
                suggested_wording=entry.suggested_revision,
                standard_version=entry.version,
                negotiation_goal=entry.negotiation_goal,
                pattern_notes=notes,
            )
        )
    return missing


def confirm_difference(clause: AgreementClause, entry: StandardClause) -> bool:
    return bool(_matching_indicators(entry, clause.text))


def _searchable(text: str) -> str:
    return " ".join(text.replace("\u00ad", "-").split()).lower()


def _matching_indicators(entry: StandardClause, text: str) -> list[str]:
    lowered = _searchable(text)
    hits = [indicator for indicator in entry.contradiction_indicators if indicator.lower() in lowered]
    if not hits:
        return []
    if entry.presence_indicators and not _indicators_present(entry.presence_indicators, text):
        return []
    return hits


def _indicators_present(indicators: list[str], text: str) -> bool:
    lowered = _searchable(text)
    return any(indicator.lower() in lowered for indicator in indicators)


def _missing_element_descriptions(entry: StandardClause, text: str) -> list[str]:
    lowered = _searchable(text)
    missing: list[str] = []
    for check in entry.element_checks:
        if not any(phrase.lower() in lowered for phrase in check.any_of):
            missing.append(check.description)
    return missing


def _difference(quote: str, entry: StandardClause, indicators: list[str], missing: list[str]) -> str:
    shown = ", ".join(f'"{item}"' for item in indicators)
    absent = "; ".join(missing) if missing else "no further element check failed"
    compact_quote = " ".join(quote.split())
    return (
        f'The agreement says: "{compact_quote}" '
        f"The comparison standard {entry.standard_id} ({entry.title}) expects: {entry.standard_expectation} "
        f"The clause contains wording that differs from that standard: {shown}. "
        f"Elements not found in this clause: {absent}."
    )


def _reason(entry: StandardClause, pattern_notes: list[str]) -> str:
    base = entry.comparison_guidance
    if not pattern_notes:
        return base
    joined = " ".join(pattern_notes)
    return f"{base} Documented comparison pattern, not a legal rule: {joined}"


def _pattern_notes(patterns: PatternLibrary, standard_id: str, text: str, absent: bool) -> list[str]:
    notes: list[str] = []
    lowered = _searchable(text)
    for pattern in patterns.patterns:
        if standard_id not in pattern.related_standard_ids:
            continue
        indicators_hit = any(indicator.lower() in lowered for indicator in pattern.indicators)
        if indicators_hit or (absent and not pattern.indicators):
            notes.append(pattern.why_it_matters)
    return notes
