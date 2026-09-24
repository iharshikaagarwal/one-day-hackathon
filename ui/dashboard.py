from __future__ import annotations

import pandas as pd
import streamlit as st

from graph.workflow import canonical_trace
from models.schemas import AnalysisRun, Finding
from standards.library import load_library_for
from utils.format import format_inr

EXPOSURE_LABELS = {
    "explicit_amount": "Explicit amount",
    "formula": "Formula from agreement values",
    "maximum_asset": "Maximum relevant asset",
    "unknown": "Unknown",
}

IMPACT_COLORS = {
    "HIGH IMPACT": "red",
    "MEDIUM IMPACT": "orange",
    "LOW IMPACT": "gray",
    "MISSING": "violet",
    "REVIEW REQUIRED": "orange",
}


def render_dashboard(result: AnalysisRun) -> None:
    detected = result.agreement_type
    st.markdown(
        f"**Agreement Type:** {detected.label} &nbsp;·&nbsp; **Confidence:** {detected.confidence:.0%}"
    )
    if detected.reasoning:
        st.caption(detected.reasoning)
    if result.library_available:
        st.caption(
            f"{result.library_name} {result.library_version}, reviewed { _review_date(result) }. "
            "This is a comparison baseline, not a legal requirement. "
            "ClauseLens does not make a signing decision."
        )
    else:
        st.info(
            "Agreement type detected, but a standard comparison library is not currently available "
            "for this type. ClauseLens does not make a signing decision."
        )
    if result.warnings:
        for warning in result.warnings:
            st.warning(warning)

    overview, unusual, missing, financial, negotiation, evidence, evaluation = st.tabs(
        [
            "Overview",
            "Unusual Clauses",
            "Missing Clauses",
            "Financial Exposure",
            "Negotiation Drafts",
            "Evidence",
            "Evaluation / Trace",
        ]
    )
    with overview:
        _overview(result)
    with unusual:
        _unusual(result)
    with missing:
        _missing(result)
    with financial:
        _financial(result)
    with negotiation:
        _negotiation(result)
    with evidence:
        _evidence(result)
    with evaluation:
        _evaluation(result)


def _review_date(result: AnalysisRun) -> str:
    library = load_library_for(result.agreement_type.agreement_type)
    if library and library.version == result.library_version:
        return library.review_date
    return result.library_version


def _overview(result: AnalysisRun) -> None:
    with st.container(horizontal=True):
        st.metric("Unusual clauses", result.unusual_count, border=True)
        st.metric("Missing clauses", result.missing_count, border=True)
        st.metric(
            "Potential financial exposure",
            format_inr(result.largest_exposure) if result.largest_exposure is not None else "Unknown",
            border=True,
            help=(
                "Largest defensible single-clause exposure. Amounts are not added together, "
                "because different clauses may overlap. This is not a prediction of loss."
            ),
        )
        st.metric("Clauses requiring review", result.review_count, border=True)

    st.subheader("Top financial exposures")
    st.caption(
        "Ranked by potential financial exposure. Ranking is based on defensible financial exposure "
        "derived from the agreement. Clauses without a monetary basis are not assigned invented values."
    )
    ranked = [item for item in result.findings if item.kind == "unusual" and item.rank is not None]
    if not ranked:
        st.caption("No clause had a defensible monetary exposure.")
    for finding in sorted(ranked, key=lambda item: item.rank or 0):
        _exposure_card(finding)

    unknown = [
        item
        for item in result.findings
        if item.kind == "unusual" and (item.exposure is None or item.exposure.amount is None)
    ]
    if unknown:
        st.subheader("Clauses without a defensible amount")
        for finding in unknown:
            st.caption(f"Clause {finding.clause_number} — {finding.title}. No amount was invented.")

    _lawyer_note()


def _exposure_card(finding: Finding) -> None:
    exposure = finding.exposure
    with st.container(border=True):
        st.badge(
            finding.impact_label,
            color=IMPACT_COLORS.get(finding.impact_label, "gray"),
            icon=":material/payments:",
        )
        if finding.rank == 1:
            st.badge("Highest measurable exposure", color="primary")
        st.markdown(f"**#{finding.rank} {finding.title}**")
        amount = format_inr(exposure.amount) if exposure and exposure.amount is not None else "Unknown"
        kind = EXPOSURE_LABELS.get(exposure.exposure_type, exposure.exposure_type) if exposure else "Unknown"
        st.write(f"{amount} · {kind}")
        st.caption(f"Page {finding.page} · Clause {finding.clause_number}")
        if exposure:
            st.write(exposure.statement)
        _action_row(finding, "overview")


def _unusual(result: AnalysisRun) -> None:
    st.caption("Each flag quotes the agreement, names a standard-library entry, and explains the difference.")
    findings = [item for item in result.findings if item.kind == "unusual"]
    if not findings:
        st.caption("No unusual clause passed evidence validation.")
        return
    for finding in findings:
        label = f"#{finding.rank} {finding.title}" if finding.rank else finding.title
        with st.expander(label):
            _finding_detail(finding, "unusual")


def _missing(result: AnalysisRun) -> None:
    st.subheader("What's missing?")
    findings = [item for item in result.findings if item.kind == "missing"]
    if not findings:
        st.caption("Every comparison topic marked as a required protection was found in the agreement.")
        return
    for finding in findings:
        with st.container(border=True):
            st.badge("MISSING", color="violet", icon=":material/search_off:")
            st.markdown(f"**{finding.title}**")
            st.markdown("**Why it matters**")
            st.write(finding.reason)
            st.markdown("**Standard expectation**")
            st.write(finding.standard_expectation)
            st.markdown("**Evidence that it is absent**")
            st.write(finding.difference)
            if finding.negotiation:
                st.markdown("**Suggested wording**")
                st.write(finding.negotiation.replacement_wording)
            _action_row(finding, "missing")


def _financial(result: AnalysisRun) -> None:
    st.subheader("Ranked by potential financial exposure")
    st.caption(
        "Ranking is based on defensible financial exposure derived from the agreement. "
        "Clauses without a monetary basis are not assigned invented values. "
        "Score weights: financial exposure 50%, recurrence 20%, trigger likelihood 15%, ambiguity 15%."
    )
    ranked = [item for item in result.findings if item.kind == "unusual" and item.exposure and item.exposure.amount]
    if ranked:
        frame = pd.DataFrame(
            {
                "Clause": [f"{item.clause_number} {item.title}" for item in ranked],
                "Potential exposure (INR)": [item.exposure.amount for item in ranked],
            }
        )
        st.bar_chart(frame, x="Clause", y="Potential exposure (INR)", horizontal=True, sort=False)
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Rank": item.rank,
                        "Clause": item.clause_number,
                        "Title": item.title,
                        "Exposure": format_inr(item.exposure.amount),
                        "Type": EXPOSURE_LABELS.get(item.exposure.exposure_type, item.exposure.exposure_type),
                        "Confidence": item.exposure.confidence,
                        "Page": item.page,
                    }
                    for item in ranked
                ]
            ),
            hide_index=True,
        )
        for item in ranked:
            if item.ranking:
                with st.expander(f"Why clause {item.clause_number} is ranked #{item.rank}"):
                    st.write(item.ranking.ranking_reason)
                    st.write(item.exposure.calculation)
    else:
        st.caption("No quantitative ranking was available.")


def _negotiation(result: AnalysisRun) -> None:
    st.subheader("Negotiation drafts")
    st.caption("Messages are concise and non-confrontational. Edit names or dates if you need to.")
    drafts = [item for item in result.findings if item.negotiation]
    if not drafts:
        st.caption("No negotiation draft passed validation.")
        return
    for finding in drafts:
        draft = finding.negotiation
        with st.container(border=True):
            title = finding.clause_number or finding.standard_id
            st.markdown(f"**{title} — {finding.title}**")
            st.markdown("**Problem**")
            st.write(finding.reason)
            st.markdown("**Suggested replacement clause**")
            st.write(draft.replacement_wording)
            st.markdown("**Ready-to-send message**")
            st.caption("Copy message")
            st.code(draft.ready_to_send_message, language="text")


def _evidence(result: AnalysisRun) -> None:
    for finding in result.findings:
        label = finding.clause_number or finding.standard_id
        with st.expander(f"{label} — {finding.title}"):
            _evidence_block(finding)


def _evaluation(result: AnalysisRun) -> None:
    validation = result.validation
    st.subheader("Validation")
    st.write(f"Evidence-backed findings: {validation.evidence_backed}/{validation.evidence_considered}")
    st.write(f"Unsupported findings rejected: {validation.rejected}")
    st.write(
        f"Financial calculations validated: {validation.calculations_validated}/{validation.calculations_considered}"
    )
    st.write(f"Missing-clause checks: {validation.missing_checks}")
    injection = {
        "passed": "Passed",
        "flagged": "Flagged",
        "not_detected": "No hostile instruction detected",
    }.get(validation.prompt_injection, validation.prompt_injection)
    st.write(f"Prompt-injection checks: {injection}")
    if validation.injection_note:
        st.caption(validation.injection_note)
    if result.injection_excerpts:
        st.caption("Detected in the document and not followed:")
        for excerpt in result.injection_excerpts:
            st.code(excerpt, language="text")
    if validation.rejected_reasons:
        with st.expander("Rejected finding notes"):
            for reason in validation.rejected_reasons:
                st.write(reason)

    st.subheader("Evaluation dataset")
    if result.evaluation is None:
        st.caption(
            "These metrics are computed only when the uploaded PDF is the ClauseLens evaluation agreement. "
            "They are not shown as general accuracy. Upload evaluation/test_agreements/karthik_agreement.pdf to score this case."
        )
    else:
        stats = result.evaluation
        st.caption(stats.dataset_label)
        st.write(f"Clause detection recall: {_pct(stats.clause_detection_recall)}")
        st.write(f"Clause detection precision: {_pct(stats.clause_detection_precision)}")
        st.write(f"Missing-clause detection: {_pct(stats.missing_detection_recall)}")
        st.write(f"False positive rate on normal clauses: {_pct(stats.normal_clause_false_positive_rate)}")
        agreement = "n/a" if stats.ranking_agreement is None else _pct(stats.ranking_agreement)
        st.write(f"Ranking agreement: {agreement} on this evaluation case.")
        st.write(f"Evidence validation rate: {_pct(stats.evidence_validation_rate)}")
        left, right = st.columns(2)
        with left:
            st.markdown("**Expected ranking**")
            st.write(" > ".join(stats.expected_ranking))
        with right:
            st.markdown("**AI ranking**")
            st.write(" > ".join(stats.actual_ranking) if stats.actual_ranking else "None")
        if stats.missed_unusual or stats.unexpected_unusual or stats.false_positive_normal_clauses or stats.missed_missing:
            st.markdown("**Differences from the expected case**")
            if stats.missed_unusual:
                st.write("Unusual clauses not found: " + ", ".join(stats.missed_unusual))
            if stats.unexpected_unusual:
                st.write("Additional unusual clauses: " + ", ".join(stats.unexpected_unusual))
            if stats.false_positive_normal_clauses:
                st.write("Normal clauses flagged: " + ", ".join(stats.false_positive_normal_clauses))
            if stats.missed_missing:
                st.write("Missing topics not found: " + ", ".join(stats.missed_missing))

    with st.expander("Analysis trace"):
        st.write(f"Run ID: {result.run_id}")
        for entry in canonical_trace(result.trace):
            mark = "Completed" if entry.status in {"success", "fallback"} else entry.status
            st.write(
                f"{mark} — {entry.agent} — {entry.duration_ms} ms — "
                f"input tokens {entry.input_tokens} — output tokens {entry.output_tokens}"
            )
            if entry.detail:
                st.caption(entry.detail)
            if entry.status == "fallback":
                st.caption("This step used the library fallback after the model request failed.")
        cost = result.cost
        st.write(f"Total input tokens: {cost.input_tokens}")
        st.write(f"Total output tokens: {cost.output_tokens}")
        st.write(f"Estimated API cost: ${cost.estimated_cost_usd:.6f}")
        st.caption(cost.pricing_note)
        st.write("Model: " + cost.model)
        total_ms = sum(entry.duration_ms for entry in result.trace)
        st.write(f"Total traced step time: {total_ms} ms")

    _library_maintenance()
    _lawyer_note()


def _finding_detail(finding: Finding, scope: str) -> None:
    _badges(finding)
    st.markdown(f"**{finding.title}**")
    left, right = st.columns(2)
    with left:
        st.markdown("**Agreement clause**")
        st.write(finding.agreement_text or "This topic is not in the agreement.")
        st.caption(f"Page {finding.page if finding.page else 'not present'} · Clause {finding.clause_number or 'not present'}")
    with right:
        st.markdown("**Standard comparison**")
        st.write(finding.standard_expectation)
        st.caption(f"{finding.standard_id} · {finding.standard_title} · v{finding.standard_version}")
    st.markdown("**Why flagged**")
    st.write(finding.reason)
    st.markdown("**Difference**")
    st.write(finding.difference)
    if finding.exposure:
        st.markdown("**Financial exposure**")
        amount = format_inr(finding.exposure.amount) if finding.exposure.amount is not None else "Unknown"
        kind = EXPOSURE_LABELS.get(finding.exposure.exposure_type, finding.exposure.exposure_type)
        st.write(f"{amount} · {kind} · Confidence {finding.exposure.confidence}")
        st.write(finding.exposure.calculation)
        st.caption(finding.exposure.statement)
    if finding.pattern_notes:
        st.caption("Documented comparison pattern, not a legal rule: " + " ".join(finding.pattern_notes))
    if finding.negotiation:
        st.markdown("**Negotiation**")
        st.write(finding.negotiation.ask)
        st.markdown("**Suggested change**")
        st.write(finding.negotiation.replacement_wording)
        st.caption("Copy message")
        st.code(finding.negotiation.ready_to_send_message, language="text")
    _evidence_block(finding)
    if finding.legal_review:
        st.badge("Review required", color="orange", icon=":material/balance:")
        st.caption("; ".join(finding.legal_review_reasons))
    _review_button(finding, scope)


def _evidence_block(finding: Finding) -> None:
    evidence = finding.evidence
    st.markdown("**Source**")
    if evidence.page and evidence.clause_number:
        st.caption(f"Page {evidence.page} — Clause {evidence.clause_number}")
    elif evidence.page:
        st.caption(f"Page {evidence.page}")
    else:
        st.caption("No page, because this topic was not found in the extracted text.")
    if evidence.agreement_text:
        st.write(evidence.agreement_text)
    st.markdown("**Standard**")
    st.caption(f"{evidence.standard_title} · {evidence.standard_id} · library {evidence.library_version}")
    st.write(evidence.standard_text)
    st.markdown("**Difference**")
    st.write(evidence.difference)


def _action_row(finding: Finding, scope: str) -> None:
    if finding.legal_review:
        st.badge("Review required", color="orange", icon=":material/balance:")
        st.caption("; ".join(finding.legal_review_reasons))
    with st.container(horizontal=True):
        evidence_key = f"evidence-{scope}-{finding.finding_id}"
        draft_key = f"draft-{scope}-{finding.finding_id}"
        if st.button("View evidence", key=f"btn-{evidence_key}"):
            _toggle(evidence_key)
        if finding.negotiation and st.button("Negotiation draft", key=f"btn-{draft_key}"):
            _toggle(draft_key)
        _review_button(finding, scope)
    if st.session_state.get(evidence_key):
        _evidence_block(finding)
    if finding.negotiation and st.session_state.get(draft_key):
        st.caption("Copy message")
        st.code(finding.negotiation.ready_to_send_message, language="text")


def _review_button(finding: Finding, scope: str) -> None:
    marks = st.session_state.setdefault("legal_marks", [])
    label = "Marked for legal review" if finding.finding_id in marks else "Mark for legal review"
    if st.button(label, key=f"review-{scope}-{finding.finding_id}"):
        if finding.finding_id in marks:
            marks.remove(finding.finding_id)
        else:
            marks.append(finding.finding_id)
        st.rerun()


def _badges(finding: Finding) -> None:
    st.badge(
        finding.impact_label,
        color=IMPACT_COLORS.get(finding.impact_label, "gray"),
    )
    st.badge("Validated", color="green", icon=":material/check:")


def _toggle(key: str) -> None:
    st.session_state[key] = not st.session_state.get(key, False)


def _lawyer_note() -> None:
    with st.container(border=True):
        st.markdown("**Where a lawyer belongs**")
        st.write(
            "ClauseLens does not replace legal advice. Ask a qualified lawyer to review high-value exposure, "
            "ambiguous clauses, jurisdiction-specific enforceability, conflicting clauses, unusual termination "
            "provisions, clauses that touch statutory rights, clauses whose cost cannot be calculated, and "
            "disputes about what a sentence means. Use Mark for legal review to keep those items in view."
        )


def _library_maintenance() -> None:
    with st.expander("How the standard library stays current"):
        st.write(
            "Standards live in data/standard_clauses.json and are maintained separately from the model. "
            "A person reviews every change. The model is not allowed to publish a new library version. "
            "Each run records the library version. A proposed change should be drafted, reviewed by a person, "
            "saved as a new version, checked against the evaluation suite, and only then marked active."
        )


def _pct(value: float) -> str:
    return f"{value:.0%}"
