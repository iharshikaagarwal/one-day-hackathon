from __future__ import annotations


def format_inr(amount: float | None) -> str:
    if amount is None:
        return "Unknown"
    sign = "-" if amount < 0 else ""
    whole = int(round(abs(amount)))
    digits = str(whole)
    if len(digits) <= 3:
        grouped = digits
    else:
        head, tail = digits[:-3], digits[-3:]
        parts: list[str] = []
        while len(head) > 2:
            parts.append(head[-2:])
            head = head[:-2]
        if head:
            parts.append(head)
        grouped = ",".join(reversed(parts)) + "," + tail
    return f"{sign}₹{grouped}"


def normalize_text(value: str) -> str:
    return " ".join(value.split()).strip().lower()
