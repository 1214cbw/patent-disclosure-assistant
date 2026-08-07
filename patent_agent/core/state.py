from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from .models import PatentCase, StageVersion, utc_now


CASE_DIRS = ("source", "working", "figures", "search", "drafts", "review", "output", "logs")


class CaseStore:
    def __init__(self, workspace_root: Path):
        self.root = Path(workspace_root) / "cases"
        self.root.mkdir(parents=True, exist_ok=True)

    def case_dir(self, case_id: str) -> Path:
        return self.root / case_id

    def create(self, case_id: str, title: str = "") -> PatentCase:
        path = self.case_dir(case_id)
        path.mkdir(parents=True, exist_ok=True)
        for name in CASE_DIRS:
            (path / name).mkdir(exist_ok=True)
        case = PatentCase(case_id=case_id, title=title)
        self.save_case(case)
        return case

    def load(self, case_id: str) -> PatentCase:
        return PatentCase.model_validate_json((self.case_dir(case_id) / "case.json").read_text(encoding="utf-8"))

    def save_case(self, case: PatentCase) -> None:
        case.updated_at = utc_now()
        (self.case_dir(case.case_id) / "case.json").write_text(case.model_dump_json(indent=2), encoding="utf-8")

    def save_stage(self, case_id: str, stage: str, payload: Any) -> Path:
        case = self.load(case_id)
        version = 1 + max((v.version for v in case.versions if v.stage == stage), default=0)
        stage_dir = self.case_dir(case_id) / "working" / stage
        stage_dir.mkdir(parents=True, exist_ok=True)
        path = stage_dir / f"v{version:03d}.json"
        if hasattr(payload, "model_dump_json"):
            text = payload.model_dump_json(indent=2)
        else:
            text = json.dumps(payload, ensure_ascii=False, indent=2)
        path.write_text(text, encoding="utf-8")
        case.current_stage = stage
        case.status = "in_progress"
        case.versions.append(StageVersion(stage=stage, version=version, path=str(path)))
        self.save_case(case)
        return path

    def latest_stage_path(self, case_id: str, stage: str) -> Path:
        case = self.load(case_id)
        versions = [v for v in case.versions if v.stage == stage]
        if not versions:
            raise FileNotFoundError(f"No artifact for stage {stage}")
        return Path(max(versions, key=lambda item: item.version).path)

    def restore_stage(self, case_id: str, stage: str, version: int) -> Path:
        case = self.load(case_id)
        selected = next((item for item in case.versions if item.stage == stage and item.version == version), None)
        if selected is None: raise FileNotFoundError(f"No {stage} version {version}")
        return self.save_stage(case_id, stage, json.loads(Path(selected.path).read_text(encoding="utf-8")))

    def approve_checkpoint(self, case_id: str, name: str, decision: str = "approve", note: str = "") -> None:
        case = self.load(case_id)
        case.checkpoints[name] = {"decision": decision, "note": note, "updated_at": utc_now()}
        self.save_case(case)

    def checkpoint_approved(self, case_id: str, name: str) -> bool:
        return self.load(case_id).checkpoints.get(name, {}).get("decision") == "approve"

    def import_source_file(self, case_id: str, source: Path) -> Path:
        target = self.case_dir(case_id) / "source" / source.name
        if source.resolve() != target.resolve():
            shutil.copy2(source, target)
        return target
