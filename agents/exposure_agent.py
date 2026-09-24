from __future__ import annotations

import json

from models.llm_schemas import LLMExposureBatch, LLMExposureRule
from models.schemas import AgreementClause, ClauseComparison, FinancialContext, FinancialExposure
from financial.calculator import calculate
from financial.rules import choose_rule, to_calculation_request
from utils.format import format_inr
from utils.security import text_is_safe
from agents.common import started, state_library, system_prompt, trace_dict, try_parse, untrusted_user

AGENT = "Financial Exposure Analyzer"


def run_exposure(state: dict, llm, tracker) -> dict:
    mark = started()
    comparisons = [ClauseComparison.model_validate(item) for item in state.get("comparisons", [])]
    library = state_library(state)
    if not comparisons or library is None:
        return {"exposures": [], "trace": [trace_dict(AGENT, mark, tracker, "success", "No unusual clauses to price.")]}

    terms = library.financial_terms
    clauses = {item["clause_number"]: AgreementClause.model_validate(item) for item in state.get("clauses", [])}
    context = FinancialContext.model_validate(state.get("financial_context") or {})
    warnings: list[str] = []
    brief = [
        {
            "clause_number": item.clause_number,
            "category": item.category,
            "text": item.agreement_text,
            "financial_basis": item.financial_basis,
        }
        for item in comparisons
    ]
    context_note = (
        f"Base amount ({context.base_amount_label}): "
        f"{context.base_amount if context.base_amount is not None else 'not stated'}. "
        f"Held amount ({context.held_amount_label}) months: "
        f"{context.held_months if context.held_months is not None else 'not stated'}. "
        f"Held amount source: {context.held_amount_source or 'unavailable'}. "
        "Do not multiply these figures. Name the rule only."
    )
    user = untrusted_user(context_note, json.dumps(brief, ensure_ascii=False))
    parsed, error = try_parse(llm, tracker, AGENT, system_prompt("financial_exposure.txt"), user, LLMExposureBatch)
    model_rules: dict[str, LLMExposureRule] = {}
    if error:
        warnings.append(error + " Financial rules were read from the clause text and calculated in Python.")
    elif isinstance(parsed, LLMExposureBatch):
        model_rules = {item.clause_number: item for item in parsed.rules}

    exposures: list[FinancialExposure] = []
    for comparison in comparisons:
        clause = clauses.get(comparison.clause_number)
        text = clause.text if clause else comparison.agreement_text
        category = clause.category if clause else comparison.category
        rule, source = choose_rule(text, category, context, model_rules.get(comparison.clause_number), terms)
        if rule.rule_explanation and not text_is_safe(rule.rule_explanation):
            rule = rule.model_copy(update={"rule_explanation": "The financial rule was taken from the clause text."})
            warnings.append(f"A model financial note for clause {comparison.clause_number} was replaced.")
        result = calculate(to_calculation_request(rule), context)
        exposures.append(
            FinancialExposure(
                target_id=comparison.comparison_id,
                clause_number=comparison.clause_number,
                standard_id=comparison.standard_id,
                amount=result.amount,
                exposure_type=result.exposure_type,
                calculation=result.calculation,
                calculation_source=result.calculation_source,
                formula=rule.formula if result.supported else "none",
                inputs=result.inputs,
                confidence=rule.confidence if result.supported else "low",
                recurrence=rule.recurrence,
                trigger_likelihood=rule.trigger_likelihood,
                ambiguity=rule.ambiguity if result.supported else "high",
                statement=_statement(result.exposure_type, result.amount, result.calculation, context.held_amount_label),
                rule_explanation=rule.rule_explanation,
            )
        )
        if source == "text_rule" and comparison.clause_number in model_rules:
            warnings.append(
                f"The model rule for clause {comparison.clause_number} was not used because the clause text did not support it."
            )

    known = [item.amount for item in exposures if item.amount is not None]
    detail = f"{len(exposures)} rules calculated in Python."
    if known:
        detail += f" Largest amount {format_inr(max(known))}."
    return {
        "exposures": [item.model_dump() for item in exposures],
        "warnings": warnings,
        "trace": [trace_dict(AGENT, mark, tracker, "fallback" if error else "success", detail)],
    }


def _statement(exposure_type: str, amount: float | None, calculation: str, held_label: str) -> str:
    if amount is None or exposure_type == "unknown":
        return "No defensible monetary amount can be calculated from the agreement for this clause."
    if exposure_type == "maximum_asset":
        return (
            f"Up to {format_inr(amount)} is potentially exposed. "
            f"The agreement permits a potential deduction from the {held_label}. "
            "This is a potential maximum, not a prediction of actual loss."
        )
    if exposure_type == "formula":
        return f"Based on {calculation.strip()} The potential exposure is {format_inr(amount)}."
    return (
        f"The agreement states a charge of {format_inr(amount)}. "
        f"The potential exposure is {format_inr(amount)}."
    )
