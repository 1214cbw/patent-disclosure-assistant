from patent_agent.core.models import FigureEdge, FigureNode, FigureSpec, PatentKnowledge


class FigurePlanner:
    def run(self, knowledge: PatentKnowledge) -> list[FigureSpec]:
        steps = knowledge.steps[:5] or ["获取多源信号", "生成融合状态量", "输出自适应控制指令"]
        nodes = [FigureNode(id=f"S{i}", label=f"S{i}：{step}", claim_step=f"S{i}") for i, step in enumerate(steps, 1)]
        edges = [FigureEdge(source=nodes[i].id, target=nodes[i + 1].id) for i in range(len(nodes) - 1)]
        source_ids = [item.id for item in knowledge.evidence]
        return [
            FigureSpec(id="FIG-001", number=1, type="flowchart", title="电机状态监测与自适应控制方法流程图", nodes=nodes, edges=edges, source_ids=source_ids),
            FigureSpec(id="FIG-002", number=2, type="system", title="电机状态监测与自适应控制系统结构示意图", nodes=[FigureNode(id="A", label="状态采集单元"), FigureNode(id="B", label="状态估计单元"), FigureNode(id="C", label="控制处理单元"), FigureNode(id="D", label="电机驱动单元")], edges=[FigureEdge(source="A", target="B"), FigureEdge(source="B", target="C"), FigureEdge(source="C", target="D")], source_ids=source_ids),
        ]

