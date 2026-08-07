from patent_agent.core.models import DisclosureDraft, FigureSpec, PatentKnowledge, ProtectionStrategy


class DisclosureWriter:
    def run(self, title: str, knowledge: PatentKnowledge, strategy: ProtectionStrategy, figures: list[FigureSpec]) -> DisclosureDraft:
        sections = {
            "1. 发明名称": [title],
            "2. 技术领域": [f"本方案涉及{knowledge.technical_field}，尤其涉及一种基于多源传感信息的电机状态监测与自适应控制方法。"],
            "3. 背景技术": knowledge.existing_technology or ["现有电机控制通常依赖单一电流或转速反馈，难以同时表征机械、热和电气状态。"],
            "4. 现有技术存在的问题": knowledge.existing_limitations,
            "5. 本发明要解决的技术问题": [knowledge.technical_problem],
            "6. 技术方案": [strategy.core_inventive_concept] + [f"步骤S{index}：{step}" for index, step in enumerate(knowledge.steps, 1)],
            "7. 有益效果": knowledge.technical_effects,
            "8. 附图说明": [f"图{figure.number}为{figure.title}。" for figure in figures],
            "9. 具体实施方式": ["在合成演示实施例中，状态采集单元同步获得振动、定子电流、转速和温度信号，并形成统一时间窗内的多源特征。", "状态估计单元计算各信号的置信度并形成融合状态量；控制处理单元依据融合状态量与目标状态之间的偏差生成控制参数修正量。"] + knowledge.experimental_evidence,
            "10. 可替代实施方式": knowledge.alternative_embodiments or ["传感信号种类、融合权重计算方式及控制器形式可根据电机类型进行替换。"],
            "11. 关键创新点与拟保护点": [strategy.core_inventive_concept] + strategy.mandatory_features,
            "12. 需要发明人进一步确认的问题": knowledge.uncertain_information,
        }
        return DisclosureDraft(title=title, sections=sections, equations=knowledge.equations, figures=figures, inventor_questions=knowledge.uncertain_information, evidence_ids=[item.id for item in knowledge.evidence])

