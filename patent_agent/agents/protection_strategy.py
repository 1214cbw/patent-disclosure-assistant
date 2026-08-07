import re

from patent_agent.core.models import InventionCandidate, PatentKnowledge, ProtectionStrategy


def _clean_feature(value: str) -> str:
    return re.sub(r"[，。；;、,.：:\s]+$", "", value.strip())


class ProtectionStrategyAgent:
    def run(self, candidate: InventionCandidate, knowledge: PatentKnowledge) -> ProtectionStrategy:
        return ProtectionStrategy(
            core_inventive_concept=f"针对{_clean_feature(candidate.technical_problem)}，通过{'、'.join(_clean_feature(item) for item in candidate.mandatory_features)}，输出电机状态估计结果和自适应控制指令。",
            mandatory_features=candidate.mandatory_features,
            optional_features=candidate.optional_features,
            preferred_embodiment=knowledge.steps,
            alternative_embodiments=knowledge.alternative_embodiments,
            parameter_ranges=[f"{key}：{value}（具体范围待发明人确认）" for key, value in knowledge.key_parameters.items()],
            broad_terminology={"传感器": "状态采集单元", "控制器": "控制处理单元"},
            narrow_terminology={"状态采集单元": "振动、电流、转速和温度传感器组合", "控制处理单元": "电机控制器"},
            risk_points=["不将合成演示参数写入正式独立权利要求", "查新覆盖范围有限", "真实控制器实现和采样同步精度待确认"],
        )
