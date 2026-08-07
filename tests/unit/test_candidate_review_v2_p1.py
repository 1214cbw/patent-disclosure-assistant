from patent_agent.core.models import CandidateScoreBreakdown, GroundedInventionCandidate, GroundedStatement
from patent_agent.human_review import CandidateReviewEngine


def _candidate(identifier, text):
    gs = GroundedStatement(text=text, evidence_ids=[f"EV-{identifier}"], status="SOURCE_FACT", confidence=1)
    return GroundedInventionCandidate(candidate_id=identifier, title=text, technical_problem=gs, core_idea=gs, mandatory_features=[gs], optional_features=[], technical_effects=[gs], evidence_ids=[f"EV-{identifier}"], novelty_hypothesis="h", inventiveness_hypothesis="h", protection_value_score=.5, evidence_strength_score=.5, risk_score=.5, score_breakdown=CandidateScoreBreakdown(evidence_strength=.5, novelty_potential=.5, technical_importance=.5, claimability=.5, alternative_coverage=.5, implementation_support=.5, risk=.5))


def test_candidate_merge_and_split_preserve_lineage():
    left, right = _candidate("INV-1", "特征一"), _candidate("INV-2", "特征二")
    engine = CandidateReviewEngine(); merged = engine.merge([left, right], ["INV-1", "INV-2"], "INV-M001")
    assert merged.merged_from == ["INV-1", "INV-2"] and merged.locked
    parts = engine.split(merged, [{"title": "分支一", "feature_texts": ["特征一"]}, {"title": "分支二", "feature_texts": ["特征二"]}])
    assert all(item.split_from == "INV-M001" for item in parts)
