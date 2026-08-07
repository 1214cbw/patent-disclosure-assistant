from pathlib import Path

from patent_agent.core.models import EvidenceScope, SourceChunk, SourceFileRecord
from patent_agent.evidence import EvidenceStore
from patent_agent.ingestion.readers import split_pdf_page_text


def test_logical_pdf_blocks_split_conclusion_and_references():
    text = """IV. CONCLUSION
The proposed model generates motor topology images.
VI. REFERENCES
[1] A. Author, Prior motor paper, 2023.
[2] B. Author, Diffusion paper, 2022.
"""
    blocks = split_pdf_page_text(text, 4)
    invention = [item for item in blocks if item.scope == EvidenceScope.INVENTION_SOURCE]
    references = [item for item in blocks if item.scope == EvidenceScope.REFERENCE]
    assert any("proposed model" in item.text for item in invention)
    assert len(references) == 2
    assert all(item.block_type == "reference" for item in references)


def test_evidence_supersession_archives_old_version(tmp_path: Path):
    root = tmp_path / "evidence"
    store = EvidenceStore(root)
    record = SourceFileRecord(path=str(tmp_path / "paper.pdf"), original_path="paper.pdf", media_type="pdf", sha256="abc")
    old = [SourceChunk(id="P001", source_file="paper.pdf", source_location="第1页", heading="第1页", text="Dataset definition. Forward diffusion process.", sha256="x", page=1)]
    old_ids = [item.evidence_id for item in store.build([record], old)]
    refined = [
        SourceChunk(id="P001", source_file="paper.pdf", source_location="第1页 · Dataset", heading="Dataset", text="Dataset definition.", sha256="y", page=1),
        SourceChunk(id="P002", source_file="paper.pdf", source_location="第1页 · Method", heading="Method", text="Forward diffusion process.", sha256="z", page=1),
    ]
    new = store.build([record], refined)
    assert (root / "versions" / "v001" / "chunks.jsonl").exists()
    assert old_ids[0] in {old for item in new for old in item.supersedes}
    assert (root / "supersession.json").exists()
