from __future__ import annotations

from models.schemas import FinancialExposure, RankingResult
from utils.format import format_inr

WEIGHTS = {
    "financial_exposure": 0.50,
    "recurrence": 0.20,
    "trigger_likelihood": 0.15,
    "ambiguity": 0.15,
}

RECURRENCE_SCORE = {"one_time": 0.35, "per_occurrence": 0.55, "monthly": 0.85, "per_day": 1.0}
LIKELIHOOD_SCORE = {"low": 0.25, "medium": 0.60, "high": 0.90}
AMBIGUITY_SCORE = {"low": 0.20, "medium": 0.55, "high": 0.90}

HIGH_VALUE_INR = 50_000
MEDIUM_VALUE_INR = 10_000


def rank_exposures(exposures: list[FinancialExposure]) -> list[RankingResult]:
    known = [item for item in exposures if item.amount is not None and item.amount > 0]
    unknown = [item for item in exposures if item not in known]
    max_amount = max((item.amount or 0) for item in known) if known else 0

    scored: list[tuple[float, FinancialExposure, RankingResult]] = []
    for item in known:
        financial = (item.amount or 0) / max_amount if max_amount else 0
        recurrence = RECURRENCE_SCORE.get(item.recurrence, 0.35)
        likelihood = LIKELIHOOD_SCORE.get(item.trigger_likelihood, 0.6)
        ambiguity = AMBIGUITY_SCORE.get(item.ambiguity, 0.55)
        components = {
            "financial_exposure": round(financial, 4),
            "recurrence": round(recurrence, 4),
            "trigger_likelihood": round(likelihood, 4),
            "ambiguity": round(ambiguity, 4),
        }
        score = (
            financial * WEIGHTS["financial_exposure"]
            + recurrence * WEIGHTS["recurrence"]
            + likelihood * WEIGHTS["trigger_likelihood"]
            + ambiguity * WEIGHTS["ambiguity"]
        )
        reason = (
            f"Score {score:.2f} uses financial exposure {WEIGHTS['financial_exposure']:.0%}, "
            f"recurrence {WEIGHTS['recurrence']:.0%}, trigger likelihood {WEIGHTS['trigger_likelihood']:.0%}, "
            f"and ambiguity {WEIGHTS['ambiguity']:.0%}. "
            f"The exposure component is {format_inr(item.amount)} divided by the largest exposure in this agreement. "
            f"{item.statement}"
        )
        scored.append(
            (
                score,
                item,
                RankingResult(
                    target_id=item.target_id,
                    clause_number=item.clause_number,
                    ranking_score=round(score, 4),
                    ranking_reason=reason,
                    quantitatively_ranked=True,
                    component_scores=components,
                ),
            )
        )

    scored.sort(key=lambda row: (-row[0], -(row[1].amount or 0), row[1].clause_number or ""))
    ranked: list[RankingResult] = []
    for index, (_, _, result) in enumerate(scored, start=1):
        ranked.append(result.model_copy(update={"rank": index}))

    for item in unknown:
        ranked.append(
            RankingResult(
                target_id=item.target_id,
                clause_number=item.clause_number,
                rank=None,
                ranking_score=None,
                ranking_reason=(
                    "This clause has no defensible monetary amount, so it is not placed on the quantitative ranking "
                    "and no amount was invented for it."
                ),
                quantitatively_ranked=False,
            )
        )
    return ranked


def impact_label(kind: str, amount: float | None) -> str:
    if kind == "missing":
        return "MISSING"
    if amount is None:
        return "REVIEW REQUIRED"
    if amount >= HIGH_VALUE_INR:
        return "HIGH IMPACT"
    if amount >= MEDIUM_VALUE_INR:
        return "MEDIUM IMPACT"
    return "LOW IMPACT"
