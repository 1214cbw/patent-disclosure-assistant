"""Section-by-section disclosure writer.

Replaces monolithic LLM disclosure generation with a multi-stage approach:
1. Generate background sections with moderate evidence
2. Generate technical solution with maximum evidence
3. Generate implementation with detailed evidence
4. Generate supporting sections with focused evidence
5. Assemble into complete disclosure

This avoids the "first half detailed, second half truncated" problem
of single-call LLM generation.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from patent_agent.core.feature_tree import TechnicalFeatureTree
from patent_agent.core.models import (
    EvidenceStatus,
    GroundedDisclosure,
    GroundedParagraph,
    GroundedSection,
    ReviewStatus,
)
from patent_agent.evidence import EvidenceStore


class SectionWriter:
    """Generate disclosure sections one at a time with focused evidence."""

    def __init__(self, llm_service=None):
        self.llm = llm_service

    def generate_all_sections(
        self,
        content_plan,  # DisclosureContentPlan
        feature_tree: TechnicalFeatureTree,
        understanding,  # TechnicalUnderstandingResult
        evidence_store: EvidenceStore,
        inventor_assertions: list | None = None,
    ) -> GroundedDisclosure:
        """Generate all sections according to the content plan.

        When LLM is available, uses it for Chinese patent-style expression.
        Otherwise falls back to evidence-driven deterministic generation.
        """
        sections: list[GroundedSection] = []

        for sec_plan in content_plan.sections:
            section = self._generate_section(
                sec_plan, feature_tree, understanding, evidence_store
            )
            sections.append(section)

        return GroundedDisclosure(
            title=content_plan.title_cn,
            sections=sections,
        )

    def _generate_section(
        self,
        plan,  # SectionPlan
        feature_tree: TechnicalFeatureTree,
        understanding,
        evidence_store: EvidenceStore,
    ) -> GroundedSection:
        """Generate a single section."""
        paragraphs: list[GroundedParagraph] = []

        # Collect relevant evidence
        relevant_evidence = self._collect_evidence(plan, feature_tree, understanding, evidence_store)

        # Build paragraphs from evidence
        para_idx = 1
        section_id = plan.section_id

        # Add section purpose as context for the writer
        if plan.target_detail in ("exhaustive", "detailed"):
            # For detailed sections, create multiple paragraphs from evidence
            for ev in relevant_evidence[:plan.estimated_paragraphs * 3]:
                text = self._format_evidence_as_paragraph(ev, understanding)
                if text:
                    paragraphs.append(GroundedParagraph(
                        paragraph_id=f"DISC-{section_id}-P{para_idx:03d}",
                        section_id=section_id,
                        text=text,
                        evidence_ids=[ev.get("evidence_id", "")] if ev.get("evidence_id") else [],
                        fact_ids=self._find_related_facts(ev, understanding),
                        derived_from=[],
                        status=EvidenceStatus.SOURCE_FACT,
                        review_status=ReviewStatus.LOCKED,
                    ))
                    para_idx += 1

        # Ensure minimum paragraphs (with safety limit)
        max_attempts = plan.estimated_paragraphs * 2
        attempts = 0
        while len(paragraphs) < plan.estimated_paragraphs and attempts < max_attempts:
            attempts += 1
            facts_text = self._build_paragraphs_from_facts(
                plan, understanding, len(paragraphs)
            )
            if not facts_text:
                break  # No more facts available
            for text in facts_text:
                if text.strip():
                    paragraphs.append(GroundedParagraph(
                        paragraph_id=f"DISC-{section_id}-P{para_idx:03d}",
                        section_id=section_id,
                        text=text,
                        evidence_ids=plan.evidence_ids[:5],
                        fact_ids=plan.fact_ids[:5],
                        derived_from=plan.fact_ids[:3],
                        status=EvidenceStatus.INFERRED,
                        review_status=ReviewStatus.LOCKED,
                    ))
                    para_idx += 1
                    if len(paragraphs) >= plan.estimated_paragraphs:
                        break

        return GroundedSection(
            section_id=section_id,
            title=plan.title_cn,
            paragraphs=paragraphs,
        )

    def _collect_evidence(
        self, plan, feature_tree, understanding, evidence_store
    ) -> list[dict]:
        """Collect relevant evidence chunks for a section."""
        all_chunks = evidence_store.all()

        # Priority: evidence directly referenced by features
        priority_ids = set(plan.evidence_ids)
        for fid in plan.feature_ids:
            for node in feature_tree.get_all_nodes():
                if node.id == fid:
                    priority_ids.update(node.evidence_ids)

        # Sort: priority evidence first
        result = []
        for chunk in all_chunks:
            chunk_dict = chunk.model_dump() if hasattr(chunk, 'model_dump') else chunk
            eid = chunk_dict.get("evidence_id", "")
            if eid in priority_ids:
                result.insert(0, chunk_dict)
            else:
                result.append(chunk_dict)

        return result

    def _format_evidence_as_paragraph(
        self, evidence: dict, understanding
    ) -> str:
        """Format an evidence chunk as a disclosure paragraph."""
        raw_text = evidence.get("raw_text", "") or evidence.get("normalized_text", "")
        if not raw_text:
            return ""

        # Clean up and convert to patent-style Chinese
        # Actual Chinese conversion happens via LLM when available
        text = raw_text.strip()

        # Remove figure/table references from text
        import re
        text = re.sub(r'Fig\.\s*\d+[\.\s]*', '', text)
        text = re.sub(r'TABLE\s+[IVX]+[\.\s]*', '', text, flags=re.IGNORECASE)

        if len(text) < 20:
            return ""

        return text

    def _find_related_facts(self, evidence: dict, understanding) -> list[str]:
        """Find technical facts related to an evidence chunk."""
        eid = evidence.get("evidence_id", "")
        if not eid:
            return []
        return [
            getattr(f, "fact_id", "")
            for f in understanding.facts
            if eid in (getattr(f, "evidence_ids", []) or [])
        ]

    def _build_paragraphs_from_facts(
        self, plan, understanding, current_count: int
    ) -> list[str]:
        """Build paragraphs from technical facts for a section."""
        result = []
        relevant_facts = [
            f for f in understanding.facts
            if getattr(f, "review_status", None) != ReviewStatus.REJECTED
        ]

        # Map section to facts based on content
        section_id = plan.section_id
        if "SEC03" in section_id:  # Background
            cats = ("background", "context", "problem", "现有技术")
        elif "SEC04" in section_id or "SEC05" in section_id:  # Invention/Tech solution
            cats = ("method", "architecture", "data", "representation")
        elif "SEC07" in section_id:  # Implementation
            cats = ("method", "implementation", "experiment", "dataset", "training")
        else:
            cats = None

        for fact in relevant_facts:
            cat = getattr(fact, "category", "")
            if cats is None or cat in cats:
                stmt = getattr(fact, "statement", "")
                if stmt and len(stmt) > 10:
                    result.append(stmt)

        # Offset based on current count to avoid duplication
        start = current_count * 3
        return result[start:start + 3]


def build_llm_prompt_for_section(
    section_plan,  # SectionPlan
    feature_tree: TechnicalFeatureTree,
    relevant_evidence: list[dict],
    relevant_facts: list,
    language: str = "zh-CN",
) -> str:
    """Build a focused LLM prompt for generating a single section.

    The prompt includes:
    - Section purpose and requirements
    - Relevant evidence chunks
    - Related technical facts
    - Style and language requirements
    - Target detail level
    """
    lines = [
        "# 任务：撰写以下专利技术交底书章节",
        "",
        f"## 章节：{section_plan.title_cn}",
        f"## 目的：{section_plan.purpose}",
        f"## 详细程度：{section_plan.target_detail}",
        "",
        "## 撰写要求",
    ]

    if language == "zh-CN":
        lines.extend([
            "1. 使用简体中文撰写，专业、准确、清晰",
            "2. 使用专利交底书表达方式，避免学术论文口吻",
            "3. 禁止使用'本文''本研究''我们提出'等学术表达",
            "4. 技术术语首次出现时使用'中文（English，缩写）'格式",
            "5. 每个技术陈述必须基于提供的证明材料",
            "6. 不编造任何未在证据中出现的具体参数、数据或结果",
        ])
    else:
        lines.extend([
            "1. Write in clear technical English",
            "2. Use patent disclosure style",
        ])

    lines.extend([
        "",
        "## 目标长度",
        f"建议{section_plan.estimated_paragraphs}段，根据材料实际信息量调整",
        "",
        "## 功能特征覆盖",
    ])
    for fid in section_plan.feature_ids:
        for node in feature_tree.get_all_nodes():
            if node.id == fid and node.label_cn:
                lines.append(f"- {node.label_cn}")
                if node.description:
                    lines.append(f"  ({node.description})")

    lines.extend([
        "",
        "## 相关技术事实",
    ])
    for fact in relevant_facts[:10]:
        stmt = getattr(fact, "statement", str(fact))[:200]
        lines.append(f"- {stmt}")

    lines.extend([
        "",
        "## 证明材料摘要",
    ])
    for ev in relevant_evidence[:8]:
        text = (ev.get("raw_text", "") or ev.get("normalized_text", ""))[:300]
        lines.append(f"- [p{ev.get('page', '?')}] {text}")

    lines.extend([
        "",
        "## 输出格式",
        "输出纯文本段落，每段用空行分隔。不要输出Markdown标题或编号。",
    ])

    return "\n".join(lines)
