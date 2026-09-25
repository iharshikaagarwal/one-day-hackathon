from __future__ import annotations

import json
import re
from collections.abc import Iterator
from functools import lru_cache

from agents.common import system_prompt, untrusted_user
from models.schemas import AnalysisRun
from standards.library import available_types, load_library_for
from utils.cost_tracker import CostTracker
from utils.errors import UserFacingError
from utils.format import format_inr
from utils.security import text_is_safe

AGENT = "Chat Assistant"
MAX_HISTORY = 10
MAX_HISTORY_CHARS = 800
MAX_QUOTE = 600

SAFE_FALLBACK = (
    "I can't answer that in a way that stays grounded in the validated findings. "
    "ClauseLens does not make a signing decision or legal conclusions. "
    "Open the report above to see each clause, its page, and the comparison standard."
)

SAFE_FALLBACK_GENERAL = (
    "I can't help with that one. ClauseLens does not make a signing decision or legal conclusions. "
    "Attach an agreement PDF with the + button and I'll show you how its clauses compare with the standard."
)

EMPTY_REPLY = "Sorry, I couldn't reply just now. Please try again."

SIGNING_NOTE = (
    "Note: ClauseLens does not make a signing decision. The report above has the clauses, gaps, and costs."
)
SIGNING_NOTE_GENERAL = (
    "Note: ClauseLens does not make a signing decision. Attach an agreement to see the clauses, gaps, and costs."
)
_SIGNING_ASK = re.compile(
    r"\b(?:should i (?:singh|sign)|shall i sign|can i sign|do i sign|is it (?:safe|ok|okay) to sign)\b",
    re.I,
)


def is_signing_question(text: str) -> bool:
    return bool(_SIGNING_ASK.search(text or ""))


def general_messages(question: str, history: list[dict]) -> tuple[str, str]:
    user = (
        f"ClauseLens comparison standards by agreement type:\n{standards_overview()}\n\n"
        f"Conversation so far:\n{_history_text(history)}\n\n"
        f"User message: {question.strip()}"
    )
    return system_prompt("chat_general.txt"), user


@lru_cache(maxsize=1)
def standards_overview() -> str:
    sections = []
    for agreement_type in available_types():
        library = load_library_for(agreement_type)
        if library is None:
            continue
        lines = [f"{agreement_type.title()} (library {library.version}):"]
        lines += [f"- {entry.title}: {entry.standard_expectation}" for entry in library.entries]
        sections.append("\n".join(lines))
    return "\n\n".join(sections) or "(no libraries available)"


def findings_messages(question: str, result: AnalysisRun, history: list[dict]) -> tuple[str, str]:
    instructions = (
        f"Agreement type: {result.agreement_type.label}.\n"
        f"Comparison library: {result.library_name or 'none available'} {result.library_version}.\n"
        f"Recent conversation:\n{_history_text(history)}\n\n"
        f"User question: {question.strip()}\n\n"
        "Answer using only the validated findings below."
    )
    return system_prompt("chat_assistant.txt"), untrusted_user(instructions, _findings_context(result))


def stream_reply(llm, tracker: CostTracker, system: str, user: str, fallback: str) -> Iterator[str]:
    """Yield the reply text so far after each chunk. Unsafe text is replaced by the fallback."""
    text = ""
    try:
        for piece in llm.stream_text(agent=AGENT, system=system, user=user, tracker=tracker):
            text += piece
            if not text_is_safe(text):
                yield fallback
                return
            yield text
    except UserFacingError as exc:
        yield exc.message
        return
    if not text.strip():
        yield EMPTY_REPLY


def answer_general(question: str, history: list[dict], llm, tracker: CostTracker) -> str:
    if is_signing_question(question):
        return SIGNING_NOTE_GENERAL
    system, user = general_messages(question, history)
    return _last(stream_reply(llm, tracker, system, user, SAFE_FALLBACK_GENERAL))


def answer_question(question: str, result: AnalysisRun, history: list[dict], llm, tracker: CostTracker) -> str:
    if is_signing_question(question):
        return SIGNING_NOTE
    system, user = findings_messages(question, result, history)
    return _last(stream_reply(llm, tracker, system, user, SAFE_FALLBACK))


def _last(snapshots: Iterator[str]) -> str:
    reply = EMPTY_REPLY
    for reply in snapshots:
        pass
    return reply


def _history_text(history: list[dict]) -> str:
    lines = [
        f"{item['role']}: {item['content'][:MAX_HISTORY_CHARS]}"
        for item in history[-MAX_HISTORY:]
        if item.get("kind") == "text" and item.get("content")
    ]
    return "\n".join(lines) or "(none)"


def _findings_context(result: AnalysisRun) -> str:
    items = []
    for finding in result.findings:
        exposure = finding.exposure
        items.append(
            {
                "kind": finding.kind,
                "clause": finding.clause_number or None,
                "page": finding.page or None,
                "title": finding.title,
                "quote": (finding.agreement_text or "")[:MAX_QUOTE],
                "standard_id": finding.standard_id,
                "standard_expectation": finding.standard_expectation,
                "difference": finding.difference,
                "reason": finding.reason,
                "rank": finding.rank,
                "exposure": format_inr(exposure.amount) if exposure and exposure.amount is not None else "unknown",
                "calculation": exposure.calculation if exposure else "",
                "legal_review": finding.legal_review,
                "suggested_wording": finding.negotiation.replacement_wording if finding.negotiation else "",
                "message_draft": finding.negotiation.ready_to_send_message if finding.negotiation else "",
            }
        )
    if not items:
        return "No validated findings were produced for this agreement."
    return json.dumps(items, ensure_ascii=False, indent=1)
