from __future__ import annotations

import html
import io
from pathlib import Path

import pymupdf

from graph.workflow import canonical_trace
from models.schemas import AnalysisRun, Finding
from standards.library import load_library_for
from ui.dashboard import EXPOSURE_LABELS
from utils.format import format_inr

PRIMARY = "#0b57d0"
TEXT = "#1f1f1f"
MUTED = "#5f6368"
CARD = "#f0f4f9"
BORDER = "#dde3ea"
WHITE = "#ffffff"
RED = "#c5221f"
ORANGE = "#e37400"
VIOLET = "#8e44ad"
GREEN = "#188038"
GRAY = "#5f6368"

BADGE_COLORS = {
    "HIGH IMPACT": (RED, "#fdecea"),
    "MEDIUM IMPACT": (ORANGE, "#fff4e5"),
    "LOW IMPACT": (GRAY, CARD),
    "MISSING": (VIOLET, "#f3e8f8"),
    "REVIEW REQUIRED": (ORANGE, "#fff4e5"),
}

CSS = f"""
body {{
    font-family: sans-serif;
    color: {TEXT};
    font-size: 10.5pt;
    line-height: 1.45;
}}
h1 {{
    color: {PRIMARY};
    font-size: 20pt;
    margin: 0 0 6pt 0;
}}
h2 {{
    color: {PRIMARY};
    font-size: 14pt;
    border-bottom: 2px solid {PRIMARY};
    padding-bottom: 4pt;
    margin: 18pt 0 10pt 0;
}}
h3 {{
    font-size: 12pt;
    margin: 14pt 0 6pt 0;
}}
h4 {{
    font-size: 11pt;
    margin: 8pt 0 4pt 0;
}}
.caption {{
    color: {MUTED};
    font-size: 9pt;
}}
.toc a {{
    color: {PRIMARY};
    text-decoration: none;
}}
.metrics td {{
    width: 25%;
    background: {WHITE};
    border: 1px solid {BORDER};
    padding: 8pt 10pt;
    vertical-align: top;
}}
.mlabel {{
    color: {MUTED};
    font-size: 8pt;
}}
.mvalue {{
    color: {TEXT};
    font-size: 16pt;
    font-weight: bold;
}}
.card {{
    background: {WHITE};
    border: 1px solid {BORDER};
    padding: 10pt 12pt;
    margin: 8pt 0;
}}
.badge {{
    font-size: 8pt;
    font-weight: bold;
    padding: 2pt 6pt;
}}
.note {{
    background: {CARD};
    border: 1px solid {BORDER};
    padding: 10pt 12pt;
    margin: 10pt 0;
}}
.warn {{
    background: #fff4e5;
    border: 1px solid {ORANGE};
    padding: 8pt 10pt;
    margin: 8pt 0;
}}
.info {{
    background: {CARD};
    border: 1px solid {PRIMARY};
    padding: 8pt 10pt;
    margin: 8pt 0;
}}
.code {{
    background: {CARD};
    border: 1px solid {BORDER};
    padding: 8pt 10pt;
    font-family: monospace;
    font-size: 9.5pt;
}}
.split td {{
    width: 50%;
    vertical-align: top;
    padding: 0 8pt 0 0;
}}
.data {{
    width: 100%;
    border-collapse: collapse;
    font-size: 9pt;
}}
.data th {{
    background: {CARD};
    color: {TEXT};
    border: 1px solid {BORDER};
    padding: 5pt 6pt;
    text-align: left;
}}
.data td {{
    border: 1px solid {BORDER};
    padding: 5pt 6pt;
}}
.bar-fill {{
    background: {PRIMARY};
    color: {WHITE};
    font-size: 8pt;
}}
"""


def report_filename(result: AnalysisRun) -> str:
    stem = Path(result.filename).stem
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in stem).strip("-")
    return f"ClauseLens-{safe or 'agreement'}-{result.run_id}.pdf"


def build_report_pdf(result: AnalysisRun) -> bytes:
    story = pymupdf.Story(_report_html(result), user_css=CSS)
    box = pymupdf.paper_rect("a4")
    where = box + (36, 46, -36, -38)

    def rectfn(_rect_num: int, _filled):
        return box, where, pymupdf.Identity

    stream = io.BytesIO()
    writer = pymupdf.DocumentWriter(stream)
    story.write(writer, rectfn)
    writer.close()
    document = pymupdf.open(stream=stream.getvalue(), filetype="pdf")
    _decorate_pages(document, result)
    return document.tobytes()


def _report_html(result: AnalysisRun) -> str:
    detected = result.agreement_type
    parts = [
        f"<h1>ClauseLens report</h1>",
        f"<p><b>{_t(result.filename)}</b> · {result.page_count} pages · Run {_t(result.run_id)}</p>",
        f"<p><b>Agreement Type:</b> {_t(detected.label)} &nbsp;·&nbsp; <b>Confidence:</b> {detected.confidence:.0%}</p>",
    ]
    if detected.reasoning:
        parts.append(f"<p class='caption'>{_t(detected.reasoning)}</p>")
    if result.library_available:
        parts.append(
            f"<p class='caption'>{_t(result.library_name)} {_t(result.library_version)}, "
            f"reviewed {_t(_review_date(result))}. This is a comparison baseline, not a legal "
            f"requirement. ClauseLens does not make a signing decision.</p>"
        )
    else:
        parts.append(
            "<div class='info'>Agreement type detected, but a standard comparison library is "
            "not currently available for this type. ClauseLens does not make a signing decision.</div>"
        )
    if result.warnings:
        parts.append(f"<p class='caption'>{len(result.warnings)} analysis notes are in Evaluation / Trace.</p>")

    parts.append(
        "<p class='caption'>Overview · Unusual Clauses · Missing Clauses · "
        "Financial Exposure · Negotiation Drafts · Evidence · Evaluation / Trace</p>"
    )
    parts += [_overview_html(result), _unusual_html(result), _missing_html(result)]
    parts += [_financial_html(result), _negotiation_html(result), _evidence_html(result)]
    parts += [_evaluation_html(result), _lawyer_html()]
    return "<body>" + "".join(parts) + "</body>"


def _overview_html(result: AnalysisRun) -> str:
    exposure = format_inr(result.largest_exposure) if result.largest_exposure is not None else "Unknown"
    blocks = [
        "<h2 id='overview'>Overview</h2>",
        "<table width='100%'>",
        "<tr>",
        _metric("Unusual clauses", str(result.unusual_count)),
        _metric("Missing clauses", str(result.missing_count)),
        "</tr><tr>",
        _metric("Potential financial exposure", exposure),
        _metric("Clauses requiring review", str(result.review_count)),
        "</tr></table>",
        "<p class='caption'>Largest defensible single-clause exposure. Amounts are not added together, "
        "because different clauses may overlap. This is not a prediction of loss.</p>",
        "<h3>Top financial exposures</h3>",
        "<p class='caption'>Ranked by potential financial exposure. Ranking is based on defensible "
        "financial exposure derived from the agreement. Clauses without a monetary basis are not "
        "assigned invented values.</p>",
    ]
    ranked = [item for item in result.findings if item.kind == "unusual" and item.rank is not None]
    if not ranked:
        blocks.append("<p class='caption'>No clause had a defensible monetary exposure.</p>")
    for finding in sorted(ranked, key=lambda item: item.rank or 0):
        blocks.append(_exposure_card_html(finding))

    unknown = [
        item
        for item in result.findings
        if item.kind == "unusual" and (item.exposure is None or item.exposure.amount is None)
    ]
    if unknown:
        blocks.append("<h3>Clauses without a defensible amount</h3>")
        for finding in unknown:
            blocks.append(
                f"<p class='caption'>Clause {_t(finding.clause_number)} — {_t(finding.title)}. "
                "No amount was invented.</p>"
            )
    return "".join(blocks)


def _unusual_html(result: AnalysisRun) -> str:
    parts = [
        "<h2 id='unusual-clauses'>Unusual Clauses</h2>",
        "<p class='caption'>Each flag quotes the agreement, names a standard-library entry, and explains the difference.</p>",
    ]
    findings = [item for item in result.findings if item.kind == "unusual"]
    if not findings:
        parts.append("<p class='caption'>No unusual clause passed evidence validation.</p>")
        return "".join(parts)
    for finding in findings:
        label = f"#{finding.rank} {finding.title}" if finding.rank else finding.title
        parts.append(_finding_card_html(finding, label))
    return "".join(parts)


def _missing_html(result: AnalysisRun) -> str:
    parts = ["<h2 id='missing-clauses'>Missing Clauses</h2>", "<h3>What's missing?</h3>"]
    findings = [item for item in result.findings if item.kind == "missing"]
    if not findings:
        parts.append(
            "<p class='caption'>Every comparison topic marked as a required protection was found in the agreement.</p>"
        )
        return "".join(parts)
    for finding in findings:
        draft = ""
        if finding.negotiation:
            draft = (
                "<p><b>Suggested wording</b></p>"
                f"<p>{_block(finding.negotiation.replacement_wording)}</p>"
            )
        parts.append(
            "<div class='card'>"
            + _badge("MISSING")
            + f"<h4>{_t(finding.title)}</h4>"
            + "<p><b>Why it matters</b></p>"
            + f"<p>{_block(finding.reason)}</p>"
            + "<p><b>Standard expectation</b></p>"
            + f"<p>{_block(finding.standard_expectation)}</p>"
            + "<p><b>Evidence that it is absent</b></p>"
            + f"<p>{_block(finding.difference)}</p>"
            + draft
            + _review_html(finding)
            + "</div>"
        )
    return "".join(parts)


def _financial_html(result: AnalysisRun) -> str:
    parts = [
        "<h2 id='financial-exposure'>Financial Exposure</h2>",
        "<h3>Ranked by potential financial exposure</h3>",
        "<p class='caption'>Ranking is based on defensible financial exposure derived from the agreement. "
        "Clauses without a monetary basis are not assigned invented values. "
        "Score weights: financial exposure 50%, recurrence 20%, trigger likelihood 15%, ambiguity 15%.</p>",
    ]
    ranked = [item for item in result.findings if item.kind == "unusual" and item.exposure and item.exposure.amount]
    if not ranked:
        parts.append("<p class='caption'>No quantitative ranking was available.</p>")
        return "".join(parts)

    peak = max(item.exposure.amount for item in ranked)
    parts.append("<table width='100%'>")
    for item in ranked:
        pct = max(8, int(round(100 * item.exposure.amount / peak))) if peak else 8
        rest = 100 - pct
        parts.append(
            "<tr>"
            f"<td width='28%'>{_t(item.clause_number)} {_t(item.title)}</td>"
            "<td width='52%'>"
            f"<table width='100%'><tr><td class='bar-fill' width='{pct}%'>&nbsp;</td>"
            f"<td width='{rest}%'></td></tr></table>"
            "</td>"
            f"<td width='20%'>{_t(format_inr(item.exposure.amount))}</td>"
            "</tr>"
        )
    parts.append("</table>")
    parts.append(
        "<table class='data'><tr>"
        "<th>Rank</th><th>Clause</th><th>Title</th><th>Exposure</th>"
        "<th>Type</th><th>Confidence</th><th>Page</th></tr>"
    )
    for item in ranked:
        kind = EXPOSURE_LABELS.get(item.exposure.exposure_type, item.exposure.exposure_type)
        parts.append(
            "<tr>"
            f"<td>{item.rank}</td><td>{_t(item.clause_number)}</td><td>{_t(item.title)}</td>"
            f"<td>{_t(format_inr(item.exposure.amount))}</td><td>{_t(kind)}</td>"
            f"<td>{_t(item.exposure.confidence)}</td><td>{item.page}</td>"
            "</tr>"
        )
    parts.append("</table>")
    for item in ranked:
        if item.ranking:
            parts.append(
                f"<h4>Why clause {_t(item.clause_number)} is ranked #{item.rank}</h4>"
                f"<p>{_block(item.ranking.ranking_reason)}</p>"
                f"<p>{_block(item.exposure.calculation)}</p>"
            )
    return "".join(parts)


def _negotiation_html(result: AnalysisRun) -> str:
    parts = [
        "<h2 id='negotiation-drafts'>Negotiation Drafts</h2>",
        "<p class='caption'>Messages are concise and non-confrontational. Edit names or dates if you need to.</p>",
    ]
    drafts = [item for item in result.findings if item.negotiation]
    if not drafts:
        parts.append("<p class='caption'>No negotiation draft passed validation.</p>")
        return "".join(parts)
    for finding in drafts:
        draft = finding.negotiation
        title = finding.clause_number or finding.standard_id
        parts.append(
            "<div class='card'>"
            f"<h4>{_t(title)} — {_t(finding.title)}</h4>"
            "<p><b>Problem</b></p>"
            f"<p>{_block(finding.reason)}</p>"
            "<p><b>Suggested replacement clause</b></p>"
            f"<p>{_block(draft.replacement_wording)}</p>"
            "<p><b>Ready-to-send message</b></p>"
            f"<div class='code'>{_block(draft.ready_to_send_message)}</div>"
            "</div>"
        )
    return "".join(parts)


def _evidence_html(result: AnalysisRun) -> str:
    parts = ["<h2 id='evidence'>Evidence</h2>"]
    if not result.findings:
        parts.append("<p class='caption'>No validated findings.</p>")
        return "".join(parts)
    for finding in result.findings:
        parts.append(_evidence_block_html(finding, heading=True))
    return "".join(parts)


def _evaluation_html(result: AnalysisRun) -> str:
    validation = result.validation
    injection = {
        "passed": "Passed",
        "flagged": "Flagged",
        "not_detected": "No hostile instruction detected",
    }.get(validation.prompt_injection, validation.prompt_injection)
    parts = [
        "<h2 id='evaluation-trace'>Evaluation / Trace</h2>",
        "<h3>Validation</h3>",
        f"<p>Evidence-backed findings: {validation.evidence_backed}/{validation.evidence_considered}</p>",
        f"<p>Unsupported findings rejected: {validation.rejected}</p>",
        f"<p>Financial calculations validated: {validation.calculations_validated}/{validation.calculations_considered}</p>",
        f"<p>Missing-clause checks: {validation.missing_checks}</p>",
        f"<p>Prompt-injection checks: {_t(injection)}</p>",
    ]
    if result.warnings:
        parts.append("<h3>Analysis notes</h3>")
        for warning in result.warnings:
            parts.append(f"<p class='caption'>{_t(warning)}</p>")
    if validation.injection_note:
        parts.append(f"<p class='caption'>{_t(validation.injection_note)}</p>")
    if result.injection_excerpts:
        parts.append("<p class='caption'>Detected in the document and not followed:</p>")
        for excerpt in result.injection_excerpts:
            parts.append(f"<div class='code'>{_block(excerpt)}</div>")
    if validation.rejected_reasons:
        parts.append("<h4>Rejected finding notes</h4>")
        for reason in validation.rejected_reasons:
            parts.append(f"<p>{_t(reason)}</p>")

    parts.append("<h3>Evaluation dataset</h3>")
    if result.evaluation is None:
        parts.append(
            "<p class='caption'>Answer-key scores are computed in the test suite only. "
            "They are not produced when a PDF is analyzed in the app.</p>"
        )
    else:
        stats = result.evaluation
        parts += [
            f"<p class='caption'>{_t(stats.dataset_label)}</p>",
            f"<p>Clause detection recall: {_pct(stats.clause_detection_recall)}</p>",
            f"<p>Clause detection precision: {_pct(stats.clause_detection_precision)}</p>",
            f"<p>Missing-clause detection: {_pct(stats.missing_detection_recall)}</p>",
            f"<p>Missing-clause precision: {_pct(stats.missing_detection_precision)}</p>",
            f"<p>False positive rate on normal clauses: {_pct(stats.normal_clause_false_positive_rate)}</p>",
            f"<p>Ranking agreement: {'n/a' if stats.ranking_agreement is None else _pct(stats.ranking_agreement)} on this evaluation case.</p>",
            f"<p>Evidence validation rate: {_pct(stats.evidence_validation_rate)}</p>",
            f"<p><b>Expected ranking</b><br/>{_t(' > '.join(stats.expected_ranking) or 'None')}</p>",
            f"<p><b>AI ranking</b><br/>{_t(' > '.join(stats.actual_ranking) or 'None')}</p>",
        ]
        if stats.missed_unusual or stats.unexpected_unusual or stats.false_positive_normal_clauses or stats.missed_missing:
            parts.append("<p><b>Differences from the expected case</b></p>")
            if stats.missed_unusual:
                parts.append(f"<p>Unusual clauses not found: {_t(', '.join(stats.missed_unusual))}</p>")
            if stats.unexpected_unusual:
                parts.append(f"<p>Additional unusual clauses: {_t(', '.join(stats.unexpected_unusual))}</p>")
            if stats.false_positive_normal_clauses:
                parts.append(f"<p>Normal clauses flagged: {_t(', '.join(stats.false_positive_normal_clauses))}</p>")
            if stats.missed_missing:
                parts.append(f"<p>Missing topics not found: {_t(', '.join(stats.missed_missing))}</p>")

    parts.append("<h3>Analysis trace</h3>")
    parts.append(f"<p>Run ID: {_t(result.run_id)}</p>")
    for entry in canonical_trace(result.trace):
        mark = "Completed" if entry.status in {"success", "fallback"} else entry.status
        parts.append(
            f"<p>{_t(mark)} — {_t(entry.agent)} — {entry.duration_ms} ms — "
            f"input tokens {entry.input_tokens} — output tokens {entry.output_tokens}</p>"
        )
        if entry.detail:
            parts.append(f"<p class='caption'>{_t(entry.detail)}</p>")
        if entry.status == "fallback":
            parts.append("<p class='caption'>This step used the library fallback after the model request failed.</p>")
    cost = result.cost
    parts += [
        f"<p>Total input tokens: {cost.input_tokens}</p>",
        f"<p>Total output tokens: {cost.output_tokens}</p>",
        f"<p>Estimated API cost: ${cost.estimated_cost_usd:.6f}</p>",
        f"<p class='caption'>{_t(cost.pricing_note)}</p>",
        f"<p>Model: {_t(cost.model)}</p>",
        f"<p>Total traced step time: {sum(entry.duration_ms for entry in result.trace)} ms</p>",
        "<h3>How the standard library stays current</h3>",
        "<p>Standards live in data/standard_clauses.json and are maintained separately from the model. "
        "A person reviews every change. The model is not allowed to publish a new library version. "
        "Each run records the library version. A proposed change should be drafted, reviewed by a person, "
        "saved as a new version, checked against the evaluation suite, and only then marked active.</p>",
    ]
    return "".join(parts)


def _lawyer_html() -> str:
    return (
        "<p class='caption'>ClauseLens informs. You decide.</p>"
    )


def _finding_card_html(finding: Finding, heading: str) -> str:
    left = (
        "<p><b>Agreement clause</b></p>"
        f"<p>{_block(finding.agreement_text or 'This topic is not in the agreement.')}</p>"
        f"<p class='caption'>Page {finding.page if finding.page else 'not present'} · "
        f"Clause {finding.clause_number or 'not present'}</p>"
    )
    right = (
        "<p><b>Standard comparison</b></p>"
        f"<p>{_block(finding.standard_expectation)}</p>"
        f"<p class='caption'>{_t(finding.standard_id)} · {_t(finding.standard_title)} · "
        f"v{_t(finding.standard_version)}</p>"
    )
    money = ""
    if finding.exposure:
        kind = EXPOSURE_LABELS.get(finding.exposure.exposure_type, finding.exposure.exposure_type)
        amount = format_inr(finding.exposure.amount) if finding.exposure.amount is not None else "Unknown"
        money = (
            "<p><b>Financial exposure</b></p>"
            f"<p>{_t(amount)} · {_t(kind)} · Confidence {_t(finding.exposure.confidence)}</p>"
            f"<p>{_block(finding.exposure.calculation)}</p>"
            f"<p class='caption'>{_block(finding.exposure.statement)}</p>"
        )
    notes = ""
    if finding.pattern_notes:
        notes = (
            "<p class='caption'>Documented comparison pattern, not a legal rule: "
            f"{_t(' '.join(finding.pattern_notes))}</p>"
        )
    negotiation = ""
    if finding.negotiation:
        negotiation = (
            "<p><b>Negotiation</b></p>"
            f"<p>{_block(finding.negotiation.ask)}</p>"
            "<p><b>Suggested change</b></p>"
            f"<p>{_block(finding.negotiation.replacement_wording)}</p>"
            f"<div class='code'>{_block(finding.negotiation.ready_to_send_message)}</div>"
        )
    return (
        "<div class='card'>"
        + _badges_html(finding)
        + f"<h4>{_t(heading)}</h4>"
        + left
        + right
        + "<p><b>Why flagged</b></p>"
        + f"<p>{_block(finding.reason)}</p>"
        + "<p><b>Difference</b></p>"
        + f"<p>{_block(finding.difference)}</p>"
        + money
        + notes
        + negotiation
        + _evidence_block_html(finding, heading=False)
        + _review_html(finding)
        + "</div>"
    )


def _exposure_card_html(finding: Finding) -> str:
    exposure = finding.exposure
    amount = format_inr(exposure.amount) if exposure and exposure.amount is not None else "Unknown"
    kind = EXPOSURE_LABELS.get(exposure.exposure_type, exposure.exposure_type) if exposure else "Unknown"
    extras = _badge(finding.impact_label)
    if finding.rank == 1:
        extras += _badge("Highest measurable exposure", PRIMARY, "#e8f0fe")
    extras += _badge("Validated", GREEN, "#e6f4ea")
    body = (
        f"<h4>#{finding.rank} {_t(finding.title)}</h4>"
        f"<p>{_t(amount)} · {_t(kind)}</p>"
        f"<p class='caption'>Page {finding.page} · Clause {_t(finding.clause_number)}</p>"
    )
    if exposure:
        body += f"<p>{_block(exposure.statement)}</p>"
    return "<div class='card'>" + extras + body + _review_html(finding) + "</div>"


def _evidence_block_html(finding: Finding, *, heading: bool) -> str:
    evidence = finding.evidence
    label = finding.clause_number or finding.standard_id
    if evidence.page and evidence.clause_number:
        location = f"Page {evidence.page} — Clause {evidence.clause_number}"
    elif evidence.page:
        location = f"Page {evidence.page}"
    else:
        location = "No page, because this topic was not found in the extracted text."
    quote = f"<p>{_block(evidence.agreement_text)}</p>" if evidence.agreement_text else ""
    title = f"<h4>{_t(label)} — {_t(finding.title)}</h4>" if heading else ""
    return (
        f"<div class='card'>{title}"
        f"<p><b>Source</b></p><p class='caption'>{_t(location)}</p>{quote}"
        f"<p><b>Standard</b></p>"
        f"<p class='caption'>{_t(evidence.standard_title)} · {_t(evidence.standard_id)} · "
        f"library {_t(evidence.library_version)}</p>"
        f"<p>{_block(evidence.standard_text)}</p>"
        f"<p><b>Difference</b></p><p>{_block(evidence.difference)}</p>"
        "</div>"
    )


def _review_html(finding: Finding) -> str:
    if not finding.legal_review:
        return ""
    return (
        _badge("Review required", ORANGE, "#fff4e5")
        + f"<p class='caption'>{_t('; '.join(finding.legal_review_reasons))}</p>"
    )


def _badges_html(finding: Finding) -> str:
    return _badge(finding.impact_label) + _badge("Validated", GREEN, "#e6f4ea")


def _badge(label: str, color: str | None = None, background: str | None = None) -> str:
    if color is None or background is None:
        color, background = BADGE_COLORS.get(label, (GRAY, CARD))
    return f"<span class='badge' style='color:{color};background:{background}'>{_t(label)}</span> "


def _metric(label: str, value: str) -> str:
    return (
        "<td width='50%' style='border:1px solid #dde3ea;padding:10pt 12pt'>"
        "<div class='mlabel'>"
        + _t(label)
        + "</div><div class='mvalue'>"
        + _t(value)
        + "</div></td>"
    )


def _decorate_pages(document, result: AnalysisRun) -> None:
    filename = result.filename.encode("ascii", "replace").decode("ascii")
    blue = (11 / 255, 87 / 255, 208 / 255)
    footer = (240 / 255, 244 / 255, 249 / 255)
    white = (1, 1, 1)
    muted = (95 / 255, 99 / 255, 104 / 255)
    total = document.page_count
    for index, page in enumerate(document, start=1):
        width, height = page.rect.width, page.rect.height
        page.draw_rect(pymupdf.Rect(0, 0, width, 32), color=None, fill=blue)
        page.insert_text((36, 21), "ClauseLens", fontsize=11, color=white, fontname="helv")
        page.insert_text((110, 21), filename[:48], fontsize=8, color=white, fontname="helv")
        page.draw_rect(pymupdf.Rect(0, height - 26, width, height), color=None, fill=footer)
        page.insert_text(
            (36, height - 10),
            "Comparison baseline, not legal advice. ClauseLens does not make a signing decision.",
            fontsize=7,
            color=muted,
            fontname="helv",
        )
        page.insert_text((width - 56, height - 10), f"{index} / {total}", fontsize=8, color=muted, fontname="helv")


def _review_date(result: AnalysisRun) -> str:
    library = load_library_for(result.agreement_type.agreement_type)
    if library and library.version == result.library_version:
        return library.review_date
    return result.library_version


def _t(value: object) -> str:
    return html.escape(" ".join(str(value or "").split()), quote=True)


def _block(value: str | None) -> str:
    return html.escape(value or "", quote=False).replace("\n", "<br/>")


def _pct(value: float) -> str:
    return f"{value:.0%}"
