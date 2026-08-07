from __future__ import annotations

import re

from patent_agent.core.models import FeatureNoveltyAssessmentV2, GroundedInventionCandidate, GroundedNoveltyMatrix


class GroundedNoveltyAnalysisAgent:
    def run(self, candidate: GroundedInventionCandidate, prior_art_store) -> GroundedNoveltyMatrix:
        assessments = []
        for index, feature in enumerate(candidate.mandatory_features, 1):
            feature_tokens = _tokens(feature.text)
            for evidence in prior_art_store.all():
                evidence_tokens = _tokens(evidence.normalized_text)
                overlap = len(feature_tokens & evidence_tokens) / len(feature_tokens) if feature_tokens else 0
                status = "EXPLICITLY_DISCLOSED" if overlap >= .55 else "POSSIBLY_DISCLOSED" if overlap >= .2 else "NOT_FOUND"
                assessments.append(FeatureNoveltyAssessmentV2(feature_id=f"NF-{index:03d}", feature_text=feature.text, prior_art_document_id=evidence.metadata.get("reference_id", evidence.source_file_id), assessment=status, prior_art_evidence_ids=[evidence.evidence_id], reasoning=f"基于人工导入摘要的确定性词项覆盖率 {overlap:.2f}；需要专利专业人员核对全文。"))
        return GroundedNoveltyMatrix(assessments=assessments)


def _tokens(value: str) -> set[str]:
    words = set(re.findall(r"[a-z0-9_]+", value.lower()))
    chinese = "".join(re.findall(r"[\u4e00-\u9fff]", value))
    return words | {chinese[index:index + 2] for index in range(max(0, len(chinese) - 1))}
