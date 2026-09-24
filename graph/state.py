from __future__ import annotations

import operator
from typing import Annotated, TypedDict


class AnalysisState(TypedDict):
    run_id: str
    filename: str
    document: dict
    agreement_type: dict
    library: dict | None
    patterns: dict | None
    clauses: list
    financial_context: dict
    comparisons: list
    missing_clauses: list
    exposures: list
    ranked: list
    negotiations: list
    findings: list
    validation: dict
    injection: dict
    library_version: str
    trace: Annotated[list, operator.add]
    errors: Annotated[list, operator.add]
    warnings: Annotated[list, operator.add]
