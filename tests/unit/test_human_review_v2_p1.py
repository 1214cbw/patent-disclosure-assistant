from pathlib import Path

import pytest
from pydantic import ValidationError

from patent_agent.agents import DeterministicGroundedAnalyzer
from patent_agent.core.models import EvidenceStatus, ReviewStatus
from patent_agent.core.state import CaseStore
from patent_agent.evidence import EvidenceStore
from patent_agent.human_review import (
    CheckpointStateMachine,
    CheckpointStatus,
    CorrectionAction,
    DependencyGraph,
    HumanCorrection,
    HumanCorrectionEngine,
    HumanReviewManager,
    RevisionSeverity,
    ReviewImport,
)
from patent_agent.ingestion import SourceManager


def _understanding(tmp_path: Path):
    store = CaseStore(tmp_path / "workspace"); store.create("PAT-HUMAN-001")
    source = tmp_path / "material.md"; source.write_text("# 技术方案\n状态采集单元输出温度特征。", encoding="utf-8")
    _, chunks, _ = SourceManager(store).ingest("PAT-HUMAN-001", [source])
    evidence = EvidenceStore(store.case_dir("PAT-HUMAN-001") / "evidence")
    return store, evidence, DeterministicGroundedAnalyzer().run(chunks, evidence)


def test_human_correction_requires_confirmation():
    with pytest.raises(ValidationError, match="EXPLICIT_CONFIRMATION"):
        HumanCorrection(correction_id="HC-1", case_id="PAT-X", target_type="fact", target_id="F-1", action="ACCEPT", confirmed_by_user=False)


def test_human_edit_becomes_confirmed_locked_and_versions(tmp_path: Path):
    store, evidence, understanding = _understanding(tmp_path)
    fact = understanding.facts[0]
    correction = HumanCorrection(correction_id="HC-001", case_id="PAT-HUMAN-001", target_type="fact", target_id=fact.fact_id, original_value=fact.statement, corrected_value="状态采集单元输出温度与压力融合特征。", action=CorrectionAction.EDIT, severity=RevisionSeverity.MAJOR, reason="发明人补充压力通道")
    engine = HumanCorrectionEngine(store.case_dir("PAT-HUMAN-001"))
    revised, impact = engine.apply_fact(understanding, correction, evidence)
    updated = revised.facts[0]
    assert updated.status == EvidenceStatus.HUMAN_CONFIRMED
    assert updated.review_status == ReviewStatus.LOCKED and updated.locked
    assert updated.evidence_ids == fact.evidence_ids  # retained only as partial provenance, not SOURCE_FACT
    assert "candidate" in impact.affected_ids and impact.stale_artifacts
    assert (store.case_dir("PAT-HUMAN-001") / "review" / "revision_graph.json").exists()
    assert "statement" not in (store.case_dir("PAT-HUMAN-001") / "review" / "human_audit.jsonl").read_text(encoding="utf-8")
    with pytest.raises(PermissionError, match="HUMAN_LOCKED"):
        engine.apply_fact(revised, correction.model_copy(update={"correction_id": "HC-002"}), evidence)


def test_dependency_graph_respects_locked_downstream():
    graph = DependencyGraph.standard(); graph.lock("claim")
    correction = HumanCorrection(correction_id="HC-2", case_id="PAT-X", target_type="fact", target_id="FACT-1", action="EDIT", corrected_value="x", severity="MINOR")
    impact = graph.invalidate(correction, ["FACT-1"])
    assert graph.states["claim"].value == "LOCKED"
    assert graph.states["candidate"].value == "STALE"
    assert "scope_review" in impact.affected_ids


def test_checkpoint_state_machine_order_and_completion():
    machine = CheckpointStateMachine(); machine.configure("A1", ["F1", "F2"])
    machine.transition("A1", CheckpointStatus.GENERATED); machine.transition("A1", CheckpointStatus.UNDER_REVIEW)
    with pytest.raises(ValueError, match="HUMAN_REVIEW_INCOMPLETE"):
        machine.transition("A1", CheckpointStatus.APPROVED, reviewed_ids=["F1"])
    machine.transition("A1", CheckpointStatus.APPROVED, reviewed_ids=["F1", "F2"])
    machine.configure("B", ["BF1"]); machine.transition("B", CheckpointStatus.GENERATED); machine.transition("B", CheckpointStatus.UNDER_REVIEW)
    with pytest.raises(ValueError, match="CHECKPOINT_ORDER_VIOLATION"):
        machine.transition("B", CheckpointStatus.APPROVED, reviewed_ids=["BF1"])


def test_incremental_review_import_accumulates_reviewed_ids(tmp_path: Path):
    manager = HumanReviewManager(tmp_path / "REAL-TEST")
    manager.export_review("A1", [{"fact_id": "F1"}, {"fact_id": "F2"}])
    for index, fact_id in enumerate(("F1", "F2"), 1):
        correction = HumanCorrection(
            correction_id=f"HC-{index}",
            case_id="REAL-TEST",
            target_type="fact",
            target_id=fact_id,
            action="ACCEPT",
        )
        path = tmp_path / f"review-{index}.json"
        path.write_text(
            ReviewImport(case_id="REAL-TEST", checkpoint="A1", corrections=[correction]).model_dump_json(),
            encoding="utf-8",
        )
        manager.import_review(path)
    assert manager.machine.records["A1"].reviewed_object_ids == ["F1", "F2"]


def test_regenerated_review_resets_prior_approval(tmp_path: Path):
    manager = HumanReviewManager(tmp_path / "REAL-REGEN")
    manager.export_review("A1", [{"fact_id": "F1"}])
    manager.machine.transition("A1", CheckpointStatus.UNDER_REVIEW)
    manager.machine.transition("A1", CheckpointStatus.APPROVED, reviewed_ids=["F1"])
    manager.machine.save(manager.state_path)

    manager.export_review("A1", [{"fact_id": "F2"}])

    record = manager.machine.records["A1"]
    assert record.status == CheckpointStatus.GENERATED
    assert record.required_object_ids == ["F2"]
    assert record.reviewed_object_ids == []
