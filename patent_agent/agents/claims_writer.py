import re

from patent_agent.core.models import Claim, ClaimTree, PatentKnowledge, ProtectionStrategy


def _clean_step(value: str) -> str:
    return re.sub(r"[，。；;、,.：:\s]+$", "", value.strip())


class ClaimsWriter:
    def run(self, title: str, knowledge: PatentKnowledge, strategy: ProtectionStrategy) -> ClaimTree:
        evidence = [item.id for item in knowledge.evidence]
        steps = knowledge.steps or strategy.mandatory_features
        method_text = "一种基于多源传感信息的电机状态监测与自适应控制方法，其特征在于，包括：" + "；".join(f"S{i}：{_clean_step(step)}" for i, step in enumerate(steps[:4], 1)) + "，并输出电机状态估计结果和自适应控制指令。"
        system_text = "一种电机状态监测与自适应控制系统，其特征在于，包括状态采集单元、状态估计单元和控制处理单元，所述各单元被配置为执行权利要求1所述方法的相应步骤。"
        claims = [
            Claim(number=1, category="method", text=method_text, feature_ids=[f"F{i}" for i in range(1, min(4, len(steps))+1)], evidence_ids=evidence, scope="broad"),
            Claim(number=2, category="dependent", depends_on=[1], text="根据权利要求1所述的方法，其特征在于，所述多源传感信息至少包括振动信号、定子电流信号、转速信号和温度信号中的两种。", feature_ids=["F5"], evidence_ids=evidence),
            Claim(number=3, category="dependent", depends_on=[1], text="根据权利要求1所述的方法，其特征在于，依据各传感信号的置信度确定对应融合权重。", feature_ids=["F6"], evidence_ids=evidence),
            Claim(number=4, category="dependent", depends_on=[1], text="根据权利要求1所述的方法，其特征在于，根据目标状态与融合状态量之间的偏差更新控制参数。", feature_ids=["F7"], evidence_ids=evidence),
            Claim(number=5, category="system", text=system_text, feature_ids=["F8"], evidence_ids=evidence, scope="conservative"),
            Claim(number=6, category="dependent", depends_on=[5], text="根据权利要求5所述的系统，其特征在于，所述控制处理单元为电机控制器，所述状态采集单元与所述电机控制器通过有线或工业现场总线连接。", feature_ids=["F9"], evidence_ids=evidence),
        ]
        return ClaimTree(title=title, claims=claims)
