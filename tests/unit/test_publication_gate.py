from pathlib import Path

import pytest

from patent_agent.core.config import Settings
from patent_agent.human_review import CheckpointStatus, HumanReviewManager
from patent_agent.real_case import RealCaseManager
from patent_agent.workflow import RealCaseWorkflow


def test_publication_metadata_blocks_real_a2(tmp_path: Path):
    project = Path(__file__).resolve().parents[2]
    settings = Settings(project_root=tmp_path, workspace_root=tmp_path / "workspace", template_root=project / "templates", output_root=tmp_path / "output")
    manager = RealCaseManager(tmp_path)
    manager.create("REAL-PUB-1", authorized=True)
    review = HumanReviewManager(manager.case_dir("REAL-PUB-1"))
    review.machine.configure("A1", [])
    review.machine.transition("A1", CheckpointStatus.GENERATED)
    review.machine.transition("A1", CheckpointStatus.UNDER_REVIEW)
    review.machine.transition("A1", CheckpointStatus.APPROVED)
    review.machine.save(review.state_path)
    with pytest.raises(ValueError, match="PUBLICATION_STATUS_REQUIRED_BEFORE_A2"):
        RealCaseWorkflow(settings).continue_case("REAL-PUB-1")
