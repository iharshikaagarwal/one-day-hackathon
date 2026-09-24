from __future__ import annotations

from pydantic import BaseModel, Field

from models.schemas import FinancialContext
from utils.format import format_inr


class CalculationRequest(BaseModel):
    formula: str
    multiplier: float = 0
    fixed_amount: float = 0
    percent: float = 0
    period_days: float = 0
    occurrences: float = 0


class CalculationResult(BaseModel):
    amount: float | None = None
    exposure_type: str
    calculation: str
    calculation_source: str = "python_calculator"
    supported: bool
    inputs: dict[str, float] = Field(default_factory=dict)


def calculate(request: CalculationRequest, context: FinancialContext) -> CalculationResult:
    formula = request.formula
    base = context.base_amount
    base_label = context.base_amount_label
    held = context.held_amount
    held_label = context.held_amount_label

    if formula == "fixed":
        if request.fixed_amount <= 0:
            return _unknown("No stated amount was available for a fixed charge.")
        amount = float(request.fixed_amount)
        return CalculationResult(
            amount=amount,
            exposure_type="explicit_amount",
            calculation=f"The clause states {format_inr(amount)}.",
            supported=True,
            inputs={"fixed_amount": amount},
        )

    if formula == "months_of_base":
        if base is None or request.multiplier <= 0:
            return _unknown(f"A months-of-{base_label} formula needs both a multiple and a stated {base_label}.")
        amount = request.multiplier * base
        return CalculationResult(
            amount=amount,
            exposure_type="formula",
            calculation=f"{_trim(request.multiplier)} × {base_label} of {format_inr(base)} = {format_inr(amount)}.",
            supported=True,
            inputs={"multiplier": request.multiplier, "base_amount": base},
        )

    if formula == "years_of_base":
        if base is None or request.multiplier <= 0:
            return _unknown(f"A years-of-{base_label} formula needs both a multiple and a stated {base_label}.")
        amount = request.multiplier * base * 12
        return CalculationResult(
            amount=amount,
            exposure_type="formula",
            calculation=(
                f"{_trim(request.multiplier)} × 12 × {base_label} of {format_inr(base)} = {format_inr(amount)}."
            ),
            supported=True,
            inputs={"multiplier": request.multiplier, "base_amount": base, "months_in_year": 12},
        )

    if formula == "percent_of_base":
        if base is None or request.percent <= 0:
            return _unknown(f"A percentage of {base_label} needs both a percentage and a stated {base_label}.")
        amount = (request.percent / 100.0) * base
        return CalculationResult(
            amount=amount,
            exposure_type="formula",
            calculation=f"{_trim(request.percent)}% × {base_label} of {format_inr(base)} = {format_inr(amount)}.",
            supported=True,
            inputs={"percent": request.percent, "base_amount": base},
        )

    if formula == "percent_of_held":
        if held is None or request.percent <= 0:
            return _unknown(f"A percentage of the {held_label} needs both a percentage and a {held_label} amount.")
        amount = (request.percent / 100.0) * held
        return CalculationResult(
            amount=amount,
            exposure_type="formula",
            calculation=f"{_trim(request.percent)}% × {held_label} of {format_inr(held)} = {format_inr(amount)}.",
            supported=True,
            inputs={"percent": request.percent, "held_amount": held},
        )

    if formula == "daily_fixed":
        if request.fixed_amount <= 0 or request.period_days <= 0:
            return _unknown("A daily charge needs a stated daily amount and a stated number of days.")
        amount = request.fixed_amount * request.period_days
        return CalculationResult(
            amount=amount,
            exposure_type="formula",
            calculation=(
                f"{format_inr(request.fixed_amount)} × {_trim(request.period_days)} days = {format_inr(amount)}."
            ),
            supported=True,
            inputs={"daily_amount": request.fixed_amount, "period_days": request.period_days},
        )

    if formula == "recurring_fixed":
        if request.fixed_amount <= 0 or request.occurrences <= 0:
            return _unknown("A recurring charge needs a stated amount and a stated number of occurrences.")
        amount = request.fixed_amount * request.occurrences
        return CalculationResult(
            amount=amount,
            exposure_type="formula",
            calculation=(
                f"{format_inr(request.fixed_amount)} × {_trim(request.occurrences)} occurrences = {format_inr(amount)}."
            ),
            supported=True,
            inputs={"fixed_amount": request.fixed_amount, "occurrences": request.occurrences},
        )

    if formula == "entire_held_amount":
        if held is None:
            return _unknown(f"The clause refers to the whole {held_label}, but that amount cannot be derived from the agreement.")
        if context.held_amount_source == "months_times_base" and context.held_months and base:
            calculation = (
                f"{_trim(context.held_months)} × {base_label} of {format_inr(base)} = {format_inr(held)}. "
                f"The clause permits retention of that {held_label}. "
                "This is a potential maximum, not a prediction of actual loss."
            )
            inputs = {"held_months": context.held_months, "base_amount": base, "held_amount": held}
        else:
            calculation = (
                f"The clause permits retention of the {held_label} of {format_inr(held)}. "
                "This is a potential maximum, not a prediction of actual loss."
            )
            inputs = {"held_amount": held}
        return CalculationResult(
            amount=held,
            exposure_type="maximum_asset",
            calculation=calculation,
            supported=True,
            inputs=inputs,
        )

    return _unknown("The agreement provides no amount or formula for this clause.")


def _unknown(reason: str) -> CalculationResult:
    return CalculationResult(
        amount=None,
        exposure_type="unknown",
        calculation=reason,
        supported=False,
        inputs={},
    )


def _trim(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return str(value)
