from __future__ import annotations

import json

from models.llm_schemas import LLMMissingBatch
from models.schemas import Agreement, AgreementClause
from standards.matcher import scan_absence
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

AGENT = "Missing Clause Detector"


def run_missing(state: dict, llm, tracker) -> dict:
    mark = started()
    library = state_library(state)
    patterns = state_patterns(state)
    if library is None or patterns is None:
        return {
            "missing_clauses": [],
            "trace": [skipped_trace(AGENT, mark, tracker, "No standard library for this agreement type.")],
        }
    document = Agreement.model_validate(state["document"])
    clauses = [AgreementClause.model_validate(item) for item in state.get("clauses", [])]
    grounded, checks = scan_absence(document, clauses, library, patterns)
    absent = [item for item in checks if item.endswith(" absent")]
    present = [item for item in checks if item.endswith(" present")]
    check_note = (
        f"Phrase check: {len(present)} present, {len(absent)} absent. "
        + "; ".join(checks)
    )
    if not grounded:
        return {
            "missing_clauses": [],
            "trace": [trace_dict(AGENT, mark, tracker, "success", "0 missing topics. " + check_note)],
        }
    warnings: list[str] = []
    candidates = [
        {
            "standard_id": item.standard_id,
            "title": item.title,
            "standard_expectation": item.standard_expectation,
            "absence_evidence": item.absence_evidence,
        }
        for item in grounded
    ]
    user = untrusted_user(
        "Candidate absent standards. Set absent=true only when the agreement never states that topic. "
        "Set absent=false when the agreement already covers the topic, even in other words. "
        "Do not add any standard that is not in this list.\n"
        + json.dumps(candidates, ensure_ascii=False),
        document.full_text,
    )
    kept = list(grounded)
    parsed, error = try_parse(llm, tracker, AGENT, system_prompt("missing_clause.txt"), user, LLMMissingBatch)
    if error:
        warnings.append(error + " Missing topics were taken from the comparison-standard library.")
    elif isinstance(parsed, LLMMissingBatch):
        proposals = {item.standard_id: item for item in parsed.missing}
        confirmed = []
        for item in grounded:
            proposal = proposals.get(item.standard_id)
            if proposal is not None and proposal.absent is False:
                continue
            if proposal and proposal.why_it_matters.strip() and not text_is_safe(proposal.why_it_matters):
                warnings.append(
                    f"The model's explanation for {item.standard_id} was replaced with the standard's template text because it was not evidence-based."
                )
            confirmed.append(item)
        if proposals:
            kept = confirmed
    status = "success" if not error else "fallback"
    return {
        "missing_clauses": [item.model_dump() for item in kept],
        "warnings": warnings,
        "trace": [trace_dict(AGENT, mark, tracker, status, f"{len(kept)} missing topics. {check_note}")],
    }
