from __future__ import annotations

import json

from models.schemas import PatternLibrary, StandardLibrary
from utils.config import ROOT

LIBRARY_DIR = ROOT / "data" / "standard_clauses"
DEFAULT_TYPE = "rental"


def available_types() -> list[str]:
    return sorted(path.stem for path in LIBRARY_DIR.glob("*.json"))


def library_available(agreement_type: str) -> bool:
    return (LIBRARY_DIR / f"{agreement_type}.json").is_file()


def load_library(agreement_type: str = DEFAULT_TYPE) -> StandardLibrary:
    path = LIBRARY_DIR / f"{agreement_type}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    return StandardLibrary.model_validate(payload)


def load_library_for(agreement_type: str) -> StandardLibrary | None:
    if not library_available(agreement_type):
        return None
    return load_library(agreement_type)


def load_patterns(agreement_type: str = DEFAULT_TYPE) -> PatternLibrary:
    payload = json.loads((ROOT / "data" / "known_failure_patterns.json").read_text(encoding="utf-8"))
    patterns = PatternLibrary.model_validate(payload)
    if patterns.agreement_type and patterns.agreement_type != agreement_type:
        return patterns.model_copy(update={"patterns": []})
    return patterns
