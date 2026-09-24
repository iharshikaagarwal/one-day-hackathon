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
            if (
                entry.standard_id in generic_ids
                and clause.category in skip_categories
                and not _overrides_generic_skip(entry, clause.text)
            ):
                continue
            indicators = _matching_indicators(entry, clause.text)
            if not indicators:
                continue
            missing = _missing_element_descriptions(entry, clause.text)
            pattern_notes = _pattern_notes(patterns, entry.standard_id, clause.text, absent=False)
            reason, goal, revision = _presentation(entry, indicators, missing)
            by_clause.setdefault(clause.clause_number, []).append(
                ClauseComparison(
                    comparison_id=f"{clause.clause_number}:{entry.standard_id}",
                    clause_number=clause.clause_number,
                    clause_title=clause.title,
                    category=entry.category,
                    page=clause.page,
                    agreement_text=clause.text,
                    standard_id=entry.standard_id,
                    standard_title=entry.title,
                    standard_version=entry.version,
                    standard_expectation=entry.standard_expectation,
                    difference=_difference(entry, indicators, missing),
                    reason=reason,
                    matched_indicators=indicators,
                    missing_elements=missing,
                    pattern_notes=pattern_notes,
                    financial_basis=entry.financial_basis,
                    suggested_revision=revision,
                    negotiation_goal=goal,
                    why_it_matters=reason,
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
    return scan_absence(document, clauses, library, patterns)[0]


def scan_absence(
    document: Agreement,
    clauses: list[AgreementClause],
    library: StandardLibrary,
    patterns: PatternLibrary,
) -> tuple[list[MissingClause], list[str]]:
    """Phrase search finds candidates. A clause in the same category means the topic is present."""
    text = "\n".join(
        part for part in [document.full_text, *(clause.text for clause in clauses)] if part
    )
    page_span = f"1–{document.page_count}" if document.page_count else "0"
    present_categories = {
        clause.category for clause in clauses if clause.category and clause.category not in {"other", "unassigned"}
    }
    missing: list[MissingClause] = []
    checks: list[str] = []
    for entry in library.entries:
        if not entry.report_if_absent:
            continue
        phrase_hit = bool(entry.presence_indicators) and _indicators_present(entry.presence_indicators, text)
        category_hit = entry.category in present_categories
        present = phrase_hit or category_hit
        checks.append(f"{entry.standard_id} {'present' if present else 'absent'}")
        if present:
            continue
        searched = ", ".join(f'"{item}"' for item in entry.presence_indicators) or "the standard's expected elements"
        evidence = (
            f"Not found in the extracted text of pages {page_span}. "
            f"Searched for: {searched}."
        )
        missing.append(
            MissingClause(
                standard_id=entry.standard_id,
                title=entry.title,
                category=entry.category,
                why_it_matters=entry.why_it_matters_if_absent or "The agreement never states this protection.",
                standard_expectation=entry.standard_expectation,
                absence_evidence=evidence,
                suggested_wording=entry.suggested_revision,
                standard_version=entry.version,
                negotiation_goal=entry.negotiation_goal,
                pattern_notes=[],
            )
        )
    return missing, checks


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
    if entry.context_indicators and not _indicators_present(entry.context_indicators, text):
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


def _overrides_generic_skip(entry: StandardClause, text: str) -> bool:
    lowered = _searchable(text)
    return any(
        group.override_generic_skip and any(phrase.lower() in lowered for phrase in group.phrases)
        for group in entry.indicator_groups
    )


def _presentation(entry: StandardClause, indicators: list[str], missing: list[str]) -> tuple[str, str, str]:
    lowered = [item.lower() for item in indicators]
    unpriced = bool(missing)
    for group in entry.indicator_groups:
        if group.only_when_unpriced and not unpriced:
            continue
        if group.reason and any(phrase.lower() in lowered for phrase in group.phrases):
            return (
                group.reason,
                group.negotiation_goal or entry.negotiation_goal,
                group.suggested_revision or entry.suggested_revision,
            )
    return entry.why_it_matters, entry.negotiation_goal, entry.suggested_revision


def _difference(entry: StandardClause, indicators: list[str], missing: list[str]) -> str:
    shown = ", ".join(f'"{item}"' for item in indicators)
    sentence = (
        f"Wording that differs from comparison standard {entry.standard_id} ({entry.title}): {shown}."
    )
    if not missing:
        return sentence
    absent = "; ".join(missing)
    return f"{sentence} Not found in this clause: {absent}."


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
