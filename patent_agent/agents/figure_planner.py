"""Legacy facade for the evidence-driven figure planner."""
from __future__ import annotations

from patent_agent.core.models import FigureEdge, FigureNode, FigureSpec, TechnicalUnderstandingResult

class FigurePlanner:
    def run(self, knowledge, case_id: str | None = None) -> list[FigureSpec]:
        return self._from_knowledge(knowledge, case_id=case_id)

    def from_understanding(self, understanding: TechnicalUnderstandingResult, case_id: str | None = None) -> list[FigureSpec]:
        from patent_agent.v7.figure_planner import FigurePlannerV7
        return FigurePlannerV7(case_id=case_id or "UNKNOWN-CASE",
                               understanding=understanding).plan()

    def _generic_flowchart(self, steps: list[str]) -> list[FigureSpec]:
        display_steps = steps[:8] if steps else ["步骤1","步骤2","步骤3"]
        nodes = [FigureNode(id=f"S{i}", label=f"S{i}：{step[:40]}", claim_step=f"S{i}")
                 for i, step in enumerate(display_steps, 1)]
        edges = [FigureEdge(source=nodes[i].id, target=nodes[i+1].id)
                 for i in range(len(nodes)-1)]
        return [FigureSpec(id="FIG-001", number=1, type="flowchart",
                           title="本发明方法总体流程图",
                           nodes=nodes, edges=edges, source_ids=[])]

    def _from_knowledge(self, knowledge, source_ids=None, case_id: str | None = None) -> list[FigureSpec]:
        from patent_agent.v7.figure_planner import FigurePlannerV7
        return FigurePlannerV7(case_id=case_id or "UNKNOWN-CASE",
                               understanding=knowledge).plan()
