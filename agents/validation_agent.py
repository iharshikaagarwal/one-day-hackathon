from __future__ import annotations

from models.schemas import (
    Agreement,
    ClauseComparison,
    Evidence,
    FinancialContext,
    FinancialExposure,
    Finding,
    MissingClause,
    NegotiationDraft,
    RankingResult,
    ValidationCheck,
    ValidationSummary,
)
from financial.calculator import CalculationRequest, calculate
from financial.ranking import HIGH_VALUE_INR, impact_label
from utils.format import normalize_text
from utils.security import text_is_safe
from agents.common import started, state_library, trace_dict

AGENT = "Evidence Validator"

FINDING_TITLES = {
    "STD-DAMAGE-001": "Undefined damage deduction",
    "STD-CHARGES-001": "Additional charge or penalty",
    "STD-MOVEIN-001": "Administrative charge",
    "STD-MOVEOUT-001": "Key-return charge",
    "STD-EARLYTERM-001": "Early-termination charge",
}


def run_validation(state: dict, tracker, library_version: str | None = None) -> dict:
    mark = started()
    library = state_library(state)
    legal_categories = set(library.legal_review_categories) if library else set()
    library_version = library_version or state.get("library_version", "")
    document = Agreement.model_validate(state["document"])
    context = FinancialContext.model_validate(state.get("financial_context") or {})
    comparisons = {
        item.comparison_id: item
        for item in (ClauseComparison.model_validate(raw) for raw in state.get("comparisons", []))
    }
    exposures = {
        item.target_id: item
        for item in (FinancialExposure.model_validate(raw) for raw in state.get("exposures", []))
    }
    rankings = {
        item.target_id: item
        for item in (RankingResult.model_validate(raw) for raw in state.get("ranked", []))
    }
    negotiations = {
        item.finding_key: item
        for item in (NegotiationDraft.model_validate(raw) for raw in state.get("negotiations", []))
    }
    missing = [MissingClause.model_validate(raw) for raw in state.get("missing_clauses", [])]
    pages = {page.page: page.text for page in document.pages}

    accepted: list[Finding] = []
    checks: list[ValidationCheck] = []
    rejected_reasons: list[str] = []
    calculations_ok = 0
    calculations_seen = 0

    def _order(item: ClauseComparison) -> tuple[int, str]:
        ranking = rankings.get(item.comparison_id)
        rank = ranking.rank if ranking is not None else None
        return (rank or 10_000, item.clause_number)

    ordered = sorted(comparisons.values(), key=_order)
    for comparison in ordered:
        exposure = exposures.get(comparison.comparison_id)
        ranking = rankings.get(comparison.comparison_id)
        negotiation = negotiations.get(comparison.comparison_id)
        reasons = _validate_unusual(comparison, exposure, negotiation, pages, context)
        calculations_seen += 1
        if exposure and "financial calculation" not in " ".join(reasons):
            calculations_ok += 1
        finding_key = comparison.comparison_id
        if reasons:
            checks.append(ValidationCheck(finding_key=finding_key, accepted=False, reasons=reasons))
            rejected_reasons.extend(reasons)
            continue
        checks.append(ValidationCheck(finding_key=finding_key, accepted=True, reasons=[]))
        accepted.append(
            _unusual_finding(comparison, exposure, ranking, negotiation, library_version, legal_categories)
        )

    for item in missing:
        negotiation = negotiations.get(item.standard_id)
        reasons = _validate_missing(item, negotiation, document)
        if reasons:
            checks.append(ValidationCheck(finding_key=item.standard_id, accepted=False, reasons=reasons))
            rejected_reasons.extend(reasons)
            continue
        checks.append(ValidationCheck(finding_key=item.standard_id, accepted=True, reasons=[]))
        accepted.append(_missing_finding(item, negotiation, library_version, legal_categories))

    accepted = _renumber(accepted)
    excerpts = state.get("injection", {}).get("excerpts", [])
    output_blob = " ".join(_public_text(finding) for finding in accepted)
    if excerpts and text_is_safe(output_blob):
        injection_status = "passed"
        injection_note = (
            "A hostile instruction was found in the document and treated as untrusted text. "
            "It was not followed."
        )
    elif excerpts:
        injection_status = "flagged"
        injection_note = "Hostile text remained in a finding and that finding was held back."
        accepted = [finding for finding in accepted if text_is_safe(_public_text(finding))]
        accepted = _renumber(accepted)
    else:
        injection_status = "not_detected"
        injection_note = "No hostile instruction was detected in the extracted text."

    summary = ValidationSummary(
        evidence_backed=sum(1 for check in checks if check.accepted),
        evidence_considered=len(checks),
        rejected=sum(1 for check in checks if not check.accepted),
        rejected_reasons=rejected_reasons,
        calculations_validated=calculations_ok,
        calculations_considered=calculations_seen,
        missing_checks=len(missing),
        prompt_injection=injection_status,
        injection_note=injection_note,
        checks=checks,
    )
    detail = (
        f"Evidence-backed findings: {summary.evidence_backed}/{summary.evidence_considered}. "
        f"Rejected: {summary.rejected}."
    )
    return {
        "findings": [item.model_dump() for item in accepted],
        "validation": summary.model_dump(),
        "trace": [trace_dict(AGENT, mark, tracker, "success", detail)],
    }


def _quote_candidates(text: str) -> list[str]:
    full = text.strip()
    candidates = [full]
    lines = [line for line in full.splitlines() if line.strip()]
    if len(lines) > 1:
        candidates.append("\n".join(lines[1:]).strip())
    return [item for item in candidates if item]


def _page_contains(quote: str, page_text: str) -> bool:
    return bool(page_text) and normalize_text(quote) in normalize_text(page_text)


def _locate_quote(comparison, pages: dict[int, str]) -> tuple[int | None, str]:
    cited = comparison.page
    quotes = _quote_candidates(comparison.agreement_text)
    order = [cited]
    for offset in (-1, 1):
        neighbour = (cited or 0) + offset
        if neighbour in pages and neighbour not in order:
            order.append(neighbour)
    for page in order:
        page_text = pages.get(page, "")
        if any(_page_contains(quote, page_text) for quote in quotes):
            if page != cited:
                comparison.page = page
            return page, ""
    cited_text = pages.get(cited, "")
    snippet = " ".join(cited_text.split())[:180]
    quote = " ".join((quotes[0] if quotes else comparison.agreement_text).split())[:180]
    detail = (
        f"Clause {comparison.clause_number}: quoted text was not found on page {cited}. "
        f'Rejected quote: "{quote}". Closest page text: "{snippet}".'
    )
    return None, detail


def _validate_unusual(comparison, exposure, negotiation, pages, context) -> list[str]:
    reasons: list[str] = []
    located, reject_note = _locate_quote(comparison, pages)
    if located is None:
        reasons.append(reject_note)
    if not comparison.standard_id or not comparison.standard_expectation:
        reasons.append(f"Clause {comparison.clause_number}: the standard reference is missing.")
    if not comparison.difference or not comparison.reason:
        reasons.append(f"Clause {comparison.clause_number}: the difference is missing.")
    if not text_is_safe(comparison.difference) or not text_is_safe(comparison.reason):
        reasons.append(f"Clause {comparison.clause_number}: the explanation contains an unsupported conclusion.")
    if exposure is None:
        reasons.append(f"Clause {comparison.clause_number}: financial calculation is missing.")
    elif not _calculation_matches(exposure, context):
        reasons.append(f"Clause {comparison.clause_number}: financial calculation is not supported.")
    elif exposure.statement and not text_is_safe(exposure.statement):
        reasons.append(f"Clause {comparison.clause_number}: the exposure statement contains an unsupported conclusion.")
    if negotiation is None:
        reasons.append(f"Clause {comparison.clause_number}: negotiation wording is missing.")
    elif not _negotiation_safe(negotiation):
        reasons.append(f"Clause {comparison.clause_number}: negotiation wording does not match the evidence rules.")
    return reasons


def _validate_missing(item: MissingClause, negotiation, document: Agreement) -> list[str]:
    reasons: list[str] = []
    if not item.standard_id or not item.standard_expectation:
        reasons.append(f"{item.title}: the standard reference is missing.")
    if not item.absence_evidence:
        reasons.append(f"{item.title}: evidence of absence is missing.")
    blob = " ".join([item.why_it_matters, item.absence_evidence, item.suggested_wording])
    if not text_is_safe(blob):
        reasons.append(f"{item.title}: the missing-clause note contains an unsupported conclusion.")
    if "Not found in the extracted text" not in item.absence_evidence and document.full_text:
        reasons.append(f"{item.title}: absence evidence does not describe the search.")
    if negotiation is None or not _negotiation_safe(negotiation):
        reasons.append(f"{item.title}: negotiation wording does not match the evidence rules.")
    return reasons


def _calculation_matches(exposure: FinancialExposure, context: FinancialContext) -> bool:
    request = CalculationRequest(
        formula=exposure.formula if exposure.formula not in {"", "none"} else "none",
        multiplier=exposure.inputs.get("multiplier", 0),
        fixed_amount=exposure.inputs.get("fixed_amount", exposure.inputs.get("daily_amount", 0)),
        percent=exposure.inputs.get("percent", 0),
        period_days=exposure.inputs.get("period_days", 0),
        occurrences=exposure.inputs.get("occurrences", 0),
    )
    if exposure.formula in {"", "none"} or exposure.amount is None:
        return exposure.amount is None
    result = calculate(request, context)
    return result.supported and result.amount is not None and abs(result.amount - exposure.amount) < 0.51


def _negotiation_safe(negotiation: NegotiationDraft) -> bool:
    fields = [
        negotiation.ask,
        negotiation.why_it_matters,
        negotiation.replacement_wording,
        negotiation.ready_to_send_message,
    ]
    return all(field.strip() and text_is_safe(field) for field in fields)


def _unusual_finding(comparison, exposure, ranking, negotiation, library_version: str, legal_categories: set[str]) -> Finding:
    amount = exposure.amount if exposure else None
    reasons = _legal_reasons(comparison.category, exposure, legal_categories)
    return Finding(
        finding_id=comparison.comparison_id,
        kind="unusual",
        rank=ranking.rank if ranking else None,
        clause_number=comparison.clause_number,
        title=FINDING_TITLES.get(comparison.standard_id) or comparison.standard_title or comparison.clause_title,
        category=comparison.category,
        page=comparison.page,
        agreement_text=comparison.agreement_text,
        standard_id=comparison.standard_id,
        standard_title=comparison.standard_title,
        standard_version=comparison.standard_version,
        standard_expectation=comparison.standard_expectation,
        difference=comparison.difference,
        reason=comparison.reason,
        exposure=exposure,
        ranking=ranking,
        negotiation=negotiation,
        evidence=Evidence(
            agreement_text=comparison.agreement_text,
            page=comparison.page,
            clause_number=comparison.clause_number,
            standard_id=comparison.standard_id,
            standard_title=comparison.standard_title,
            standard_text=comparison.standard_expectation,
            difference=comparison.difference,
            library_version=library_version,
        ),
        legal_review=bool(reasons),
        legal_review_reasons=reasons,
        impact_label=impact_label("unusual", amount),
        pattern_notes=comparison.pattern_notes,
        validated=True,
    )


def _missing_finding(item: MissingClause, negotiation, library_version: str, legal_categories: set[str]) -> Finding:
    reasons = _legal_reasons(item.category, None, legal_categories)
    if item.category in legal_categories and not reasons:
        reasons.append("the agreement does not state a figure for this absent topic")
    return Finding(
        finding_id=item.standard_id,
        kind="missing",
        title=item.title,
        category=item.category,
        standard_id=item.standard_id,
        standard_title=item.title,
        standard_version=item.standard_version,
        standard_expectation=item.standard_expectation,
        difference=item.absence_evidence,
        reason=item.why_it_matters,
        negotiation=negotiation,
        evidence=Evidence(
            agreement_text=None,
            page=None,
            clause_number=None,
            standard_id=item.standard_id,
            standard_title=item.title,
            standard_text=item.standard_expectation,
            difference=item.absence_evidence,
            library_version=library_version,
        ),
        legal_review=bool(reasons),
        legal_review_reasons=reasons,
        impact_label="MISSING",
        pattern_notes=item.pattern_notes,
        validated=True,
    )


def _legal_reasons(category: str, exposure: FinancialExposure | None, legal_categories: set[str]) -> list[str]:
    reasons: list[str] = []
    amount = exposure.amount if exposure else None
    ambiguity = exposure.ambiguity if exposure else ""
    if amount is not None and amount >= HIGH_VALUE_INR:
        reasons.append("high-value financial exposure")
    if ambiguity == "high":
        reasons.append("ambiguous clause")
    if exposure is not None and amount is None:
        reasons.append("financial exposure cannot be reliably calculated")
    if category in legal_categories:
        reasons.append("jurisdiction-specific enforceability should be reviewed by a qualified legal professional")
    return reasons


def _renumber(findings: list[Finding]) -> list[Finding]:
    ranked = [item for item in findings if item.kind == "unusual" and item.rank is not None]
    ranked.sort(key=lambda item: item.rank or 0)
    updated = []
    for index, item in enumerate(ranked, start=1):
        ranking = item.ranking.model_copy(update={"rank": index}) if item.ranking else None
        updated.append(item.model_copy(update={"rank": index, "ranking": ranking}))
    others = [item for item in findings if item.kind != "unusual" or item.rank is None]
    return updated + others


def _public_text(finding: Finding) -> str:
    negotiation = finding.negotiation
    parts = [finding.difference, finding.reason, finding.title]
    if finding.exposure:
        parts.append(finding.exposure.statement)
    if negotiation:
        parts.extend(
            [
                negotiation.ask,
                negotiation.why_it_matters,
                negotiation.replacement_wording,
                negotiation.ready_to_send_message,
            ]
        )
    return " ".join(part for part in parts if part)
