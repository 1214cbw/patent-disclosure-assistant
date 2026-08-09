import re

from patent_agent.core.models import Claim, ClaimTree, PatentKnowledge, ProtectionStrategy


def _clean_step(value: str) -> str:
    return re.sub(r"[，。；;、,.：:\s]+$", "", value.strip())


class ClaimsWriter:
    def run(self, title: str, knowledge: PatentKnowledge, strategy: ProtectionStrategy) -> ClaimTree:
        evidence = [item.id for item in knowledge.evidence]
        steps = knowledge.steps or strategy.mandatory_features
        subject = title.rstrip("。") or "技术方法"
        method_text = f"一种{subject}，其特征在于，包括：" + "；".join(
            f"S{i}：{_clean_step(step)}" for i, step in enumerate(steps, 1)) + "。"
        claims = [Claim(number=1, category="method", text=method_text,
                        feature_ids=[f"F{i}" for i in range(1, len(steps) + 1)],
                        evidence_ids=evidence, scope="broad")]
        dependent_pool = list(dict.fromkeys(
            list(strategy.optional_features) + list(knowledge.inputs) +
            list(knowledge.outputs) + list(knowledge.components) +
            list(knowledge.relationships) + list(knowledge.steps)
        ))[:5]
        for index, feature in enumerate(dependent_pool, 2):
            claims.append(Claim(
                number=index, category="dependent", depends_on=[1],
                text=f"根据权利要求1所述的方法，其特征在于，{_clean_step(feature)}。",
                feature_ids=[f"F{index}"], evidence_ids=evidence,
            ))
        return ClaimTree(title=title, claims=claims)
