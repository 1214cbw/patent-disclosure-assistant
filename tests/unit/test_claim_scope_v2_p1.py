import pytest

from patent_agent.core.models import (
    ClaimFeature,
    ClaimSupportRecord,
    ClaimTerminologyRegistry,
    ClaimsSupportMatrix,
    FeatureNoveltyAssessmentV2,
    GroundedClaimSet,
    GroundedNoveltyMatrix,
    GroundedProtectionStrategy,
    GroundedStatement,
    PatentClaimV2,
    TerminologyChoice,
)
from patent_agent.review import ClaimFeatureEditor, ClaimScopeEngine


def _gs(text):
    return GroundedStatement(text=text, evidence_ids=["EV-1"], status="SOURCE_FACT", confidence=1)


def _fixture():
    f1 = ClaimFeature(feature_id="F1", text="获取多源信号", source_fact_ids=["FACT-1"], evidence_ids=["EV-1"], support_status="SUPPORTED", mandatory=True)
    f2 = ClaimFeature(feature_id="F2", text="计算融合状态量", source_fact_ids=["FACT-2"], evidence_ids=["EV-1"], support_status="SUPPORTED", mandatory=True)
    f3 = ClaimFeature(feature_id="F3", text="温度阈值为85℃并使用STM32处理器", source_fact_ids=["FACT-3"], evidence_ids=["EV-1"], support_status="SUPPORTED")
    claims = GroundedClaimSet(title="demo", claims=[PatentClaimV2(claim_number=1, claim_type="method", features=[f1, f3], rendered_text="demo", draft_strategy="broad")])
    strategy = GroundedProtectionStrategy(inventive_concept="融合", independent_claim_core=[_gs(f1.text), _gs(f2.text)], dependent_claim_features=[_gs(f3.text)], optional_features=[], broad_terms=[TerminologyChoice(concept_id="T1", selected_term="处理模块", evidence_ids=["EV-1"])], narrow_terms=[], parameters_to_avoid_locking=["85℃"], alternative_embodiments_needed=[], support_gaps=[], risks=[], inventor_questions=[])
    support = ClaimsSupportMatrix(records=[ClaimSupportRecord(claim_number=1, feature_id=f.feature_id, feature_text=f.text, disclosure_paragraph_ids=["P1"], fact_ids=f.source_fact_ids, evidence_ids=f.evidence_ids, support_status="SUPPORTED", notes="ok") for f in [f1, f3]], validation_status="PASS")
    novelty = GroundedNoveltyMatrix(assessments=[FeatureNoveltyAssessmentV2(feature_id="F1", feature_text=f1.text, prior_art_document_id="PA1", assessment="EXPLICITLY_DISCLOSED", prior_art_evidence_ids=["EV-PA"], reasoning="explicit")])
    registry = ClaimTerminologyRegistry(terms=strategy.broad_terms)
    return f1, f2, f3, claims, strategy, support, novelty, registry


def test_scope_detects_missing_core_parameter_and_implementation_narrowing():
    _, _, _, claims, strategy, support, novelty, registry = _fixture()
    review = ClaimScopeEngine().assess(claims, strategy, novelty, support, registry)
    assessment = review.assessments[0]
    assert assessment.scope_level == "BROAD"
    assert "计算融合状态量" in assessment.potentially_missing_core_features
    assert assessment.parameter_locking_risks == ["PARAMETER_LOCKING_RISK:F3"]
    assert assessment.terminology_narrowing_risks == ["IMPLEMENTATION_NARROWING:F3"]
    assert {item.name for item in review.comparisons[0].variants} == {"Broad", "Balanced", "Conservative"}
    assert set(review.comparisons[0].same_feature_pool) == {"F1", "F3"}


def test_claim_feature_edit_rerenders_and_manual_text_marks_stale():
    f1, f2, f3, claims, *_ = _fixture(); editor = ClaimFeatureEditor(); pool = {item.feature_id: item for item in (f1, f2, f3)}
    updated = editor.edit(claims, claim_number=1, action="ADD", feature_id="F2", supported_pool=pool)
    assert "计算融合状态量" in updated.claims[0].rendered_text
    assert updated.claims[0].human_modified
    manual = editor.manual_text_edit(updated, 1, "人工长句")
    assert manual.claims[0].structured_mapping_stale
    with pytest.raises(ValueError, match="CLAIM_FEATURE_UNSUPPORTED"):
        editor.edit(claims, claim_number=1, action="ADD", feature_id="F-X", supported_pool=pool)


def test_unsupported_feature_is_hard_blocked():
    f1, *_rest = _fixture()
    bad = ClaimFeature(feature_id="BAD", text="不存在的特征", source_fact_ids=[], evidence_ids=[], support_status="UNSUPPORTED", mandatory=True)
    claims = GroundedClaimSet(title="x", claims=[PatentClaimV2(claim_number=1, claim_type="method", features=[f1], rendered_text="x")])
    with pytest.raises(ValueError, match="UNSUPPORTED_INDEPENDENT"):
        ClaimFeatureEditor().edit(claims, claim_number=1, action="ADD", feature_id="BAD", supported_pool={"BAD": bad})
