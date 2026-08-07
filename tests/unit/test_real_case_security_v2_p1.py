from pathlib import Path

import pytest

from patent_agent.real_case import RealCaseManager, effective_llm_mode


def test_real_case_explicit_create_ingest_and_manifest(tmp_path: Path):
    manager = RealCaseManager(tmp_path)
    manifest = manager.create("REAL-001", authorized=True)
    source = tmp_path / "explicit.md"; source.write_text("confidential synthetic fixture", encoding="utf-8")
    copied = manager.ingest("REAL-001", source)
    loaded = manager.load("REAL-001")
    assert manifest.confidential and copied.exists()
    assert len(loaded.source_paths) == 1 and str(source.resolve()) not in loaded.source_paths[0]
    assert effective_llm_mode("external-approved", loaded) == "disabled"


def test_real_case_external_llm_requires_both_policies(tmp_path: Path):
    manager = RealCaseManager(tmp_path)
    with pytest.raises(ValueError, match="EXTERNAL_LLM_REQUIRES_CASE_APPROVAL"):
        manager.create("REAL-002", authorized=True, llm_mode="external-approved")
    manifest = manager.create("REAL-003", authorized=True, llm_mode="external-approved", external_llm_approved=True)
    assert effective_llm_mode("external-approved", manifest) == "external-approved"
    with pytest.raises(PermissionError, match="REAL_CASE_LLM_BLOCKED"):
        manager.assert_llm_allowed("REAL-003", "disabled", "external-approved")


def test_real_case_never_auto_approves_and_requires_real_prefix(tmp_path: Path):
    manager = RealCaseManager(tmp_path)
    with pytest.raises(ValueError, match="start with REAL"):
        manager.create("PAT-REAL", authorized=True)
    with pytest.raises(ValueError, match="NOT_AUTHORIZED"):
        manager.create("REAL-004", authorized=False)
