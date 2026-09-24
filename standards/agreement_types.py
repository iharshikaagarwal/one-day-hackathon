from __future__ import annotations

import json
import re

from models.schemas import AgreementTypeDetection
from standards.library import library_available
from utils.config import ROOT

MAX_CONFIDENCE = 0.99
FULL_COVERAGE_SIGNALS = 5


def load_type_config() -> dict:
    return json.loads((ROOT / "data" / "agreement_types.json").read_text(encoding="utf-8"))


def detect_agreement_type(text: str) -> AgreementTypeDetection:
    config = load_type_config()
    flat = " ".join(text.replace("\u00ad", "-").split()).lower()
    scored: list[tuple[int, dict, list[str]]] = []
    for item in config["types"]:
        hits = [signal for signal in item["signals"] if re.search(rf"\b{re.escape(signal)}\b", flat)]
        scored.append((len(hits), item, hits))
    scored.sort(key=lambda row: -row[0])
    top_hits, top, matched = scored[0]
    total = sum(row[0] for row in scored)

    if top_hits < config["minimum_signals"]:
        return AgreementTypeDetection(
            agreement_type="unknown",
            label="Unrecognized agreement",
            confidence=0.0,
            evidence=matched,
            reasoning=(
                f"Fewer than {config['minimum_signals']} type signals were found, "
                "so no agreement type was assigned."
            ),
            library_available=False,
        )

    share = top_hits / total
    coverage = min(1.0, top_hits / FULL_COVERAGE_SIGNALS)
    confidence = round(min(MAX_CONFIDENCE, share * coverage), 2)
    runner_up = scored[1]
    reasoning = (
        f"Matched {top_hits} {top['label'].lower()} signals: {', '.join(matched)}. "
        f"Next closest was {runner_up[1]['label'].lower()} with {runner_up[0]}."
    )
    return AgreementTypeDetection(
        agreement_type=top["agreement_type"],
        label=top["label"],
        confidence=confidence,
        evidence=[_snippet(flat, signal) for signal in matched[:4]],
        reasoning=reasoning,
        library_available=library_available(top["agreement_type"]),
    )


def _snippet(flat: str, signal: str) -> str:
    index = flat.find(signal)
    start = max(0, index - 40)
    return "…" + flat[start : index + len(signal) + 40].strip() + "…"
