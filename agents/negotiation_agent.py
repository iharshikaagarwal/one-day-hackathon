from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

from models.llm_schemas import LLMNegotiationBatch
from models.schemas import Agreement, ClauseComparison, MissingClause, NegotiationDraft
from utils.security import text_is_safe
from agents.common import started, system_prompt, trace_dict, try_parse, untrusted_user

AGENT = "Negotiation Agent"
_BATCH = 4


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
    chunks = [brief[index : index + _BATCH] for index in range(0, len(brief), _BATCH)]
    system = system_prompt("negotiation.txt")

    def _request(chunk: list[dict]):
        user = untrusted_user(
            "Write a calm revision request for each finding in the untrusted data. Use the finding_key values exactly.",
            json.dumps(chunk, ensure_ascii=False),
        )
        return try_parse(llm, tracker, AGENT, system, user, LLMNegotiationBatch)

    results: list[tuple] = []
    if len(chunks) == 1:
        results.append(_request(chunks[0]))
    else:
        with ThreadPoolExecutor(max_workers=min(3, len(chunks))) as pool:
            futures = [pool.submit(_request, chunk) for chunk in chunks]
            for future in as_completed(futures):
                results.append(future.result())

    errors = [error for parsed, error in results if error]
    if errors and all(error for _parsed, error in results):
        warnings.append(errors[0] + " Negotiation messages use the comparison library's suggested wording.")
    for parsed, error in results:
        if error or not isinstance(parsed, LLMNegotiationBatch):
            continue
        for proposal in parsed.drafts:
            current = by_key.get(proposal.finding_key)
            if current is None:
                continue
            reason = _discard_reason(proposal, current)
            if reason is None:
                by_key[proposal.finding_key] = NegotiationDraft(
                    finding_key=proposal.finding_key,
                    ask=proposal.ask.strip(),
                    why_it_matters=current.why_it_matters,
                    replacement_wording=proposal.replacement_wording.strip(),
                    ready_to_send_message=_with_greeting(proposal.ready_to_send_message.strip(), owner),
                    source="model",
                )
            else:
                warnings.append(f"A negotiation draft for {proposal.finding_key} was discarded because {reason}.")

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


def _discard_reason(proposal, current: NegotiationDraft) -> str | None:
    fields = [
        proposal.ask,
        proposal.why_it_matters,
        proposal.replacement_wording,
        proposal.ready_to_send_message,
    ]
    if not all(field.strip() for field in fields):
        return "it was incomplete"
    if not all(text_is_safe(field) for field in fields):
        return "it was not neutral"
    if not _relevant(proposal, current):
        return "it was not specific to this clause"
    return None


_REJECTED_NAME_PARTS = {
    "no",
    "item",
    "quantity",
    "owner",
    "schedule",
    "the",
}


def _owner_name(state: dict) -> str:
    try:
        document = Agreement.model_validate(state.get("document") or {})
        text = document.full_text or ""
    except Exception:
        text = ""
    for match in re.finditer(
        r"\b((?:Mr|Mrs|Ms|Dr)\.?\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3})\b",
        text,
    ):
        window = text[match.end() : match.end() + 800]
        if re.search(r"called\s+the\s+[\"“']?Owner\b", window, re.I):
            name = _clean_name(match.group(1))
            if name:
                return name
    parenthetical = re.search(
        r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})\s+\((?:[Tt]he\s+)?[Oo]wner\)",
        text,
    )
    if parenthetical:
        name = _clean_name(parenthetical.group(1))
        if name:
            return name
    return ""


def _clean_name(raw: str) -> str:
    name = " ".join(raw.replace("\n", " ").split()).strip(" .,")
    parts = [part.strip(".") for part in name.split() if part.strip(".")]
    if not parts or len(name) > 60:
        return ""
    if any(part.lower() in _REJECTED_NAME_PARTS for part in parts):
        return ""
    return " ".join(parts)


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
    message = f'{greeting} could we change the {title} clause to: "{revision}"'
    return NegotiationDraft(
        finding_key=key,
        ask=goal or f"Revise the {title} wording.",
        why_it_matters=why,
        replacement_wording=revision,
        ready_to_send_message=message,
        source="library_template",
    )
