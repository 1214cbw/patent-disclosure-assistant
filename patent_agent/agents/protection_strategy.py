import re

from patent_agent.core.models import InventionCandidate, PatentKnowledge, ProtectionStrategy


def _clean_feature(value: str) -> str:
    return re.sub(r"[，。；;、,.：:\s]+$", "", value.strip())


class ProtectionStrategyAgent:
    def run(self, candidate: InventionCandidate, knowledge: PatentKnowledge) -> ProtectionStrategy:
        return ProtectionStrategy(
            core_inventive_concept=f"针对{_clean_feature(candidate.technical_problem)}，采用{'、'.join(_clean_feature(item) for item in candidate.mandatory_features)}。",
            mandatory_features=candidate.mandatory_features,
            optional_features=candidate.optional_features,
            preferred_embodiment=knowledge.steps,
            alternative_embodiments=knowledge.alternative_embodiments,
            parameter_ranges=[f"{key}：{value}（具体范围待发明人确认）" for key, value in knowledge.key_parameters.items()],
            broad_terminology={},
            narrow_terminology={},
            risk_points=["不将未获证据支持的参数写入独立权利要求", "查新覆盖范围有限", "实施细节待发明人确认"],
        )
