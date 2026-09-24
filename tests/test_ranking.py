from models.schemas import FinancialExposure
from financial.ranking import rank_exposures


def _exposure(clause: str, amount: float | None, ambiguity: str = "low") -> FinancialExposure:
    return FinancialExposure(
        target_id=clause,
        clause_number=clause,
        amount=amount,
        exposure_type="explicit_amount" if amount is not None else "unknown",
        calculation="test",
        calculation_source="python_calculator",
        formula="fixed" if amount is not None else "none",
        confidence="high" if amount is not None else "low",
        recurrence="one_time",
        trigger_likelihood="medium",
        ambiguity=ambiguity,
        statement="potential exposure" if amount is not None else "No defensible monetary amount can be calculated.",
        rule_explanation="test",
    )


def test_higher_exposure_ranks_first_even_if_less_ambiguous():
    ranked = rank_exposures(
        [
            _exposure("4.2", 2000, ambiguity="high"),
            _exposure("7.1", 120000, ambiguity="low"),
            _exposure("9.3", 40000, ambiguity="high"),
        ]
    )
    order = [item.clause_number for item in ranked if item.quantitatively_ranked]
    assert order == ["7.1", "9.3", "4.2"]
    assert ranked[0].rank == 1


def test_unknown_exposure_is_not_given_an_invented_rank():
    ranked = rank_exposures([_exposure("7.1", 120000), _exposure("8.2", None)])
    unknown = next(item for item in ranked if item.clause_number == "8.2")
    assert unknown.quantitatively_ranked is False
    assert unknown.rank is None
    assert unknown.ranking_score is None
    assert "invented" in unknown.ranking_reason
