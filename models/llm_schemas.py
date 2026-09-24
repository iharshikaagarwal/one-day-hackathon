from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class LLMClauseAnnotation(BaseModel):
    clause_number: str = ""
    category: str = "other"
    title: str = ""
    obligations: list[str] = Field(default_factory=list)
    conditions: list[str] = Field(default_factory=list)
    penalties: list[str] = Field(default_factory=list)


class LLMFinancialExtraction(BaseModel):
    base_amount: float = -1
    base_amount_evidence: str = ""
    held_amount: float = -1
    held_months: float = -1
    held_amount_evidence: str = ""
    currency: str = "INR"


class LLMAgreementAnalysis(BaseModel):
    clauses: list[LLMClauseAnnotation] = Field(default_factory=list)
    financials: LLMFinancialExtraction = Field(default_factory=LLMFinancialExtraction)
    notes: str = ""


class LLMComparison(BaseModel):
    clause_number: str = ""
    standard_id: str = ""
    is_unusual: bool = False
    difference: str = ""
    reason: str = ""
    missing_element_ids: list[str] = Field(default_factory=list)


class LLMComparisonBatch(BaseModel):
    comparisons: list[LLMComparison] = Field(default_factory=list)


class LLMMissing(BaseModel):
    standard_id: str = ""
    why_it_matters: str = ""
    absence_evidence: str = ""


class LLMMissingBatch(BaseModel):
    missing: list[LLMMissing] = Field(default_factory=list)


class LLMExposureRule(BaseModel):
    clause_number: str = ""
    level: Literal["explicit_amount", "formula", "maximum_asset", "unknown"] = "unknown"
    formula: Literal[
        "fixed",
        "months_of_base",
        "years_of_base",
        "percent_of_base",
        "percent_of_held",
        "daily_fixed",
        "recurring_fixed",
        "entire_held_amount",
        "none",
    ] = "none"
    multiplier: float = 0
    fixed_amount: float = 0
    percent: float = 0
    period_days: float = 0
    occurrences: float = 0
    recurrence: Literal["one_time", "monthly", "per_day", "per_occurrence"] = "one_time"
    trigger_likelihood: Literal["low", "medium", "high"] = "medium"
    ambiguity: Literal["low", "medium", "high"] = "medium"
    rule_explanation: str = ""
    confidence: Literal["low", "medium", "high"] = "medium"


class LLMExposureBatch(BaseModel):
    rules: list[LLMExposureRule] = Field(default_factory=list)


class LLMNegotiation(BaseModel):
    finding_key: str = ""
    ask: str = ""
    why_it_matters: str = ""
    replacement_wording: str = ""
    ready_to_send_message: str = ""


class LLMNegotiationBatch(BaseModel):
    drafts: list[LLMNegotiation] = Field(default_factory=list)
