from financial.calculator import CalculationRequest, calculate
from financial.context import extract_financial_context
from models.schemas import AgreementClause, FinancialContext
from standards.library import load_library
from utils.format import format_inr


def _context(**kwargs) -> FinancialContext:
    base = dict(base_amount=20000, base_amount_label="monthly rent", held_months=6, held_amount=120000, held_amount_label="security deposit", held_amount_source="months_times_base")
    base.update(kwargs)
    return FinancialContext(**base)


def test_months_of_rent():
    result = calculate(CalculationRequest(formula="months_of_base", multiplier=2), _context())
    assert result.supported
    assert result.amount == 40000
    assert result.calculation_source == "python_calculator"
    assert "20,000" in result.calculation


def test_percent_of_rent():
    result = calculate(CalculationRequest(formula="percent_of_base", percent=10), _context())
    assert result.amount == 2000


def test_entire_deposit_is_maximum_not_a_loss_prediction():
    result = calculate(CalculationRequest(formula="entire_held_amount", multiplier=1), _context())
    assert result.amount == 120000
    assert result.exposure_type == "maximum_asset"
    assert "potential maximum" in result.calculation.lower()
    assert "you will lose" not in result.calculation.lower()


def test_daily_penalty_requires_a_stated_day_count():
    missing_days = calculate(CalculationRequest(formula="daily_fixed", fixed_amount=500), _context())
    assert missing_days.amount is None
    assert missing_days.supported is False
    counted = calculate(CalculationRequest(formula="daily_fixed", fixed_amount=500, period_days=3), _context())
    assert counted.amount == 1500


def test_unknown_when_inputs_are_missing():
    result = calculate(
        CalculationRequest(formula="months_of_base", multiplier=2),
        FinancialContext(),
    )
    assert result.amount is None


def test_fixed_amount_and_indian_grouping():
    result = calculate(CalculationRequest(formula="fixed", fixed_amount=2000), _context())
    assert result.amount == 2000
    assert format_inr(120000) == "₹1,20,000"
    assert format_inr(40000) == "₹40,000"
    assert format_inr(2000) == "₹2,000"


def test_financial_context_from_clause_text():
    clauses = [
        AgreementClause(
            clause_id="2.1",
            clause_number="2.1",
            title="Monthly rent",
            category="monthly_rent",
            text="The tenant shall pay a monthly rent of ₹20,000, due on the 5th day of each month.",
            page=2,
            chunk_id="page_2_chunk_1",
        ),
        AgreementClause(
            clause_id="2.2",
            clause_number="2.2",
            title="Security deposit",
            category="security_deposit",
            text="The tenant shall pay a security deposit equal to six months' rent before receiving possession.",
            page=2,
            chunk_id="page_2_chunk_2",
        ),
    ]
    context = extract_financial_context(clauses, "\n".join(clause.text for clause in clauses), load_library().financial_terms)
    assert context.base_amount == 20000
    assert context.held_months == 6
    assert context.held_amount == 120000
    assert context.held_amount_source == "months_times_base"
