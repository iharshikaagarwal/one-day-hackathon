from __future__ import annotations

from models.schemas import Agreement, StandardLibrary
from standards.agreement_types import detect_agreement_type
from standards.library import load_library_for, load_patterns
from agents.common import started, trace_dict

AGENT = "Agreement Type Detector"


def run_type_detection(state: dict, tracker, library_override: StandardLibrary | None = None) -> dict:
    """Pick the standard library. It never picks a different analysis engine."""
    mark = started()
    document = Agreement.model_validate(state["document"])
    detection = detect_agreement_type(document.full_text)
    library = load_library_for(detection.agreement_type)
    if library_override is not None and library_override.agreement_type == detection.agreement_type:
        library = library_override
    detection = detection.model_copy(update={"library_available": library is not None})

    warnings: list[str] = []
    if library is None:
        warnings.append(
            f"Agreement type detected ({detection.label}), but a standard comparison library is not currently "
            "available for this type. Clauses were extracted, but no comparison findings were produced."
        )
        patterns = None
        detail = f"{detection.label} at {detection.confidence:.0%}. No standard library for this type."
    else:
        patterns = load_patterns(detection.agreement_type)
        detail = f"{detection.label} at {detection.confidence:.0%}. Loaded {library.library_name} v{library.version}."

    return {
        "agreement_type": detection.model_dump(),
        "library": library.model_dump() if library else None,
        "patterns": patterns.model_dump() if patterns else None,
        "library_version": library.version if library else "",
        "warnings": warnings,
        "trace": [trace_dict(AGENT, mark, tracker, "success", detail)],
    }
