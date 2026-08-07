"""Disclosure Depth Validator - 技术交底书深度质量检查器。

Checks:
1. Technical Solution Coverage (输入/处理/模块/步骤/输出/数据流/公式)
2. Implementation Coverage (至少一个完整实施例)
3. Figure Coverage (附图是否真正嵌入)
4. Evidence Coverage (关键段落是否有来源支持)
5. Thin Section Warning (过短章节警告)
6. Source Utilization Rate (材料利用率)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


REQUIRED_SUBSECTIONS = {
    "技术方案": ["总体", "参数", "编码", "扩散", "去噪", "解码"],
    "具体实施方式": ["实施例", "数据集", "训练", "生成"],
}

THIN_THRESHOLD_CHARS = 100  # Sections shorter than this trigger warning

SECTION_RECOMMENDED_LENGTHS = {
    "技术方案": 2000,
    "具体实施方式": 1500,
    "背景技术": 500,
    "有益效果": 300,
}


@dataclass
class DepthCheckResult:
    """Result of disclosure depth quality check."""

    overall: str = "PASS"  # PASS | NEEDS_IMPROVEMENT | FAIL
    tech_solution_depth: str = "PASS"
    implementation_depth: str = "PASS"
    background_depth: str = "PASS"
    figure_coverage: str = "PASS"
    evidence_coverage: str = "PASS"
    source_utilization_rate: float = 0.0
    thin_sections: list[str] = field(default_factory=list)
    missing_subsections: list[str] = field(default_factory=list)
    section_char_counts: dict[str, int] = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall": self.overall,
            "tech_solution_depth": self.tech_solution_depth,
            "implementation_depth": self.implementation_depth,
            "background_depth": self.background_depth,
            "figure_coverage": self.figure_coverage,
            "evidence_coverage": self.evidence_coverage,
            "source_utilization_rate": round(self.source_utilization_rate, 3),
            "thin_sections": self.thin_sections,
            "missing_subsections": self.missing_subsections,
            "section_char_counts": self.section_char_counts,
            "issues": self.issues,
            "warnings": self.warnings,
        }


class DisclosureDepthValidator:
    """Validate the depth and coverage of a generated Chinese disclosure."""

    def validate(
        self,
        sections: list[dict],
        total_evidence_chunks: int = 0,
        used_evidence_ids: set | None = None,
        figure_count: int = 0,
        embedded_figure_count: int = 0,
    ) -> DepthCheckResult:
        """Run all depth checks.

        Args:
            sections: List of section dicts with title, paragraphs
            total_evidence_chunks: Total INVENTION_SOURCE evidence chunks available
            used_evidence_ids: Set of evidence IDs actually referenced in disclosure
            figure_count: Number of figure descriptions in disclosure
            embedded_figure_count: Number of figures actually embedded in DOCX
        """
        result = DepthCheckResult()

        # Collect section stats
        for s in sections:
            title = s.get("title", "")
            total_chars = sum(
                len(p.get("text", "")) for p in s.get("paragraphs", [])
            )
            result.section_char_counts[title] = total_chars

        total_chars = sum(result.section_char_counts.values())

        # 1. Technical Solution Coverage
        tech_section = self._find_section(sections, ["技术方案", "6."])
        if tech_section:
            tech_chars = sum(
                len(p.get("text", "")) for p in tech_section.get("paragraphs", [])
            )
            tech_text = " ".join(
                p.get("text", "") for p in tech_section.get("paragraphs", [])
            )

            if tech_chars < SECTION_RECOMMENDED_LENGTHS["技术方案"]:
                result.tech_solution_depth = "NEEDS_IMPROVEMENT"
                result.warnings.append(
                    f"技术方案章节偏短（{tech_chars}字），建议至少{SECTION_RECOMMENDED_LENGTHS['技术方案']}字"
                )
            else:
                result.tech_solution_depth = "PASS"

            # Check for technical flow keywords
            flow_keywords = ["输入", "输出", "步骤", "处理", "数据", "模块"]
            missing_flow = [kw for kw in flow_keywords if kw not in tech_text]
            if len(missing_flow) >= 3:
                result.warnings.append(
                    f"技术方案可能缺少关键描述要素：{', '.join(missing_flow)}"
                )
                if result.tech_solution_depth == "PASS":
                    result.tech_solution_depth = "NEEDS_IMPROVEMENT"
        else:
            result.tech_solution_depth = "FAIL"
            result.issues.append("缺少技术方案章节")

        # 2. Implementation Coverage
        impl_section = self._find_section(sections, ["具体实施方式", "9."])
        if impl_section:
            impl_chars = sum(
                len(p.get("text", "")) for p in impl_section.get("paragraphs", [])
            )
            impl_text = " ".join(
                p.get("text", "") for p in impl_section.get("paragraphs", [])
            )

            if impl_chars < SECTION_RECOMMENDED_LENGTHS["具体实施方式"]:
                result.implementation_depth = "NEEDS_IMPROVEMENT"
                result.warnings.append(
                    f"具体实施方式章节偏短（{impl_chars}字），建议至少{SECTION_RECOMMENDED_LENGTHS['具体实施方式']}字"
                )

            # Check for embodiment markers
            if "实施例" not in impl_text:
                result.warnings.append("具体实施方式中未找到明确标注的实施例")
                result.implementation_depth = "NEEDS_IMPROVEMENT"
        else:
            result.implementation_depth = "FAIL"
            result.issues.append("缺少具体实施方式章节")

        # 3. Background Coverage
        bg_section = self._find_section(sections, ["背景技术", "3."])
        if bg_section:
            bg_chars = sum(
                len(p.get("text", "")) for p in bg_section.get("paragraphs", [])
            )
            if bg_chars < SECTION_RECOMMENDED_LENGTHS["背景技术"]:
                result.background_depth = "NEEDS_IMPROVEMENT"
                result.warnings.append(f"背景技术章节偏短（{bg_chars}字）")

        # 4. Figure Coverage
        if figure_count > 0 and embedded_figure_count == 0:
            result.figure_coverage = "FAIL"
            result.issues.append(
                f"附图说明描述了{figure_count}张图，但Word中未嵌入任何实际图片"
            )
        elif figure_count > embedded_figure_count:
            result.figure_coverage = "NEEDS_IMPROVEMENT"
            result.warnings.append(
                f"附图说明描述{figure_count}张图，实际嵌入{embedded_figure_count}张"
            )
        elif figure_count > 0 and embedded_figure_count >= figure_count:
            result.figure_coverage = "PASS"

        # 5. Thin section warnings
        for title, chars in result.section_char_counts.items():
            if chars < THIN_THRESHOLD_CHARS:
                result.thin_sections.append(f"{title}（{chars}字）")

        if result.thin_sections:
            result.warnings.append(
                f"以下章节内容过少：{', '.join(result.thin_sections)}"
            )

        # 6. Evidence Coverage Rate (0-100%) + Reuse Ratio
        if total_evidence_chunks > 0 and used_evidence_ids:
            # Coverage: what fraction of available invention-source evidence is used
            coverage = min(1.0, len(used_evidence_ids) / total_evidence_chunks)
            result.source_utilization_rate = coverage  # Now 0-100%

            if coverage < 0.25:
                result.evidence_coverage = "NEEDS_IMPROVEMENT"
                result.warnings.append(
                    f"证据覆盖率偏低（{coverage:.1%}），"
                    f"仅使用了{len(used_evidence_ids)}/{total_evidence_chunks}个证据块"
                )
            elif coverage < 0.50:
                result.evidence_coverage = "ADEQUATE"
            else:
                result.evidence_coverage = "PASS"

        # 7. Overall determination
        failures = [
            result.tech_solution_depth,
            result.implementation_depth,
            result.figure_coverage,
        ]
        if "FAIL" in failures:
            result.overall = "FAIL"
        elif (
            "NEEDS_IMPROVEMENT" in failures
            or result.warnings
        ):
            result.overall = "NEEDS_IMPROVEMENT"
        else:
            result.overall = "PASS"

        return result

    def _find_section(
        self, sections: list[dict], keywords: list[str]
    ) -> dict | None:
        """Find section by keywords in title."""
        for s in sections:
            title = s.get("title", "")
            if any(kw in title for kw in keywords):
                return s
        return None


def check_disclosure_depth(
    sections: list[dict],
    total_evidence: int = 0,
    used_evidence: set | None = None,
    figure_count: int = 0,
    embedded_count: int = 0,
) -> dict:
    """Convenience function. Returns dict suitable for JSON serialization."""
    validator = DisclosureDepthValidator()
    result = validator.validate(
        sections, total_evidence, used_evidence, figure_count, embedded_count
    )
    return result.to_dict()
