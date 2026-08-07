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
        return [
            InventionCandidate(id="INVENTION-01", title="基于多源同步融合的电机状态估计与自适应控制方法", core_means=knowledge.steps, mandatory_features=knowledge.mandatory_features, distinguishing_points=["在统一时间窗内融合多源状态特征", "依据融合状态量在线修正控制参数"], protectable_scope="方法独立权利要求为主，系统权利要求为备选。", drafting_value="high", **base),
            InventionCandidate(id="INVENTION-02", title="面向电机多源信号的置信度加权状态融合方法", core_means=knowledge.steps[:3], mandatory_features=knowledge.mandatory_features[:3], distinguishing_points=["按信号置信度动态分配融合权重"], protectable_scope="作为从属方法或独立算法分案候选。", drafting_value="medium", **base),
            InventionCandidate(id="INVENTION-03", title="基于状态偏差闭环修正的电机控制系统", core_means=knowledge.components, mandatory_features=knowledge.components[:4], distinguishing_points=["将状态估计结果反馈至控制参数更新环节"], protectable_scope="系统/装置类别保护。", drafting_value="medium", **base),
        ]

