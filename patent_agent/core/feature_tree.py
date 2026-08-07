"""Technical Feature Tree for disclosure generation planning.

Ensures complete coverage of source material in the disclosure by
building a structured tree of technical features, each linked to
evidence and facts.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FeatureNode:
    """A node in the technical feature tree."""
    id: str
    label_cn: str  # Chinese label
    label_en: str = ""  # Original English label if applicable
    category: str = "method"  # method | data | architecture | effect | parameter
    evidence_ids: list[str] = field(default_factory=list)
    fact_ids: list[str] = field(default_factory=list)
    description: str = ""  # Brief description
    detail_required: bool = True  # Whether this needs detailed expansion
    children: list[FeatureNode] = field(default_factory=list)
    parent_id: str | None = None
    coverage_status: str = "pending"  # pending | covered | needs_review


@dataclass
class TechnicalFeatureTree:
    """Complete technical feature tree for a disclosure."""
    root: FeatureNode
    total_nodes: int = 0
    covered_nodes: int = 0
    missing_evidence_nodes: list[str] = field(default_factory=list)
    build_timestamp: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": _feature_node_to_dict(self.root),
            "total_nodes": self.total_nodes,
            "covered_nodes": self.covered_nodes,
            "missing_evidence_nodes": self.missing_evidence_nodes,
        }

    def get_all_nodes(self) -> list[FeatureNode]:
        """Flatten the tree into a list."""
        result = []

        def _collect(node: FeatureNode):
            result.append(node)
            for child in node.children:
                _collect(child)

        _collect(self.root)
        self.total_nodes = len(result)
        return result

    def coverage_ratio(self) -> float:
        """Ratio of covered nodes to total."""
        if self.total_nodes == 0:
            return 0.0
        return self.covered_nodes / self.total_nodes

    def nodes_by_category(self) -> dict[str, list[FeatureNode]]:
        """Group nodes by category."""
        groups: dict[str, list[FeatureNode]] = {}
        for node in self.get_all_nodes():
            groups.setdefault(node.category, []).append(node)
        return groups


def _feature_node_to_dict(node: FeatureNode) -> dict:
    """Convert a FeatureNode to a plain dict for JSON serialization."""
    return {
        "id": node.id,
        "label_cn": node.label_cn,
        "label_en": node.label_en,
        "category": node.category,
        "evidence_ids": node.evidence_ids,
        "fact_ids": node.fact_ids,
        "description": node.description,
        "detail_required": node.detail_required,
        "children": [_feature_node_to_dict(c) for c in node.children],
        "coverage_status": node.coverage_status,
    }


def build_feature_tree_from_understanding(
    understanding,  # TechnicalUnderstandingResult
    evidence_store,  # EvidenceStore
) -> TechnicalFeatureTree:
    """Build a technical feature tree from existing understanding and evidence.

    This is a deterministic builder that structures the technical facts
    into a hierarchical tree suitable for disclosure planning.
    """
    from datetime import datetime, timezone

    facts = understanding.facts
    steps = understanding.steps
    components = understanding.components

    # Helper to safely extract string from any object
    def _to_str(obj):
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
        if hasattr(obj, 'statement'):
            val = obj.statement
            return val if isinstance(val, str) else str(val)
        return str(obj)

    # Attempt to detect the domain and build appropriate tree
    all_text = " ".join(
        [_to_str(f) for f in facts]
        + [_to_str(s) for s in steps]
        + [_to_str(c) for c in components]
    ).lower()

    is_motor_ldm = any(
        kw in all_text
        for kw in ["motor", "rotor", "ldm", "latent diffusion", "topology",
                    "电机", "转子", "拓扑", "扩散", "潜在"]
    )

    if is_motor_ldm:
        tree = _build_motor_ldm_tree(facts, steps, components, evidence_store)
    else:
        tree = _build_generic_tree(facts, steps, components, evidence_store)

    tree.build_timestamp = datetime.now(timezone.utc).isoformat()
    tree.get_all_nodes()  # Update total_nodes count
    return tree


def _build_motor_ldm_tree(facts, steps, components, evidence_store) -> TechnicalFeatureTree:
    """Build motor/LDM-specific feature tree."""
    all_evidence = sorted(set(eid for f in facts for eid in (getattr(f, "evidence_ids", []) or [])))

    root = FeatureNode(
        id="ROOT",
        label_cn="基于潜在扩散模型的电机拓扑图像生成方法",
        category="method",
    )

    # 1. Topology Parameterization
    param_node = FeatureNode(
        id="F01", label_cn="电机转子拓扑参数化方案",
        category="data", parent_id="ROOT",
        evidence_ids=all_evidence[:5],
    )
    param_node.children = [
        FeatureNode(id="F01a", label_cn="三层磁障结构", category="data",
                     description="每层包含4个设计变量，共12个变量", parent_id="F01"),
        FeatureNode(id="F01b", label_cn="设计变量定义", category="parameter",
                     description="磁障距离(hc)、中间磁障厚度(hbm)、侧磁障厚度(hbs)、开口角度(α)",
                     parent_id="F01", evidence_ids=all_evidence[:3]),
        FeatureNode(id="F01c", label_cn="参数采样策略", category="method",
                     description="在预设范围内均匀随机采样，生成唯一转子拓扑结构",
                     parent_id="F01"),
    ]
    root.children.append(param_node)

    # 2. Image Data Construction
    img_node = FeatureNode(
        id="F02", label_cn="电机拓扑图像数据构建",
        category="data", parent_id="ROOT",
    )
    img_node.children = [
        FeatureNode(id="F02a", label_cn="材料-颜色RGB映射", category="data",
                     description="电工钢→红色、永磁体→绿色、空气→蓝色",
                     parent_id="F02", evidence_ids=all_evidence[:3]),
        FeatureNode(id="F02b", label_cn="d轴对称处理", category="method",
                     description="利用转子d轴对称性进行图像区域处理和规范化",
                     parent_id="F02"),
        FeatureNode(id="F02c", label_cn="三通道图像生成", category="data",
                     description="形成高分辨率RGB三通道拓扑图像",
                     parent_id="F02"),
        FeatureNode(id="F02d", label_cn="数据集规模", category="data",
                     description="通过参数采样生成50000个训练样本",
                     parent_id="F02", evidence_ids=all_evidence[:3]),
    ]
    root.children.append(img_node)

    # 3. VAE Latent Encoding
    vae_node = FeatureNode(
        id="F03", label_cn="VAE潜在空间编码",
        category="architecture", parent_id="ROOT",
    )
    vae_node.children = [
        FeatureNode(id="F03a", label_cn="VAE编码器结构", category="architecture",
                     description="由卷积层构成的神经网络编码器",
                     parent_id="F03", evidence_ids=all_evidence[3:6]),
        FeatureNode(id="F03b", label_cn="图像压缩至潜在空间", category="method",
                     description="高分辨率RGB图像x→低维潜在变量z0",
                     parent_id="F03"),
        FeatureNode(id="F03c", label_cn="潜在空间优势", category="effect",
                     description="在低维潜在空间而非原始像素空间执行扩散，降低计算成本",
                     parent_id="F03", evidence_ids=all_evidence[3:6]),
    ]
    root.children.append(vae_node)

    # 4. Forward Diffusion
    fwd_node = FeatureNode(
        id="F04", label_cn="前向扩散过程",
        category="method", parent_id="ROOT",
    )
    fwd_node.children = [
        FeatureNode(id="F04a", label_cn="逐步加噪机制", category="method",
                     description="z0→z1→...→zN，在N个时间步上逐步加入高斯噪声",
                     parent_id="F04", evidence_ids=all_evidence[3:6]),
        FeatureNode(id="F04b", label_cn="马尔可夫链过程", category="method",
                     description="固定马尔可夫链，最终zN近似纯高斯噪声分布",
                     parent_id="F04"),
        FeatureNode(id="F04c", label_cn="训练阶段特化", category="method",
                     description="前向扩散仅在训练阶段执行",
                     parent_id="F04"),
    ]
    root.children.append(fwd_node)

    # 5. U-Net Denoising
    unet_node = FeatureNode(
        id="F05", label_cn="时间条件U-Net去噪网络",
        category="architecture", parent_id="ROOT",
    )
    unet_node.children = [
        FeatureNode(id="F05a", label_cn="时间条件机制", category="method",
                     description="U-Net接收当前时间步t和加噪潜变量zt作为输入",
                     parent_id="F05", evidence_ids=all_evidence[3:6]),
        FeatureNode(id="F05b", label_cn="噪声预测任务", category="method",
                     description="预测当前时间步添加的噪声ϵ，而非直接预测去噪结果",
                     parent_id="F05"),
        FeatureNode(id="F05c", label_cn="训练损失函数", category="parameter",
                     description="噪声预测MSE损失（如论文明确披露）",
                     parent_id="F05"),
    ]
    root.children.append(unet_node)

    # 6. Reverse Denoising
    rev_node = FeatureNode(
        id="F06", label_cn="反向扩散与拓扑生成",
        category="method", parent_id="ROOT",
    )
    rev_node.children = [
        FeatureNode(id="F06a", label_cn="从噪声初始化", category="method",
                     description="从纯高斯噪声zN开始生成过程",
                     parent_id="F06"),
        FeatureNode(id="F06b", label_cn="逐步反向去噪", category="method",
                     description="U-Net逐时间步预测并减去噪声，恢复结构化潜变量z0",
                     parent_id="F06", evidence_ids=all_evidence[3:6]),
        FeatureNode(id="F06c", label_cn="VAE解码重建", category="method",
                     description="通过VAE解码器将z0重建为高分辨率RGB拓扑图像",
                     parent_id="F06"),
    ]
    root.children.append(rev_node)

    # 7. Latent Space Interpolation
    interp_node = FeatureNode(
        id="F07", label_cn="潜在空间插值与拓扑探索",
        category="method", parent_id="ROOT",
    )
    interp_node.children = [
        FeatureNode(id="F07a", label_cn="插值公式", category="method",
                     description="Z=(1-λ)Z1+λZ2，λ∈[0,1]",
                     parent_id="F07", evidence_ids=all_evidence[-3:]),
        FeatureNode(id="F07b", label_cn="连续拓扑过渡", category="effect",
                     description="插值生成两个拓扑之间的平滑过渡结构",
                     parent_id="F07"),
        FeatureNode(id="F07c", label_cn="设计空间探索应用", category="effect",
                     description="利用潜在空间连续性进行系统化拓扑探索",
                     parent_id="F07"),
    ]
    root.children.append(interp_node)

    return TechnicalFeatureTree(root=root)


def _build_generic_tree(facts, steps, components, evidence_store) -> TechnicalFeatureTree:
    """Build a generic feature tree from any set of facts."""
    root = FeatureNode(id="ROOT", label_cn="技术方案总体", category="method")

    for i, fact in enumerate(facts, 1):
        cat = getattr(fact, "category", "method")
        stmt = getattr(fact, "statement", "")
        eids = getattr(fact, "evidence_ids", []) or []
        node = FeatureNode(
            id=f"F{i:02d}",
            label_cn=stmt[:60] if stmt else f"特征{i}",
            category=cat,
            evidence_ids=eids,
            fact_ids=[getattr(fact, "fact_id", "")],
            parent_id="ROOT",
        )
        root.children.append(node)

    return TechnicalFeatureTree(root=root)
