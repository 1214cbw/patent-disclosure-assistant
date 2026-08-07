from __future__ import annotations

import threading
import traceback
import uuid
from pathlib import Path
from typing import Callable

from patent_agent.core.atomic import atomic_write_json, atomic_write_text
from patent_agent.core.models import utc_now


class JobManager:
    """Small persisted background-job registry for the single-user local UI."""

    def __init__(self, project_root: Path):
        self.path = Path(project_root) / "runtime" / "jobs.json"
        self._lock = threading.Lock()
        self._jobs: dict[str, dict] = self._load()
        for record in self._jobs.values():
            if record["status"] in {"QUEUED", "RUNNING"}:
                record.update(status="INTERRUPTED", message="应用重启，任务可从已保存阶段恢复。", updated_at=utc_now())
        self._save()

    def submit(self, kind: str, case_id: str, operation: Callable[[], object]) -> dict:
        job_id = f"JOB-{uuid.uuid4().hex[:10].upper()}"
        record = {
            "job_id": job_id,
            "kind": kind,
            "case_id": case_id,
            "status": "QUEUED",
            "message": "已排队",
            "result": None,
            "error_code": None,
            "created_at": utc_now(),
            "updated_at": utc_now(),
        }
        with self._lock:
            self._jobs[job_id] = record
            self._save()
        threading.Thread(target=self._run, args=(job_id, operation), daemon=True).start()
        return dict(record)

    def get(self, job_id: str) -> dict | None:
        with self._lock:
            record = self._jobs.get(job_id)
            return dict(record) if record else None

    def list(self, case_id: str | None = None) -> list[dict]:
        with self._lock:
            records = [dict(item) for item in self._jobs.values() if case_id is None or item["case_id"] == case_id]
        return sorted(records, key=lambda item: item["created_at"], reverse=True)

    def _run(self, job_id: str, operation: Callable[[], object]) -> None:
        self._update(job_id, status="RUNNING", message="正在执行")
        try:
            result = operation()
            self._update(job_id, status="COMPLETED", message="执行完成", result=str(result))
        except Exception as exc:  # persisted for UI recovery; no secret-bearing traceback is exposed
            self._update(job_id, status="FAILED", message=str(exc)[:500], error_code=type(exc).__name__)
            trace_path = self.path.parent / "job_errors" / f"{job_id}.log"
            trace_path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(trace_path, traceback.format_exc())

    def _update(self, job_id: str, **values) -> None:
        with self._lock:
            self._jobs[job_id].update(values, updated_at=utc_now())
            self._save()

    def _load(self) -> dict[str, dict]:
        if not self.path.exists():
            return {}
        import json

        return {item["job_id"]: item for item in json.loads(self.path.read_text(encoding="utf-8"))}

    def _save(self) -> None:
        atomic_write_json(self.path, list(self._jobs.values()))
