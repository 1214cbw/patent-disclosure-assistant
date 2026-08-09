from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import Field, model_validator

from patent_agent.core.models import StrictSchema, utc_now


class CorrectionAction(str, Enum):
    ACCEPT = "ACCEPT"
    EDIT = "EDIT"
    REJECT = "REJECT"
    MERGE = "MERGE"
    ADD = "ADD"
    DELETE = "DELETE"
    SPLIT = "SPLIT"
    RERANK = "RERANK"
    MOVE = "MOVE"
    PROMOTE = "PROMOTE"
    UNLOCK = "UNLOCK"


class RevisionSeverity(str, Enum):
    NONE = "NONE"
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    REJECT = "REJECT"


class ReviewReason(str, Enum):
    TERMINOLOGY = "TERMINOLOGY"
    RELATIONSHIP = "RELATIONSHIP"
    MISSING_FEATURE = "MISSING_FEATURE"
    EXTRA_FEATURE = "EXTRA_FEATURE"
    PARAMETER = "PARAMETER"
    EQUATION = "EQUATION"
    TECHNICAL_EFFECT = "TECHNICAL_EFFECT"
    EXPERIMENT = "EXPERIMENT"
    INVENTION_SCOPE = "INVENTION_SCOPE"
    CLAIM_SCOPE = "CLAIM_SCOPE"
    OTHER = "OTHER"


class CheckpointStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    GENERATED = "GENERATED"
    UNDER_REVIEW = "UNDER_REVIEW"
    CHANGES_REQUIRED = "CHANGES_REQUIRED"
    APPROVED = "APPROVED"
    BLOCKED = "BLOCKED"


class CaseWorkflowState(str, Enum):
    INGESTED = "INGESTED"
    A1_REVIEW = "A1_REVIEW"
    A2_REVIEW = "A2_REVIEW"
    PRIOR_ART = "PRIOR_ART"
    B_REVIEW = "B_REVIEW"
    DRAFTING = "DRAFTING"
    C_REVIEW = "C_REVIEW"
    FINAL_RENDER = "FINAL_RENDER"
    VALIDATED = "VALIDATED"
    CONTENT_VALIDATED = "CONTENT_VALIDATED"
    DOCX_VALIDATED = "DOCX_VALIDATED"
    RENDER_VALIDATED = "RENDER_VALIDATED"
    DELIVERY_READY = "DELIVERY_READY"
    DONE = "DONE"


class ArtifactState(str, Enum):
    CURRENT = "CURRENT"
    STALE = "STALE"
    LOCKED = "LOCKED"


class HumanCorrection(StrictSchema):
    correction_id: str
    case_id: str
    target_type: str
    target_id: str
    original_value: Any = None
    corrected_value: Any = None
    action: CorrectionAction
    severity: RevisionSeverity = RevisionSeverity.NONE
    reason: str | None = None
    reason_category: ReviewReason = ReviewReason.OTHER
    created_at: str = Field(default_factory=utc_now)
    confirmed_by_user: bool = True
    actor: Literal["local_user"] = "local_user"
    lock_after_apply: bool = True

    @model_validator(mode="after")
    def confirmed_and_consistent(self):
        if not self.confirmed_by_user:
            raise ValueError("HUMAN_CORRECTION_REQUIRES_EXPLICIT_CONFIRMATION")
        if self.action == CorrectionAction.ACCEPT and self.severity != RevisionSeverity.NONE:
            raise ValueError("ACCEPT correction must use severity NONE")
        if self.action in {CorrectionAction.EDIT, CorrectionAction.ADD} and self.corrected_value is None:
            raise ValueError("Correction requires corrected_value")
        return self


class RevisionNode(StrictSchema):
    revision_id: str
    target_id: str
    target_type: str
    version: int
    value: Any
    previous_version_id: str | None = None
    correction_id: str | None = None
    revision_reason: str | None = None
    created_at: str = Field(default_factory=utc_now)
    human_modified: bool = False
    locked: bool = False


class DependencyLink(StrictSchema):
    source_id: str
    target_id: str
    relation: str


class ChangeImpact(StrictSchema):
    correction_id: str
    changed_ids: list[str]
    affected_ids: list[str]
    stale_artifacts: dict[str, ArtifactState]
    created_at: str = Field(default_factory=utc_now)


class CheckpointRecord(StrictSchema):
    checkpoint: Literal["A1", "A2", "B", "C", "FINAL"]
    status: CheckpointStatus = CheckpointStatus.NOT_STARTED
    required_object_ids: list[str] = Field(default_factory=list)
    reviewed_object_ids: list[str] = Field(default_factory=list)
    blocking_question_ids: list[str] = Field(default_factory=list)
    risk_acknowledged: bool = False
    updated_at: str = Field(default_factory=utc_now)


class ReviewImport(StrictSchema):
    case_id: str
    checkpoint: Literal["A1", "A2", "B", "C"]
    corrections: list[HumanCorrection]
    risk_acknowledged: bool = False

    @model_validator(mode="after")
    def matching_case(self):
        if any(item.case_id != self.case_id for item in self.corrections):
            raise ValueError("CORRECTION_CASE_MISMATCH")
        return self
