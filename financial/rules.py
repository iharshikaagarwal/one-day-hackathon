from __future__ import annotations

from models.llm_schemas import LLMExposureRule
from models.schemas import FinancialContext, FinancialTermsConfig
from financial.amounts import (
    capped_amount,
    inr_amounts,
    is_entire_held,
    mentions_any,
    months_of_base_multiplier,
    per_day_amount,
    percents,
    stated_day_count,
)
from financial.calculator import CalculationRequest


def infer_rule(text: str, category: str, terms: FinancialTermsConfig) -> LLMExposureRule:
    if is_entire_held(text, terms.held_amount_nouns):
        return LLMExposureRule(
            level="maximum_asset",
            formula="entire_held_amount",
            multiplier=1,
            recurrence="one_time",
            trigger_likelihood="medium",
            ambiguity="high",
            confidence="high",
            rule_explanation=(
                f"The clause permits retention of the entire {terms.held_amount_label}. "
                f"Potential exposure is that {terms.held_amount_label}. It is a maximum, not a predicted loss."
            ),
        )

    per_day = per_day_amount(text)
    cap = capped_amount(text)
    if per_day is not None and cap is not None:
        return LLMExposureRule(
            level="explicit_amount",
            formula="fixed",
            fixed_amount=cap,
            recurrence="one_time",
            trigger_likelihood="medium",
            ambiguity="low",
            confidence="high",
            rule_explanation="The clause states a daily rate and a cap. The defensible maximum is the stated cap.",
        )
    if per_day is not None:
        days = stated_day_count(text)
        if days is None:
            return _unknown("The clause states a daily amount but not how many days apply, and it states no cap.")
        return LLMExposureRule(
            level="formula",
            formula="daily_fixed",
            fixed_amount=per_day,
            period_days=days,
            recurrence="per_day",
            trigger_likelihood="medium",
            ambiguity="low",
            confidence="medium",
            rule_explanation="The clause states a daily amount and a number of days.",
        )

    months = months_of_base_multiplier(text, terms.base_amount_nouns)
    if months is not None and category != terms.held_amount_category:
        return LLMExposureRule(
            level="formula",
            formula="months_of_base",
            multiplier=months,
            recurrence="one_time",
            trigger_likelihood="medium",
            ambiguity="low",
            confidence="high",
            rule_explanation=(
                f"The clause states a multiple of {terms.base_amount_label}. "
                f"The multiple is applied to the {terms.base_amount_label} in the agreement."
            ),
        )

    percent_values = percents(text)
    if percent_values and mentions_any(text, terms.base_amount_nouns):
        return LLMExposureRule(
            level="formula",
            formula="percent_of_base",
            percent=percent_values[0],
            recurrence="one_time",
            trigger_likelihood="medium",
            ambiguity="low",
            confidence="medium",
            rule_explanation=f"The clause states a percentage of {terms.base_amount_label}.",
        )

    amounts = inr_amounts(text)
    if len(amounts) == 1:
        return LLMExposureRule(
            level="explicit_amount",
            formula="fixed",
            fixed_amount=amounts[0],
            recurrence="one_time",
            trigger_likelihood="medium",
            ambiguity="low",
            confidence="high",
            rule_explanation="The clause states a single monetary amount.",
        )
    if len(amounts) > 1:
        return _unknown("The clause states more than one amount and no single rule identifies which amount is the exposure.")

    return _unknown("The agreement provides no amount or formula for this clause.")


def rule_is_supported(
    rule: LLMExposureRule,
    text: str,
    category: str,
    context: FinancialContext,
    terms: FinancialTermsConfig,
) -> bool:
    if rule.formula == "entire_held_amount":
        return is_entire_held(text, terms.held_amount_nouns) and context.held_amount is not None
    if rule.formula == "months_of_base":
        months = months_of_base_multiplier(text, terms.base_amount_nouns)
        return (
            category != terms.held_amount_category
            and months is not None
            and abs(months - rule.multiplier) < 0.01
            and context.base_amount is not None
        )
    if rule.formula == "years_of_base":
        return context.base_amount is not None and rule.multiplier > 0 and "year" in text.lower()
    if rule.formula == "fixed":
        amounts = inr_amounts(text)
        cap = capped_amount(text)
        candidates = amounts + ([cap] if cap is not None else [])
        return any(abs(amount - rule.fixed_amount) < 0.51 for amount in candidates)
    if rule.formula == "percent_of_base":
        return context.base_amount is not None and any(abs(value - rule.percent) < 0.01 for value in percents(text))
    if rule.formula == "percent_of_held":
        return context.held_amount is not None and any(abs(value - rule.percent) < 0.01 for value in percents(text))
    if rule.formula == "daily_fixed":
        per_day = per_day_amount(text)
        days = stated_day_count(text)
        return (
            per_day is not None
            and days is not None
            and abs(per_day - rule.fixed_amount) < 0.51
            and abs(days - rule.period_days) < 0.01
        )
    if rule.formula == "recurring_fixed":
        amounts = inr_amounts(text)
        return rule.occurrences > 0 and any(abs(amount - rule.fixed_amount) < 0.51 for amount in amounts)
    if rule.formula == "none":
        return infer_rule(text, category, terms).formula == "none"
    return False


def choose_rule(
    text: str,
    category: str,
    context: FinancialContext,
    model_rule: LLMExposureRule | None,
    terms: FinancialTermsConfig,
) -> tuple[LLMExposureRule, str]:
    inferred = infer_rule(text, category, terms)
    if model_rule and rule_is_supported(model_rule, text, category, context, terms):
        if inferred.formula != "none" and model_rule.formula != inferred.formula:
            return inferred, "text_rule"
        chosen = model_rule
        if not model_rule.rule_explanation:
            chosen = chosen.model_copy(update={"rule_explanation": inferred.rule_explanation})
        return chosen, "model_rule_validated"
    return inferred, "text_rule"


def to_calculation_request(rule: LLMExposureRule) -> CalculationRequest:
    return CalculationRequest(
        formula=rule.formula,
        multiplier=rule.multiplier,
        fixed_amount=rule.fixed_amount,
        percent=rule.percent,
        period_days=rule.period_days,
        occurrences=rule.occurrences,
    )


def _unknown(reason: str) -> LLMExposureRule:
    return LLMExposureRule(
        level="unknown",
        formula="none",
        recurrence="one_time",
        trigger_likelihood="low",
        ambiguity="high",
        confidence="low",
        rule_explanation=reason,
    )
