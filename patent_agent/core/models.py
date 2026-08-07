from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class EvidenceStatus(str, Enum):
    SOURCE_FACT = "SOURCE_FACT"
    HUMAN_CONFIRMED = "HUMAN_CONFIRMED"
    INFERRED = "INFERRED"
    AI_SUGGESTION = "AI_SUGGESTION"
    UNVERIFIED = "UNVERIFIED"


class SupportState(str, Enum):
    explicit = "explicit"
    inherent = "inherent"
    needs_confirmation = "needs-confirmation"
    unsupported = "unsupported"


class EvidenceScope(str, Enum):
    INVENTION_SOURCE = "INVENTION_SOURCE"
    PRIOR_ART = "PRIOR_ART"
    REFERENCE = "REFERENCE"
    INVENTOR_ASSERTION = "INVENTOR_ASSERTION"


class ReviewStatus(str, Enum):
    UNREVIEWED = "UNREVIEWED"
    ACCEPTED = "ACCEPTED"
    EDITED = "EDITED"
    REJECTED = "REJECTED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    LOCKED = "LOCKED"


class StrictSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = "2.0"


class EvidenceChunk(StrictSchema):
    evidence_id: str
    source_file_id: str
    source_file_name: str
    source_type: str
    scope: EvidenceScope = EvidenceScope.INVENTION_SOURCE
    section_title: str | None = None
    page: int | None = None
    paragraph_index: int | None = None
    raw_text: str
    normalized_text: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    hash: str
    block_type: str = "paragraph"
    supersedes: list[str] = Field(default_factory=list)


class GroundedStatement(StrictSchema):
    text: str
    evidence_ids: list[str] = Field(default_factory=list)
    status: EvidenceStatus
    confidence: float = Field(ge=0, le=1)
    review_status: ReviewStatus = ReviewStatus.UNREVIEWED
    human_modified: bool = False
    locked: bool = False

    @model_validator(mode="after")
    def source_fact_has_evidence(self):
        if self.status == EvidenceStatus.SOURCE_FACT and not self.evidence_ids:
            raise ValueError("SOURCE_FACT_WITHOUT_EVIDENCE")
        return self


class TechnicalFact(StrictSchema):
    fact_id: str
    statement: str
    category: str
    evidence_ids: list[str] = Field(default_factory=list)
    status: EvidenceStatus
    confidence: float = Field(ge=0, le=1)
    notes: str | None = None
    review_status: ReviewStatus = ReviewStatus.UNREVIEWED
    human_modified: bool = False
    locked: bool = False
    confirmation_id: str | None = None
    correction_id: str | None = None
    revision_id: str | None = None
    previous_version_id: str | None = None
    revision_reason: str | None = None
    reviewed_at: str | None = None

    @model_validator(mode="after")
    def source_fact_has_evidence(self):
        if self.status == EvidenceStatus.SOURCE_FACT and not self.evidence_ids:
            raise ValueError("SOURCE_FACT_WITHOUT_EVIDENCE")
        return self


class ComponentKnowledge(StrictSchema):
    component_id: str
    name: str
    description: GroundedStatement


class MethodStepKnowledge(StrictSchema):
    step_id: str
    text: GroundedStatement


class RelationshipKnowledge(StrictSchema):
    source: str
    target: str
    relation: GroundedStatement


class ParameterKnowledge(StrictSchema):
    parameter_id: str
    symbol: str | None = None
    name: str
    value: str | None = None
    unit: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    status: EvidenceStatus


class EquationKnowledge(StrictSchema):
    equation_id: str
    original_expression: str
    normalized_latex: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    status: EvidenceStatus
    symbols: dict[str, str] = Field(default_factory=dict)
    original_formula: str | None = None
    human_formula: str | None = None
    review_status: ReviewStatus = ReviewStatus.UNREVIEWED
    human_modified: bool = False
    locked: bool = False


class InventorQuestion(StrictSchema):
    question_id: str
    text: str
    priority: Literal["P0", "P1", "P2"]
    question_role: Literal["CLAIM_BLOCKING", "ENABLEMENT", "EMBODIMENT_DETAIL", "OPTIONAL_DETAIL"] = "OPTIONAL_DETAIL"
    related_fact_ids: list[str] = Field(default_factory=list)
    related_evidence_ids: list[str] = Field(default_factory=list)
    blocking_stage: Literal["A1", "A2", "B", "C", "FINAL"] | None = None
    answered: bool = False


class InventorAssertion(StrictSchema):
    assertion_id: str
    question_id: str
    statement: str
    confirmed_by_user: bool = False
    confirmed_by: Literal["user"] | None = None
    created_at: str = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def confirmation_is_human_only(self):
        if self.confirmed_by_user and self.confirmed_by != "user":
            raise ValueError("confirmed_by_user requires confirmed_by='user'")
        return self


class TechnicalUnderstandingResult(StrictSchema):
    technical_field: list[GroundedStatement]
    technical_problems: list[GroundedStatement]
    system_overview: list[GroundedStatement]
    components: list[ComponentKnowledge]
    steps: list[MethodStepKnowledge]
    data_flows: list[RelationshipKnowledge]
    control_flows: list[RelationshipKnowledge]
    inputs: list[GroundedStatement]
    outputs: list[GroundedStatement]
    parameters: list[ParameterKnowledge]
    equations: list[EquationKnowledge]
    technical_effects: list[GroundedStatement]
    experiments: list[GroundedStatement]
    alternatives: list[GroundedStatement]
    uncertainties: list[InventorQuestion]
    facts: list[TechnicalFact]


class CandidateScoreBreakdown(StrictSchema):
    evidence_strength: float = Field(ge=0, le=1)
    novelty_potential: float = Field(ge=0, le=1)
    technical_importance: float = Field(ge=0, le=1)
    claimability: float = Field(ge=0, le=1)
    alternative_coverage: float = Field(ge=0, le=1)
    implementation_support: float = Field(ge=0, le=1)
    risk: float = Field(ge=0, le=1)


class GroundedInventionCandidate(StrictSchema):
    candidate_id: str
    title: str
    technical_problem: GroundedStatement
    core_idea: GroundedStatement
    mandatory_features: list[GroundedStatement]
    optional_features: list[GroundedStatement]
    technical_effects: list[GroundedStatement]
    evidence_ids: list[str]
    novelty_hypothesis: str
    inventiveness_hypothesis: str
    protection_value_score: float = Field(ge=0, le=1)
    evidence_strength_score: float = Field(ge=0, le=1)
    risk_score: float = Field(ge=0, le=1)
    score_breakdown: CandidateScoreBreakdown
    inventor_questions: list[str] = Field(default_factory=list)
    possible_duplicate_of: list[str] = Field(default_factory=list)
    merge_recommendation: str = ""
    review_status: ReviewStatus = ReviewStatus.UNREVIEWED
    human_modified: bool = False
    locked: bool = False
    merged_from: list[str] = Field(default_factory=list)
    split_from: str | None = None


class TerminologyChoice(StrictSchema):
    concept_id: str
    selected_term: str
    alternatives: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    patent_term: str | None = None
    human_confirmed: bool = False
    review_status: ReviewStatus = ReviewStatus.UNREVIEWED


class GroundedProtectionStrategy(StrictSchema):
    inventive_concept: str
    independent_claim_core: list[GroundedStatement]
    dependent_claim_features: list[GroundedStatement]
    optional_features: list[GroundedStatement]
    broad_terms: list[TerminologyChoice]
    narrow_terms: list[TerminologyChoice]
    parameters_to_avoid_locking: list[str]
    alternative_embodiments_needed: list[str]
    support_gaps: list[str]
    risks: list[str]
    inventor_questions: list[str]
    scope_strategy: Literal["Broad", "Balanced", "Conservative"] = "Balanced"
    review_status: ReviewStatus = ReviewStatus.UNREVIEWED
    human_modified: bool = False
    locked: bool = False


class GroundedParagraph(StrictSchema):
    paragraph_id: str
    section_id: str
    text: str
    evidence_ids: list[str] = Field(default_factory=list)
    fact_ids: list[str] = Field(default_factory=list)
    derived_from: list[str] = Field(default_factory=list)
    status: EvidenceStatus
    human_modified: bool = False
    review_status: ReviewStatus = ReviewStatus.UNREVIEWED
    locked: bool = False


class GroundedSection(StrictSchema):
    section_id: str
    title: str
    paragraphs: list[GroundedParagraph]


class GroundedDisclosure(StrictSchema):
    title: str
    sections: list[GroundedSection]


class ClaimFeature(StrictSchema):
    feature_id: str
    text: str
    source_fact_ids: list[str]
    evidence_ids: list[str]
    support_status: Literal["SUPPORTED", "PARTIALLY_SUPPORTED", "UNSUPPORTED", "UNCERTAIN"]
    mandatory: bool = False
    review_status: ReviewStatus = ReviewStatus.UNREVIEWED
    human_modified: bool = False
    locked: bool = False


class PatentClaimV2(StrictSchema):
    claim_number: int
    claim_type: Literal["method", "system", "dependent"]
    parent_claims: list[int] = Field(default_factory=list)
    features: list[ClaimFeature]
    rendered_text: str
    draft_strategy: Literal["broad", "balanced", "conservative"] = "conservative"
    review_status: ReviewStatus = ReviewStatus.UNREVIEWED
    human_modified: bool = False
    structured_mapping_stale: bool = False


class GroundedClaimSet(StrictSchema):
    title: str
    claims: list[PatentClaimV2]


class ClaimSupportRecord(StrictSchema):
    claim_number: int
    feature_id: str
    feature_text: str
    disclosure_paragraph_ids: list[str]
    fact_ids: list[str]
    evidence_ids: list[str]
    support_status: Literal["SUPPORTED", "PARTIALLY_SUPPORTED", "UNSUPPORTED", "UNCERTAIN"]
    notes: str


class ClaimsSupportMatrix(StrictSchema):
    records: list[ClaimSupportRecord]
    validation_status: Literal["PASS", "FAIL", "INVENTOR_CONFIRMATION_REQUIRED"]
    unsupported_independent_features: list[str] = Field(default_factory=list)


class ClaimTerminologyRegistry(StrictSchema):
    terms: list[TerminologyChoice]


class FeatureNoveltyAssessmentV2(StrictSchema):
    feature_id: str
    feature_text: str
    prior_art_document_id: str
    assessment: Literal["EXPLICITLY_DISCLOSED", "POSSIBLY_DISCLOSED", "NOT_FOUND", "UNCERTAIN"]
    prior_art_evidence_ids: list[str]
    reasoning: str


class GroundedNoveltyMatrix(StrictSchema):
    assessments: list[FeatureNoveltyAssessmentV2]
    legal_notice: str = "仅为人工导入资料的查新辅助，不构成穷尽性检索或法律意见。"


class QualityGateResult(StrictSchema):
    gate: str
    status: Literal["PASS", "FAIL"]
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class TraceabilityLink(StrictSchema):
    link_id: str
    object_type: Literal["disclosure", "claim_feature", "equation", "figure"]
    object_id: str
    disclosure_paragraph_ids: list[str] = Field(default_factory=list)
    fact_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    status: Literal["LINKED", "BROKEN"]


class TraceabilityReport(StrictSchema):
    links: list[TraceabilityLink]
    broken_links: list[str] = Field(default_factory=list)


class SemanticReviewFinding(StrictSchema):
    code: str
    severity: Literal["ERROR", "WARNING", "INFO"]
    message: str
    location: str = ""


class SemanticReviewResult(StrictSchema):
    findings: list[SemanticReviewFinding] = Field(default_factory=list)


class EvidenceRef(BaseModel):
    id: str
    claim: str
    source_type: str = "source_document"
    source_file: str
    source_location: str
    confidence: float = Field(ge=0, le=1)
    status: EvidenceStatus = EvidenceStatus.SOURCE_FACT
    support_state: SupportState = SupportState.explicit


class SourceChunk(BaseModel):
    id: str
    source_file: str
    source_location: str
    heading: str = ""
    text: str
    sha256: str
    page: int | None = None
    paragraph_index: int | None = None
    block_type: str = "paragraph"
    scope: EvidenceScope = EvidenceScope.INVENTION_SOURCE


class SourceFileRecord(BaseModel):
    path: str
    original_path: str
    media_type: str
    sha256: str
    chunk_ids: list[str] = Field(default_factory=list)


class EquationSpec(BaseModel):
    schema_version: str = "2.0"
    id: str
    latex: str
    role: str
    source_ids: list[str]
    evidence_ids: list[str] = Field(default_factory=list)
    original_expression: str = ""
    status: EvidenceStatus = EvidenceStatus.SOURCE_FACT
    symbols: dict[str, str] = Field(default_factory=dict)
    number: int | None = None


class PatentKnowledge(BaseModel):
    schema_version: str = "2.0"
    technical_field: str
    technical_problem: str
    existing_technology: list[str] = Field(default_factory=list)
    existing_limitations: list[str] = Field(default_factory=list)
    core_idea: str
    components: list[str] = Field(default_factory=list)
    steps: list[str] = Field(default_factory=list)
    relationships: list[str] = Field(default_factory=list)
    data_flow: list[str] = Field(default_factory=list)
    control_flow: list[str] = Field(default_factory=list)
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    technical_effects: list[str] = Field(default_factory=list)
    key_parameters: dict[str, str] = Field(default_factory=dict)
    equations: list[EquationSpec] = Field(default_factory=list)
    experimental_evidence: list[str] = Field(default_factory=list)
    alternative_embodiments: list[str] = Field(default_factory=list)
    optional_features: list[str] = Field(default_factory=list)
    mandatory_features: list[str] = Field(default_factory=list)
    inventor_assertions: list[str] = Field(default_factory=list)
    uncertain_information: list[str] = Field(default_factory=list)
    evidence: list[EvidenceRef] = Field(default_factory=list)
    technical_facts: list[TechnicalFact] = Field(default_factory=list)


class InventionCandidate(BaseModel):
    schema_version: str = "2.0"
    id: str
    title: str
    technical_problem: str
    existing_pain: str
    core_means: list[str]
    mandatory_features: list[str]
    optional_features: list[str]
    expected_effects: list[str]
    distinguishing_points: list[str]
    protectable_scope: str
    evidence_ids: list[str]
    novelty_risk: str
    inventiveness_risk: str
    drafting_value: Literal["high", "medium", "low"]


class ProtectionStrategy(BaseModel):
    core_inventive_concept: str
    mandatory_features: list[str]
    optional_features: list[str]
    preferred_embodiment: list[str]
    alternative_embodiments: list[str]
    parameter_ranges: list[str]
    broad_terminology: dict[str, str]
    narrow_terminology: dict[str, str]
    risk_points: list[str]


class PriorArtReference(BaseModel):
    id: str
    title: str
    source: str
    publication_number: str = ""
    abstract: str
    imported_at: str = Field(default_factory=utc_now)
    synthetic_demo: bool = False


class FeatureAssessment(BaseModel):
    feature_id: str
    feature: str
    reference_id: str
    status: Literal["明确公开", "疑似公开", "未发现公开", "无法判断"]
    evidence: str


class NoveltyAnalysis(BaseModel):
    candidate_id: str
    features: list[str]
    references: list[PriorArtReference]
    matrix: list[FeatureAssessment]
    conclusion: str
    legal_notice: str = "仅为查新辅助分析，不构成正式法律意见或授权保证。"


class Claim(BaseModel):
    number: int
    category: Literal["method", "system", "dependent"]
    depends_on: list[int] = Field(default_factory=list)
    text: str
    feature_ids: list[str]
    evidence_ids: list[str]
    scope: Literal["broad", "balanced", "conservative"] = "conservative"


class ClaimTree(BaseModel):
    schema_version: str = "2.0"
    title: str
    claims: list[Claim]

    @model_validator(mode="after")
    def validate_dependencies(self):
        numbers = {claim.number for claim in self.claims}
        for claim in self.claims:
            if any(parent not in numbers or parent >= claim.number for parent in claim.depends_on):
                raise ValueError(f"Claim {claim.number} has an invalid dependency")
        return self


class FigureNode(BaseModel):
    id: str
    label: str
    claim_step: str | None = None
    fact_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class FigureEdge(BaseModel):
    source: str
    target: str
    label: str = ""
    fact_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class FigureSpec(BaseModel):
    id: str
    number: int
    type: Literal["flowchart", "system", "methodology"]
    title: str
    nodes: list[FigureNode]
    edges: list[FigureEdge]
    source_ids: list[str]
    png_path: str = ""
    svg_path: str = ""


class DisclosureDraft(BaseModel):
    title: str
    sections: dict[str, list[str]]
    equations: list[EquationSpec]
    figures: list[FigureSpec]
    inventor_questions: list[str]
    evidence_ids: list[str]


class ReviewFinding(BaseModel):
    code: str
    severity: Literal["ERROR", "WARNING", "INFO"]
    message: str
    location: str = ""


class StageVersion(BaseModel):
    stage: str
    version: int
    path: str
    created_at: str = Field(default_factory=utc_now)
    human_modified: bool = False


class PatentCase(BaseModel):
    schema_version: str = "2.0"
    case_id: str
    title: str = ""
    status: str = "initialized"
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)
    inventors: list[str] = Field(default_factory=list)
    technical_field: str = ""
    source_files: list[SourceFileRecord] = Field(default_factory=list)
    current_stage: str = "stage_0_initialization"
    versions: list[StageVersion] = Field(default_factory=list)
    checkpoints: dict[str, dict[str, Any]] = Field(default_factory=dict)
