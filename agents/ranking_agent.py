from __future__ import annotations

from models.schemas import FinancialExposure
from financial.ranking import rank_exposures
from agents.common import started, trace_dict

AGENT = "Financial Impact Ranker"


def run_ranking(state: dict, tracker) -> dict:
    mark = started()
    exposures = [FinancialExposure.model_validate(item) for item in state.get("exposures", [])]
    ranked = rank_exposures(exposures)
    quantitative = sum(1 for item in ranked if item.quantitatively_ranked)
    detail = (
        f"{quantitative} clauses ranked by the configured score. "
        "Weights: financial exposure 50%, recurrence 20%, trigger likelihood 15%, ambiguity 15%."
    )
    return {
        "ranked": [item.model_dump() for item in ranked],
        "trace": [trace_dict(AGENT, mark, tracker, "success", detail)],
    }
