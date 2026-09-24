from __future__ import annotations

import json

from models.llm_schemas import LLMComparisonBatch
from models.schemas import Agreement, AgreementClause
from standards.matcher import confirm_difference, find_unusual
from agents.common import (
    skipped_trace,
    started,
    state_library,
    state_patterns,
    system_prompt,
    trace_dict,
    try_parse,
    untrusted_user,
)

AGENT = "Standards Comparator"


def run_comparison(state: dict, llm, tracker) -> dict:
    mark = started()
    library = state_library(state)
    patterns = state_patterns(state)
    if library is None or patterns is None:
        return {"comparisons": [], "trace": [skipped_trace(AGENT, mark, tracker, "No standard library for this agreement type.")]}
    document = Agreement.model_validate(state["document"])
    clauses = [AgreementClause.model_validate(item) for item in state.get("clauses", [])]
    grounded = find_unusual(clauses, library, patterns)
    by_clause = {item.clause_number: item for item in grounded}
    warnings: list[str] = []
    standards_brief = [
        {
            "standard_id": entry.standard_id,
            "title": entry.title,
            "standard_expectation": entry.standard_expectation,
            "comparison_guidance": entry.comparison_guidance,
            "contradiction_indicators": entry.contradiction_indicators,
            "presence_indicators": entry.presence_indicators,
        }
        for entry in library.entries
        if entry.contradiction_indicators
    ]
    clause_brief = [
        {
            "clause_number": clause.clause_number,
            "title": clause.title,
            "page": clause.page,
            "category": clause.category,
            "text": clause.text,
        }
        for clause in clauses
    ]
    user = untrusted_user(
        "Comparison standards:\n"
        + json.dumps(standards_brief, ensure_ascii=False)
        + "\n\nReturn one verdict for every clause: aligned, differs, or no_standard.",
        json.dumps(clause_brief, ensure_ascii=False),
    )
    parsed, error = try_parse(llm, tracker, AGENT, system_prompt("comparison.txt"), user, LLMComparisonBatch)
    aligned = 0
    no_standard = 0
    added = 0
    if error:
        warnings.append(error + " Differences were taken from the comparison-standard library.")
    elif isinstance(parsed, LLMComparisonBatch):
        clauses_by_number = {clause.clause_number: clause for clause in clauses}
        for proposal in parsed.comparisons:
            verdict = proposal.verdict or ("differs" if proposal.is_unusual else "no_standard")
            if verdict == "aligned":
                aligned += 1
                continue
            if verdict == "no_standard":
                no_standard += 1
                continue
            if proposal.clause_number in by_clause:
                continue
            entry = library.by_id(proposal.standard_id)
            clause = clauses_by_number.get(proposal.clause_number)
            if entry is None or clause is None or not confirm_difference(clause, entry):
                continue
            extras = find_unusual([clause], library, patterns)
            match = next((item for item in extras if item.standard_id == entry.standard_id), None)
            if match is None:
                continue
            by_clause[clause.clause_number] = match
            added += 1

    grounded = list(by_clause.values())
    status = "success" if not error else "fallback"
    detail = (
        f"{len(grounded)} unusual clause differences matched the library "
        f"({aligned} aligned, {no_standard} no_standard, {added} added from a confirmed verdict)."
    )
    return {
        "comparisons": [item.model_dump() for item in grounded],
        "warnings": warnings,
        "trace": [trace_dict(AGENT, mark, tracker, status, detail)],
    }
