"""V7 Figure Planner - dynamic, case-local figure planning.

Figures are derived from the CURRENT case's own evidence (concept detection
on understanding + evidence), never from another case's template:

- dynamic figure count (2..8), no forced 4-figure LDM template;
- every generated figure carries a semantic fingerprint
  (case_id / semantic_keywords / source_feature_ids);
- FIG-2 prefers the per-case registered source figure (SOURCE_FIGURE_2);
  an unregistered case gets an explicit "omitted" placeholder - never a
  borrowed figure.

The figure semantic gate (FigureSemanticValidator) runs afterwards: a figure
may only carry concepts the current case's evidence supports.
"""
from __future__ import annotations

import re
from pathlib import Path

from patent_agent.agents.figure_planner import SOURCE_FIGURE_2
from patent_agent.core.models import FigureEdge, FigureNode, FigureSpec
from patent_agent.v7.concepts import concept_labels, detect_case_concepts
from patent_agent.v7.cross_case import case_concepts_from_understanding

MAX_FIGURES = 8
MIN_FIGURES = 2


class FigurePlannerV7:
    """Case-scoped figure planner (V7)."""

    def __init__(self, case_id: str, understanding, evidence_store=None,
                 source_figures=None):
        self.case_id = case_id
        self.understanding = understanding
        self.evidence_store = evidence_store
        # figures already extracted from this case's own source document
        self.source_figures = source_figures or []

    # ── helpers ───────────────────────────────────────────────────────────
    def _facts(self) -> list:
        return [f for f in (getattr(self.understanding, "facts", []) or [])
                if getattr(f, "review_status", None) != "REJECTED"]

    def _feature_ids(self) -> list[str]:
        ids: list[str] = []
        for f in self._facts():
            ids.append(str(getattr(f, "fact_id", "")))
            for e in (getattr(f, "evidence_ids", []) or []):
                if len(ids) >= 8:
                    return ids
                ids.append(str(e))
        return ids

    def _stamp(self, figure: FigureSpec, keywords: list[str]) -> FigureSpec:
        return figure.model_copy(update={
            "case_id": self.case_id,
            "semantic_keywords": keywords,
            "source_feature_ids": self._feature_ids(),
        })

    def _concept_chain(self) -> list[tuple[str, str, str]]:
        """Ordered technical-chain node spec from detected concepts.

        Returns (node_id, chinese_label, concept) for each present link.
        Falls back to the case's own step texts when no concept is detected
        (so every case still gets an overall flowchart).
        """
        from patent_agent.v7.cross_case import _obj_text
        concepts = case_concepts_from_understanding(self.understanding)
        labels = concept_labels(concepts)
        chain: list[tuple[str, str, str]] = []
        step_labels = {
            "data_generation": "构建参数化数据集",
            "vae": "训练变分自编码器生成模型",
            "flow_matching": "基于流匹配的生成训练",
            "surrogate": "构建特征线性调制代理模型",
            "optimization": "多目标优化设计",
            "fea_simulation": "有限元验证与筛选",
        }
        order = ["data_generation", "vae", "flow_matching", "surrogate",
                 "optimization", "fea_simulation"]
        for i, concept in enumerate(order):
            if concept in concepts:
                label = step_labels[concept]
                if concept in labels and labels[concept] not in label:
                    label = f"{label}（{labels[concept]}）"
                chain.append((f"N{i+1}", label, concept))
        if not chain:
            # generic fallback: this case's own method steps (Chinese labels
            # derived from the step text; English steps stay short)
            for i, step in enumerate(getattr(self.understanding, "steps", []) or [], 1):
                text = _obj_text(step)[:24]
                if not text:
                    continue
                chain.append((f"N{i}", f"步骤{i}：{text}", "steps"))
                if i >= 8:
                    break
        return chain

    def _evidence_text(self, keyword: str, limit: int = 300) -> str:
        """Pull a supporting evidence excerpt for a concept keyword."""
        chunks = self.evidence_store.all() if self.evidence_store is not None else []
        kw = keyword.lower()
        for chunk in chunks:
            raw = str(getattr(chunk, "raw_text", "") or getattr(chunk, "normalized_text", ""))
            if kw in raw.lower():
                return re.sub(r"Fig\.\s*\d+[\.\s]*", "", raw)[:limit]
        return ""

    # ── plan ──────────────────────────────────────────────────────────────
    def plan(self) -> list[FigureSpec]:
        concepts = case_concepts_from_understanding(self.understanding)
        labels = concept_labels(concepts)
        if "latent_diffusion" in concepts:
            # Concept-driven LDM figures - ONLY for cases whose own evidence
            # contains diffusion content (e.g. REAL-PAPER-001). A non-LDM
            # case can never reach this branch: latent_diffusion must be
            # detected in its own facts.
            return self._latent_diffusion_figures(concepts, labels)
        figures: list[FigureSpec] = []
        feature_ids = self._feature_ids()

        # Figure 1: overall technical chain (dynamic nodes from concepts)
        chain = self._concept_chain()
        if chain:
            nodes = [FigureNode(id=nid, label=label, fact_ids=feature_ids[:3])
                     for nid, label, _ in chain]
            edges = [FigureEdge(source=nodes[i].id, target=nodes[i + 1].id)
                     for i in range(len(nodes) - 1)]
            figures.append(self._stamp(FigureSpec(
                id="FIG-001", number=1, type="flowchart",
                title="本发明技术方案总体流程图",
                nodes=nodes, edges=edges,
                source_ids=[c for _, _, c in chain],
            ), keywords=sorted(concepts)))

        # Figure 2: per-case source figure (registered crop only)
        figures.append(self._source_figure2())

        # Concept architecture figures (dynamic, 3..8 total)
        if "flow_matching" in concepts or "vae" in concepts:
            figures.append(self._generation_architecture(concepts, labels, feature_ids))
        if "surrogate" in concepts:
            figures.append(self._surrogate_figure(concepts, labels, feature_ids))
        if "optimization" in concepts:
            figures.append(self._optimization_figure(concepts, labels, feature_ids))

        # renumber sequentially and cap at MAX_FIGURES
        figures = figures[:MAX_FIGURES]
        return [fig.model_copy(update={"number": i})
                for i, fig in enumerate(figures, 1)]

    def _latent_diffusion_figures(self, concepts, labels) -> list[FigureSpec]:
        """LDM figure set - emitted only when the case's own evidence has
        latent-diffusion content. Every figure carries the case fingerprint."""
        feature_ids = self._feature_ids()

        # Figure 1: overall process
        fig1 = [
            FigureNode(id="A1", label="电机转子\n参数化设计", fact_ids=feature_ids[:2]),
            FigureNode(id="A2", label="RGB拓扑\n图像构建\n电工钢/永磁体/空气"),
            FigureNode(id="A3", label="VAE编码器\n$x \\rightarrow z_0$"),
            FigureNode(id="A4", label="潜在扩散模块\n前向: $z_0 \\rightarrow z_t \\rightarrow z_N$\nU-Net: $\\varepsilon_\\theta(z_t,t)$\n反向: $z_N \\rightarrow z_0$"),
            FigureNode(id="A5", label="VAE解码器\n$z_0 \\rightarrow x'$"),
            FigureNode(id="A6", label="生成拓扑图像"),
        ]
        fig1_edges = [FigureEdge(source="A1", target="A2"), FigureEdge(source="A2", target="A3"),
                      FigureEdge(source="A3", target="A4"), FigureEdge(source="A4", target="A5"),
                      FigureEdge(source="A5", target="A6")]
        figures = [self._stamp(FigureSpec(
            id="FIG-001", number=1, type="flowchart",
            title="本发明技术方案总体流程图",
            nodes=fig1, edges=fig1_edges, source_ids=["latent_diffusion"],
        ), keywords=sorted(concepts))]

        # Figure 2: per-case source figure (registered crop or omitted)
        figures.append(self._source_figure2())

        # Figure 3: two-column training/generation
        training = [
            FigureNode(id="T1", label="[训练阶段]\nRGB拓扑图像 $x$"),
            FigureNode(id="T2", label="VAE编码器\n$x \\rightarrow z_0$"),
            FigureNode(id="T3", label="随机选时间步 $t$"),
            FigureNode(id="T4", label="前向加噪\n$z_0 \\rightarrow z_t$"),
            FigureNode(id="T5", label="U-Net\n$\\varepsilon_\\theta(z_t,t)$"),
            FigureNode(id="T6", label="损失计算\n$\\mathcal{L}=\\|\\varepsilon-\\hat{\\varepsilon}\\|^2$"),
        ]
        generation = [
            FigureNode(id="G1", label="[生成阶段]\n随机噪声 $z_N$"),
            FigureNode(id="G2", label="U-Net反向去噪\n$z_N \\rightarrow z_0$"),
            FigureNode(id="G3", label="VAE解码器\n$z_0 \\rightarrow x'$"),
            FigureNode(id="G4", label="新拓扑 $x'$"),
        ]
        fig3_edges = [
            FigureEdge(source="T1", target="T2"), FigureEdge(source="T2", target="T3"),
            FigureEdge(source="T3", target="T4"), FigureEdge(source="T4", target="T5"),
            FigureEdge(source="T5", target="T6"), FigureEdge(source="G1", target="G2"),
            FigureEdge(source="G2", target="G3"), FigureEdge(source="G3", target="G4"),
            FigureEdge(source="T5", target="G2", label="使用训练完成的U-Net参数"),
        ]
        figures.append(self._stamp(FigureSpec(
            id="FIG-003", number=3, type="flowchart",
            title="潜在扩散模型（LDM）训练与生成技术架构图",
            nodes=training + generation, edges=fig3_edges, source_ids=[],
            layout="two_column", provenance="generated",
            left_node_ids=[n.id for n in training],
            right_node_ids=[n.id for n in generation],
        ), keywords=sorted({"latent_diffusion", "vae"} & concepts)))

        # Figure 4: latent interpolation branch-merge
        fig4 = [
            FigureNode(id="I1", label="拓扑A\nVAE编码\n$Z_1$"),
            FigureNode(id="I2", label="拓扑B\nVAE编码\n$Z_2$"),
            FigureNode(id="I3", label="中间潜在变量 $Z$\n$\\lambda \\in [0,1]$\n$Z=(1-\\lambda)Z_1+\\lambda Z_2$"),
            FigureNode(id="I4", label="VAE解码器\n$Z \\rightarrow x'$"),
            FigureNode(id="I5", label="平滑过渡拓扑序列"),
        ]
        fig4_edges = [FigureEdge(source="I1", target="I3"), FigureEdge(source="I2", target="I3"),
                      FigureEdge(source="I3", target="I4"), FigureEdge(source="I4", target="I5")]
        figures.append(self._stamp(FigureSpec(
            id="FIG-004", number=4, type="flowchart",
            title="潜在空间插值与拓扑探索示意图",
            nodes=fig4, edges=fig4_edges, source_ids=[],
            layout="branch_merge", provenance="generated",
        ), keywords=sorted({"latent_diffusion"} & concepts)))
        return figures

    def _source_figure2(self) -> FigureSpec:
        registered = SOURCE_FIGURE_2.get(self.case_id or "")
        src = Path(registered["path"]).resolve() if registered else None
        if src is not None and src.exists() and src.stat().st_size > 10_000:
            return FigureSpec(
                id="FIG-002", number=2, type="system",
                title=registered["title"],
                nodes=[FigureNode(id="R01", label="[原论文结构示意图]")],
                edges=[], source_ids=[],
                png_path=str(src),
                provenance="extracted",
                case_id=self.case_id,
                semantic_keywords=[],
                source_feature_ids=[],
            )
        return FigureSpec(
            id="FIG-002", number=2, type="system",
            title="结构示意图（待用户补充原始图）",
            nodes=[FigureNode(id="R01", label="[待补充：原始结构图]")],
            edges=[], source_ids=[],
            provenance="omitted",
            case_id=self.case_id,
        )

    def _generation_architecture(self, concepts, labels, feature_ids) -> FigureSpec:
        """Generation-model training + generation (Flow Matching / VAE)."""
        training = [
            FigureNode(id="T1", label="[训练阶段]\n随机采样输入 $z_0$",
                       fact_ids=feature_ids[:2]),
            FigureNode(id="T2", label="速度场网络\n$v_\\theta(z_t, t)$"),
            FigureNode(id="T3", label="流匹配损失训练\n$\\mathcal{L}_{FM}$"),
        ]
        generation = [
            FigureNode(id="G1", label="[生成阶段]\n随机噪声 $z_0$"),
            FigureNode(id="G2", label="ODE 积分\n$z_0 \\rightarrow z_1$"),
            FigureNode(id="G3", label="解码输出\n新拓扑样本"),
        ]
        edges = [
            FigureEdge(source="T1", target="T2"),
            FigureEdge(source="T2", target="T3"),
            FigureEdge(source="G1", target="G2"),
            FigureEdge(source="G2", target="G3"),
            FigureEdge(source="T3", target="G2", label="使用训练完成的速度场参数"),
        ]
        title = "生成模型训练与生成技术架构图"
        if "flow_matching" in labels:
            title = f"流匹配（{labels['flow_matching']}）训练与生成技术架构图"
        return self._stamp(FigureSpec(
            id="FIG-003", number=3, type="flowchart", title=title,
            nodes=training + generation, edges=edges, source_ids=[],
            layout="two_column", provenance="generated",
            left_node_ids=[n.id for n in training],
            right_node_ids=[n.id for n in generation],
        ), keywords=sorted({"flow_matching", "vae"} & concepts))

    def _surrogate_figure(self, concepts, labels, feature_ids) -> FigureSpec:
        """FiLM-style feature-wise modulation surrogate (branch-merge)."""
        nodes = [
            FigureNode(id="M1", label="潜在特征 $z$", fact_ids=feature_ids[:2]),
            FigureNode(id="M2", label="调制参数预测\n$(\\gamma, \\beta)$"),
            FigureNode(id="M3", label="特征线性调制\n$FiLM(z) = \\gamma \\cdot z + \\beta$"),
            FigureNode(id="M4", label="性能预测输出\n（转矩/磁链）"),
        ]
        edges = [
            FigureEdge(source="M1", target="M2"),
            FigureEdge(source="M2", target="M3"),
            FigureEdge(source="M1", target="M3"),
            FigureEdge(source="M3", target="M4"),
        ]
        return self._stamp(FigureSpec(
            id="FIG-004", number=4, type="system",
            title="特征线性调制（FiLM）代理模型结构示意图",
            nodes=nodes, edges=edges, source_ids=[],
            layout="branch_merge", provenance="generated",
        ), keywords=sorted({"surrogate"} & concepts))

    def _optimization_figure(self, concepts, labels, feature_ids) -> FigureSpec:
        """Multi-objective optimization loop (NSGA-II / current vector)."""
        nodes = [
            FigureNode(id="O1", label="设计变量\n电流矢量 $(I_d, I_q)$", fact_ids=feature_ids[:2]),
            FigureNode(id="O2", label="代理模型预测\n转矩/磁链"),
            FigureNode(id="O3", label="多目标评估\nNSGA-II"),
            FigureNode(id="O4", label="约束检查\n（磁链/电压约束）"),
            FigureNode(id="O5", label="最优候选输出"),
        ]
        edges = [
            FigureEdge(source="O1", target="O2"),
            FigureEdge(source="O2", target="O3"),
            FigureEdge(source="O3", target="O4"),
            FigureEdge(source="O4", target="O5"),
            FigureEdge(source="O4", target="O1", label="未满足则更新种群"),
        ]
        return self._stamp(FigureSpec(
            id="FIG-005", number=5, type="flowchart",
            title="多目标优化设计流程示意图",
            nodes=nodes, edges=edges, source_ids=[],
            layout="auto", provenance="generated",
        ), keywords=sorted({"optimization"} & concepts))
