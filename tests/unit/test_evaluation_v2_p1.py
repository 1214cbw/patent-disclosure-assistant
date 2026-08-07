from pathlib import Path

from patent_agent.core.models import ClaimFeature, GroundedClaimSet, PatentClaimV2
from patent_agent.evaluation import ModelEvaluationEngine
from patent_agent.human_review import HumanCorrection
from patent_agent.review.claim_scope import ClaimScopeAssessment, ClaimScopeReview


def test_evaluation_metrics_and_immutable_snapshot(tmp_path: Path):
    evidence = tmp_path / "chunks.jsonl"; evidence.write_text("synthetic evidence snapshot", encoding="utf-8")
    engine = ModelEvaluationEngine()
    snapshot = engine.create_snapshot(run_id="RUN-001", case_id="SYN-P1", evidence_file=evidence, prompt_versions={"technical": "v2.2"}, provider="mock", model="synthetic", checkpoint_starting_state="A1_REVIEW")
    corrections = [
        HumanCorrection(correction_id="H1", case_id="SYN-P1", target_type="fact", target_id="F1", action="ACCEPT"),
        HumanCorrection(correction_id="H2", case_id="SYN-P1", target_type="fact", target_id="F2", action="EDIT", corrected_value="minor", severity="MINOR"),
        HumanCorrection(correction_id="H3", case_id="SYN-P1", target_type="fact", target_id="F3", action="EDIT", corrected_value="major", severity="MAJOR"),
        HumanCorrection(correction_id="H4", case_id="SYN-P1", target_type="fact", target_id="F4", action="REJECT", severity="REJECT"),
        HumanCorrection(correction_id="H5", case_id="SYN-P1", target_type="fact", target_id="F5", action="ADD", corrected_value="omission", severity="MAJOR"),
        HumanCorrection(correction_id="C1", case_id="SYN-P1", target_type="candidate", target_id="I1", action="MERGE", corrected_value={"with": "I2"}, severity="MINOR"),
        HumanCorrection(correction_id="CF1", case_id="SYN-P1", target_type="claim_feature", target_id="CF1", action="ACCEPT"),
        HumanCorrection(correction_id="CF2", case_id="SYN-P1", target_type="claim_feature", target_id="CF2", action="DELETE", severity="REJECT"),
    ]
    feature = ClaimFeature(feature_id="CF1", text="supported", source_fact_ids=["F1"], evidence_ids=["EV1"], support_status="SUPPORTED", mandatory=True)
    claims = GroundedClaimSet(title="x", claims=[PatentClaimV2(claim_number=1, claim_type="method", features=[feature], rendered_text="x")])
    scope = ClaimScopeReview(assessments=[ClaimScopeAssessment(claim_number=1, scope_level="BALANCED", mandatory_feature_count=1)], comparisons=[])
    summary = engine.evaluate(snapshot=snapshot, corrections=corrections, generated_fact_ids=["F1", "F2", "F3", "F4"], generated_candidate_ids=["I1", "I2"], proposed_feature_ids=["CF1", "CF2"], final_claims=claims, scope_review=scope)
    assert summary.technical_fact_accept_rate == .25
    assert summary.minor_revision == 1 and summary.major_revision == 1 and summary.rejected == 1
    assert summary.omitted_important_facts == 1
    assert summary.claim_feature_acceptance == .5
    run = engine.save_run(tmp_path / "runs", snapshot, summary)
    assert (run / "snapshot.json").exists() and (run / "model_evaluation_report.md").exists()
