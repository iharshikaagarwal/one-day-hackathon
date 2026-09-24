import re
from pathlib import Path

from evaluation.agreement_text import PAGES as RENTAL_PAGES
from evaluation.build_sample import build_pdf_bytes
from graph.workflow import run_analysis
from standards.agreement_types import detect_agreement_type
from standards.library import library_available, load_library_for
from utils.openai_client import LLMResult

ROOT = Path(__file__).resolve().parents[1]

EMPLOYMENT_PAGES = [
    """EMPLOYMENT AGREEMENT

1. Appointment
1.1 Appointment
The Employer appoints the Employee to the designation of Senior Analyst. The employment starts on 1 October 2026.

2. Salary
2.1 Salary
The Employee shall receive a monthly salary of ₹80,000, paid through payroll on the last working day of each month.

3. Probation and notice
3.1 Probation
The Employee shall be on probation for six months.
3.2 Notice period
Either party may end the employment by giving one month's written notice.""",
    """4. Leaving
4.1 Payment in lieu of notice
If the Employee leaves without serving the notice period, the Employee shall pay the Employer three months' salary in lieu of notice.

5. Restrictions
5.1 Non-compete
For five years after leaving, the Employee shall not work for any competitor anywhere in the world.

6. General
6.1 Confidentiality
The Employee shall keep the Employer's business information confidential.""",
]

VENDOR_PAGES = [
    """SUPPLY AGREEMENT

1. Supply
1.1 Supply of goods
The Supplier shall supply the goods listed in each purchase order issued by the Buyer.
1.2 Delivery schedule
The Vendor shall follow the delivery schedule in each purchase order.

2. Payment
2.1 Invoice
The Buyer shall pay each invoice within 45 days of receiving the goods."""
]


class FakeLLM:
    model = "gpt-4.1-mini"

    def parse(self, *, agent, system, user, response_model):
        return LLMResult(parsed=response_model(), input_tokens=5, output_tokens=2)


def _run(pages: list[str], name: str):
    return run_analysis(build_pdf_bytes(pages), name, llm=FakeLLM(), model_name="gpt-4.1-mini")


def test_rental_sample_is_detected_and_loads_rental_library():
    detected = detect_agreement_type("\n".join(RENTAL_PAGES))
    assert detected.agreement_type == "rental"
    assert detected.library_available is True
    assert detected.confidence >= 0.8
    assert load_library_for("rental").agreement_type == "rental"


def test_employment_agreement_is_routed_through_the_same_pipeline():
    result = _run(EMPLOYMENT_PAGES, "employment.pdf")
    assert result.agreement_type.agreement_type == "employment"
    assert result.library_available is True
    assert "Employment" in result.library_name
    unusual = {item.clause_number: item for item in result.findings if item.kind == "unusual"}
    assert set(unusual) == {"4.1", "5.1"}
    assert unusual["4.1"].exposure.amount == 240000
    assert unusual["4.1"].exposure.calculation_source == "python_calculator"
    assert "monthly salary" in unusual["4.1"].exposure.calculation
    assert unusual["5.1"].exposure is None or unusual["5.1"].exposure.amount is None
    missing = [item.standard_id for item in result.findings if item.kind == "missing"]
    assert missing == ["STD-EMP-FNF-001"]
    assert [entry.agent for entry in result.trace][0] == "Agreement Type Detector"


def test_unsupported_type_is_handled_gracefully():
    assert library_available("vendor") is False
    result = _run(VENDOR_PAGES, "vendor.pdf")
    assert result.agreement_type.agreement_type == "vendor"
    assert result.library_available is False
    assert result.findings == []
    assert result.library_name == ""
    assert any("standard comparison library is not currently available" in item for item in result.warnings)
    skipped = {entry.agent for entry in result.trace if entry.status == "skipped"}
    assert "Standards Comparator" in skipped

    from streamlit.testing.v1 import AppTest

    app = AppTest.from_file(ROOT / "app.py", default_timeout=30)
    app.session_state["results"] = {result.run_id: result.model_dump()}
    app.session_state["latest_run"] = result.run_id
    app.session_state["messages"] = [
        {"role": "user", "kind": "file", "content": "vendor.pdf", "text": ""},
        {"role": "assistant", "kind": "report", "content": "", "run_id": result.run_id},
    ]
    app.session_state["legal_marks"] = []
    app.run()
    assert not app.exception
    assert any("not currently available for this type" in item.value for item in app.info)


def test_engine_code_has_no_rental_vocabulary():
    pattern = re.compile(r"\b(rent|rental|tenant|landlord|security deposit)\b", re.I)
    engine = ["agents", "financial", "graph", "standards", "document"]
    offenders = [
        f"{path.relative_to(ROOT)}:{number}"
        for folder in engine
        for path in (ROOT / folder).glob("*.py")
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if pattern.search(line) and "DEFAULT_TYPE" not in line
    ]
    assert offenders == []
