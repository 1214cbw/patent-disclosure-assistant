"""Disclosure Content Planner - plans section-by-section content generation.

Builds a detailed content plan from the TechnicalFeatureTree, ensuring
every feature node maps to a disclosure section with proper evidence.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from patent_agent.core.feature_tree import TechnicalFeatureTree


@dataclass
class SectionPlan:
    """Plan for a single disclosure section."""
    section_id: str
    title_cn: str
    purpose: str  # What this section should achieve
    feature_ids: list[str] = field(default_factory=list)  # FeatureTree node IDs
    evidence_ids: list[str] = field(default_factory=list)
    fact_ids: list[str] = field(default_factory=list)
    figure_refs: list[str] = field(default_factory=list)  # Figure IDs to reference
    equation_refs: list[str] = field(default_factory=list)
    target_detail: str = "standard"  # brief | standard | detailed | exhaustive
    estimated_paragraphs: int = 2
    subsections: list[SectionPlan] = field(default_factory=list)


@dataclass
class DisclosureContentPlan:
    """Complete content plan for generating a disclosure."""
    case_id: str
    title_cn: str
    sections: list[SectionPlan] = field(default_factory=list)
    total_features: int = 0
    covered_features: int = 0
    total_evidence: int = 0
    figure_plan: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        def _section_dict(sp: SectionPlan) -> dict:
            return {
                "section_id": sp.section_id,
                "title_cn": sp.title_cn,
                "purpose": sp.purpose,
                "feature_ids": sp.feature_ids,
                "evidence_ids": sp.evidence_ids,
                "fact_ids": sp.fact_ids,
                "figure_refs": sp.figure_refs,
                "equation_refs": sp.equation_refs,
                "target_detail": sp.target_detail,
                "estimated_paragraphs": sp.estimated_paragraphs,
                "subsections": [_section_dict(s) for s in sp.subsections],
            }

        return {
            "case_id": self.case_id,
            "title_cn": self.title_cn,
            "sections": [_section_dict(s) for s in self.sections],
            "total_features": self.total_features,
            "covered_features": self.covered_features,
            "total_evidence": self.total_evidence,
            "figure_plan": self.figure_plan,
        }

    def coverage_ratio(self) -> float:
        if self.total_features == 0:
            return 0.0
        return self.covered_features / self.total_features

    def save(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = self.to_dict()
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        return path


class DisclosureContentPlanner:
    """Plan disclosure content from a TechnicalFeatureTree."""

    def plan(
        self,
        case_id: str,
        title_cn: str,
        feature_tree: TechnicalFeatureTree,
        understanding,  # TechnicalUnderstandingResult
    ) -> DisclosureContentPlan:
        """Build a complete content plan."""
        all_nodes = feature_tree.get_all_nodes()
        all_nodes_by_id = {n.id: n for n in all_nodes}
        non_root = [n for n in all_nodes if n.parent_id is not None]
        leaf_nodes = [n for n in non_root if not n.children]

        all_evidence = sorted(set(
            eid for n in all_nodes for eid in n.evidence_ids
        ))

        plan = DisclosureContentPlan(
            case_id=case_id,
            title_cn=title_cn,
            total_features=len(non_root),
            covered_features=len(leaf_nodes),
            total_evidence=len(all_evidence),
        )

        # ── Build section plans ──

        # 1. 发明名称
        plan.sections.append(SectionPlan(
            section_id="SEC01", title_cn="一、发明名称",
            purpose="准确、简洁、技术性的发明名称",
            target_detail="brief", estimated_paragraphs=1,
        ))

        # 2. 技术领域
        plan.sections.append(SectionPlan(
            section_id="SEC02", title_cn="二、技术领域",
            purpose="说明本发明所属技术领域和具体应用场景",
            feature_ids=[],
            target_detail="standard", estimated_paragraphs=2,
        ))

        # 3. 背景技术
        plan.sections.append(SectionPlan(
            section_id="SEC03", title_cn="三、背景技术",
            purpose="详细说明技术应用背景、现有技术路线、现有技术不足",
            feature_ids=[],
            target_detail="detailed", estimated_paragraphs=6,
            subsections=[
                SectionPlan(section_id="SEC03a", title_cn="3.1 技术应用背景",
                             purpose="说明该技术为什么存在及其重要性"),
                SectionPlan(section_id="SEC03b", title_cn="3.2 现有主要技术路线",
                             purpose="基于参考材料说明现有生成/设计方法路线"),
                SectionPlan(section_id="SEC03c", title_cn="3.3 现有技术具体不足",
                             purpose="每个不足对应后续技术手段"),
                SectionPlan(section_id="SEC03d", title_cn="3.4 本方案提出的必要性",
                             purpose="自然过渡到发明内容"),
            ],
        ))

        # 4. 发明内容
        plan.sections.append(SectionPlan(
            section_id="SEC04", title_cn="四、发明内容",
            purpose="概述要解决的技术问题、总体构思、技术方案和有益效果",
            target_detail="detailed", estimated_paragraphs=4,
        ))

        # 5. 技术方案详细说明 (THE CORE)
        tech_section = SectionPlan(
            section_id="SEC05", title_cn="五、技术方案详细说明",
            purpose="逐模块、逐步骤详细说明技术方案，是全文最重要部分",
            target_detail="exhaustive", estimated_paragraphs=20,
        )

        # Build subsections from feature tree
        category_order = ["data", "architecture", "method", "parameter", "effect"]
        root_children = feature_tree.root.children

        sub_idx = 1
        for child in root_children:
            sub = SectionPlan(
                section_id=f"SEC05_{sub_idx}",
                title_cn=f"5.{sub_idx} {child.label_cn}",
                purpose=child.description or f"详细说明{child.label_cn}",
                feature_ids=[child.id] + [c.id for c in child.children],
                evidence_ids=child.evidence_ids,
                target_detail="exhaustive",
                estimated_paragraphs=max(3, len(child.children) + 1),
            )
            # Add leaf-level detail
            for leaf in child.children:
                sub.subsections.append(SectionPlan(
                    section_id=f"SEC05_{sub_idx}_{leaf.id}",
                    title_cn=f"  {leaf.label_cn}",
                    purpose=leaf.description,
                    feature_ids=[leaf.id],
                    evidence_ids=leaf.evidence_ids,
                    target_detail="detailed",
                    estimated_paragraphs=2,
                ))
            tech_section.subsections.append(sub)
            sub_idx += 1

        plan.sections.append(tech_section)

        # 6. 附图说明
        figure_features = [n.id for n in non_root if n.category in ("architecture", "method")][:6]
        plan.sections.append(SectionPlan(
            section_id="SEC06", title_cn="六、附图说明",
            purpose="列出所有附图并逐一说明图中内容",
            feature_ids=figure_features,
            target_detail="standard", estimated_paragraphs=6,
        ))

        # 7. 具体实施方式
        impl_section = SectionPlan(
            section_id="SEC07", title_cn="七、具体实施方式",
            purpose="提供可实施的具体实施例，每个实施例包含完整步骤",
            target_detail="exhaustive", estimated_paragraphs=16,
        )
        # V7: embodiments are derived from the case's own feature tree
        # (phases from node categories), never a hardcoded LDM template.
        cn_numerals = ["一", "二", "三", "四", "五", "六", "七", "八", "九", "十"]
        phase_labels = {
            "data": "数据构建", "architecture": "模型结构",
            "method": "处理流程", "parameter": "关键参数",
            "effect": "效果验证",
        }
        for e_idx, child in enumerate(root_children, 1):
            phase = phase_labels.get(child.category, "实施细节")
            cn = cn_numerals[min(e_idx - 1, 9)]
            impl_section.subsections.append(SectionPlan(
                section_id=f"SEC07_{e_idx}",
                title_cn=f"7.{e_idx} 实施例{cn}：{phase}",
                purpose=f"围绕'{child.label_cn}'给出可实施的具体步骤、参数和输出",
                feature_ids=[child.id] + [c.id for c in child.children],
                evidence_ids=child.evidence_ids,
                target_detail="exhaustive", estimated_paragraphs=4,
            ))
        plan.sections.append(impl_section)

        # 8. 建议重点向专利代理机构说明的技术内容
        plan.sections.append(SectionPlan(
            section_id="SEC08", title_cn="八、建议重点向专利代理机构说明的技术内容",
            purpose="以代理师友好列表形式标注核心技术特征和注意事项",
            target_detail="standard", estimated_paragraphs=3,
        ))

        # 9. 待确认信息
        plan.sections.append(SectionPlan(
            section_id="SEC09", title_cn="九、待发明人或代理机构进一步确认的信息",
            purpose="分类列出材料中缺失的技术信息",
            target_detail="standard", estimated_paragraphs=3,
        ))

        # ── Figure Plan ──
        # V7: dynamic from the case's own feature tree (2..4 figures), no
        # hardcoded LDM architecture.
        plan.figure_plan = [{
            "figure_id": "FIG-001", "number": 1,
            "title_cn": "图1 本发明技术方案总体流程图",
            "type": "flowchart", "category": "A_redraw",
            "description": "→".join(n.label_cn[:12] for n in root_children) or "总体流程",
            "feature_ids": [n.id for n in root_children[:6]],
        }]
        data_children = [n for n in root_children if n.category == "data"]
        if data_children:
            data_child = data_children[0]
            plan.figure_plan.append({
                "figure_id": "FIG-002", "number": 2,
                "title_cn": f"图2 {data_child.label_cn[:16]}示意图",
                "type": "system", "category": "A_redraw",
                "description": data_child.description or data_child.label_cn,
                "feature_ids": [data_child.id] + [c.id for c in data_child.children],
            })
        arch = [n for n in root_children if n.category in ("architecture", "method")]
        if arch:
            arch_child = arch[0]
            plan.figure_plan.append({
                "figure_id": "FIG-003", "number": 3,
                "title_cn": f"图3 {arch_child.label_cn[:16]}结构示意图",
                "type": "flowchart", "category": "A_redraw",
                "description": arch_child.description or arch_child.label_cn,
                "feature_ids": [arch_child.id] + [c.id for c in arch_child.children],
            })
        if len(arch) > 1:
            extra = arch[1]
            plan.figure_plan.append({
                "figure_id": "FIG-004", "number": 4,
                "title_cn": f"图4 {extra.label_cn[:16]}流程示意图",
                "type": "flowchart", "category": "A_redraw",
                "description": extra.description or extra.label_cn,
                "feature_ids": [extra.id] + [c.id for c in extra.children],
            })

        return plan
