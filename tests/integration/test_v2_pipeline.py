from pathlib import Path

from patent_agent.core.config import Settings
from patent_agent.llm import MockLLMProvider
from patent_agent.llm.demo_mock import SyntheticDemoResponder
from patent_agent.workflow import PatentPipelineV2


def test_v2_synthetic_e2e_without_word_com(tmp_path: Path):
    project = Path(__file__).resolve().parents[2]
    settings = Settings(project_root=tmp_path, workspace_root=tmp_path / "workspace", template_root=tmp_path / "templates", output_root=tmp_path / "output")
    output = tmp_path / "output" / "v2_demo"
    result = PatentPipelineV2(settings, MockLLMProvider(responder=SyntheticDemoResponder())).run("PAT-V2-TEST-001", [project / "demo" / "motor_control" / "materials"], project / "demo" / "motor_control" / "prior_art_demo.json", output, auto_approve_demo=True, use_word_com=False)
    assert result["support_matrix"].validation_status == "PASS"
    assert "如何" in result["understanding"].technical_problems[0].text
    assert result["support_matrix"].unsupported_independent_features == []
    assert result["traceability"].broken_links == []
    assert result["validation"]["xml"]["omml_count"] == 5
    assert all(item.status == "PASS" for item in result["gates"])
    assert (output / "技术交底书_v2_demo.docx").exists()
    assert (output / "权利要求草案_v2_demo.docx").exists()
    assert "SOURCE_FACT_WITHOUT_EVIDENCE: 0" in (output / "validation_report.md").read_text(encoding="utf-8")


def test_real_case_dry_run_stops_before_claims_and_word(tmp_path: Path):
    project = Path(__file__).resolve().parents[2]
    settings = Settings(project_root=tmp_path, workspace_root=tmp_path / "workspace", template_root=tmp_path / "templates", output_root=tmp_path / "output")
    output = tmp_path / "dry_run"
    result = PatentPipelineV2(settings).dry_run_real("PAT-DRY-TEST-001", [project / "tests" / "fixtures" / "synthetic_motor_case"], output)
    assert result["stop_point"] == "Checkpoint A preview"
    assert not list(output.glob("*.docx"))
    assert (output / "technical_understanding_review.md").exists()
    assert (output / "invention_candidates_review.md").exists()
