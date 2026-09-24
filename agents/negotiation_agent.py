from __future__ import annotations

import json
import re

from models.llm_schemas import LLMNegotiationBatch
from models.schemas import Agreement, ClauseComparison, MissingClause, NegotiationDraft
from utils.security import text_is_safe
from agents.common import started, system_prompt, trace_dict, try_parse, untrusted_user

AGENT = "Negotiation Agent"


def run_negotiation(state: dict, llm, tracker) -> dict:
    mark = started()
    comparisons = [ClauseComparison.model_validate(item) for item in state.get("comparisons", [])]
    missing = [MissingClause.model_validate(item) for item in state.get("missing_clauses", [])]
    warnings: list[str] = []
    owner = _owner_name(state)
    drafts = [_template_for_comparison(item, owner) for item in comparisons]
    drafts.extend(_template_for_missing(item, owner) for item in missing)
    by_key = {item.finding_key: item for item in drafts}
    if not drafts:
        return {"negotiations": [], "trace": [trace_dict(AGENT, mark, tracker, "success", "0 negotiation drafts.")]}

    brief = [
        {
            "finding_key": item.finding_key,
            "ask": item.ask,
            "why_it_matters": item.why_it_matters,
            "library_revision": item.replacement_wording,
        }
        for item in drafts
    ]
    user = untrusted_user(
        "Write a calm revision request for each finding in the untrusted data. Use the finding_key values exactly.",
        json.dumps(brief, ensure_ascii=False),
    )
    parsed, error = try_parse(llm, tracker, AGENT, system_prompt("negotiation.txt"), user, LLMNegotiationBatch)
    if error:
        warnings.append(error + " Negotiation messages use the comparison library's suggested wording.")
    elif isinstance(parsed, LLMNegotiationBatch):
        for proposal in parsed.drafts:
            current = by_key.get(proposal.finding_key)
            if current is None:
                continue
            fields = [
                proposal.ask,
                proposal.why_it_matters,
                proposal.replacement_wording,
                proposal.ready_to_send_message,
            ]
            if all(text_is_safe(field) and field.strip() for field in fields) and _relevant(proposal, current):
                by_key[proposal.finding_key] = NegotiationDraft(
                    finding_key=proposal.finding_key,
                    ask=proposal.ask.strip(),
                    why_it_matters=current.why_it_matters,
                    replacement_wording=proposal.replacement_wording.strip(),
                    ready_to_send_message=_with_greeting(proposal.ready_to_send_message.strip(), owner),
                    source="model",
                )
            else:
                warnings.append(
                    f"A negotiation draft for {proposal.finding_key} was discarded because it was not neutral or not specific."
                )

    status = "success" if not error else "fallback"
    return {
        "negotiations": [item.model_dump() for item in by_key.values()],
        "warnings": warnings,
        "trace": [trace_dict(AGENT, mark, tracker, status, f"{len(by_key)} negotiation drafts.")],
    }


def _template_for_comparison(item: ClauseComparison, owner: str) -> NegotiationDraft:
    return _template(
        item.comparison_id,
        item.standard_title or item.clause_title,
        item.negotiation_goal,
        item.why_it_matters,
        item.suggested_revision,
        owner,
    )


def _template_for_missing(item: MissingClause, owner: str) -> NegotiationDraft:
    return _template(
        item.standard_id,
        item.title,
        item.negotiation_goal,
        item.why_it_matters,
        item.suggested_wording,
        owner,
    )


def _relevant(proposal, current: NegotiationDraft) -> bool:
    blob = f"{proposal.replacement_wording} {proposal.ready_to_send_message}".lower()
    anchors = set(re.findall(r"[a-z]{5,}", f"{current.ask} {current.replacement_wording}".lower()))
    hits = sum(1 for token in anchors if token in blob)
    return hits >= 2


def _owner_name(state: dict) -> str:
    try:
        document = Agreement.model_validate(state.get("document") or {})
        text = document.full_text or ""
    except Exception:
        text = ""
    match = re.search(
        r"([A-Z][A-Za-z.]+(?:\s+[A-Z][A-Za-z.]+)?)\s+\((?:[Tt]he\s+)?[Oo]wner\)",
        text,
    )
    if match:
        return match.group(1).strip()
    labeled = re.search(r"\bOwner:\s*([A-Z][A-Za-z.]+(?:\s+[A-Z][A-Za-z.]+)?)", text)
    if labeled:
        return labeled.group(1).strip()
    return ""


def _with_greeting(message: str, owner: str = "") -> str:
    greeting = f"Hi {owner}," if owner else "Hi,"
    stripped = (message or "").strip()
    if not stripped:
        return greeting
    if owner and stripped.lower().startswith(f"hi {owner.lower()},"):
        return stripped
    if stripped.lower().startswith("hi"):
        rest = stripped.split(",", 1)[1].strip() if "," in stripped[:40] else stripped[2:].lstrip(" ,")
        return f"{greeting} {rest}".strip()
    return f"{greeting} {stripped}"


def _template(key: str, title: str, goal: str, why: str, revision: str, owner: str = "") -> NegotiationDraft:
    greeting = f"Hi {owner}," if owner else "Hi,"
    message = f'{greeting} could we revise the {title} wording so that it reads as follows: "{revision}"'
    return NegotiationDraft(
        finding_key=key,
        ask=goal or f"Revise the {title} wording.",
        why_it_matters=why,
        replacement_wording=revision,
        ready_to_send_message=message,
        source="library_template",
    )
