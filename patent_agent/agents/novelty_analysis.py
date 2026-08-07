from __future__ import annotations

from patent_agent.core.models import FeatureAssessment, InventionCandidate, NoveltyAnalysis, PriorArtReference


class NoveltyAnalysisAgent:
    def run(self, candidate: InventionCandidate, references: list[PriorArtReference]) -> NoveltyAnalysis:
        features = candidate.mandatory_features or candidate.distinguishing_points
        matrix = []
        for index, feature in enumerate(features, 1):
            tokens = {token for token in feature.replace("，", " ").replace("、", " ").split() if len(token) >= 2}
            for reference in references:
                hit = sum(token in reference.abstract for token in tokens)
                status = "明确公开" if tokens and hit == len(tokens) else "疑似公开" if hit else "未发现公开"
                matrix.append(FeatureAssessment(feature_id=f"F{index}", feature=feature, reference_id=reference.id, status=status, evidence=reference.abstract[:180]))
        conclusion = "未发现单一导入文献明确公开全部必要特征；该结果仅基于当前导入材料，不能据此确定新颖性。" if references else "未导入可比对文献，无法判断。"
        return NoveltyAnalysis(candidate_id=candidate.id, features=features, references=references, matrix=matrix, conclusion=conclusion)

