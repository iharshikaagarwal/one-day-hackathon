from __future__ import annotations

import re

_NUMBER = r"([0-9]{1,3}(?:,[0-9]{2,3})+|[0-9]+(?:\.[0-9]+)?)"
_CURRENCY = r"(?:₹|rs\.?|inr)"

_INR = re.compile(rf"{_CURRENCY}\s*{_NUMBER}", re.IGNORECASE)
_PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_PER_DAY = re.compile(rf"{_CURRENCY}\s*{_NUMBER}\s*(?:per|/|a)\s*day", re.IGNORECASE)
_CAP = re.compile(rf"capp?ed at\s*{_CURRENCY}\s*{_NUMBER}", re.IGNORECASE)
_DAY_COUNT = re.compile(r"(\d+)\s+days?", re.IGNORECASE)

MONTH_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
}


def parse_number(raw: str) -> float:
    return float(raw.replace(",", ""))


def _flat(text: str) -> str:
    return " ".join(text.replace("\u00ad", "-").split())


def _alternation(phrases: list[str]) -> str:
    return "|".join(re.escape(phrase) for phrase in sorted(phrases, key=len, reverse=True))


def inr_amounts(text: str) -> list[float]:
    return [parse_number(match.group(1)) for match in _INR.finditer(_flat(text))]


def word_or_number(raw: str) -> float | None:
    token = raw.strip().lower()
    if token in MONTH_WORDS:
        return float(MONTH_WORDS[token])
    try:
        return float(token)
    except ValueError:
        return None


def amount_after(text: str, phrases: list[str], currency_required: bool = False) -> float | None:
    """Amount written right after a library phrase, e.g. 'monthly fee of ₹20,000'."""
    if not phrases:
        return None
    currency = _CURRENCY if currency_required else f"{_CURRENCY}?"
    pattern = re.compile(rf"(?:{_alternation(phrases)})\s*{currency}\s*{_NUMBER}", re.IGNORECASE)
    match = pattern.search(_flat(text))
    return parse_number(match.group(1)) if match else None


def months_after(text: str, phrases: list[str]) -> float | None:
    """Month count after a phrase, e.g. 'bond equal to six months' salary'."""
    if not phrases:
        return None
    pattern = re.compile(rf"(?:{_alternation(phrases)})\s+([a-z]+|\d+(?:\.\d+)?)\s+months?'?", re.IGNORECASE)
    match = pattern.search(_flat(text))
    return word_or_number(match.group(1)) if match else None


def months_of_base_multiplier(text: str, nouns: list[str]) -> float | None:
    """Multiple in phrases such as "two months' fee" or "three months' salary"."""
    if not nouns:
        return None
    pattern = re.compile(
        rf"([a-z]+|\d+(?:\.\d+)?)\s+months?'?(?:\s+of)?\s+(?:{_alternation(nouns)})\b",
        re.IGNORECASE,
    )
    match = pattern.search(_flat(text))
    return word_or_number(match.group(1)) if match else None


def mentions_any(text: str, nouns: list[str]) -> bool:
    lowered = _flat(text).lower()
    return any(re.search(rf"\b{re.escape(noun.lower())}\b", lowered) for noun in nouns)


def percents(text: str) -> list[float]:
    return [float(match.group(1)) for match in _PERCENT.finditer(_flat(text))]


def per_day_amount(text: str) -> float | None:
    match = _PER_DAY.search(_flat(text))
    return parse_number(match.group(1)) if match else None


def capped_amount(text: str) -> float | None:
    match = _CAP.search(_flat(text))
    return parse_number(match.group(1)) if match else None


def stated_day_count(text: str) -> float | None:
    match = _DAY_COUNT.search(_flat(text))
    return float(match.group(1)) if match else None


def is_entire_held(text: str, nouns: list[str]) -> bool:
    lowered = _flat(text).lower()
    has_scope = any(token in lowered for token in ("entire", "whole", "full"))
    return has_scope and mentions_any(lowered, nouns)
