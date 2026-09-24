from __future__ import annotations

import json

from models.llm_schemas import LLMComparisonBatch
from models.schemas import Agreement, AgreementClause
from standards.matcher import find_unusual
from utils.security import text_is_safe
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
    warnings: list[str] = []
    standards_brief = [
        {
            "standard_id": entry.standard_id,
            "title": entry.title,
            "standard_expectation": entry.standard_expectation,
            "comparison_guidance": entry.comparison_guidance,
            "contradiction_indicators": entry.contradiction_indicators,
        }
        for entry in library.entries
        if entry.contradiction_indicators
    ]
    user = untrusted_user(
        "Comparison standards:\n" + json.dumps(standards_brief, ensure_ascii=False),
        json.dumps([clause.model_dump() for clause in clauses], ensure_ascii=False) + "\n" + document.full_text,
    )
    parsed, error = try_parse(llm, tracker, AGENT, system_prompt("comparison.txt"), user, LLMComparisonBatch)
    if error:
        warnings.append(error + " Differences were taken from the comparison-standard library.")
    elif isinstance(parsed, LLMComparisonBatch):
        proposals = {(item.clause_number, item.standard_id): item for item in parsed.comparisons}
        revised = []
        for item in grounded:
            proposal = proposals.get((item.clause_number, item.standard_id))
            if (
                proposal
                and proposal.is_unusual
                and text_is_safe(proposal.difference)
                and text_is_safe(proposal.reason)
                and proposal.difference.strip()
                and proposal.reason.strip()
            ):
                revised.append(
                    item.model_copy(update={"difference": proposal.difference, "reason": proposal.reason})
                )
            else:
                if proposal and (not text_is_safe(proposal.difference) or not text_is_safe(proposal.reason)):
                    warnings.append(
                        f"A model explanation for clause {item.clause_number} was discarded because it was not an evidence-based comparison."
                    )
                revised.append(item)
        grounded = revised
    status = "success" if not error else "fallback"
    detail = f"{len(grounded)} unusual clause differences matched the library."
    return {
        "comparisons": [item.model_dump() for item in grounded],
        "warnings": warnings,
        "trace": [trace_dict(AGENT, mark, tracker, status, detail)],
    }
