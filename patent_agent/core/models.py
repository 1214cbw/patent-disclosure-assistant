from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class EvidenceStatus(str, Enum):
    SOURCE_FACT = "SOURCE_FACT"
    INFERRED = "INFERRED"
    AI_SUGGESTION = "AI_SUGGESTION"
    UNVERIFIED = "UNVERIFIED"


class SupportState(str, Enum):
    explicit = "explicit"
    inherent = "inherent"
    needs_confirmation = "needs-confirmation"
    unsupported = "unsupported"


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


class SourceFileRecord(BaseModel):
    path: str
    original_path: str
    media_type: str
    sha256: str
    chunk_ids: list[str] = Field(default_factory=list)


class EquationSpec(BaseModel):
    id: str
    latex: str
    role: str
    source_ids: list[str]
    symbols: dict[str, str] = Field(default_factory=dict)
    number: int | None = None


class PatentKnowledge(BaseModel):
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


class InventionCandidate(BaseModel):
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
    scope: Literal["broad", "conservative"] = "conservative"


class ClaimTree(BaseModel):
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


class FigureEdge(BaseModel):
    source: str
    target: str
    label: str = ""


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


class PatentCase(BaseModel):
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

