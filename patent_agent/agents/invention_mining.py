from __future__ import annotations

from patent_agent.core.models import InventionCandidate, PatentKnowledge


class InventionMiningAgent:
    def run(self, knowledge: PatentKnowledge) -> list[InventionCandidate]:
        evidence_ids = [item.id for item in knowledge.evidence]
        base = dict(
            technical_problem=knowledge.technical_problem,
            existing_pain="；".join(knowledge.existing_limitations),
            optional_features=knowledge.optional_features,
            expected_effects=knowledge.technical_effects,
            evidence_ids=evidence_ids,
            novelty_risk="尚未进行权威数据库全面检索，需由专利专业人员复核。",
            inventiveness_risk="特征组合的协同作用需要结合最接近现有技术进一步论证。",
        )
        title = f"{knowledge.technical_field}技术方案"
        distinguishing = knowledge.mandatory_features[:2] or knowledge.steps[:2]
        candidates = [
            ("INVENTION-01", title, knowledge.steps, knowledge.mandatory_features,
             distinguishing, "以证据支持的必要技术特征构建独立权利要求。", "high"),
            ("INVENTION-02", f"{knowledge.technical_field}处理方法",
             knowledge.steps[:3], knowledge.mandatory_features[:3],
             knowledge.steps[:1], "作为方法类从属或分案候选。", "medium"),
            ("INVENTION-03", f"{knowledge.technical_field}系统",
             knowledge.components, knowledge.components[:4],
             knowledge.relationships[:1], "作为系统或装置类别保护候选。", "medium"),
        ]
        return [InventionCandidate(
            id=identifier, title=item_title, core_means=means,
            mandatory_features=mandatory, distinguishing_points=points,
            protectable_scope=scope, drafting_value=value, **base,
        ) for identifier, item_title, means, mandatory, points, scope, value in candidates]
