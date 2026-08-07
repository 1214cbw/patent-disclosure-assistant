from __future__ import annotations

import json
import shutil
from pathlib import Path

from patent_agent.core.models import utc_now
from patent_agent.core.state import CaseStore

from .models import RealCaseManifest
from patent_agent.core.atomic import atomic_write_text


def effective_llm_mode(global_mode: str, manifest: RealCaseManifest) -> str:
    """Return the most restrictive compatible policy; ambiguous combinations disable LLM."""
    if global_mode == "disabled" or manifest.llm_mode == "disabled":
        return "disabled"
    if global_mode == manifest.llm_mode == "local":
        return "local"
    if global_mode == manifest.llm_mode == "external-approved" and manifest.external_llm_approved:
        return "external-approved"
    return "disabled"


class RealCaseManager:
    """Explicit-path-only confidential case store. It never scans for source material."""

    def __init__(self, project_root: Path):
        self.project_root = Path(project_root)
        self.workspace_root = self.project_root / "workspace"
        self.root = self.workspace_root / "private_cases"
        self.root.mkdir(parents=True, exist_ok=True)
        self.case_store = CaseStore(self.workspace_root, "private_cases")

    def case_dir(self, case_id: str) -> Path:
        return self.root / case_id

    def manifest_path(self, case_id: str) -> Path:
        return self.case_dir(case_id) / "real_case_manifest.json"

    def create(self, case_id: str, *, authorized: bool, llm_mode: str = "disabled", external_llm_approved: bool = False, synthetic: bool = False, title: str = "[待发明人确认]") -> RealCaseManifest:
        manifest = RealCaseManifest(case_id=case_id, authorized_for_processing=authorized, llm_mode=llm_mode, external_llm_approved=external_llm_approved, synthetic=synthetic)
        case_dir = self.case_dir(case_id)
        if not (case_dir / "case.json").exists():
            self.case_store.create(case_id, title)
        for name in ("source", "evidence", "working", "review", "output", "logs", "evaluation_runs"):
            (case_dir / name).mkdir(parents=True, exist_ok=True)
        self.save(manifest)
        return manifest

    def load(self, case_id: str) -> RealCaseManifest:
        return RealCaseManifest.model_validate_json(self.manifest_path(case_id).read_text(encoding="utf-8"))

    def save(self, manifest: RealCaseManifest) -> None:
        manifest.updated_at = utc_now()
        atomic_write_text(self.manifest_path(manifest.case_id), manifest.model_dump_json(indent=2))

    def ingest(self, case_id: str, source: Path) -> Path:
        manifest = self.load(case_id)
        source = Path(source).resolve()
        if not source.exists():
            raise FileNotFoundError(f"Explicit real-case source does not exist: {source}")
        target = self.case_dir(case_id) / "source" / source.name
        if source != target.resolve():
            if source.is_dir():
                if target.exists(): raise FileExistsError(f"Real-case source already ingested: {target.name}")
                shutil.copytree(source, target)
            else:
                shutil.copy2(source, target)
        original_hash = _hash_path(source)
        entry = json.dumps({"name": source.name, "sha256": original_hash}, ensure_ascii=False, sort_keys=True)
        if entry not in manifest.source_paths:
            manifest.source_paths.append(entry)
        self.save(manifest)
        return target

    def assert_llm_allowed(self, case_id: str, global_mode: str, requested_mode: str) -> str:
        manifest = self.load(case_id)
        effective = effective_llm_mode(global_mode, manifest)
        if requested_mode != effective or effective == "disabled":
            raise PermissionError(f"REAL_CASE_LLM_BLOCKED: global={global_mode}, case={manifest.llm_mode}, effective={effective}")
        return effective


def _hash_path(path: Path) -> str:
    import hashlib
    digest = hashlib.sha256()
    files = sorted(item for item in path.rglob("*") if item.is_file()) if path.is_dir() else [path]
    for item in files:
        digest.update(item.relative_to(path).as_posix().encode("utf-8") if path.is_dir() else item.name.encode("utf-8"))
        with item.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()
