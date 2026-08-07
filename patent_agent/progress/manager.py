from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from patent_agent.core.atomic import atomic_write_text
from patent_agent.core.models import utc_now


ProgressStatus = Literal["NOT_STARTED", "STARTED", "COMPLETED", "FAILED", "WAITING_FOR_HUMAN_REVIEW", "READY_TO_RESUME", "ABANDONED"]


class ProgressRecord(BaseModel):
    schema_version: str = "2.0"
    task: str
    phase: str = ""
    subphase: str = ""
    status: ProgressStatus = "NOT_STARTED"
    last_completed_step: str = ""
    next_step: str = ""
    git_commit: str = ""
    tests_last_run: str = ""
    updated_at: str = Field(default_factory=utc_now)
    blocking_reason: str | None = None
    case_id: str | None = None
    error_code: str | None = None
    attempts: int = 0
    stage_states: dict[str, str] = Field(default_factory=dict)


class ProgressManager:
    def __init__(self, project_root: Path):
        self.root = Path(project_root) / "runtime" / "progress"
        self.root.mkdir(parents=True, exist_ok=True)
        self.latest_path = self.root / "latest_checkpoint.json"
        self.global_path = self.root / "global_progress.json"

    def path_for(self, case_id: str | None = None) -> Path:
        return self.root / f"{case_id}.json" if case_id else self.global_path

    def load(self, case_id: str | None = None) -> ProgressRecord | None:
        path = self.path_for(case_id)
        return ProgressRecord.model_validate_json(path.read_text(encoding="utf-8")) if path.exists() else None

    def latest(self) -> ProgressRecord | None:
        return ProgressRecord.model_validate_json(self.latest_path.read_text(encoding="utf-8")) if self.latest_path.exists() else None

    def save(self, record: ProgressRecord) -> ProgressRecord:
        record.updated_at = utc_now()
        text = record.model_dump_json(indent=2)
        atomic_write_text(self.path_for(record.case_id), text)
        atomic_write_text(self.latest_path, text)
        if record.case_id is None:
            atomic_write_text(self.global_path, text)
        return record

    def start(self, *, task: str, phase: str, subphase: str, next_step: str, git_commit: str = "", case_id: str | None = None) -> ProgressRecord:
        previous = self.load(case_id)
        record = ProgressRecord(
            task=task,
            phase=phase,
            subphase=subphase,
            status="STARTED",
            last_completed_step=previous.last_completed_step if previous else "",
            next_step=next_step,
            git_commit=git_commit,
            tests_last_run=previous.tests_last_run if previous else "",
            case_id=case_id,
            attempts=(previous.attempts if previous else 0) + 1,
            stage_states=dict(previous.stage_states) if previous else {},
        )
        record.stage_states[subphase] = "STARTED"
        return self.save(record)

    def update(self, record: ProgressRecord, **changes) -> ProgressRecord:
        updated = record.model_copy(update=changes)
        return self.save(updated)

    def complete(self, record: ProgressRecord, *, completed_step: str, next_step: str, tests: str = "", git_commit: str = "") -> ProgressRecord:
        stages = dict(record.stage_states)
        stages[record.subphase] = "COMPLETED"
        return self.update(record, status="COMPLETED", last_completed_step=completed_step, next_step=next_step, tests_last_run=tests or record.tests_last_run, git_commit=git_commit or record.git_commit, blocking_reason=None, error_code=None, stage_states=stages)

    def fail(self, record: ProgressRecord, *, error_code: str, reason: str) -> ProgressRecord:
        stages = dict(record.stage_states)
        stages[record.subphase] = "FAILED"
        return self.update(record, status="FAILED", error_code=error_code, blocking_reason=reason, stage_states=stages)

    def wait_for_human(self, record: ProgressRecord, *, reason: str, next_step: str) -> ProgressRecord:
        stages = dict(record.stage_states)
        stages[record.subphase] = "WAITING_FOR_HUMAN_REVIEW"
        return self.update(record, status="WAITING_FOR_HUMAN_REVIEW", blocking_reason=reason, next_step=next_step, stage_states=stages)

    def resume(self, case_id: str | None = None) -> ProgressRecord:
        record = self.load(case_id) if case_id else self.latest()
        if record is None:
            raise FileNotFoundError("NO_RESUMABLE_PROGRESS")
        if record.status == "WAITING_FOR_HUMAN_REVIEW":
            return record
        if record.status in {"FAILED", "STARTED"}:
            return self.update(record, status="READY_TO_RESUME", blocking_reason=None)
        return record

    def abandon(self, case_id: str | None = None) -> ProgressRecord:
        record = self.load(case_id) if case_id else self.latest()
        if record is None:
            raise FileNotFoundError("NO_RESUMABLE_PROGRESS")
        return self.update(record, status="ABANDONED", next_step="", blocking_reason=None)

    def summary(self, case_id: str | None = None) -> dict:
        record = self.load(case_id) if case_id else self.latest()
        if record is None:
            return {"status": "NOT_STARTED", "message": "No resumable task"}
        return json.loads(record.model_dump_json())
