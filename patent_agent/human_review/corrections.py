from __future__ import annotations

import hashlib
import json
from pathlib import Path

from patent_agent.core.models import EvidenceStatus, ReviewStatus, TechnicalFact, TechnicalUnderstandingResult, utc_now
from patent_agent.evidence.validation import _semantic_tokens

from .dependency import DependencyGraph, render_change_impact_markdown
from .models import CorrectionAction, HumanCorrection, RevisionNode


class HumanCorrectionEngine:
    def __init__(self, case_dir: Path, dependency_graph: DependencyGraph | None = None):
        self.case_dir = Path(case_dir)
        self.review_dir = self.case_dir / "review"
        self.review_dir.mkdir(parents=True, exist_ok=True)
        graph_path = self.review_dir / "dependency_graph.json"
        self.graph = DependencyGraph.load(graph_path) if graph_path.exists() else (dependency_graph or DependencyGraph.standard())
        self.graph_path = graph_path

    def apply_fact(self, understanding: TechnicalUnderstandingResult, correction: HumanCorrection, evidence_store) -> tuple[TechnicalUnderstandingResult, object]:
        if correction.target_type not in {"fact", "technical_fact"}:
            raise ValueError("Correction target_type must be fact or technical_fact")
        facts = list(understanding.facts)
        index = next((i for i, item in enumerate(facts) if item.fact_id == correction.target_id), None)
        if index is None and correction.action != CorrectionAction.ADD:
            raise KeyError(f"Unknown fact: {correction.target_id}")
        if correction.action == CorrectionAction.ADD:
            payload = correction.corrected_value if isinstance(correction.corrected_value, dict) else {"statement": str(correction.corrected_value), "category": "human_added"}
            fact = TechnicalFact(fact_id=correction.target_id, statement=payload["statement"], category=payload.get("category", "human_added"), evidence_ids=payload.get("evidence_ids", []), status=EvidenceStatus.HUMAN_CONFIRMED, confidence=1.0)
            original = None
        else:
            fact = facts[index]
            original = fact.model_dump()
            if fact.locked and correction.action != CorrectionAction.UNLOCK:
                raise PermissionError(f"HUMAN_LOCKED: {fact.fact_id}; explicit UNLOCK required")
        if correction.action == CorrectionAction.UNLOCK:
            revised = fact.model_copy(update={"locked": False, "review_status": ReviewStatus.EDITED, "reviewed_at": utc_now()})
            self.graph.unlock(fact.fact_id)
        elif correction.action == CorrectionAction.ACCEPT:
            revised = fact.model_copy(update={"review_status": ReviewStatus.LOCKED if correction.lock_after_apply else ReviewStatus.ACCEPTED, "locked": correction.lock_after_apply, "confirmation_id": correction.correction_id, "correction_id": correction.correction_id, "reviewed_at": utc_now()})
        elif correction.action in {CorrectionAction.REJECT, CorrectionAction.DELETE}:
            revised = fact.model_copy(update={"review_status": ReviewStatus.REJECTED, "human_modified": True, "locked": True, "correction_id": correction.correction_id, "revision_reason": correction.reason, "reviewed_at": utc_now()})
        else:
            statement = correction.corrected_value["statement"] if isinstance(correction.corrected_value, dict) else str(correction.corrected_value)
            evidence_ids = list(fact.evidence_ids)
            fully_supported = _supported(statement, evidence_ids, evidence_store)
            status = fact.status if fully_supported and fact.status == EvidenceStatus.SOURCE_FACT else EvidenceStatus.HUMAN_CONFIRMED
            revised = fact.model_copy(update={"statement": statement, "status": status, "confidence": 1.0, "review_status": ReviewStatus.LOCKED if correction.lock_after_apply else ReviewStatus.EDITED, "human_modified": True, "locked": correction.lock_after_apply, "confirmation_id": correction.correction_id, "correction_id": correction.correction_id, "revision_reason": correction.reason, "reviewed_at": utc_now()})
        revision = self._append_revision(correction, original, revised.model_dump())
        revised = revised.model_copy(update={"revision_id": revision.revision_id, "previous_version_id": revision.previous_version_id})
        if correction.action == CorrectionAction.ADD:
            facts.append(revised)
        else:
            facts[index] = revised
        if revised.locked:
            self.graph.lock(revised.fact_id)
        self._save_correction(correction)
        impact = self.graph.invalidate(correction, [revised.fact_id])
        self.graph.save(self.graph_path)
        (self.review_dir / "change_impact_report.md").write_text(render_change_impact_markdown(impact), encoding="utf-8")
        self._audit(correction, revised)
        return understanding.model_copy(update={"facts": facts}), impact

    def record_generic(self, correction: HumanCorrection, changed_ids: list[str]):
        self._save_correction(correction)
        impact = self.graph.invalidate(correction, changed_ids)
        self.graph.save(self.graph_path)
        (self.review_dir / "change_impact_report.md").write_text(render_change_impact_markdown(impact), encoding="utf-8")
        payload = json.dumps(correction.corrected_value, ensure_ascii=False, sort_keys=True, default=str)
        record = {"who": correction.actor, "action": correction.action.value, "target": correction.target_id, "timestamp": correction.created_at, "content_hash": hashlib.sha256(payload.encode("utf-8")).hexdigest()}
        with (self.review_dir / "human_audit.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        return impact

    def _append_revision(self, correction: HumanCorrection, original, corrected) -> RevisionNode:
        path = self.review_dir / "revision_graph.json"
        nodes = [RevisionNode.model_validate(item) for item in json.loads(path.read_text(encoding="utf-8"))] if path.exists() else []
        previous = next((item for item in reversed(nodes) if item.target_id == correction.target_id), None)
        version = 1 + max((item.version for item in nodes if item.target_id == correction.target_id), default=0)
        if previous is None and original is not None:
            previous = RevisionNode(revision_id=f"{correction.target_id}-v001", target_id=correction.target_id, target_type=correction.target_type, version=1, value=original)
            nodes.append(previous); version = 2
        node = RevisionNode(revision_id=f"{correction.target_id}-v{version:03d}", target_id=correction.target_id, target_type=correction.target_type, version=version, value=corrected, previous_version_id=previous.revision_id if previous else None, correction_id=correction.correction_id, revision_reason=correction.reason, human_modified=True, locked=correction.lock_after_apply)
        nodes.append(node)
        path.write_text(json.dumps([item.model_dump(mode="json") for item in nodes], ensure_ascii=False, indent=2), encoding="utf-8")
        return node

    def _save_correction(self, correction: HumanCorrection) -> None:
        path = self.review_dir / "human_corrections.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(correction.model_dump_json() + "\n")

    def _audit(self, correction: HumanCorrection, revised: TechnicalFact) -> None:
        record = {"who": correction.actor, "action": correction.action.value, "target": correction.target_id, "timestamp": correction.created_at, "content_hash": hashlib.sha256(revised.statement.encode("utf-8")).hexdigest()}
        with (self.review_dir / "human_audit.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _supported(statement: str, evidence_ids: list[str], evidence_store) -> bool:
    if not evidence_ids:
        return False
    source_tokens = set()
    for identifier in evidence_ids:
        if not evidence_store.contains(identifier):
            return False
        source_tokens |= _semantic_tokens(evidence_store.get(identifier).normalized_text)
    target = _semantic_tokens(statement)
    # Human edits keep SOURCE_FACT only when almost the entire edited statement is
    # already present in the cited source. New technical concepts must remain a
    # HUMAN_CONFIRMED assertion instead of inheriting evidence by proximity.
    return bool(target) and len(target & source_tokens) / len(target) >= 0.90
