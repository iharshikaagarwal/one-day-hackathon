from __future__ import annotations

import time
from typing import Any

from pydantic import BaseModel

from models.schemas import PatternLibrary, StandardLibrary
from utils.cost_tracker import CostTracker
from utils.errors import UserFacingError
from utils.logging import get_logger
from utils.prompts import load_prompt
from utils.security import wrap_untrusted

logger = get_logger("clauselens.agents")


def state_library(state: dict) -> StandardLibrary | None:
    raw = state.get("library")
    return StandardLibrary.model_validate(raw) if raw else None


def state_patterns(state: dict) -> PatternLibrary | None:
    raw = state.get("patterns")
    return PatternLibrary.model_validate(raw) if raw else None


def skipped_trace(agent: str, mark: float, tracker: CostTracker, detail: str) -> dict:
    return trace_dict(agent, mark, tracker, "skipped", detail)


def system_prompt(filename: str) -> str:
    return load_prompt(filename)


def untrusted_user(instructions: str, document_text: str) -> str:
    return f"{instructions.strip()}\n\n{wrap_untrusted(document_text)}"


def try_parse(llm: Any, tracker: CostTracker, agent: str, system: str, user: str, response_model: type[BaseModel]):
    try:
        result = llm.parse(agent=agent, system=system, user=user, response_model=response_model)
    except UserFacingError as exc:
        if "API key" in exc.message or "OPENAI_API_KEY" in exc.message or "OPENAI_MODEL is missing" in exc.message:
            raise
        logger.error("%s fallback: %s", agent, type(exc).__name__)
        return None, exc.message
    tracker.record(agent, result.input_tokens, result.output_tokens)
    return result.parsed, ""


def started() -> float:
    return time.perf_counter()


def trace_dict(agent: str, mark: float, tracker: CostTracker, status: str, detail: str) -> dict:
    incoming, outgoing = tracker.tokens_for(agent)
    return {
        "agent": agent,
        "status": status,
        "duration_ms": int((time.perf_counter() - mark) * 1000),
        "input_tokens": incoming,
        "output_tokens": outgoing,
        "detail": detail,
    }
