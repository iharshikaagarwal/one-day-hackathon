from models.schemas import (
    Agreement,
    ClauseComparison,
    FinancialContext,
    FinancialExposure,
    NegotiationDraft,
    PageText,
)
from agents.validation_agent import run_validation
from standards.library import load_library
from utils.cost_tracker import CostTracker
from utils.security import text_is_safe


def _document() -> Agreement:
    text = "7.1 Damage\nThe owner may retain the entire security deposit for any damage caused to the property."
    return Agreement(
        filename="sample.pdf",
        page_count=1,
        pages=[PageText(page=6, text=text)],
        chunks=[],
        clauses=[],
        full_text=text,
    )


def _comparison(**updates) -> dict:
    base = ClauseComparison(
        comparison_id="7.1:STD-DAMAGE-001",
        clause_number="7.1",
        clause_title="Damage",
        category="damage",
        page=6,
        agreement_text="7.1 Damage\nThe owner may retain the entire security deposit for any damage caused to the property.",
        standard_id="STD-DAMAGE-001",
        standard_title="Damage deductions",
        standard_version="1.0.0",
        standard_expectation="Damage should be defined.",
        difference="The clause differs from the comparison standard because damage is undefined.",
        reason="The comparison standard expects a definition and an inspection.",
        financial_basis="Deposit amount.",
        suggested_revision="Deductions shall be itemised.",
        negotiation_goal="Define damage.",
        why_it_matters="The deposit may be retained.",
    )
    return base.model_copy(update=updates).model_dump()


def _exposure() -> dict:
    return FinancialExposure(
        target_id="7.1:STD-DAMAGE-001",
        clause_number="7.1",
        standard_id="STD-DAMAGE-001",
        amount=120000,
        exposure_type="maximum_asset",
        calculation="6 × monthly rent of ₹20,000 = ₹1,20,000.",
        calculation_source="python_calculator",
        formula="entire_held_amount",
        inputs={"held_months": 6, "base_amount": 20000, "held_amount": 120000},
        confidence="high",
        ambiguity="high",
        statement="Up to ₹1,20,000 is potentially exposed.",
        rule_explanation="Entire deposit.",
    ).model_dump()


def _draft() -> dict:
    return NegotiationDraft(
        finding_key="7.1:STD-DAMAGE-001",
        ask="Define damage and itemise deductions.",
        why_it_matters="The deposit may be retained for an undefined word.",
        replacement_wording="Deductions shall be itemised following a joint inspection.",
        ready_to_send_message="Hi, could we revise the damage wording so deductions are itemised after a joint inspection?",
        source="library_template",
    ).model_dump()


def _state(comparison: dict) -> dict:
    return {
        "document": _document().model_dump(),
        "financial_context": FinancialContext(
            base_amount=20000,
            base_amount_label="monthly rent",
            held_months=6,
            held_amount=120000,
            held_amount_label="security deposit",
            held_amount_source="months_times_base",
        ).model_dump(),
        "comparisons": [comparison],
        "exposures": [_exposure()],
        "ranked": [],
        "negotiations": [_draft()],
        "missing_clauses": [],
        "injection": {"excerpts": []},
        "library": load_library().model_dump(),
    }


def test_grounded_finding_is_accepted():
    result = run_validation(_state(_comparison()), CostTracker(model="gpt-4.1-mini", run_id="t"), "1.0.0")
    assert result["validation"]["evidence_backed"] == 1
    assert result["findings"][0]["clause_number"] == "7.1"
    assert result["findings"][0]["legal_review"] is True
    assert result["findings"][0]["title"] == "Undefined damage deduction"


def test_missing_quote_is_rejected():
    bad = _comparison(agreement_text="This sentence is not in the PDF.")
    result = run_validation(_state(bad), CostTracker(model="gpt-4.1-mini", run_id="t"), "1.0.0")
    assert result["findings"] == []
    assert result["validation"]["rejected"] == 1
    note = result["validation"]["rejected_reasons"][0]
    assert "Rejected quote" in note
    assert "Closest page text" in note
    assert "This sentence is not in the PDF." in note


def test_quote_on_adjacent_page_is_accepted():
    comparison = _comparison(page=5)
    result = run_validation(_state(comparison), CostTracker(model="gpt-4.1-mini", run_id="t"), "1.0.0")
    assert result["validation"]["rejected"] == 0
    assert result["findings"][0]["page"] == 6


def test_signing_recommendation_is_rejected():
    bad = _comparison(difference="This agreement is safe to sign.")
    result = run_validation(_state(bad), CostTracker(model="gpt-4.1-mini", run_id="t"), "1.0.0")
    assert result["findings"] == []
    assert text_is_safe("This agreement is safe to sign.") is False


def test_missing_wear_is_not_sent_to_legal_review():
    from models.schemas import MissingClause

    state = _state(_comparison())
    state["missing_clauses"] = [
        MissingClause(
            standard_id="STD-WEAR-001",
            title="Normal wear and tear",
            category="normal_wear",
            why_it_matters="A missing wear-and-tear definition leaves ordinary use open to being treated as damage.",
            standard_expectation="The agreement should define normal wear and tear.",
            absence_evidence='Not found in the extracted text of pages 1–1. Searched for: "wear and tear".',
            suggested_wording="Normal wear and tear means deterioration from ordinary use.",
            standard_version="1.0.0",
            negotiation_goal="Define wear and tear.",
        ).model_dump()
    ]
    state["negotiations"].append(
        NegotiationDraft(
            finding_key="STD-WEAR-001",
            ask="Define wear and tear.",
            why_it_matters="A missing wear-and-tear definition leaves ordinary use open to being treated as damage.",
            replacement_wording="Normal wear and tear means deterioration from ordinary use.",
            ready_to_send_message='Hi, could we revise the Normal wear and tear wording so that it reads as follows: "Normal wear and tear means deterioration from ordinary use."',
            source="library_template",
        ).model_dump()
    )
    result = run_validation(state, CostTracker(model="gpt-4.1-mini", run_id="t"), "1.2.0")
    wear = next(item for item in result["findings"] if item["standard_id"] == "STD-WEAR-001")
    assert wear["legal_review"] is False


def test_negotiation_greeting_uses_owner_name():
    from agents.negotiation_agent import _owner_name, _with_greeting

    assert _with_greeting("Could we revise the damage clause?", "the Owner") == (
        "Hi the Owner, Could we revise the damage clause?"
    )
    assert _with_greeting("Hi, could we revise the damage clause?", "the Owner") == (
        "Hi the Owner, could we revise the damage clause?"
    )
    schedule = (
        'Mr. Test Counterparty (hereinafter called the "Owner").\n'
        "property of the Owner:\nNo.\nItem\nQuantity\n"
    )
    blank = {"filename": "a.pdf", "page_count": 1, "pages": [], "chunks": [], "clauses": []}
    assert _owner_name({"document": {**blank, "full_text": schedule}}) == "Mr Test Counterparty"
    assert _owner_name({"document": {**blank, "full_text": "Owner:\nNo.\nItem\n"}}) == ""


def test_illegal_claim_is_rejected():
    bad = _comparison(reason="This clause is legally invalid and the landlord cannot do this.")
    result = run_validation(_state(bad), CostTracker(model="gpt-4.1-mini", run_id="t"), "1.0.0")
    assert result["findings"] == []
