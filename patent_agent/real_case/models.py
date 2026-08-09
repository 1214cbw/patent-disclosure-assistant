from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from patent_agent.core.models import StrictSchema, utc_now
from patent_agent.human_review.models import CaseWorkflowState


class RealCaseManifest(StrictSchema):
    case_id: str
    confidential: bool = True
    authorized_for_processing: bool
    llm_mode: Literal["disabled", "local", "external-approved"] = "disabled"
    external_llm_approved: bool = False
    source_paths: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)
    current_checkpoint: Literal["A1", "A2", "B", "C", "FINAL"] = "A1"
    case_state: CaseWorkflowState = CaseWorkflowState.INGESTED
    synthetic: bool = False
    paper_title: str = "UNKNOWN"
    publication_status: Literal["UNKNOWN", "UNPUBLISHED", "PREPRINT", "PUBLISHED", "ACCEPTED"] = "UNKNOWN"
    first_public_date: str = "UNKNOWN"
    doi: str = "UNKNOWN"
    preprint_status: Literal["UNKNOWN", "YES", "NO"] = "UNKNOWN"
    patent_filed_before_publication: Literal["UNKNOWN", "YES", "NO", "NOT_APPLICABLE"] = "UNKNOWN"
    publication_review_status: Literal["UNREVIEWED", "CONFIRMED"] = "UNREVIEWED"
    # V6.5: project-level model selection
    llm_model: str = ""  # Empty = use system default
    # V7: language contract - source language(s) vs. patent output language.
    # Patent deliverables are ALWAYS Chinese (PATENT_OUTPUT_LANGUAGE=zh-CN)
    # regardless of source language; translation_postprocess_used documents
    # that Chinese was generated natively (True would mean post-hoc
    # translation happened, which V7 forbids for real cases).
    source_languages: list[str] = Field(default_factory=list)
    patent_output_language: str = "zh-CN"
    disclosure_language: str = "zh-CN"
    translation_postprocess_used: bool = False
    # Append-only delivery-state evidence. ``case_state`` is the current
    # state; this list records the V7.1 validation sequence.
    state_history: list[str] = Field(default_factory=list)
    delivery_version: str = ""

    @model_validator(mode="after")
    def safe_policy(self):
        if not self.authorized_for_processing:
            raise ValueError("REAL_CASE_PROCESSING_NOT_AUTHORIZED")
        if self.llm_mode == "external-approved" and not self.external_llm_approved:
            raise ValueError("EXTERNAL_LLM_REQUIRES_CASE_APPROVAL")
        if not self.synthetic and not self.case_id.startswith("REAL-"):
            raise ValueError("Real case id must start with REAL-")
        return self
