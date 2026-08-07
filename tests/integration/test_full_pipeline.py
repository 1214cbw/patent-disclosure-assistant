from pathlib import Path

from patent_agent.core.config import Settings
from patent_agent.workflow import PatentPipeline


def test_full_demo_pipeline_without_word_com(tmp_path: Path):
    project_root = Path(__file__).resolve().parents[2]
    settings = Settings(
        project_root=tmp_path,
        workspace_root=tmp_path / "workspace",
        template_root=tmp_path / "templates",
        output_root=tmp_path / "output",
    )
    output_dir = settings.output_root / "demo"

    result = PatentPipeline(settings).run(
        case_id="PAT-INTEGRATION-001",
        materials=[project_root / "demo" / "motor_control" / "materials"],
        prior_art=project_root / "demo" / "motor_control" / "prior_art_demo.json",
        output_dir=output_dir,
        auto_approve_demo=True,
        use_word_com=False,
    )

    assert result["validation"]["pass"] is True
    assert len(result["knowledge"].equations) == 4
    assert len(result["claims"].claims) == 6
    assert (output_dir / "技术交底书_demo.docx").exists()
    assert (output_dir / "权利要求草案_demo.docx").exists()
    assert (output_dir / "patent_knowledge.json").exists()
    assert (output_dir / "validation_report.md").exists()

