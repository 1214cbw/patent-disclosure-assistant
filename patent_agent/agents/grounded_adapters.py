from __future__ import annotations

from patent_agent.core.models import Claim, ClaimTree, DisclosureDraft, EquationSpec, EvidenceRef, EvidenceStatus, GroundedClaimSet, GroundedDisclosure, PatentKnowledge, TechnicalUnderstandingResult


def understanding_to_patent_knowledge(result: TechnicalUnderstandingResult, evidence_store) -> PatentKnowledge:
    evidence_ids = sorted({identifier for fact in result.facts for identifier in fact.evidence_ids})
    evidence = []
    for evidence_id in evidence_ids:
        chunk = evidence_store.get(evidence_id)
        evidence.append(EvidenceRef(id=evidence_id, claim=chunk.raw_text[:160], source_type=chunk.scope.value, source_file=chunk.source_file_name, source_location=chunk.section_title or f"paragraph {chunk.paragraph_index}", confidence=1.0, status=EvidenceStatus.SOURCE_FACT))
    equations = [EquationSpec(id=item.equation_id, latex=item.normalized_latex or item.original_expression, role="材料公式", source_ids=item.evidence_ids, evidence_ids=item.evidence_ids, original_expression=item.original_expression, status=item.status, symbols=item.symbols) for item in result.equations if item.status != EvidenceStatus.AI_SUGGESTION and (item.normalized_latex or item.original_expression)]
    return PatentKnowledge(
        technical_field=result.technical_field[0].text if result.technical_field else "[待发明人确认]",
        technical_problem="；".join(item.text for item in result.technical_problems) or "[待发明人确认]",
        existing_technology=[],
        existing_limitations=[item.text for item in result.technical_problems],
        core_idea="；".join(item.text for item in result.system_overview),
        components=[item.name for item in result.components],
        steps=[item.text.text for item in result.steps],
        relationships=[item.relation.text for item in result.data_flows + result.control_flows],
        data_flow=[item.relation.text for item in result.data_flows],
        control_flow=[item.relation.text for item in result.control_flows],
        inputs=[item.text for item in result.inputs],
        outputs=[item.text for item in result.outputs],
        technical_effects=[item.text for item in result.technical_effects],
        key_parameters={item.symbol or item.name: " ".join(part for part in (item.value, item.unit) if part) or "[待发明人确认]" for item in result.parameters},
        equations=equations,
        experimental_evidence=[item.text for item in result.experiments if item.status == EvidenceStatus.SOURCE_FACT],
        alternative_embodiments=[item.text for item in result.alternatives],
        optional_features=[item.text for item in result.alternatives],
        mandatory_features=[item.text.text for item in result.steps],
        uncertain_information=[item.text for item in result.uncertainties],
        evidence=evidence,
        technical_facts=result.facts,
    )


def grounded_disclosure_to_draft(disclosure: GroundedDisclosure, knowledge: PatentKnowledge, figures: list) -> DisclosureDraft:
    sections = {section.title: [paragraph.text for paragraph in section.paragraphs] for section in disclosure.sections}
    return DisclosureDraft(title=disclosure.title, sections=sections, equations=knowledge.equations, figures=figures, inventor_questions=knowledge.uncertain_information, evidence_ids=[item.id for item in knowledge.evidence])


def grounded_claims_to_tree(claims: GroundedClaimSet) -> ClaimTree:
    converted = [Claim(number=item.claim_number, category=item.claim_type, depends_on=item.parent_claims, text=item.rendered_text, feature_ids=[feature.feature_id for feature in item.features], evidence_ids=sorted({identifier for feature in item.features for identifier in feature.evidence_ids}), scope=item.draft_strategy) for item in claims.claims]
    return ClaimTree(title=claims.title, claims=converted)
