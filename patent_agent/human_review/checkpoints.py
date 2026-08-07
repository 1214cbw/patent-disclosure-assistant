from __future__ import annotations

import json
from pathlib import Path

from patent_agent.core.models import ReviewStatus, utc_now

from .models import CheckpointRecord, CheckpointStatus, ReviewImport
from patent_agent.core.atomic import atomic_write_json


ORDER = ["A1", "A2", "B", "C", "FINAL"]
ALLOWED = {
    CheckpointStatus.NOT_STARTED: {CheckpointStatus.GENERATED},
    CheckpointStatus.GENERATED: {CheckpointStatus.UNDER_REVIEW, CheckpointStatus.BLOCKED},
    CheckpointStatus.UNDER_REVIEW: {CheckpointStatus.CHANGES_REQUIRED, CheckpointStatus.APPROVED, CheckpointStatus.BLOCKED},
    CheckpointStatus.CHANGES_REQUIRED: {CheckpointStatus.UNDER_REVIEW, CheckpointStatus.APPROVED, CheckpointStatus.BLOCKED},
    CheckpointStatus.BLOCKED: {CheckpointStatus.UNDER_REVIEW},
    CheckpointStatus.APPROVED: set(),
}


class CheckpointStateMachine:
    def __init__(self, records: dict[str, CheckpointRecord] | None = None):
        self.records = records or {name: CheckpointRecord(checkpoint=name) for name in ORDER}

    def transition(self, checkpoint: str, status: CheckpointStatus, *, reviewed_ids: list[str] | None = None, blocking_questions: list[str] | None = None, risk_acknowledged: bool | None = None) -> CheckpointRecord:
        record = self.records[checkpoint]
        if status not in ALLOWED[record.status]:
            raise ValueError(f"ILLEGAL_CHECKPOINT_TRANSITION: {checkpoint} {record.status}->{status}")
        prior = ORDER[:ORDER.index(checkpoint)]
        if status == CheckpointStatus.APPROVED and any(self.records[item].status != CheckpointStatus.APPROVED for item in prior):
            raise ValueError(f"CHECKPOINT_ORDER_VIOLATION: approve {checkpoint} requires {prior}")
        reviewed = reviewed_ids if reviewed_ids is not None else record.reviewed_object_ids
        blocking = blocking_questions if blocking_questions is not None else record.blocking_question_ids
        if status == CheckpointStatus.APPROVED:
            missing = set(record.required_object_ids) - set(reviewed)
            if missing:
                raise ValueError("HUMAN_REVIEW_INCOMPLETE: " + ", ".join(sorted(missing)))
            if blocking:
                raise ValueError("BLOCKED_BY_INVENTOR_QUESTION: " + ", ".join(blocking))
        updated = record.model_copy(update={"status": status, "reviewed_object_ids": reviewed, "blocking_question_ids": blocking, "risk_acknowledged": record.risk_acknowledged if risk_acknowledged is None else risk_acknowledged, "updated_at": utc_now()})
        self.records[checkpoint] = updated
        return updated

    def configure(self, checkpoint: str, required_ids: list[str], blocking_questions: list[str] | None = None) -> CheckpointRecord:
        record = self.records[checkpoint].model_copy(update={"required_object_ids": required_ids, "blocking_question_ids": blocking_questions or []})
        self.records[checkpoint] = record
        return record

    def save(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        return atomic_write_json(path, {key: value.model_dump(mode="json") for key, value in self.records.items()})

    @classmethod
    def load(cls, path: Path) -> "CheckpointStateMachine":
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls({key: CheckpointRecord.model_validate(value) for key, value in raw.items()})


class HumanReviewManager:
    def __init__(self, case_dir: Path):
        self.case_dir = Path(case_dir)
        self.review_dir = self.case_dir / "review"
        self.review_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.review_dir / "checkpoint_state.json"
        self.machine = CheckpointStateMachine.load(self.state_path) if self.state_path.exists() else CheckpointStateMachine()

    def export_review(self, checkpoint: str, objects: list[dict]) -> Path:
        ids = [_object_id(item) for item in objects]
        self.machine.configure(checkpoint, ids)
        if self.machine.records[checkpoint].status == CheckpointStatus.NOT_STARTED:
            self.machine.transition(checkpoint, CheckpointStatus.GENERATED)
        path = self.review_dir / f"checkpoint_{checkpoint}" / "review_input.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"schema_version": "2.0", "case_id": self.case_dir.name, "checkpoint": checkpoint, "corrections": [], "risk_acknowledged": False}
        atomic_write_json(path, payload)
        atomic_write_json(path.parent / "review_objects.json", objects)
        self.machine.save(self.state_path)
        return path

    def import_review(self, path: Path) -> ReviewImport:
        review = ReviewImport.model_validate_json(Path(path).read_text(encoding="utf-8"))
        record = self.machine.records[review.checkpoint]
        reviewed = sorted(set(record.reviewed_object_ids) | {item.target_id for item in review.corrections})
        changed = any(item.action.value not in {"ACCEPT"} for item in review.corrections)
        if record.status == CheckpointStatus.GENERATED:
            self.machine.transition(review.checkpoint, CheckpointStatus.UNDER_REVIEW, reviewed_ids=reviewed, risk_acknowledged=review.risk_acknowledged)
        else:
            self.machine.records[review.checkpoint] = record.model_copy(update={"reviewed_object_ids": reviewed, "risk_acknowledged": review.risk_acknowledged})
        if changed and self.machine.records[review.checkpoint].status != CheckpointStatus.CHANGES_REQUIRED:
            self.machine.transition(review.checkpoint, CheckpointStatus.CHANGES_REQUIRED, reviewed_ids=reviewed, risk_acknowledged=review.risk_acknowledged)
        self.machine.save(self.state_path)
        return review

    def approve(self, checkpoint: str, review_statuses: dict[str, ReviewStatus], *, blocking_questions: list[str] | None = None, scope_warning: bool = False, risk_acknowledged: bool = False) -> CheckpointRecord:
        existing_reviewed = self.machine.records[checkpoint].reviewed_object_ids
        reviewed = sorted(set(existing_reviewed) | {identifier for identifier, status in review_statuses.items() if status != ReviewStatus.UNREVIEWED})
        if scope_warning and not risk_acknowledged:
            raise ValueError("WARNING_REQUIRES_ACK")
        record = self.machine.records[checkpoint]
        if record.status in {CheckpointStatus.GENERATED, CheckpointStatus.BLOCKED}:
            self.machine.transition(checkpoint, CheckpointStatus.UNDER_REVIEW)
        updated = self.machine.transition(checkpoint, CheckpointStatus.APPROVED, reviewed_ids=reviewed, blocking_questions=blocking_questions or [], risk_acknowledged=risk_acknowledged)
        self.machine.save(self.state_path)
        return updated


def _object_id(value: dict) -> str:
    for key in ("fact_id", "candidate_id", "feature_id", "concept_id", "paragraph_id", "equation_id", "id"):
        if key in value:
            return str(value[key])
    raise ValueError("Review object has no stable id")
