from models.llm_schemas import LLMAgreementAnalysis
from models.schemas import Finding, ValidationSummary
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
    assert sorted(item.standard_id for item in missing) == ["STD-INSPECT-001", "STD-REFUND-001"]


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
    missing_ids = sorted(item.standard_id for item in result.findings if item.kind == "missing")
    assert missing_ids == ["STD-INSPECT-001", "STD-REFUND-001"]
    assert result.largest_exposure == 120000
    assert result.cost.label == "Estimated API cost"
    assert result.cost.input_tokens > 0
    assert result.validation.prompt_injection == "passed"
    assert result.evaluation is not None
    assert result.evaluation.ranking_agreement == 1
    assert result.evaluation.normal_clause_false_positive_rate == 0
    assert result.evaluation.clause_detection_recall == 1
    assert result.evaluation.missing_detection_recall == 1
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
