from __future__ import annotations

from utils.config import ROOT

_CACHE: dict[str, str] = {}


def load_prompt(name: str) -> str:
    if name not in _CACHE:
        path = ROOT / "prompts" / name
        _CACHE[name] = path.read_text(encoding="utf-8")
    return _CACHE[name]
