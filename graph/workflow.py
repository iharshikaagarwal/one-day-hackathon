from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from agents.agreement_agent import run_agreement_analyst
from agents.type_detection_agent import run_type_detection
from agents.comparison_agent import run_comparison
from agents.exposure_agent import run_exposure
from agents.missing_clause_agent import run_missing
from agents.negotiation_agent import run_negotiation
from agents.ranking_agent import run_ranking
from agents.validation_agent import run_validation
from document.chunker import build_document
from document.parser import parse_pdf
from evaluation.evaluator import maybe_evaluate
from graph.state import AnalysisState
from models.schemas import (
    AgentTraceEntry,
    AgreementTypeDetection,
    AnalysisRun,
    CostSummary,
    Finding,
    StandardLibrary,
    ValidationSummary,
)
from utils.config import ROOT
from utils.cost_tracker import CostTracker
from utils.errors import UserFacingError
from utils.logging import get_logger
from utils.security import scan_injection

logger = get_logger("clauselens.workflow")

NODE_LABELS = {
    "agreement_type_detector": "Agreement Type Detector",
    "agreement_analyst": "Agreement Analyst",
    "standards_comparator": "Standards Comparator",
    "missing_clause_detector": "Missing Clause Detector",
    "financial_exposure": "Financial Exposure Analyzer",
    "financial_ranker": "Financial Impact Ranker",
    "negotiation_agent": "Negotiation Agent",
    "evidence_validator": "Evidence Validator",
}

_LIST_KEYS = {"trace", "errors", "warnings"}


def build_graph(llm, tracker: CostTracker, library_override: StandardLibrary | None = None):
    """The same graph runs for every agreement type. Only the loaded library differs."""
    graph = StateGraph(AnalysisState)  # pyrefly: ignore[bad-specialization]
    graph.add_node("agreement_type_detector", lambda state: run_type_detection(state, tracker, library_override))
    graph.add_node("agreement_analyst", lambda state: run_agreement_analyst(state, llm, tracker))
    graph.add_node("standards_comparator", lambda state: run_comparison(state, llm, tracker))
    graph.add_node("missing_clause_detector", lambda state: run_missing(state, llm, tracker))
    graph.add_node("financial_exposure", lambda state: run_exposure(state, llm, tracker))
    graph.add_node("financial_ranker", lambda state: run_ranking(state, tracker))
    graph.add_node("negotiation_agent", lambda state: run_negotiation(state, llm, tracker))
    graph.add_node("evidence_validator", lambda state: run_validation(state, tracker))
    graph.add_edge(START, "agreement_type_detector")
    graph.add_edge("agreement_type_detector", "agreement_analyst")
    graph.add_conditional_edges(
        "agreement_analyst",
        lambda _state: ["standards_comparator", "missing_clause_detector"],
        ["standards_comparator", "missing_clause_detector"],
    )
    graph.add_edge("standards_comparator", "financial_exposure")
    graph.add_edge("missing_clause_detector", "financial_exposure")
    graph.add_edge("financial_exposure", "financial_ranker")
    graph.add_edge("financial_ranker", "negotiation_agent")
    graph.add_edge("negotiation_agent", "evidence_validator")
    graph.add_edge("evidence_validator", END)
    return graph.compile()


def run_analysis(
    pdf_bytes: bytes,
    filename: str,
    *,
    llm,
    library: StandardLibrary | None = None,
    model_name: str = "",
    on_step: Callable[[str], None] | None = None,
) -> AnalysisRun:
    pages = parse_pdf(pdf_bytes)
    document = build_document(filename, pages)
    if on_step:
        on_step("Document parsed")
    if not document.clauses:
        raise UserFacingError(
            "No numbered clauses were found. Use a text-based PDF with clause numbers such as 7.1."
        )

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    tracker = CostTracker(model=model_name or getattr(llm, "model", ""), run_id=run_id)
    excerpts = scan_injection(
        document.full_text,
        pages=[(page.page, page.text) for page in document.pages],
    )
    graph = build_graph(llm, tracker, library)
    state: dict = {
        "run_id": run_id,
        "filename": filename,
        "document": document.model_dump(),
        "agreement_type": {},
        "library": None,
        "patterns": None,
        "clauses": [],
        "financial_context": {},
        "comparisons": [],
        "missing_clauses": [],
        "exposures": [],
        "ranked": [],
        "negotiations": [],
        "findings": [],
        "validation": {},
        "injection": {"excerpts": excerpts},
        "library_version": "",
        "trace": [],
        "errors": [],
        "warnings": [],
    }
    try:
        for update in graph.stream(state, stream_mode="updates"):
            node_name, partial = next(iter(update.items()))
            _merge_update(state, partial)
            logger.info("completed %s for run %s", node_name, run_id)
            if on_step:
                on_step(NODE_LABELS.get(node_name, node_name))
    except UserFacingError:
        raise
    except Exception as exc:
        logger.error("workflow failed: %s", type(exc).__name__)
        raise UserFacingError(
            "The analysis could not be completed. No signing recommendation was produced."
        ) from exc

    findings = [Finding.model_validate(item) for item in state.get("findings", [])]
    validation = ValidationSummary.model_validate(state.get("validation") or _empty_validation())
    unusual = [item for item in findings if item.kind == "unusual"]
    missing = [item for item in findings if item.kind == "missing"]
    amounts = [item.exposure.amount for item in unusual if item.exposure and item.exposure.amount is not None]
    created_at = datetime.now(timezone.utc).isoformat()
    evaluation = maybe_evaluate(document.full_text, findings, validation, filename=filename)
    active = StandardLibrary.model_validate(state["library"]) if state.get("library") else None
    result = AnalysisRun(
        run_id=run_id,
        created_at=created_at,
        agreement_type=AgreementTypeDetection.model_validate(state["agreement_type"]),
        library_available=active is not None,
        library_name=active.library_name if active else "",
        library_version=active.version if active else "",
        library_disclaimer=active.disclaimer if active else "",
        filename=filename,
        page_count=document.page_count,
        findings=findings,
        unusual_count=len(unusual),
        missing_count=len(missing),
        review_count=sum(1 for item in findings if item.legal_review),
        largest_exposure=max(amounts) if amounts else None,
        currency="INR",
        trace=[AgentTraceEntry.model_validate(item) for item in state.get("trace", [])],
        cost=CostSummary.model_validate(tracker.summary_dict()),
        validation=validation,
        evaluation=evaluation,
        errors=list(state.get("errors", [])),
        warnings=list(dict.fromkeys(state.get("warnings", []))),
        injection_excerpts=excerpts,
    )
    _save_run(result)
    return result


def _merge_update(state: dict, partial: dict) -> None:
    for key, value in partial.items():
        if key in _LIST_KEYS:
            state[key] = list(state.get(key, [])) + list(value)
        else:
            state[key] = value


def _save_run(result: AnalysisRun) -> None:
    folder = ROOT / "runs"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{result.run_id}.json"
    path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    logger.info("saved run %s", result.run_id)


def _empty_validation() -> dict:
    return {
        "evidence_backed": 0,
        "evidence_considered": 0,
        "rejected": 0,
        "rejected_reasons": [],
        "calculations_validated": 0,
        "calculations_considered": 0,
        "missing_checks": 0,
        "prompt_injection": "not_detected",
        "injection_note": "",
        "checks": [],
    }


def canonical_trace(trace: list[AgentTraceEntry]) -> list[AgentTraceEntry]:
    order = list(NODE_LABELS.values())
    by_name = {item.agent: item for item in trace}
    return [by_name[name] for name in order if name in by_name]
