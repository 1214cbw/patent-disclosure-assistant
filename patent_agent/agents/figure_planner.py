"""Figure planner V6.4/V7 - layout-aware, case-scoped concept-driven planning.

V7: the old keyword-routed LDM template (_motor_ldm_v64) is removed. All
figure planning delegates to the case-scoped FigurePlannerV7, which derives
figures from the case's OWN evidence concepts (latent diffusion figures only
for cases whose evidence contains diffusion content).
"""
from __future__ import annotations

from patent_agent.core.models import FigureEdge, FigureNode, FigureSpec, TechnicalUnderstandingResult

# V6.7 per-case source figures: only a crop verified against THAT case's own
# source PDF may be used. A case with no registered crop gets an explicit
# "omitted" placeholder - never another case's figure.
SOURCE_FIGURE_2 = {
    "REAL-PAPER-001": {
        "path": "workspace/private_cases/REAL-PAPER-001/extracted_figures/fig2_design_variables_v67.png",
        "title": "转子设计变量标注示意图（来源：原论文）",
    },
    "REAL-PAPER-002": {
        "path": "workspace/private_cases/REAL-PAPER-002/extracted_figures/fig2_rotor_topology_002.png",
        "title": "转子拓扑结构及其方形图像变换示意图（来源：原论文）",
    },
}


class FigurePlanner:
    def run(self, knowledge, case_id: str | None = None) -> list[FigureSpec]:
        return self._from_knowledge(knowledge, case_id=case_id)

    def from_understanding(self, understanding: TechnicalUnderstandingResult, case_id: str | None = None) -> list[FigureSpec]:
        # V7: concept-driven, case-scoped planning (no keyword-routed LDM).
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
        # V7: concept-driven, case-scoped planning (no keyword-routed LDM).
        from patent_agent.v7.figure_planner import FigurePlannerV7
        return FigurePlannerV7(case_id=case_id or "UNKNOWN-CASE",
                               understanding=knowledge).plan()
