import json
from pathlib import Path

from patent_agent.core.config import Settings
from patent_agent.core.models import GroundedClaimSet, TechnicalUnderstandingResult
from patent_agent.human_review import HumanCorrection, HumanReviewManager
from patent_agent.real_case import RealCaseManager
from patent_agent.workflow import RealCaseWorkflow


def _write_review(path: Path, case_id: str, checkpoint: str, corrections: list[HumanCorrection], risk=False):
    path.write_text(json.dumps({"schema_version": "2.0", "case_id": case_id, "checkpoint": checkpoint, "corrections": [item.model_dump(mode="json") for item in corrections], "risk_acknowledged": risk}, ensure_ascii=False, indent=2), encoding="utf-8")


def test_a1_to_c_human_correction_and_minimal_regeneration(tmp_path: Path):
    project = Path(__file__).resolve().parents[2]
    settings = Settings(project_root=tmp_path, workspace_root=tmp_path / "workspace", template_root=project / "templates", output_root=tmp_path / "output")
    manager = RealCaseManager(tmp_path); case_id = "REAL-SYN-P1"
    manager.create(case_id, authorized=True)
    manager.ingest(case_id, project / "demo" / "motor_control" / "materials")
    workflow = RealCaseWorkflow(settings)

    a1 = workflow.run_a1(case_id)
    understanding = TechnicalUnderstandingResult.model_validate_json(workflow.store.latest_stage_path(case_id, "p1_technical_understanding").read_text(encoding="utf-8"))
    corrections = []
    for index, fact in enumerate(understanding.facts):
        if index == 0:
            corrections.append(HumanCorrection(correction_id="A1-EDIT", case_id=case_id, target_type="fact", target_id=fact.fact_id, action="EDIT", corrected_value=fact.statement + "（人工确认术语）", severity="MINOR", reason="术语确认"))
        else:
            corrections.append(HumanCorrection(correction_id=f"A1-ACCEPT-{index}", case_id=case_id, target_type="fact", target_id=fact.fact_id, action="ACCEPT"))
    review_file = a1 / "human_review.json"; _write_review(review_file, case_id, "A1", corrections)
    workflow.import_review(case_id, review_file); workflow.approve(case_id, "A1")
    a2 = workflow.continue_case(case_id)
    candidates = json.loads(workflow.store.latest_stage_path(case_id, "p1_invention_candidates").read_text(encoding="utf-8"))
    a2_corrections = [HumanCorrection(correction_id=f"A2-{i}", case_id=case_id, target_type="candidate", target_id=item["candidate_id"], action="ACCEPT") for i, item in enumerate(candidates, 1)]
    review_file = a2 / "human_review.json"; _write_review(review_file, case_id, "A2", a2_corrections)
    workflow.import_review(case_id, review_file); workflow.approve(case_id, "A2")

    b = workflow.continue_case(case_id, project / "demo" / "motor_control" / "prior_art_demo.json")
    required = HumanReviewManager(manager.case_dir(case_id)).machine.records["B"].required_object_ids
    b_corrections = [HumanCorrection(correction_id=f"B-{item}", case_id=case_id, target_type="strategy", target_id=item, action="EDIT" if item == "scope_strategy" else "ACCEPT", corrected_value="Balanced" if item == "scope_strategy" else None, severity="MINOR" if item == "scope_strategy" else "NONE") for item in required]
    review_file = b / "human_review.json"; _write_review(review_file, case_id, "B", b_corrections)
    workflow.import_review(case_id, review_file)
    questions = json.loads((manager.case_dir(case_id) / "review" / "inventor_questions.json").read_text(encoding="utf-8"))
    for item in questions:
        if item["priority"] == "P0" and not item["answered"]: workflow.answer_inventor_question(case_id, item["question_id"], "合成测试人工确认")
    workflow.approve(case_id, "B")

    c = workflow.continue_case(case_id)
    claims = GroundedClaimSet.model_validate_json(workflow.store.latest_stage_path(case_id, "p1_claims").read_text(encoding="utf-8")); features = claims.claims[0].features
    c_corrections = []
    for feature in features[:-1]: c_corrections.append(HumanCorrection(correction_id=f"C-A-{feature.feature_id}", case_id=case_id, target_type="claim_feature", target_id=feature.feature_id, action="ACCEPT"))
    c_corrections.append(HumanCorrection(correction_id="C-REMOVE", case_id=case_id, target_type="claim_feature", target_id=features[-1].feature_id, action="DELETE", corrected_value={"claim_number": 1}, severity="REJECT", reason="移至说明书实施例"))
    review_file = c / "human_review.json"; _write_review(review_file, case_id, "C", c_corrections, risk=True)
    workflow.import_review(case_id, review_file)
    revised = GroundedClaimSet.model_validate_json(workflow.store.latest_stage_path(case_id, "p1_claims").read_text(encoding="utf-8"))
    assert features[-1].feature_id not in {item.feature_id for item in revised.claims[0].features}
    assert features[-1].text not in revised.claims[0].rendered_text
    workflow.approve(case_id, "C", risk_acknowledged=True)
    assert HumanReviewManager(manager.case_dir(case_id)).machine.records["C"].status.value == "APPROVED"
    assert (c / "claims_support_matrix.md").exists() and (c / "claim_scope_risk.md").exists()
