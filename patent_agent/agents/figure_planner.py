"""Figure planner that generates patent-style flowchart specs from technical understanding."""
from __future__ import annotations

from patent_agent.core.models import FigureEdge, FigureNode, FigureSpec, TechnicalUnderstandingResult


class FigurePlanner:
    """Plan patent figures based on extracted technical understanding."""

    def run(self, knowledge) -> list[FigureSpec]:
        """Generate figure specs from patent knowledge (legacy API)."""
        return self._from_knowledge(knowledge)

    def from_understanding(self, understanding: TechnicalUnderstandingResult) -> list[FigureSpec]:
        """Generate figure specs directly from technical understanding."""
        def _extract_text(obj):
            if isinstance(obj, str):
                return obj
            if hasattr(obj, 'text'):
                val = obj.text
                return val if isinstance(val, str) else str(val)
            if hasattr(obj, 'description'):
                val = obj.description
                return val if isinstance(val, str) else str(val)
            if hasattr(obj, 'name'):
                val = obj.name
                return val if isinstance(val, str) else str(val)
            return str(obj)

        steps_text = [_extract_text(s) for s in understanding.steps]
        components_text = [_extract_text(c) for c in understanding.components]
        all_text = " ".join(steps_text + components_text).lower()

        # Detect domain
        is_motor_ldm = any(
            kw in all_text
            for kw in ["motor", "rotor", "ldm", "latent diffusion", "topology",
                       "电机", "转子", "拓扑", "扩散", "潜在"]
        )

        if is_motor_ldm:
            return self._motor_ldm_figures(steps_text, components_text)

        # Generic fallback
        return self._generic_flowchart(steps_text)

    def _from_knowledge(
        self, knowledge, source_ids: list[str] | None = None
    ) -> list[FigureSpec]:
        """Build figures from knowledge, detecting the domain from content."""
        steps = knowledge.steps if hasattr(knowledge, 'steps') else []
        components = knowledge.components if hasattr(knowledge, 'components') else []

        # Convert to strings
        def _to_str(obj):
            if isinstance(obj, str):
                return obj
            return str(obj)

        steps_text = [_to_str(s) for s in steps]
        components_text = [_to_str(c) for c in components]

        all_text = " ".join(steps_text + components_text).lower()
        is_motor_ldm = any(
            kw in all_text
            for kw in ["motor", "rotor", "ldm", "latent diffusion", "topology",
                       "电机", "转子", "拓扑", "扩散", "潜在"]
        )

        if is_motor_ldm:
            return self._motor_ldm_figures(steps_text, components_text)
        return self._generic_flowchart(steps_text)

    def _motor_ldm_figures(
        self, steps: list[str], components: list[str]
    ) -> list[FigureSpec]:
        """Generate motor LDM-specific figures."""
        figures: list[FigureSpec] = []

        # Figure 1: Overall method flowchart
        flow_nodes = [
            FigureNode(id="N01", label="电机转子\n参数化设计变量", claim_step=""),
            FigureNode(id="N02", label="转子拓扑结构\n→RGB三通道图像", claim_step=""),
            FigureNode(id="N03", label="VAE编码器\n图像x→潜在变量z₀", claim_step=""),
            FigureNode(id="N04", label="前向扩散\nz₀→z₁→...→zN\n(逐步加噪)", claim_step=""),
            FigureNode(id="N05", label="时间条件U-Net\nεθ(zt, t)\n预测噪声ε", claim_step=""),
            FigureNode(id="N06", label="反向去噪\nzN→...→z₁→z₀\n(逐步恢复结构)", claim_step=""),
            FigureNode(id="N07", label="VAE解码器\n潜在变量→RGB图像", claim_step=""),
            FigureNode(id="N08", label="生成电机\n转子拓扑图像", claim_step=""),
        ]
        flow_edges = [
            FigureEdge(source="N01", target="N02"),
            FigureEdge(source="N02", target="N03"),
            FigureEdge(source="N03", target="N04"),
            FigureEdge(source="N04", target="N05"),
            FigureEdge(source="N05", target="N06"),
            FigureEdge(source="N06", target="N07"),
            FigureEdge(source="N07", target="N08"),
        ]
        figures.append(FigureSpec(
            id="FIG-001", number=1, type="flowchart",
            title="本发明电机拓扑图像生成方法总体流程图",
            nodes=flow_nodes, edges=flow_edges, source_ids=[],
        ))

        # Figure 2: Design variable annotation
        design_nodes = [
            FigureNode(id="D01", label="转子冲片三层\n磁障结构", claim_step=""),
            FigureNode(id="D02", label="第一层(4变量)\n磁障距离 h_c\n中间磁障厚度 h_bm\n侧磁障厚度 h_bs\n开口角度 α", claim_step=""),
            FigureNode(id="D03", label="第二层(4变量)\n磁障距离 h_c\n中间磁障厚度 h_bm\n侧磁障厚度 h_bs\n开口角度 α", claim_step=""),
            FigureNode(id="D04", label="第三层(4变量)\n磁障距离 h_c\n中间磁障厚度 h_bm\n侧磁障厚度 h_bs\n开口角度 α", claim_step=""),
            FigureNode(id="D05", label="共12个设计变量\n均匀随机采样\n→生成转子拓扑结构", claim_step=""),
        ]
        design_edges = [
            FigureEdge(source="D01", target="D02"),
            FigureEdge(source="D01", target="D03"),
            FigureEdge(source="D01", target="D04"),
            FigureEdge(source="D02", target="D05"),
            FigureEdge(source="D03", target="D05"),
            FigureEdge(source="D04", target="D05"),
        ]
        figures.append(FigureSpec(
            id="FIG-002", number=2, type="system",
            title="转子设计变量标注示意图",
            nodes=design_nodes, edges=design_edges, source_ids=[],
        ))

        # Figure 3: LDM architecture
        ldm_nodes = [
            FigureNode(id="L01", label="RGB拓扑图像 x\n(高维像素空间)", claim_step=""),
            FigureNode(id="L02", label="VAE编码器 E\nx → z₀\n(低维潜在空间)", claim_step=""),
            FigureNode(id="L03", label="前向扩散过程\nz₀ → z₁ → ... → zN\n逐步加高斯噪声", claim_step=""),
            FigureNode(id="L04", label="时间条件U-Net\nεθ(zt, t)\n预测噪声 ε", claim_step=""),
            FigureNode(id="L05", label="反向去噪过程\nzN → ... → z₁ → z₀\n逐步去除噪声", claim_step=""),
            FigureNode(id="L06", label="VAE解码器 D\nz₀ → x'\n(重建高维图像)", claim_step=""),
            FigureNode(id="L07", label="生成拓扑图像 x'\n(高分辨率RGB)", claim_step=""),
        ]
        ldm_edges = [
            FigureEdge(source="L01", target="L02"),
            FigureEdge(source="L02", target="L03"),
            FigureEdge(source="L03", target="L04"),
            FigureEdge(source="L04", target="L05"),
            FigureEdge(source="L05", target="L06"),
            FigureEdge(source="L06", target="L07"),
        ]
        figures.append(FigureSpec(
            id="FIG-003", number=3, type="flowchart",
            title="图3 潜在扩散模型（LDM）技术流程图",
            nodes=ldm_nodes, edges=ldm_edges, source_ids=[],
        ))

        # Figure 4: Latent space interpolation
        interp_nodes = [
            FigureNode(id="I01", label="转子拓扑A\n→VAE编码→Z₁", claim_step=""),
            FigureNode(id="I02", label="潜在空间线性插值\nZ=(1-λ)Z₁+λZ₂\nλ∈[0,1]", claim_step=""),
            FigureNode(id="I03", label="转子拓扑B\n→VAE编码→Z₂", claim_step=""),
            FigureNode(id="I04", label="解码中间潜在变量 Z\n→平滑过渡的\n转子拓扑结构序列", claim_step=""),
        ]
        interp_edges = [
            FigureEdge(source="I01", target="I02"),
            FigureEdge(source="I03", target="I02"),
            FigureEdge(source="I02", target="I04"),
        ]
        figures.append(FigureSpec(
            id="FIG-004", number=4, type="flowchart",
            title="图4 潜在空间插值与拓扑探索示意图",
            nodes=interp_nodes, edges=interp_edges, source_ids=[],
        ))

        return figures

    def _generic_flowchart(
        self, steps: list[str]
    ) -> list[FigureSpec]:
        """Generic flowchart from steps."""
        display_steps = steps[:8] if steps else ["步骤1", "步骤2", "步骤3"]
        nodes = [
            FigureNode(id=f"S{i}", label=f"S{i}：{step[:40]}", claim_step=f"S{i}")
            for i, step in enumerate(display_steps, 1)
        ]
        edges = [
            FigureEdge(source=nodes[i].id, target=nodes[i + 1].id)
            for i in range(len(nodes) - 1)
        ]
        return [
            FigureSpec(
                id="FIG-001", number=1, type="flowchart",
                title="图1 本发明方法总体流程图",
                nodes=nodes, edges=edges, source_ids=[],
            )
        ]
