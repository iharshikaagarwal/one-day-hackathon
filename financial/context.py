from __future__ import annotations

from models.schemas import AgreementClause, FinancialContext, FinancialTermsConfig
from financial.amounts import amount_after, months_after


def extract_financial_context(
    clauses: list[AgreementClause],
    full_text: str,
    terms: FinancialTermsConfig | None,
) -> FinancialContext:
    if terms is None:
        return FinancialContext()

    base, base_quote, base_page = _first(clauses, full_text, lambda text: amount_after(text, terms.base_amount_phrases))
    months, months_quote, months_page = _first(clauses, full_text, lambda text: months_after(text, terms.held_months_phrases))
    stated = amount_after(full_text, terms.held_amount_phrases, currency_required=True)

    if stated is not None:
        held, source = stated, "stated_amount"
    elif months is not None and base is not None:
        held, source = months * base, "months_times_base"
    else:
        held, source = None, ""

    return FinancialContext(
        base_amount=base,
        base_amount_label=terms.base_amount_label,
        base_amount_quote=base_quote,
        base_amount_page=base_page,
        held_months=months,
        held_months_quote=months_quote,
        held_months_page=months_page,
        held_amount=held,
        held_amount_label=terms.held_amount_label,
        held_amount_source=source,
    )


def _first(clauses, full_text, finder):
    for clause in clauses:
        value = finder(clause.text)
        if value is not None:
            return value, clause.text, clause.page
    return finder(full_text), "", None
