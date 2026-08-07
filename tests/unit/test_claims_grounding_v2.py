from pathlib import Path

from patent_agent.core.models import EvidenceStatus, GroundedClaimSet, GroundedDisclosure, TechnicalUnderstandingResult
from patent_agent.core.state import CaseStore
from patent_agent.evidence import EvidenceStore
from patent_agent.ingestion import SourceManager
from patent_agent.review import ClaimsSupportMatrixBuilder, build_traceability


def _setup(tmp_path: Path):
    case_store = CaseStore(tmp_path / "workspace"); case_store.create("PAT-CLAIM-001")
    source = tmp_path / "source.txt"; source.write_text("状态采集单元获取振动信号。", encoding="utf-8")
    SourceManager(case_store).ingest("PAT-CLAIM-001", [source])
    evidence_store = EvidenceStore(case_store.case_dir("PAT-CLAIM-001") / "evidence")
    return evidence_store, evidence_store.all()[0].evidence_id


def test_claim_support_matrix_and_traceability(tmp_path: Path):
    evidence_store, evidence_id = _setup(tmp_path)
    disclosure = GroundedDisclosure(title="x", sections=[{"section_id": "06", "title": "6. 技术方案", "paragraphs": [{"paragraph_id": "DISC-06-P001", "section_id": "06", "text": "状态采集单元获取振动信号。", "evidence_ids": [evidence_id], "fact_ids": ["FACT-001"], "derived_from": ["FACT-001"], "status": "SOURCE_FACT"}]}])
    claims = GroundedClaimSet(title="x", claims=[{"claim_number": 1, "claim_type": "method", "parent_claims": [], "features": [{"feature_id": "CORE-F001", "text": "获取振动信号", "source_fact_ids": ["FACT-001"], "evidence_ids": [evidence_id], "support_status": "SUPPORTED", "mandatory": True}], "rendered_text": "一种方法，包括获取振动信号。", "draft_strategy": "broad"}])
    understanding = TechnicalUnderstandingResult(technical_field=[], technical_problems=[], system_overview=[], components=[], steps=[], data_flows=[], control_flows=[], inputs=[], outputs=[], parameters=[], equations=[], technical_effects=[], experiments=[], alternatives=[], uncertainties=[], facts=[{"fact_id": "FACT-001", "statement": "状态采集单元获取振动信号", "category": "step", "evidence_ids": [evidence_id], "status": EvidenceStatus.SOURCE_FACT, "confidence": 1}])
    matrix = ClaimsSupportMatrixBuilder().build(claims, disclosure, evidence_store)
    traceability = build_traceability(disclosure, claims, understanding)
    assert matrix.validation_status == "PASS"
    assert matrix.records[0].support_status == "SUPPORTED"
    assert traceability.broken_links == []


def test_unsupported_independent_feature_fails(tmp_path: Path):
    evidence_store, _ = _setup(tmp_path)
    disclosure = GroundedDisclosure(title="x", sections=[])
    claims = GroundedClaimSet(title="x", claims=[{"claim_number": 1, "claim_type": "method", "features": [{"feature_id": "CORE-F999", "text": "不存在的模块", "source_fact_ids": [], "evidence_ids": [], "support_status": "UNSUPPORTED", "mandatory": True}], "rendered_text": "x"}])
    matrix = ClaimsSupportMatrixBuilder().build(claims, disclosure, evidence_store)
    assert matrix.validation_status == "FAIL"
    assert matrix.unsupported_independent_features == ["CORE-F999"]
