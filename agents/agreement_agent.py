from __future__ import annotations

import json

from models.llm_schemas import LLMAgreementAnalysis
from models.schemas import Agreement, AgreementClause
from standards.categories import allowed_categories, resolve_category
from financial.context import extract_financial_context
from agents.common import started, state_library, system_prompt, trace_dict, try_parse, untrusted_user

AGENT = "Agreement Analyst"


def run_agreement_analyst(state: dict, llm, tracker) -> dict:
    mark = started()
    document = Agreement.model_validate(state["document"])
    library = state_library(state)
    terms = library.financial_terms if library else None
    agreement_label = (state.get("agreement_type") or {}).get("label", "agreement")
    warnings: list[str] = []

    clauses = [
        clause.model_copy(
            update=dict(zip(("category", "category_source"), resolve_category(clause.title, "", clause.text, library)))
        )
        for clause in document.clauses
    ]
    payload = [
        {"clause_number": clause.clause_number, "title": clause.title, "page": clause.page, "text": clause.text}
        for clause in clauses
    ]
    categories = sorted(allowed_categories(library))
    user = untrusted_user(
        f"Detected agreement type: {agreement_label}. Allowed categories: {', '.join(categories)}. "
        "Annotate each clause in the untrusted document data. Use -1 when an amount is not explicit. Do not compute totals.",
        json.dumps(payload, ensure_ascii=False) + "\n" + document.full_text,
    )
    parsed, error = try_parse(llm, tracker, AGENT, system_prompt("agreement_analysis.txt"), user, LLMAgreementAnalysis)

    if error:
        warnings.append(error + " Clause headings and amounts stated in the PDF were still used.")
    elif isinstance(parsed, LLMAgreementAnalysis):
        by_number = {item.clause_number: item for item in parsed.clauses}
        updated: list[AgreementClause] = []
        for clause in clauses:
            annotation = by_number.get(clause.clause_number)
            if annotation is None:
                updated.append(clause)
                continue
            category, source = clause.category, clause.category_source
            if source != "heading":
                category, source = resolve_category(clause.title, annotation.category, clause.text, library)
            updated.append(
                clause.model_copy(
                    update={
                        "category": category,
                        "category_source": source,
                        "obligations": annotation.obligations,
                        "conditions": annotation.conditions,
                        "penalties": annotation.penalties,
                    }
                )
            )
        clauses = updated

    financials = extract_financial_context(clauses, document.full_text, terms)
    if (
        isinstance(parsed, LLMAgreementAnalysis)
        and parsed.financials.base_amount > 0
        and financials.base_amount is not None
        and abs(parsed.financials.base_amount - financials.base_amount) > 1
    ):
        warnings.append(
            f"A model {financials.base_amount_label} figure was not used because it was not the amount stated in the agreement."
        )

    return {
        "clauses": [clause.model_dump() for clause in clauses],
        "financial_context": financials.model_dump(),
        "warnings": warnings,
        "trace": [
            trace_dict(AGENT, mark, tracker, "fallback" if error else "success", f"Extracted {len(clauses)} clauses.")
        ],
    }
