from __future__ import annotations

from pydantic import BaseModel, Field


class DocumentChunk(BaseModel):
    chunk_id: str
    page: int
    text: str
    section: str = ""


class PageText(BaseModel):
    page: int
    text: str


class AgreementClause(BaseModel):
    clause_id: str
    clause_number: str
    title: str
    category: str
    text: str
    page: int
    chunk_id: str
    conditions: list[str] = Field(default_factory=list)
    obligations: list[str] = Field(default_factory=list)
    penalties: list[str] = Field(default_factory=list)
    category_source: str = "heading"


class FinancialTerm(BaseModel):
    name: str
    amount: float | None = None
    currency: str = "INR"
    quote: str = ""
    page: int | None = None
    source: str = ""


class FinancialContext(BaseModel):
    """Agreement-type independent money inputs.

    base_amount is the recurring monthly figure (rent, salary, fee).
    held_amount is money held by the other party (deposit, bond, retention).
    Labels come from the active standard library.
    """

    base_amount: float | None = None
    base_amount_label: str = "monthly amount"
    base_amount_quote: str = ""
    base_amount_page: int | None = None
    held_months: float | None = None
    held_months_quote: str = ""
    held_months_page: int | None = None
    held_amount: float | None = None
    held_amount_label: str = "held amount"
    held_amount_source: str = ""
    currency: str = "INR"


class AgreementTypeDetection(BaseModel):
    agreement_type: str
    label: str
    confidence: float
    evidence: list[str] = Field(default_factory=list)
    reasoning: str
    library_available: bool = False


class Agreement(BaseModel):
    filename: str
    page_count: int
    pages: list[PageText]
    chunks: list[DocumentChunk]
    clauses: list[AgreementClause]
    full_text: str


class ElementCheck(BaseModel):
    element_id: str
    description: str
    any_of: list[str]


class StandardClause(BaseModel):
    standard_id: str
    category: str
    title: str
    standard_expectation: str
    expected_elements: list[str]
    missing_elements: list[str]
    element_checks: list[ElementCheck] = Field(default_factory=list)
    contradiction_indicators: list[str] = Field(default_factory=list)
    presence_indicators: list[str] = Field(default_factory=list)
    report_if_absent: bool = False
    comparison_guidance: str
    financial_basis: str
    suggested_revision: str
    negotiation_goal: str
    why_it_matters: str
    version: str
    review_date: str
    source_notes: str


class FinancialTermsConfig(BaseModel):
    base_amount_label: str = "monthly amount"
    base_amount_phrases: list[str] = Field(default_factory=list)
    base_amount_nouns: list[str] = Field(default_factory=list)
    held_amount_label: str = "held amount"
    held_amount_phrases: list[str] = Field(default_factory=list)
    held_months_phrases: list[str] = Field(default_factory=list)
    held_amount_nouns: list[str] = Field(default_factory=list)
    held_amount_category: str = ""
    percent_categories: list[str] = Field(default_factory=list)


class CategoryKeywords(BaseModel):
    category: str
    phrases: list[str]


class StandardLibrary(BaseModel):
    library_name: str
    agreement_type: str
    version: str
    jurisdiction: str
    status: str
    review_date: str
    disclaimer: str
    financial_terms: FinancialTermsConfig = Field(default_factory=FinancialTermsConfig)
    legal_review_categories: list[str] = Field(default_factory=list)
    generic_standard_ids: list[str] = Field(default_factory=list)
    generic_skip_categories: list[str] = Field(default_factory=list)
    heading_aliases: dict[str, str] = Field(default_factory=dict)
    category_keywords: list[CategoryKeywords] = Field(default_factory=list)
    entries: list[StandardClause]

    def by_id(self, standard_id: str) -> StandardClause | None:
        for entry in self.entries:
            if entry.standard_id == standard_id:
                return entry
        return None


class FailurePattern(BaseModel):
    pattern_id: str
    category: str
    description: str
    why_it_matters: str
    related_standard_ids: list[str]
    indicators: list[str] = Field(default_factory=list)
    suggested_review_action: str


class PatternLibrary(BaseModel):
    name: str
    agreement_type: str = ""
    version: str
    review_date: str
    disclaimer: str
    patterns: list[FailurePattern]


class ClauseComparison(BaseModel):
    comparison_id: str
    clause_number: str
    clause_title: str
    category: str
    page: int
    agreement_text: str
    standard_id: str
    standard_title: str
    standard_version: str
    standard_expectation: str
    difference: str
    reason: str
    matched_indicators: list[str] = Field(default_factory=list)
    missing_elements: list[str] = Field(default_factory=list)
    pattern_notes: list[str] = Field(default_factory=list)
    financial_basis: str = ""
    suggested_revision: str = ""
    negotiation_goal: str = ""
    why_it_matters: str = ""


class MissingClause(BaseModel):
    standard_id: str
    title: str
    category: str
    why_it_matters: str
    standard_expectation: str
    absence_evidence: str
    suggested_wording: str
    standard_version: str
    negotiation_goal: str = ""
    pattern_notes: list[str] = Field(default_factory=list)


class FinancialExposure(BaseModel):
    target_id: str
    clause_number: str | None = None
    standard_id: str | None = None
    amount: float | None = None
    currency: str = "INR"
    exposure_type: str
    calculation: str
    calculation_source: str
    formula: str
    inputs: dict[str, float] = Field(default_factory=dict)
    confidence: str = "medium"
    recurrence: str = "one_time"
    trigger_likelihood: str = "medium"
    ambiguity: str = "medium"
    statement: str
    rule_explanation: str


class RankingResult(BaseModel):
    target_id: str
    clause_number: str | None = None
    rank: int | None = None
    ranking_score: float | None = None
    ranking_reason: str
    quantitatively_ranked: bool
    component_scores: dict[str, float] = Field(default_factory=dict)


class NegotiationDraft(BaseModel):
    finding_key: str
    ask: str
    why_it_matters: str
    replacement_wording: str
    ready_to_send_message: str
    source: str


class Evidence(BaseModel):
    agreement_text: str | None = None
    page: int | None = None
    clause_number: str | None = None
    standard_id: str
    standard_title: str
    standard_text: str
    difference: str
    library_version: str


class Finding(BaseModel):
    finding_id: str
    kind: str
    rank: int | None = None
    clause_number: str | None = None
    title: str
    category: str
    page: int | None = None
    agreement_text: str | None = None
    standard_id: str
    standard_title: str
    standard_version: str
    standard_expectation: str
    difference: str
    reason: str
    exposure: FinancialExposure | None = None
    ranking: RankingResult | None = None
    negotiation: NegotiationDraft | None = None
    evidence: Evidence
    legal_review: bool = False
    legal_review_reasons: list[str] = Field(default_factory=list)
    impact_label: str
    pattern_notes: list[str] = Field(default_factory=list)
    validated: bool = True


class ValidationCheck(BaseModel):
    finding_key: str
    accepted: bool
    reasons: list[str] = Field(default_factory=list)


class ValidationSummary(BaseModel):
    evidence_backed: int
    evidence_considered: int
    rejected: int
    rejected_reasons: list[str] = Field(default_factory=list)
    calculations_validated: int
    calculations_considered: int
    missing_checks: int
    prompt_injection: str
    injection_note: str = ""
    checks: list[ValidationCheck] = Field(default_factory=list)


class AgentTraceEntry(BaseModel):
    agent: str
    status: str
    duration_ms: int
    input_tokens: int = 0
    output_tokens: int = 0
    detail: str = ""


class CostSummary(BaseModel):
    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    estimated_cost_usd: float
    currency: str = "USD"
    label: str = "Estimated API cost"
    timestamp: str
    run_id: str
    pricing_note: str


class EvaluationResult(BaseModel):
    case_id: str
    dataset_label: str
    clause_detection_recall: float
    clause_detection_precision: float
    missing_detection_recall: float
    normal_clause_false_positive_rate: float
    ranking_agreement: float | None
    evidence_validation_rate: float
    expected_ranking: list[str]
    actual_ranking: list[str]
    expected_unusual: list[str]
    found_unusual: list[str]
    missed_unusual: list[str]
    unexpected_unusual: list[str]
    expected_missing: list[str]
    found_missing: list[str]
    missed_missing: list[str]
    false_positive_normal_clauses: list[str]
    notes: str


class AnalysisRun(BaseModel):
    run_id: str
    created_at: str
    agreement_type: AgreementTypeDetection
    library_available: bool
    library_name: str
    library_version: str
    library_disclaimer: str
    filename: str
    page_count: int
    findings: list[Finding]
    unusual_count: int
    missing_count: int
    review_count: int
    largest_exposure: float | None
    currency: str
    trace: list[AgentTraceEntry]
    cost: CostSummary
    validation: ValidationSummary
    evaluation: EvaluationResult | None = None
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    injection_excerpts: list[str] = Field(default_factory=list)
