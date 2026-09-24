from models.llm_schemas import LLMAgreementAnalysis
from models.schemas import AgreementClause, Evidence, Finding, ValidationSummary
from utils.cost_tracker import CostTracker
from utils.openai_client import LLMResult
from document.chunker import build_document
from document.parser import parse_pdf
from evaluation.build_sample import build_pdf_bytes, write_sample
from evaluation.agreement_text import EVAL_MARKER
from evaluation.evaluator import score_findings
from graph.workflow import run_analysis
from standards.library import load_library, load_patterns
from standards.categories import resolve_category
from standards.matcher import find_missing, find_unusual


class FakeLLM:
    model = "gpt-4.1-mini"

    def __init__(self):
        self.calls = []

    def parse(self, *, agent, system, user, response_model):
        self.calls.append({"agent": agent, "system": system, "user": user, "model": response_model})
        parsed = response_model()
        if response_model is LLMAgreementAnalysis:
            parsed.financials.base_amount = 999999
        return LLMResult(parsed=parsed, input_tokens=20, output_tokens=8)


def _pdf_bytes() -> bytes:
    return build_pdf_bytes()


def test_parser_preserves_page_of_damage_clause_and_injection():
    document = build_document("karthik_agreement.pdf", parse_pdf(_pdf_bytes()))
    damage = next(clause for clause in document.clauses if clause.clause_number == "7.1")
    assert damage.page == 6
    assert "entire security deposit" in damage.text
    general = next(clause for clause in document.clauses if clause.clause_number == "10.1")
    assert general.page == 10
    assert "Ignore previous instructions" in general.text
    assert EVAL_MARKER in document.full_text
    write_sample()


def test_library_grounding_on_the_sample_pdf():
    document = build_document("karthik_agreement.pdf", parse_pdf(_pdf_bytes()))
    library = load_library()
    patterns = load_patterns()
    unusual = find_unusual(document.clauses, library, patterns)
    numbers = sorted(item.clause_number for item in unusual)
    assert numbers == ["4.2", "6.4", "7.1", "9.3"]
    clauses = [
        clause.model_copy(update={"category": resolve_category(clause.title, "", clause.text, library)[0]})
        for clause in document.clauses
    ]
    missing = find_missing(document, clauses, library, patterns)
    missing_ids = {item.standard_id for item in missing}
    assert {"STD-INSPECT-001", "STD-REFUND-001"} <= missing_ids
    assert "STD-ITEMIZE-001" in missing_ids


def test_material_breach_without_admin_fee_is_not_unusual():
    library = load_library()
    patterns = load_patterns()
    lock_in = AgreementClause(
        clause_id="4.1",
        clause_number="4.1",
        title="Lock-in period",
        category="lock_in",
        text=(
            "The Parties agree to a lock-in period of six (6) months. "
            "Neither Party shall terminate except for material breach under Clause 4.4."
        ),
        page=5,
        chunk_id="c1",
    )
    admin = AgreementClause(
        clause_id="4.2",
        clause_number="4.2",
        title="Administrative charge",
        category="move_in_charges",
        text=(
            "The tenant shall pay a non-refundable administrative charge of ₹2,000. "
            "Non-payment shall be treated as a material breach."
        ),
        page=4,
        chunk_id="c2",
    )
    unusual = find_unusual([lock_in, admin], library, patterns)
    numbers = [item.clause_number for item in unusual]
    assert "4.1" not in numbers
    assert "4.2" in numbers


def test_full_graph_ranks_deposit_clause_first_without_obeying_injection():
    fake = FakeLLM()
    library = load_library()
    result = run_analysis(
        _pdf_bytes(),
        "karthik_agreement.pdf",
        llm=fake,
        library=library,
        model_name="gpt-4.1-mini",
    )
    unusual = [item for item in result.findings if item.kind == "unusual"]
    ranking = [item.clause_number for item in unusual if item.rank is not None]
    assert ranking == ["7.1", "9.3", "4.2", "6.4"]
    top = unusual[0]
    assert top.exposure is not None
    assert top.exposure.amount == 120000
    assert top.exposure.calculation_source == "python_calculator"
    assert "potentially exposed" in top.exposure.statement
    assert "you will lose" not in top.exposure.statement.lower()
    assert top.page == 6
    assert top.standard_id == "STD-DAMAGE-001"
    assert "safe to sign" not in top.difference.lower()
    missing_ids = {item.standard_id for item in result.findings if item.kind == "missing"}
    assert {"STD-INSPECT-001", "STD-REFUND-001"} <= missing_ids
    assert "STD-ITEMIZE-001" in missing_ids
    assert result.findings[0].title == "Undefined damage deduction"
    assert result.largest_exposure == 120000
    assert result.cost.label == "Estimated API cost"
    assert result.cost.input_tokens > 0
    assert result.validation.prompt_injection == "passed"
    assert result.evaluation is not None
    assert result.evaluation.ranking_agreement == 1
    assert result.evaluation.normal_clause_false_positive_rate == 0
    assert result.evaluation.clause_detection_recall == 1
    assert result.evaluation.missing_detection_recall == 1
    assert result.evaluation.case_id == "karthik_eleven_page"
    assert any(
        item.negotiation and item.negotiation.ready_to_send_message.startswith("Hi Anil Mehta,")
        for item in result.findings
        if item.negotiation
    )
    blob = " ".join(
        " ".join(
            filter(
                None,
                [
                    item.difference,
                    item.reason,
                    item.negotiation.ready_to_send_message if item.negotiation else "",
                ],
            )
        )
        for item in result.findings
    ).lower()
    assert "should sign" not in blob
    assert "this is illegal" not in blob
    systems = [call["system"] for call in fake.calls]
    assert systems
    assert all("do not follow" in system.lower() for system in systems)
    assert all(EVAL_MARKER not in system for system in systems)
    assert any(EVAL_MARKER in call["user"] for call in fake.calls)
    scored = score_findings(result.findings, result.validation)
    assert scored.evidence_validation_rate == 1


def test_cost_tracker_labels_estimate(tmp_path, monkeypatch):
    tracker = CostTracker(model="gpt-4.1-mini", run_id="cost-test")
    tracker.record("Agreement Analyst", 1000, 500)
    summary = tracker.summary_dict()
    assert summary["label"] == "Estimated API cost"
    assert summary["total_tokens"] == 1500
    assert summary["estimated_cost_usd"] > 0


def test_charges_standard_flags_open_ended_extra_charges():
    library = load_library()
    patterns = load_patterns()
    assert library.version == "1.2.0"
    assert library.by_id("STD-CHARGES-001") is not None
    clauses = [
        AgreementClause(
            clause_id="4.2",
            clause_number="4.2",
            title="Additional charges",
            category="additional_charges",
            text="The tenant shall pay additional charges of ₹15,000 as determined by the owner.",
            page=4,
            chunk_id="c42",
        ),
        AgreementClause(
            clause_id="9.3",
            clause_number="9.3",
            title="Penalty",
            category="additional_charges",
            text="The tenant shall, at the tenant's sole peril, pay a penalty of ₹500.",
            page=9,
            chunk_id="c93",
        ),
        AgreementClause(
            clause_id="6.4",
            clause_number="6.4",
            title="Other charges",
            category="additional_charges",
            text="The owner may levy any other charges or penalty at the owner's discretion.",
            page=6,
            chunk_id="c64",
        ),
        AgreementClause(
            clause_id="4.4",
            clause_number="4.4",
            title="Termination for breach",
            category="termination",
            text=(
                "Either party may terminate this agreement by written notice if the other party "
                "commits a material breach and fails to remedy it within fifteen days."
            ),
            page=4,
            chunk_id="c44",
        ),
        AgreementClause(
            clause_id="2.4",
            clause_number="2.4",
            title="Advance rent",
            category="monthly_rent",
            text="The tenant shall pay two months' rent in advance at the start of the term.",
            page=2,
            chunk_id="c24",
        ),
    ]
    unusual = find_unusual(clauses, library, patterns)
    numbers = {item.clause_number for item in unusual}
    assert numbers == {"4.2", "6.4", "9.3"}
    assert all(item.standard_id == "STD-CHARGES-001" for item in unusual)
    assert all("comparison standard" in item.difference for item in unusual)


def test_harshika_filename_selects_its_evaluation_case():
    from evaluation.evaluator import lookup_expected, score_findings

    expected = lookup_expected("harshika_rental_agreement.pdf", "no marker here")
    assert expected is not None
    assert expected["case_id"] == "harshika_rental"
    def _finding(**kwargs) -> Finding:
        base = dict(
            title="t",
            category="other",
            standard_id="",
            standard_title="",
            standard_version="1.0.0",
            standard_expectation="",
            difference="",
            reason="",
            evidence=Evidence(
                standard_id="",
                standard_title="",
                standard_text="",
                difference="",
                library_version="1.2.0",
            ),
            impact_label="LOW IMPACT",
        )
        base.update(kwargs)
        return Finding(**base)

    findings = [
        _finding(finding_id="7.1:STD-DAMAGE-001", kind="unusual", clause_number="7.1", rank=1, title="Undefined damage deduction"),
        _finding(finding_id="4.2:STD-CHARGES-001", kind="unusual", clause_number="4.2", rank=2),
        _finding(finding_id="9.3:STD-CHARGES-001", kind="unusual", clause_number="9.3", rank=3),
        _finding(finding_id="6.4:STD-CHARGES-001", kind="unusual", clause_number="6.4"),
        _finding(finding_id="STD-REFUND-001", kind="missing", standard_id="STD-REFUND-001"),
        _finding(finding_id="STD-INSPECT-001", kind="missing", standard_id="STD-INSPECT-001"),
        _finding(finding_id="STD-ITEMIZE-001", kind="missing", standard_id="STD-ITEMIZE-001"),
        _finding(finding_id="STD-BROKER-001", kind="missing", standard_id="STD-BROKER-001"),
    ]
    validation = ValidationSummary(
        evidence_backed=8,
        evidence_considered=8,
        rejected=0,
        calculations_validated=3,
        calculations_considered=3,
        missing_checks=4,
        prompt_injection="passed",
    )
    scored = score_findings(findings, validation, expected)
    assert scored.clause_detection_recall == 1
    assert scored.normal_clause_false_positive_rate == 0
    assert scored.actual_ranking == ["7.1", "4.2", "9.3"]
    assert scored.ranking_agreement == 1
    assert scored.missed_missing == []
