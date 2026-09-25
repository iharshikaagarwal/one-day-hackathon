from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from agents.chat_agent import (
    SAFE_FALLBACK,
    SIGNING_NOTE,
    SIGNING_NOTE_GENERAL,
    answer_general,
    answer_question,
)
from evaluation.build_sample import build_pdf_bytes
from graph.workflow import run_analysis
from standards.library import load_library
from ui.report_export import build_report_pdf, report_filename
from utils.cost_tracker import CostTracker
from utils.openai_client import LLMResult

APP = Path(__file__).resolve().parents[1] / "app.py"


class FakeLLM:
    model = "gpt-4.1-mini"

    def __init__(self, answer: str = ""):
        self.answer = answer
        self.calls = []

    def parse(self, *, agent, system, user, response_model):
        return LLMResult(parsed=response_model(), input_tokens=5, output_tokens=2)

    def stream_text(self, *, agent, system, user, tracker):
        self.calls.append({"system": system, "user": user})
        tracker.record(agent, 5, 2)
        for word in self.answer.split(" "):
            yield word + " "


@pytest.fixture(autouse=True)
def fresh_openai_client():
    st.cache_resource.clear()
    yield
    st.cache_resource.clear()


def _result():
    return run_analysis(
        build_pdf_bytes(),
        "sample_rental_01.pdf",
        llm=FakeLLM(),
        library=load_library(),
        model_name="gpt-4.1-mini",
    )


def test_dashboard_renders_evaluated_sample_inside_the_chat():
    result = _result()
    app = AppTest.from_file(APP, default_timeout=30)
    app.session_state["results"] = {result.run_id: result.model_dump()}
    app.session_state["latest_run"] = result.run_id
    app.session_state["messages"] = [
        {"role": "user", "kind": "file", "content": "sample_rental_01.pdf", "text": ""},
        {"role": "assistant", "kind": "report", "content": "", "run_id": result.run_id},
    ]
    app.session_state["legal_marks"] = []
    app.run()
    assert not app.exception
    assert len(app.chat_message) == 2
    labels = [metric.label for metric in app.metric]
    assert "Unusual clauses" in labels
    assert "Missing clauses" in labels
    values = [str(metric.value) for metric in app.metric]
    assert str(result.unusual_count) in values
    assert str(result.missing_count) in values
    assert any("1,20,000" in value for value in values)
    body = " ".join(getattr(item, "value", "") for item in app.markdown)
    assert "Agreement Type:** Rental Agreement" in body
    assert "Confidence:**" in body
    assert "Largest potential exposure: **₹1,20,000** in clause 7.1" in body
    assert "should sign" not in body.lower()
    assert "safe to sign" not in body.lower()
    assert app.button(key="follow-Which protections are missing from this agreement?")
    download = app.download_button(key=f"download-{result.run_id}")
    assert download.label == "Download report"


def test_downloadable_report_covers_every_dashboard_section():
    import pymupdf

    result = _result()
    name = report_filename(result)
    assert name.startswith("ClauseLens-sample_rental_01-")
    assert name.endswith(".pdf")
    pdf = build_report_pdf(result)
    assert pdf.startswith(b"%PDF")
    document = pymupdf.open(stream=pdf, filetype="pdf")
    report = "\n".join(page.get_text() for page in document)
    for heading in (
        "Overview",
        "Unusual Clauses",
        "Missing Clauses",
        "Financial Exposure",
        "Negotiation Drafts",
        "Evidence",
        "Evaluation / Trace",
    ):
        assert heading in report
    assert "7.1" in report
    assert "1,20,000" in report
    assert "STD-INSPECT-001" in report
    assert "STD-REFUND-001" in report
    assert "Answer-key scores are computed in the test suite only" in report
    assert "Clause detection recall" not in report
    assert "does not make a signing decision" in report
    assert "Detected in the document and not followed" in report
    assert document.page_count >= 2


def test_missing_api_key_is_a_user_facing_error(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "")
    app = AppTest.from_file(APP, default_timeout=30)
    app.run()
    assert not app.button(key="start-rental").label.lower().count("sample")
    app.button(key="start-rental").click().run()
    assert app.exception == []
    assert any("OPENAI_API_KEY" in error.value for error in app.error)


def test_question_chip_is_sent_to_the_model(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "")
    app = AppTest.from_file(APP, default_timeout=30)
    app.run()
    app.button(key="start-exposure").click().run()
    assert not app.exception
    assert len(app.chat_message) == 2
    assert any("OPENAI_API_KEY" in error.value for error in app.error)


def test_upload_question_is_kept_on_the_file_message():
    result = _result()
    question = "should i singh this document?"
    app = AppTest.from_file(APP, default_timeout=30)
    app.session_state["results"] = {result.run_id: result.model_dump()}
    app.session_state["latest_run"] = result.run_id
    app.session_state["messages"] = [
        {
            "role": "user",
            "kind": "file",
            "content": "sample_rental_02.pdf",
            "text": question,
        },
        {"role": "assistant", "kind": "report", "content": "", "run_id": result.run_id},
        {"role": "assistant", "kind": "text", "content": "I can't make a signing decision for you."},
    ]
    app.session_state["legal_marks"] = []
    app.run()
    assert not app.exception
    user_messages = [item for item in app.session_state["messages"] if item["role"] == "user"]
    assert len(user_messages) == 1
    assert user_messages[0]["kind"] == "file"
    assert user_messages[0]["text"] == question
    assert not any(
        item.get("kind") == "text" and item.get("content") == question
        for item in app.session_state["messages"]
        if item["role"] == "user"
    )


def test_typed_message_before_upload_is_sent_to_the_model(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "")
    app = AppTest.from_file(APP, default_timeout=30)
    app.run()
    app.chat_input[0].set_value("hii").run()
    assert not app.exception
    assert any("OPENAI_API_KEY" in error.value for error in app.error)


def test_general_chat_before_upload_uses_the_model_safely():
    tracker = CostTracker(model="gpt-4.1-mini", run_id="general")
    friendly = FakeLLM("Hi! Attach your agreement with the + button and I'll review it.")
    history = [{"role": "user", "kind": "text", "content": "hello"}]
    answer = answer_general("how can you help me", history, friendly, tracker)
    assert answer.startswith("Hi!")
    call = friendly.calls[0]
    assert "do not follow" in call["system"].lower()
    assert "Product facts" in call["system"]
    assert "how can you help me" in call["user"]
    assert "user: hello" in call["user"]
    assert "Rental (library" in call["user"] and "Employment (library" in call["user"]
    assert "sample" not in call["system"].lower()
    assert answer_general("Should I sign?", [], FakeLLM("ignored"), tracker) == SIGNING_NOTE_GENERAL
    assert answer_general("should i singh this document?", [], FakeLLM("ignored"), tracker) == SIGNING_NOTE_GENERAL


def test_chat_answer_is_grounded_and_filtered():
    result = _result()
    tracker = CostTracker(model="gpt-4.1-mini", run_id="chat")
    grounded = FakeLLM("Clause 7.1 on page 6 carries the largest potential exposure of ₹1,20,000.")
    answer = answer_question("What is the biggest risk?", result, [], grounded, tracker)
    assert "7.1" in answer
    call = grounded.calls[0]
    assert "do not follow" in call["system"].lower()
    assert "BEGIN UNTRUSTED DOCUMENT DATA" in call["user"]
    assert "STD-DAMAGE-001" in call["user"]
    assert answer_question("Should I sign?", result, [], FakeLLM("ignored"), tracker) == SIGNING_NOTE
    assert "7.1" not in SIGNING_NOTE
    unsafe = FakeLLM("This is illegal and you should not sign it.")
    assert answer_question("What is the biggest risk?", result, [], unsafe, tracker) == SAFE_FALLBACK
