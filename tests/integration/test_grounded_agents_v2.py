from pathlib import Path

from patent_agent.agents import GroundedDisclosureWriter, GroundedInventionMiningAgent, GroundedProtectionStrategyAgent, GroundedTechnicalUnderstandingAgent
from patent_agent.core.config import Settings
from patent_agent.core.state import CaseStore
from patent_agent.evidence import EvidenceStore
from patent_agent.ingestion import SourceManager
from patent_agent.llm import MockLLMProvider, StructuredLLMService


def _gs(text, evidence_id, status="SOURCE_FACT"):
    return {"text": text, "evidence_ids": [evidence_id], "status": status, "confidence": .96}


def test_mock_llm_grounded_agent_chain(tmp_path: Path):
    project = Path(__file__).resolve().parents[2]
    case_store = CaseStore(tmp_path / "workspace"); case_store.create("PAT-GROUND-001", "合成电机控制")
    SourceManager(case_store).ingest("PAT-GROUND-001", [project / "tests" / "fixtures" / "synthetic_motor_case"])
    evidence_store = EvidenceStore(case_store.case_dir("PAT-GROUND-001") / "evidence")
    evidence_id = evidence_store.search("状态采集单元", top_k=1)[0].evidence_id
    technical = {
        "technical_field": [_gs("电机状态监测与控制", evidence_id)],
        "technical_problems": [_gs("状态监测结果进入控制环路的信息链路较长", evidence_id, "INFERRED")],
        "system_overview": [_gs("系统包括状态采集单元、状态估计单元和控制处理单元", evidence_id)],
        "components": [{"component_id": "C1", "name": "状态采集单元", "description": _gs("获取振动和定子电流信号", evidence_id)}],
        "steps": [{"step_id": "S1", "text": _gs("获取并同步振动信号和定子电流信号", evidence_id)}],
        "data_flows": [], "control_flows": [], "inputs": [_gs("振动信号和定子电流信号", evidence_id)], "outputs": [_gs("控制参数修正量", evidence_id)],
        "parameters": [], "equations": [], "technical_effects": [_gs("预期缩短信息链路", evidence_id, "INFERRED")], "experiments": [], "alternatives": [],
        "uncertainties": [{"question_id": "Q1", "text": "请确认真实样机结果。", "priority": "P1", "related_fact_ids": ["FACT-001"], "related_evidence_ids": [evidence_id]}],
        "facts": [{"fact_id": "FACT-001", "statement": "状态采集单元获取振动信号和定子电流信号", "category": "component", "evidence_ids": [evidence_id], "status": "SOURCE_FACT", "confidence": .98}],
    }
    candidate = {"candidate_id": "INV-001", "title": "多源状态融合控制", "technical_problem": _gs("状态监测结果进入控制环路的信息链路较长", evidence_id, "INFERRED"), "core_idea": _gs("同步多源信号并计算融合状态量用于控制参数修正", evidence_id), "mandatory_features": [_gs("获取振动和定子电流信号", evidence_id), _gs("计算融合状态量", evidence_id)], "optional_features": [], "technical_effects": [_gs("预期缩短信息链路", evidence_id, "INFERRED")], "evidence_ids": [evidence_id], "novelty_hypothesis": "查新前假设：闭环融合关系可能构成区别点。", "inventiveness_hypothesis": "需要结合 prior art 判断。", "protection_value_score": .8, "evidence_strength_score": .9, "risk_score": .3, "score_breakdown": {"evidence_strength": .9, "novelty_potential": .6, "technical_importance": .8, "claimability": .8, "alternative_coverage": .5, "implementation_support": .7, "risk": .3}, "inventor_questions": ["请确认评价指标。"]}
    strategy = {"inventive_concept": "多源状态融合进入控制闭环", "independent_claim_core": candidate["mandatory_features"], "dependent_claim_features": [], "optional_features": [], "broad_terms": [{"concept_id": "C1", "selected_term": "状态采集单元", "alternatives": ["传感模块"], "evidence_ids": [evidence_id]}], "narrow_terms": [], "parameters_to_avoid_locking": [], "alternative_embodiments_needed": [], "support_gaps": [], "risks": ["查新范围有限"], "inventor_questions": []}
    disclosure = {"title": "合成电机控制", "sections": [{"section_id": "06", "title": "6. 技术方案", "paragraphs": [{"paragraph_id": "DISC-06-P001", "section_id": "06", "text": "状态采集单元获取振动信号和定子电流信号。", "evidence_ids": [evidence_id], "fact_ids": ["FACT-001"], "derived_from": ["FACT-001"], "status": "SOURCE_FACT"}]}]}
    provider = MockLLMProvider(responses={"TechnicalUnderstandingResult": technical, "GroundedCandidateList": {"candidates": [candidate]}, "GroundedProtectionStrategy": strategy, "GroundedDisclosure": disclosure})
    settings = Settings(project_root=tmp_path, workspace_root=tmp_path / "workspace", template_root=tmp_path / "templates", output_root=tmp_path / "output")
    llm = StructuredLLMService(provider, settings, case_store.case_dir("PAT-GROUND-001"))
    understanding = GroundedTechnicalUnderstandingAgent().run(evidence_store, llm)
    candidates = GroundedInventionMiningAgent().run(understanding, evidence_store, llm)
    protection = GroundedProtectionStrategyAgent().run(candidates[0], understanding, evidence_store, llm)
    draft = GroundedDisclosureWriter().run("合成电机控制", understanding, candidates[0], protection, evidence_store, llm)
    assert understanding.facts[0].evidence_ids == [evidence_id]
    assert candidates[0].evidence_strength_score == .9
    assert protection.independent_claim_core[0].evidence_ids
    assert draft.sections[0].paragraphs[0].fact_ids == ["FACT-001"]
