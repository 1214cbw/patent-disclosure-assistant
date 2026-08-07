from __future__ import annotations

import hashlib
import json
from pathlib import Path

from patent_agent.core.models import GroundedClaimSet
from patent_agent.human_review.models import CorrectionAction, HumanCorrection, RevisionSeverity
from patent_agent.review.claim_scope import ClaimScopeReview

from .models import EvaluationSnapshot, EvaluationSummary


class ModelEvaluationEngine:
    def create_snapshot(self, *, run_id: str, case_id: str, evidence_file: Path, prompt_versions: dict[str, str], provider: str, model: str, checkpoint_starting_state: str, temperature: float | None = None) -> EvaluationSnapshot:
        evidence_hash = hashlib.sha256(Path(evidence_file).read_bytes()).hexdigest()
        return EvaluationSnapshot(run_id=run_id, case_id=case_id, evidence_hash=evidence_hash, knowledge_schema_version="2.0", prompt_versions=prompt_versions, provider=provider, model=model, temperature=temperature, checkpoint_starting_state=checkpoint_starting_state)

    def evaluate(self, *, snapshot: EvaluationSnapshot, corrections: list[HumanCorrection], generated_fact_ids: list[str], generated_candidate_ids: list[str], proposed_feature_ids: list[str], final_claims: GroundedClaimSet, scope_review: ClaimScopeReview, llm_audit_path: Path | None = None) -> EvaluationSummary:
        fact_reviews = [item for item in corrections if item.target_type in {"fact", "technical_fact"} and item.action != CorrectionAction.ADD]
        omissions = [item for item in corrections if item.target_type in {"fact", "technical_fact"} and item.action == CorrectionAction.ADD]
        exact = sum(item.action == CorrectionAction.ACCEPT for item in fact_reviews)
        minor = sum(item.severity == RevisionSeverity.MINOR for item in fact_reviews)
        major = sum(item.severity == RevisionSeverity.MAJOR for item in fact_reviews)
        rejected = sum(item.action in {CorrectionAction.REJECT, CorrectionAction.DELETE} or item.severity == RevisionSeverity.REJECT for item in fact_reviews)
        candidate_reviews = [item for item in corrections if "candidate" in item.target_type]
        accepted_candidates = sum(item.action == CorrectionAction.ACCEPT for item in candidate_reviews)
        merged = sum(item.action == CorrectionAction.MERGE for item in candidate_reviews)
        rejected_candidates = sum(item.action in {CorrectionAction.REJECT, CorrectionAction.DELETE} for item in candidate_reviews)
        human_candidates = sum(item.action == CorrectionAction.ADD for item in candidate_reviews)
        feature_reviews = [item for item in corrections if "claim_feature" in item.target_type]
        accepted_features = sum(item.action == CorrectionAction.ACCEPT for item in feature_reviews)
        removed_features = sum(item.action in {CorrectionAction.DELETE, CorrectionAction.REJECT} for item in feature_reviews)
        modified_features = sum(item.action in {CorrectionAction.EDIT, CorrectionAction.MOVE, CorrectionAction.PROMOTE} for item in feature_reviews)
        added_features = sum(item.action == CorrectionAction.ADD for item in feature_reviews)
        final_features = [item for claim in final_claims.claims for item in claim.features]
        unsupported = sum(item.support_status == "UNSUPPORTED" for item in final_features)
        narrowing = sum(bool(item.parameter_locking_risks or item.terminology_narrowing_risks) for item in scope_review.assessments)
        missing_core = sum(bool(item.potentially_missing_core_features) for item in scope_review.assessments)
        calls, input_tokens, output_tokens, cost = _audit_totals(llm_audit_path)
        total_facts = len(generated_fact_ids)
        reviewed_features = len(feature_reviews)
        candidate_denominator = max(1, len(generated_candidate_ids))
        return EvaluationSummary(run_id=snapshot.run_id, model=snapshot.model, prompt_versions=snapshot.prompt_versions, total_facts=total_facts, exact_accept=exact, minor_revision=minor, major_revision=major, rejected=rejected, omitted_important_facts=len(omissions), technical_fact_accept_rate=_rate(exact, len(fact_reviews)), major_error_rate=_rate(major + rejected, len(fact_reviews)), generated_candidates=len(generated_candidate_ids), accepted_candidates=accepted_candidates, merged_candidates=merged, rejected_candidates=rejected_candidates, human_added_candidates=human_candidates, candidate_precision_proxy=_rate(accepted_candidates + merged, candidate_denominator), candidate_coverage_proxy=_rate(accepted_candidates + merged, candidate_denominator + human_candidates), claim_features_proposed=len(proposed_feature_ids), claim_features_accepted=accepted_features, claim_features_removed=removed_features, claim_features_modified=modified_features, claim_features_added_by_human=added_features, claim_feature_acceptance=_rate(accepted_features, reviewed_features), unsupported_feature_rate=_rate(unsupported, len(final_features)), unnecessary_narrowing_rate=_rate(narrowing, len(scope_review.assessments)), missing_core_feature_rate=_rate(missing_core, len(scope_review.assessments)), human_correction_count=len(corrections), llm_calls=calls, input_tokens=input_tokens, output_tokens=output_tokens, estimated_cost=cost)

    def save_run(self, root: Path, snapshot: EvaluationSnapshot, summary: EvaluationSummary) -> Path:
        run = Path(root) / snapshot.run_id; run.mkdir(parents=True, exist_ok=False)
        (run / "snapshot.json").write_text(snapshot.model_dump_json(indent=2), encoding="utf-8")
        (run / "evaluation_summary.json").write_text(summary.model_dump_json(indent=2), encoding="utf-8")
        (run / "technical_understanding_scorecard.md").write_text(render_technical_scorecard(summary), encoding="utf-8")
        (run / "model_evaluation_report.md").write_text(render_model_evaluation(summary), encoding="utf-8")
        return run


def _rate(value: int, total: int) -> float:
    return round(value / total, 4) if total else 0.0


def _audit_totals(path: Path | None) -> tuple[int, int, int, float | str]:
    if path is None or not path.exists(): return 0, 0, 0, "unknown"
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    input_tokens = sum(item.get("token_usage", {}).get("prompt_tokens", item.get("token_usage", {}).get("input_tokens", 0)) for item in records)
    output_tokens = sum(item.get("token_usage", {}).get("completion_tokens", item.get("token_usage", {}).get("output_tokens", 0)) for item in records)
    known = [item.get("estimated_cost") for item in records if isinstance(item.get("estimated_cost"), (int, float))]
    return len(records), input_tokens, output_tokens, round(sum(known), 8) if known and len(known) == len(records) else "unknown"


def render_technical_scorecard(item: EvaluationSummary) -> str:
    return f"""# Technical Understanding Scorecard

- Total Facts: {item.total_facts}
- Exact Accept: {item.exact_accept}
- Minor Revision: {item.minor_revision}
- Major Revision: {item.major_revision}
- Rejected: {item.rejected}
- Omitted Important Facts: {item.omitted_important_facts}
- Technical Fact Accept Rate: {item.technical_fact_accept_rate:.2%}
- Major Error Rate: {item.major_error_rate:.2%}
"""


def render_model_evaluation(item: EvaluationSummary) -> str:
    return f"""# Model Evaluation Report

- Model: {item.model}
- Prompt Versions: {json.dumps(item.prompt_versions, ensure_ascii=False)}
- Technical Fact Accept Rate: {item.technical_fact_accept_rate:.2%}
- Major Error Rate: {item.major_error_rate:.2%}
- Omission Count: {item.omitted_important_facts}
- Candidate Acceptance Proxy: {item.candidate_precision_proxy:.2%}
- Claim Feature Acceptance: {item.claim_feature_acceptance:.2%}
- Unsupported Claim Features: {item.unsupported_feature_rate:.2%}
- Human Correction Count: {item.human_correction_count}
- LLM Calls: {item.llm_calls}
- Input Tokens: {item.input_tokens}
- Output Tokens: {item.output_tokens}
- Estimated Cost: {item.estimated_cost}
"""
