from __future__ import annotations

from pathlib import Path

import streamlit as st

from models.schemas import AnalysisRun
from ui.dashboard import render_dashboard
from utils.format import format_inr

BRAND_MARK = "⌁"
BRAND_ICON = str(Path(__file__).resolve().parent / "assets" / "clauselens_mark.svg")
ASSISTANT_AVATAR = BRAND_ICON
USER_AVATAR = ":material/person:"

STEP_NOTES = {
    "Document parsed": "Extracted the text page by page and split it into numbered clauses.",
    "Agreement Type Detector": "Identified the agreement type and loaded the matching standard library.",
    "Agreement Analyst": "Read each clause and recorded the figures the agreement states.",
    "Standards Comparator": "Compared clauses with the standard library.",
    "Missing Clause Detector": "Checked for protections the agreement never mentions.",
    "Financial Exposure Analyzer": "Worked out each clause's financial rule. Python did the arithmetic.",
    "Financial Impact Ranker": "Ranked clauses by potential financial exposure.",
    "Negotiation Agent": "Drafted replacement wording and a ready-to-send message.",
    "Evidence Validator": "Checked every quote, page, standard, and calculation.",
}

START_CHIPS = {
    "rental": ":material/home: What should I check before signing a rental agreement?",
    "job": ":material/work: I got a job offer. Which clauses should I watch for?",
    "capabilities": ":material/help: What can you do?",
    "exposure": ":material/calculate: How do you calculate financial risk?",
}

FOLLOW_UP_CHIPS = {
    "Which clause carries the biggest financial risk, and why?": ":material/trending_up: Biggest financial risk",
    "Which protections are missing from this agreement?": ":material/search_off: What's missing?",
    "Summarize the negotiation messages I could send.": ":material/forum: Negotiation messages",
}


def greeting() -> None:
    st.space("large")
    st.markdown("# :blue[Hello.] Let's read the fine print.")
    st.markdown(
        "Attach a rental, employment, or service agreement and I'll find unusual clauses, "
        "missing protections, and potential financial exposure."
    )
    st.space("small")


def chips(options: dict[str, str], prefix: str, on_pick) -> None:
    with st.container(horizontal=True, gap="small"):
        for value, label in options.items():
            st.button(
                label,
                key=f"{prefix}-{value}",
                on_click=on_pick,
                args=(value,),
            )


def render_message(message: dict, results: dict, latest_run: str | None) -> None:
    role = message["role"]
    avatar = ASSISTANT_AVATAR if role == "assistant" else USER_AVATAR
    with st.chat_message(role, avatar=avatar):
        kind = message.get("kind", "text")
        if kind == "file":
            st.markdown(f":material/attach_file: **{message['content']}**")
            if message.get("text"):
                st.markdown(message["text"])
        elif kind == "error":
            st.error(message["content"])
        elif kind == "report":
            result = AnalysisRun.model_validate(results[message["run_id"]])
            st.markdown(summary(result))
            if message["run_id"] == latest_run:
                with st.expander("Full report", icon=":material/dashboard:", expanded=True):
                    render_dashboard(result)
            else:
                st.caption("A newer analysis replaced this report.")
        else:
            st.markdown(message["content"])


def summary(result: AnalysisRun) -> str:
    detected = result.agreement_type
    lines = [
        f"I analyzed **{result.filename}** ({result.page_count} pages). "
        f"It looks like a **{detected.label}** ({detected.confidence:.0%} confidence).",
        "",
    ]
    if not result.library_available:
        lines.append(
            "Agreement type detected, but a standard comparison library is not currently available for this type, "
            "so I extracted the clauses without comparison findings."
        )
        return "\n".join(lines)

    top = next(
        (item for item in result.findings if item.kind == "unusual" and item.rank == 1 and item.exposure),
        None,
    )
    lines.append(f"- **{result.unusual_count}** unusual clauses")
    lines.append(f"- **{result.missing_count}** missing protections")
    if top and top.exposure and top.exposure.amount is not None:
        lines.append(
            f"- Largest potential exposure: **{format_inr(top.exposure.amount)}** "
            f"in clause {top.clause_number} ({top.title}, page {top.page})"
        )
    lines.append(f"- **{result.review_count}** items worth showing a lawyer")
    lines.append("")
    lines.append("The full report is below. Ask me anything about it. I don't make a signing decision.")
    return "\n".join(lines)
