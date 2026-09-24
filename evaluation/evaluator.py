from __future__ import annotations

import json

from models.schemas import EvaluationResult, Finding, ValidationSummary
from utils.config import ROOT
from evaluation.agreement_text import EVAL_MARKER


def load_expected() -> dict:
    return json.loads((ROOT / "evaluation" / "expected_results.json").read_text(encoding="utf-8"))


def maybe_evaluate(full_text: str, findings: list[Finding], validation: ValidationSummary) -> EvaluationResult | None:
    expected = load_expected()
    if expected["marker"] not in full_text and EVAL_MARKER not in full_text:
        return None
    return score_findings(findings, validation, expected)


def score_findings(findings: list[Finding], validation: ValidationSummary, expected: dict | None = None) -> EvaluationResult:
    expected = expected or load_expected()
    found_unusual = [item.clause_number for item in findings if item.kind == "unusual" and item.clause_number]
    found_set = set(found_unusual)
    expected_unusual = list(expected["expected_unusual_clauses"])
    expected_set = set(expected_unusual)
    expected_normal = list(expected["expected_normal_clauses"])
    false_positives = [clause for clause in expected_normal if clause in found_set]
    missed_unusual = [clause for clause in expected_unusual if clause not in found_set]
    unexpected = [clause for clause in found_unusual if clause not in expected_set]

    found_missing = [item.standard_id for item in findings if item.kind == "missing"]
    expected_missing = list(expected["expected_missing_clauses"])
    missed_missing = [item for item in expected_missing if item not in found_missing]

    actual_ranking = [
        item.clause_number
        for item in findings
        if item.kind == "unusual" and item.rank is not None and item.clause_number
    ]
    expected_ranking = list(expected["expected_ranking"])

    recall = _ratio(len(expected_set & found_set), len(expected_set))
    precision = _ratio(len(expected_set & found_set), len(found_set)) if found_set else 0.0
    missing_recall = _ratio(len(set(expected_missing) & set(found_missing)), len(expected_missing))
    false_positive_rate = _ratio(len(false_positives), len(expected_normal))
    ranking = _ranking_agreement(expected_ranking, actual_ranking)
    evidence_rate = _ratio(validation.evidence_backed, validation.evidence_considered)

    return EvaluationResult(
        case_id=expected["case_id"],
        dataset_label="Results on the ClauseLens evaluation dataset only. Not a measure of general accuracy.",
        clause_detection_recall=recall,
        clause_detection_precision=precision,
        missing_detection_recall=missing_recall,
        normal_clause_false_positive_rate=false_positive_rate,
        ranking_agreement=ranking,
        evidence_validation_rate=evidence_rate,
        expected_ranking=expected_ranking,
        actual_ranking=actual_ranking,
        expected_unusual=expected_unusual,
        found_unusual=found_unusual,
        missed_unusual=missed_unusual,
        unexpected_unusual=unexpected,
        expected_missing=expected_missing,
        found_missing=found_missing,
        missed_missing=missed_missing,
        false_positive_normal_clauses=false_positives,
        notes=expected["notes"],
    )


def _ranking_agreement(expected: list[str], actual: list[str]) -> float | None:
    pairs = 0
    correct = 0
    positions = {clause: index for index, clause in enumerate(actual)}
    for left_index, left in enumerate(expected):
        for right in expected[left_index + 1 :]:
            pairs += 1
            if left in positions and right in positions and positions[left] < positions[right]:
                correct += 1
    if pairs == 0:
        return None
    return correct / pairs


def _ratio(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator
