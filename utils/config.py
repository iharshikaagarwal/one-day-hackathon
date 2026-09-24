from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CHAT_MODEL = "gpt-4.1-nano"


@dataclass(frozen=True)
class Settings:
    api_key: str
    model: str
    embedding_model: str
    chat_model: str = DEFAULT_CHAT_MODEL


def load_settings() -> Settings:
    load_dotenv(ROOT / ".env")
    return Settings(
        api_key=os.getenv("OPENAI_API_KEY", "").strip(),
        model=os.getenv("OPENAI_MODEL", "").strip(),
        embedding_model=os.getenv("OPENAI_EMBEDDING_MODEL", "").strip(),
        chat_model=os.getenv("OPENAI_CHAT_MODEL", "").strip() or DEFAULT_CHAT_MODEL,
    )
