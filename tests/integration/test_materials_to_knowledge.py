from pathlib import Path

from patent_agent.agents import TechnicalUnderstandingAgent
from patent_agent.core.state import CaseStore
from patent_agent.ingestion import SourceManager


def test_demo_materials_to_knowledge(tmp_path: Path):
    root = Path(__file__).resolve().parents[2]
    store = CaseStore(tmp_path / "workspace"); store.create("PAT-DEMO")
    _, chunks, _ = SourceManager(store).ingest("PAT-DEMO", [root / "demo" / "motor_control" / "materials"])
    knowledge = TechnicalUnderstandingAgent().run(chunks)
    assert len(knowledge.equations) == 4
    assert len(knowledge.steps) == 5
    assert knowledge.equations[0].source_ids[0].startswith("P")

