from __future__ import annotations

from typing import Any

from pydantic import Field

from patent_agent.core.models import StrictSchema, utc_now


class EvaluationSnapshot(StrictSchema):
    run_id: str
    case_id: str
    evidence_hash: str
    knowledge_schema_version: str
    prompt_versions: dict[str, str]
    provider: str
    model: str
    temperature: float | None = None
    checkpoint_starting_state: str
    created_at: str = Field(default_factory=utc_now)


class EvaluationSummary(StrictSchema):
    run_id: str
    model: str
    prompt_versions: dict[str, str]
    total_facts: int
    exact_accept: int
    minor_revision: int
    major_revision: int
    rejected: int
    omitted_important_facts: int
    technical_fact_accept_rate: float
    major_error_rate: float
    generated_candidates: int
    accepted_candidates: int
    merged_candidates: int
    rejected_candidates: int
    human_added_candidates: int
    candidate_precision_proxy: float
    candidate_coverage_proxy: float
    claim_features_proposed: int
    claim_features_accepted: int
    claim_features_removed: int
    claim_features_modified: int
    claim_features_added_by_human: int
    claim_feature_acceptance: float
    unsupported_feature_rate: float
    unnecessary_narrowing_rate: float
    missing_core_feature_rate: float
    human_correction_count: int
    llm_calls: int
    input_tokens: int
    output_tokens: int
    estimated_cost: float | str = "unknown"
    metadata: dict[str, Any] = Field(default_factory=dict)
