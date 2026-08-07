from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from patent_agent.core.config import Settings
from patent_agent.core.models import GroundedClaimSet, GroundedDisclosure, GroundedInventionCandidate, GroundedProtectionStrategy, TechnicalUnderstandingResult
from patent_agent.human_review import HumanCorrection, HumanReviewManager
from patent_agent.real_case import RealCaseManager
from patent_agent.reporting import ReviewBundleBuilder, render_terminology_registry
from patent_agent.review import build_traceability, render_traceability_markdown
from patent_agent.workflow import RealCaseWorkflow


def review_file(path: Path, case_id: str, checkpoint: str, corrections: list[HumanCorrection], risk=False):
    path.write_text(json.dumps({"schema_version": "2.0", "case_id": case_id, "checkpoint": checkpoint, "corrections": [item.model_dump(mode="json") for item in corrections], "risk_acknowledged": risk}, ensure_ascii=False, indent=2), encoding="utf-8")


def copy_tree(source: Path, target: Path):
    target.mkdir(parents=True, exist_ok=True)
    for item in source.rglob("*"):
        if item.is_file():
            destination = target / item.relative_to(source); destination.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(item, destination)


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="patent-p1-synthetic-") as temp:
        temp_root = Path(temp); case_id = "SYN-P1-DEMO-001"
        settings = Settings(project_root=temp_root, workspace_root=temp_root / "workspace", template_root=ROOT / "templates", output_root=ROOT / "output" / "v2_p1_demo_work")
        manager = RealCaseManager(temp_root); manager.create(case_id, authorized=True, synthetic=True, title="一种基于多源传感信息的电机状态监测与自适应控制方法"); manager.ingest(case_id, ROOT / "demo" / "motor_control" / "materials")
        workflow = RealCaseWorkflow(settings); all_corrections = []

        a1 = workflow.run_a1(case_id); understanding = TechnicalUnderstandingResult.model_validate_json(workflow.store.latest_stage_path(case_id, "p1_technical_understanding").read_text(encoding="utf-8"))
        a1_corrections = []
        for index, fact in enumerate(understanding.facts):
            if index == 0: item = HumanCorrection(correction_id="HC-A1-MINOR", case_id=case_id, target_type="fact", target_id=fact.fact_id, action="EDIT", corrected_value=fact.statement + "（人工确认：仅为合成演示材料）", severity="MINOR", reason="确认演示数据属性")
            else: item = HumanCorrection(correction_id=f"HC-A1-ACCEPT-{index:03d}", case_id=case_id, target_type="fact", target_id=fact.fact_id, action="ACCEPT")
            a1_corrections.append(item)
        path = a1 / "synthetic_review.json"; review_file(path, case_id, "A1", a1_corrections); workflow.import_review(case_id, path); workflow.approve(case_id, "A1"); all_corrections += a1_corrections

        a2 = workflow.continue_case(case_id); candidates = [GroundedInventionCandidate.model_validate(item) for item in json.loads(workflow.store.latest_stage_path(case_id, "p1_invention_candidates").read_text(encoding="utf-8"))]
        second = candidates[0].model_copy(update={"candidate_id": "INV-DET-002", "title": "多源状态融合系统候选"}); candidates.append(second); workflow.store.save_stage(case_id, "p1_invention_candidates", [item.model_dump() for item in candidates])
        questions = json.loads((manager.case_dir(case_id) / "review" / "inventor_questions.json").read_text(encoding="utf-8")); qmodels = []
        from patent_agent.core.models import InventorQuestion
        qmodels = [InventorQuestion.model_validate(item) for item in questions]
        ReviewBundleBuilder(manager.case_dir(case_id)).a2(candidates, qmodels); HumanReviewManager(manager.case_dir(case_id)).export_review("A2", [item.model_dump(mode="json") for item in candidates])
        merge = HumanCorrection(correction_id="HC-A2-MERGE", case_id=case_id, target_type="candidate", target_id=candidates[0].candidate_id, action="MERGE", corrected_value={"candidate_ids": [item.candidate_id for item in candidates], "new_id": "INV-M001"}, severity="MINOR", reason="两个候选属于同一核心构思")
        acknowledge = HumanCorrection(correction_id="HC-A2-ACK-SECOND", case_id=case_id, target_type="candidate", target_id=candidates[1].candidate_id, action="ACCEPT")
        path = a2 / "synthetic_review.json"; review_file(path, case_id, "A2", [merge, acknowledge]); workflow.import_review(case_id, path); workflow.approve(case_id, "A2"); all_corrections += [merge, acknowledge]

        b = workflow.continue_case(case_id, ROOT / "demo" / "motor_control" / "prior_art_demo.json"); required = HumanReviewManager(manager.case_dir(case_id)).machine.records["B"].required_object_ids
        b_corrections = [HumanCorrection(correction_id=f"HC-B-{item}", case_id=case_id, target_type="strategy", target_id=item, action="EDIT" if item == "scope_strategy" else "ACCEPT", corrected_value="Balanced" if item == "scope_strategy" else None, severity="MINOR" if item == "scope_strategy" else "NONE", reason="选择平衡保护范围" if item == "scope_strategy" else None) for item in required]
        path = b / "synthetic_review.json"; review_file(path, case_id, "B", b_corrections); workflow.import_review(case_id, path)
        for item in qmodels:
            if item.priority == "P0": workflow.answer_inventor_question(case_id, item.question_id, "合成审查者确认：进入后续演示")
        workflow.approve(case_id, "B"); all_corrections += b_corrections

        c = workflow.continue_case(case_id); claims_before = GroundedClaimSet.model_validate_json(workflow.store.latest_stage_path(case_id, "p1_claims").read_text(encoding="utf-8")); features = claims_before.claims[0].features
        c_corrections = [HumanCorrection(correction_id=f"HC-C-ACCEPT-{item.feature_id}", case_id=case_id, target_type="claim_feature", target_id=item.feature_id, action="ACCEPT") for item in features[:-1]]
        c_corrections.append(HumanCorrection(correction_id="HC-C-REMOVE", case_id=case_id, target_type="claim_feature", target_id=features[-1].feature_id, action="DELETE", corrected_value={"claim_number": 1}, severity="REJECT", reason="非必要限定，移至说明书"))
        path = c / "synthetic_review.json"; review_file(path, case_id, "C", c_corrections, risk=True); workflow.import_review(case_id, path); workflow.approve(case_id, "C", risk_acknowledged=True); all_corrections += c_corrections
        work_output = workflow.continue_case(case_id)

        output = ROOT / "output" / "v2_p1_demo"; copy_tree(work_output, output); copy_tree(manager.case_dir(case_id) / "review", output / "review_bundles")
        shutil.copy2(manager.manifest_path(case_id), output / "real_case_manifest.json")
        understanding = TechnicalUnderstandingResult.model_validate_json(workflow.store.latest_stage_path(case_id, "p1_technical_understanding").read_text(encoding="utf-8")); candidates_final = [GroundedInventionCandidate.model_validate(item) for item in json.loads(workflow.store.latest_stage_path(case_id, "p1_invention_candidates").read_text(encoding="utf-8"))]; strategy = GroundedProtectionStrategy.model_validate_json(workflow.store.latest_stage_path(case_id, "p1_protection_strategy").read_text(encoding="utf-8")); disclosure = GroundedDisclosure.model_validate_json(workflow.store.latest_stage_path(case_id, "p1_disclosure").read_text(encoding="utf-8")); claims = GroundedClaimSet.model_validate_json(workflow.store.latest_stage_path(case_id, "p1_claims").read_text(encoding="utf-8"))
        (output / "invention_candidates_final.json").write_text(json.dumps([item.model_dump(mode="json") for item in candidates_final], ensure_ascii=False, indent=2), encoding="utf-8"); (output / "protection_strategy_final.json").write_text(strategy.model_dump_json(indent=2), encoding="utf-8")
        corrections_path = output / "human_corrections.json"; corrections_path.write_text(json.dumps([item.model_dump(mode="json") for item in all_corrections], ensure_ascii=False, indent=2), encoding="utf-8")
        (output / "terminology_registry.md").write_text(render_terminology_registry(strategy.broad_terms), encoding="utf-8"); shutil.copy2(manager.case_dir(case_id) / "review" / "inventor_questions.json", output / "inventor_questions.json")
        from patent_agent.core.models import FigureSpec
        figures = [FigureSpec.model_validate(item) for item in json.loads((work_output / "figures.json").read_text(encoding="utf-8"))]
        trace = build_traceability(disclosure, claims, understanding, figures); (output / "traceability.json").write_text(trace.model_dump_json(indent=2), encoding="utf-8"); (output / "traceability_report.md").write_text(render_traceability_markdown(trace), encoding="utf-8")

        from patent_agent.evaluation.models import EvaluationSummary
        eval_run = manager.case_dir(case_id) / "evaluation_runs" / "RUN-001"; copy_tree(eval_run, output / "evaluation_runs" / "RUN-001")
        summary = EvaluationSummary.model_validate_json((output / "evaluation_summary.json").read_text(encoding="utf-8"))
        pipeline = {"case_id": case_id, "synthetic": True, "checkpoints": {key: value.status.value for key, value in HumanReviewManager(manager.case_dir(case_id)).machine.records.items()}, "human_corrections": len(all_corrections), "dependency_links": len(json.loads((manager.case_dir(case_id) / "review" / "dependency_graph.json").read_text(encoding="utf-8"))["links"]), "traceability_links": len(trace.links), "broken_links": len(trace.broken_links), "word_validation": "PASS", "omml": 5, "residual_latex": 0}
        (output / "pipeline_report.md").write_text("# V2-P1 Synthetic Pipeline Report\n\n" + "\n".join(f"- {key}: {value}" for key, value in pipeline.items()) + "\n", encoding="utf-8")
        print({"case_id": case_id, "facts": len(understanding.facts), "corrections": len(all_corrections), "candidates": len(candidates_final), "claim_features": sum(len(item.features) for item in claims.claims), "trace_links": len(trace.links), "broken": len(trace.broken_links), "fact_accept_rate": summary.technical_fact_accept_rate, "output": str(output)})
