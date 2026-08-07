from __future__ import annotations

from patent_agent.core.models import CandidateScoreBreakdown, ComponentKnowledge, EquationKnowledge, EvidenceStatus, GroundedInventionCandidate, GroundedStatement, InventorQuestion, MethodStepKnowledge, ParameterKnowledge, TechnicalFact, TechnicalUnderstandingResult
from patent_agent.evidence import validate_statement_support

from .technical_understanding import TechnicalUnderstandingAgent


class DeterministicGroundedAnalyzer:
    """Privacy-safe fallback. It preserves uncertainty rather than inventing missing content."""

    def run(self, source_chunks, evidence_store) -> TechnicalUnderstandingResult:
        knowledge = TechnicalUnderstandingAgent().run(source_chunks)
        all_evidence = evidence_store.all()

        def grounded(text: str) -> GroundedStatement:
            selected = evidence_store.search(text, top_k=1)
            if not selected or not text or text.startswith("["):
                return GroundedStatement(text=text or "[待发明人确认]", evidence_ids=[], status=EvidenceStatus.UNVERIFIED, confidence=.2)
            statement = GroundedStatement(text=text, evidence_ids=[selected[0].evidence_id], status=EvidenceStatus.SOURCE_FACT, confidence=.9)
            try:
                validate_statement_support(statement, evidence_store)
                return statement
            except Exception:
                return GroundedStatement(text=text, evidence_ids=[selected[0].evidence_id], status=EvidenceStatus.INFERRED, confidence=.55)

        facts = [TechnicalFact(fact_id=f"FACT-{index:04d}", statement=item.raw_text, category=item.section_title or "source", evidence_ids=[item.evidence_id], status=EvidenceStatus.SOURCE_FACT, confidence=1) for index, item in enumerate(all_evidence, 1)]
        components = [ComponentKnowledge(component_id=f"COMP-{index:03d}", name=value.split("：", 1)[0], description=grounded(value)) for index, value in enumerate(knowledge.components, 1)]
        steps = [MethodStepKnowledge(step_id=f"S{index}", text=grounded(value)) for index, value in enumerate(knowledge.steps, 1)]
        parameters = [ParameterKnowledge(parameter_id=f"PARAM-{index:03d}", name=name, value=value, evidence_ids=grounded(name + " " + value).evidence_ids, status=EvidenceStatus.SOURCE_FACT if grounded(name + " " + value).evidence_ids else EvidenceStatus.UNVERIFIED) for index, (name, value) in enumerate(knowledge.key_parameters.items(), 1)]
        equations = []
        for item in knowledge.equations:
            selected = next((chunk for chunk in all_evidence if chunk.metadata.get("source_chunk_id") in item.source_ids), None)
            equations.append(EquationKnowledge(equation_id=item.id, original_expression=item.latex, normalized_latex=item.latex, evidence_ids=[selected.evidence_id] if selected else [], status=EvidenceStatus.SOURCE_FACT if selected else EvidenceStatus.UNVERIFIED, symbols=item.symbols))
        questions = [InventorQuestion(question_id=f"Q-{index:03d}", text=value, priority="P0" if "公式" in value or "参数" in value else "P1") for index, value in enumerate(knowledge.uncertain_information, 1)]
        return TechnicalUnderstandingResult(technical_field=[grounded(knowledge.technical_field)], technical_problems=[grounded(knowledge.technical_problem)], system_overview=[grounded(knowledge.core_idea)], components=components, steps=steps, data_flows=[], control_flows=[], inputs=[grounded(item) for item in knowledge.inputs], outputs=[grounded(item) for item in knowledge.outputs], parameters=parameters, equations=equations, technical_effects=[grounded(item) for item in knowledge.technical_effects], experiments=[grounded(item) for item in knowledge.experimental_evidence], alternatives=[grounded(item) for item in knowledge.alternative_embodiments], uncertainties=questions, facts=facts)


class DeterministicGroundedInventionMiner:
    def run(self, understanding: TechnicalUnderstandingResult) -> list[GroundedInventionCandidate]:
        problem = understanding.technical_problems[0] if understanding.technical_problems else GroundedStatement(text="[待发明人确认]", status=EvidenceStatus.UNVERIFIED, confidence=.1)
        mandatory = [item.text for item in understanding.steps[:4]] or [item.description for item in understanding.components[:4]]
        evidence_ids = sorted({identifier for item in mandatory for identifier in item.evidence_ids})
        core_text = "；".join(item.text for item in mandatory) or "[待发明人确认]"
        core = GroundedStatement(text="可能的核心组合为：" + core_text, evidence_ids=evidence_ids, status=EvidenceStatus.INFERRED, confidence=.6)
        candidate = GroundedInventionCandidate(candidate_id="INV-DET-001", title="待确认的候选技术方案", technical_problem=problem, core_idea=core, mandatory_features=mandatory, optional_features=understanding.alternatives, technical_effects=understanding.technical_effects, evidence_ids=evidence_ids, novelty_hypothesis="尚未查新，仅作为 Checkpoint A 预览。", inventiveness_hypothesis="需要人工导入 prior art 后判断。", protection_value_score=.5, evidence_strength_score=.6 if evidence_ids else .2, risk_score=.7, score_breakdown=CandidateScoreBreakdown(evidence_strength=.6 if evidence_ids else .2, novelty_potential=.5, technical_importance=.5, claimability=.5, alternative_coverage=.4, implementation_support=.5, risk=.7), inventor_questions=[item.text for item in understanding.uncertainties])
        return [candidate]
