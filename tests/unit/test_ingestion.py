from pathlib import Path

from patent_agent.core.state import CaseStore
from patent_agent.ingestion import SourceManager


def test_markdown_ingestion_preserves_headings_and_source_ids(tmp_path: Path):
    source = tmp_path / "material.md"
    source.write_text("# 技术背景\n背景内容\n# 技术方案\n方案内容", encoding="utf-8")
    store = CaseStore(tmp_path / "workspace")
    store.create("PAT-INGEST")
    records, chunks, images = SourceManager(store).ingest("PAT-INGEST", [source])
    assert [chunk.id for chunk in chunks] == ["P001", "P002"]
    assert chunks[1].source_location == "技术方案"
    assert records[0].chunk_ids == ["P001", "P002"]
    assert images == []

