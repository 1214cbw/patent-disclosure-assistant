from patent_agent.core.models import DisclosureDraft, FigureSpec, PatentKnowledge, ProtectionStrategy


class DisclosureWriter:
    def run(self, title: str, knowledge: PatentKnowledge, strategy: ProtectionStrategy, figures: list[FigureSpec]) -> DisclosureDraft:
        sections = {
            "1. 发明名称": [title],
            "2. 技术领域": [f"本方案涉及{knowledge.technical_field}。"],
            "3. 背景技术": knowledge.existing_technology or ["现有技术背景待发明人补充。"],
            "4. 现有技术存在的问题": knowledge.existing_limitations,
            "5. 本发明要解决的技术问题": [knowledge.technical_problem],
            "6. 技术方案": [strategy.core_inventive_concept] + [f"步骤S{index}：{step}" for index, step in enumerate(knowledge.steps, 1)],
            "7. 有益效果": knowledge.technical_effects,
            "8. 附图说明": [f"图{figure.number}为{figure.title}。" for figure in figures],
            "9. 具体实施方式": [f"步骤S{index}：{step}" for index, step in enumerate(knowledge.steps, 1)] + knowledge.experimental_evidence,
            "10. 可替代实施方式": knowledge.alternative_embodiments or ["可替代实施方式待发明人补充。"],
            "11. 关键创新点与拟保护点": [strategy.core_inventive_concept] + strategy.mandatory_features,
            "12. 需要发明人进一步确认的问题": knowledge.uncertain_information,
        }
        return DisclosureDraft(title=title, sections=sections, equations=knowledge.equations, figures=figures, inventor_questions=knowledge.uncertain_information, evidence_ids=[item.id for item in knowledge.evidence])
