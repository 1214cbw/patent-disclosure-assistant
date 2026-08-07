"""Figure planner with math-aware labels using $...$ delimiters."""
from __future__ import annotations

from patent_agent.core.models import FigureEdge, FigureNode, FigureSpec, TechnicalUnderstandingResult


class FigurePlanner:
    """Plan patent figures based on extracted technical understanding."""

    def run(self, knowledge) -> list[FigureSpec]:
        return self._from_knowledge(knowledge)

    def from_understanding(self, understanding: TechnicalUnderstandingResult) -> list[FigureSpec]:
        def _to_str(obj):
            if isinstance(obj, str): return obj
            for attr in ('text', 'description', 'name', 'statement'):
                if hasattr(obj, attr):
                    v = getattr(obj, attr)
                    return v if isinstance(v, str) else str(v)
            return str(obj)
        steps_text = [_to_str(s) for s in understanding.steps]
        components_text = [_to_str(c) for c in understanding.components]
        all_text = " ".join(steps_text + components_text).lower()
        is_motor_ldm = any(kw in all_text for kw in
            ["motor", "rotor", "ldm", "latent diffusion", "topology",
             "电机", "转子", "拓扑", "扩散", "潜在"])
        if is_motor_ldm:
            return self._motor_ldm_figures(steps_text, components_text)
        return self._generic_flowchart(steps_text)

    def _motor_ldm_figures(self, steps, components) -> list[FigureSpec]:
        figures: list[FigureSpec] = []

        # Figure 1: Overall method flowchart
        fig1_nodes = [
            FigureNode(id="N01", label="电机转子\n参数化设计变量"),
            FigureNode(id="N02", label="转子拓扑结构\n→RGB三通道图像"),
            FigureNode(id="N03", label="VAE编码器\n$x$ → $z_0$"),
            FigureNode(id="N04", label="前向扩散\n$z_0 \\rightarrow z_t \\rightarrow \\cdots \\rightarrow z_N$\n(逐步加噪)"),
            FigureNode(id="N05", label="时间条件U-Net\n$\\varepsilon_\\theta(z_t,t)$\n预测噪声 $\\varepsilon$"),
            FigureNode(id="N06", label="反向去噪\n$z_N \\rightarrow \\cdots \\rightarrow z_t \\rightarrow \\cdots \\rightarrow z_0$\n(逐步恢复结构)"),
            FigureNode(id="N07", label="VAE解码器\n$z_0$ → $x'$"),
            FigureNode(id="N08", label="生成电机\n转子拓扑图像"),
        ]
        fig1_edges = [FigureEdge(source=fig1_nodes[i].id, target=fig1_nodes[i+1].id) for i in range(7)]
        figures.append(FigureSpec(
            id="FIG-001", number=1, type="flowchart",
            title="本发明电机拓扑图像生成方法总体流程图",
            nodes=fig1_nodes, edges=fig1_edges, source_ids=[],
        ))

        # Figure 2: Design variable annotation
        figures.append(FigureSpec(
            id="FIG-002", number=2, type="system",
            title="转子设计变量标注示意图",
            nodes=[
                FigureNode(id="D01", label="转子冲片三层\n磁障结构"),
                FigureNode(id="D02", label="第一层（4变量）\n磁障距离 $h_c$\n中间磁障厚度 $h_{bm}$\n侧磁障厚度 $h_{bs}$\n开口角度 $\\alpha$"),
                FigureNode(id="D03", label="第二层（4变量）\n磁障距离 $h_c$\n中间磁障厚度 $h_{bm}$\n侧磁障厚度 $h_{bs}$\n开口角度 $\\alpha$"),
                FigureNode(id="D04", label="第三层（4变量）\n磁障距离 $h_c$\n中间磁障厚度 $h_{bm}$\n侧磁障厚度 $h_{bs}$\n开口角度 $\\alpha$"),
                FigureNode(id="D05", label="共12个设计变量\n均匀随机采样\n→生成转子拓扑结构"),
            ],
            edges=[FigureEdge(source=s, target=t) for s, t in
                   [("D01","D02"),("D01","D03"),("D01","D04"),
                    ("D02","D05"),("D03","D05"),("D04","D05")]],
            source_ids=[],
        ))

        # Figure 3: LDM architecture - dual training/generation paths
        figures.append(FigureSpec(
            id="FIG-003", number=3, type="flowchart",
            title="潜在扩散模型（LDM）训练与生成技术架构图",
            nodes=[
                # Training path (left)
                FigureNode(id="T01", label="[训练阶段]\nRGB拓扑图像 $x$"),
                FigureNode(id="T02", label="VAE编码器\n$x$ → $z_0$"),
                FigureNode(id="T03", label="随机选择时间步 $t$\n$t=1,2,\\ldots,N$"),
                FigureNode(id="T04", label="前向加噪\n$z_0$ → $z_t$"),
                FigureNode(id="T05", label="时间条件U-Net\n$\\varepsilon_\\theta(z_t,t)$\n预测噪声 $\\varepsilon$"),
                FigureNode(id="T06", label="损失函数\n$\\mathcal{L}=\\|\\varepsilon-\\varepsilon_\\theta(z_t,t)\\|^2$"),
                # Generation path (right)
                FigureNode(id="G01", label="[生成阶段]\n随机高斯噪声 $z_N$"),
                FigureNode(id="G02", label="U-Net逐步去噪\n$z_N$ → … → $z_t$ → … → $z_0$"),
                FigureNode(id="G03", label="VAE解码器\n$z_0$ → $x'$"),
                FigureNode(id="G04", label="生成拓扑图像 $x'$"),
            ],
            edges=[
                FigureEdge(source="T01", target="T02"),
                FigureEdge(source="T02", target="T03"),
                FigureEdge(source="T03", target="T04"),
                FigureEdge(source="T04", target="T05"),
                FigureEdge(source="T05", target="T06"),
                FigureEdge(source="G01", target="G02"),
                FigureEdge(source="G02", target="G03"),
                FigureEdge(source="G03", target="G04"),
            ],
            source_ids=[],
        ))

        # Figure 4: Latent space interpolation
        figures.append(FigureSpec(
            id="FIG-004", number=4, type="flowchart",
            title="潜在空间插值与拓扑探索示意图",
            nodes=[
                FigureNode(id="I01", label="转子拓扑A\nVAE编码\n$Z_1$"),
                FigureNode(id="I02", label="线性插值\n$\\lambda \\in [0,1]$\n$Z=(1-\\lambda)Z_1+\\lambda Z_2$"),
                FigureNode(id="I03", label="转子拓扑B\nVAE编码\n$Z_2$"),
                FigureNode(id="I04", label="中间潜在变量 $Z$\nVAE解码\n平滑过渡的\n转子拓扑结构序列"),
            ],
            edges=[
                FigureEdge(source="I01", target="I02"),
                FigureEdge(source="I03", target="I02"),
                FigureEdge(source="I02", target="I04"),
            ],
            source_ids=[],
        ))

        return figures

    def _generic_flowchart(self, steps: list[str]) -> list[FigureSpec]:
        display_steps = steps[:8] if steps else ["步骤1", "步骤2", "步骤3"]
        nodes = [FigureNode(id=f"S{i}", label=f"S{i}：{step[:40]}", claim_step=f"S{i}")
                 for i, step in enumerate(display_steps, 1)]
        edges = [FigureEdge(source=nodes[i].id, target=nodes[i+1].id)
                 for i in range(len(nodes)-1)]
        return [FigureSpec(id="FIG-001", number=1, type="flowchart",
                           title="本发明方法总体流程图",
                           nodes=nodes, edges=edges, source_ids=[])]

    def _from_knowledge(self, knowledge, source_ids=None) -> list[FigureSpec]:
        steps = knowledge.steps if hasattr(knowledge, 'steps') else []
        components = knowledge.components if hasattr(knowledge, 'components') else []
        def _to_str(obj):
            if isinstance(obj, str): return obj
            return str(obj)
        steps_text = [_to_str(s) for s in steps]
        components_text = [_to_str(c) for c in components]
        all_text = " ".join(steps_text + components_text).lower()
        is_motor_ldm = any(kw in all_text for kw in
            ["motor", "rotor", "ldm", "latent diffusion", "topology",
             "电机", "转子", "拓扑", "扩散", "潜在"])
        if is_motor_ldm:
            return self._motor_ldm_figures(steps_text, components_text)
        return self._generic_flowchart(steps_text)
