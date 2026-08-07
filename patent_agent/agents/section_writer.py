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


class ChineseSectionWriter:
    """Generate disclosure sections in Chinese using DeepSeek LLM.

    Takes the deterministic SectionWriter's evidence assembly as input,
    then calls DeepSeek per-section to produce patent-style Chinese text
    while maintaining evidence grounding.
    """

    CHINESE_STYLE_RULES = """
## 中文专利交底书撰写规则（严格遵守）

### 语言
1. 全部使用简体中文。禁止输出英文段落。
2. 技术术语首次出现：中文全称（English Full Name，缩写）
   例如：潜在扩散模型（Latent Diffusion Model，LDM）
   后续统一使用：LDM 或 潜在扩散模型
3. 术语全文统一，不要中英文随机切换。

### 专利表达
4. 禁止学术论文口吻：
   - 禁止：本文提出、本研究表明、我们设计、In this paper
   - 应使用：本技术方案、本发明提供、在一实施方式中
5. 禁止宣传用语：极大、革命性、行业领先、显著优于
6. 使用稳健表达：有利于、能够、可以、表明、实验结果表明

### 事实约束
7. 每个技术陈述必须基于提供的证明材料
8. 不编造任何未在证据中出现的参数、数据、实验结果
9. 缺失信息标注"待发明人补充"或"具体参数可根据实际应用设置"
10. 不擅自增加论文中没有的模块、步骤、公式

### 结构
11. 只输出章节正文，不要输出章节标题（标题由系统自动添加）
12. 输出纯文本段落，每段之间用空行分隔
13. 每个段落聚焦一个技术主题
"""

    def __init__(self, llm_service=None, llm_provider=None):
        """Initialize with optional LLM service or raw provider for DeepSeek calls."""
        self.llm = llm_service
        self.provider = llm_provider

    def convert_to_chinese(
        self,
        content_plan,  # DisclosureContentPlan
        feature_tree: TechnicalFeatureTree,
        understanding,  # TechnicalUnderstandingResult
        evidence_store: EvidenceStore,
        deterministic_sections: list[GroundedSection] | None = None,
    ) -> GroundedDisclosure:
        """Convert disclosure sections to Chinese using DeepSeek.

        When LLM is available, calls DeepSeek per-section for Chinese patent expression.
        Otherwise falls back to deterministic sections.
        """
        sections: list[GroundedSection] = []

        # Build terminology registry from understanding
        terminology = self._build_terminology(understanding)

        for i, sec_plan in enumerate(content_plan.sections):
            # Collect relevant evidence for this section
            relevant_evidence = self._collect_section_evidence(
                sec_plan, feature_tree, evidence_store
            )

            # Get deterministic base text if available
            base_text = ""
            if deterministic_sections and i < len(deterministic_sections):
                base_text = "\n\n".join(
                    getattr(p, "text", "")
                    for p in deterministic_sections[i].paragraphs[:10]
                )

            # Generate Chinese section
            if self.llm is not None and relevant_evidence:
                section = self._generate_chinese_section(
                    sec_plan, feature_tree, understanding,
                    relevant_evidence, terminology, base_text,
                )
            elif deterministic_sections and i < len(deterministic_sections):
                section = deterministic_sections[i]
            else:
                section = GroundedSection(
                    section_id=sec_plan.section_id,
                    title=sec_plan.title_cn,
                    paragraphs=[],
                )

            sections.append(section)

        return GroundedDisclosure(
            title=content_plan.title_cn,
            sections=sections,
        )

    def _build_terminology(self, understanding) -> dict[str, str]:
        """Build Chinese terminology mapping from understanding."""
        terms = {}
        # Motor/LDM specific terms
        defaults = {
            "Latent Diffusion Model": "潜在扩散模型（Latent Diffusion Model，LDM）",
            "LDM": "LDM",
            "Variational Autoencoder": "变分自编码器（Variational Autoencoder，VAE）",
            "VAE": "VAE",
            "Generative Adversarial Network": "生成对抗网络（Generative Adversarial Network，GAN）",
            "GAN": "GAN",
            "U-Net": "U-Net",
            "FID": "FID（Fréchet Inception Distance）",
            "PCA": "PCA（主成分分析）",
            "t-SNE": "t-SNE（t分布随机邻域嵌入）",
            "RGB": "RGB",
            "rotor": "转子",
            "stator": "定子",
            "topology": "拓扑",
            "magnetic barrier": "磁障",
            "permanent magnet": "永磁体",
            "electrical steel": "电工钢",
            "latent space": "潜在空间",
            "diffusion": "扩散",
            "denoising": "去噪",
            "encoder": "编码器",
            "decoder": "解码器",
            "forward diffusion": "前向扩散",
            "reverse denoising": "反向去噪",
        }
        terms.update(defaults)
        return terms

    def _collect_section_evidence(
        self, plan, feature_tree, evidence_store
    ) -> list[dict]:
        """Collect relevant evidence for a section, prioritizing feature-linked evidence."""
        all_chunks = evidence_store.all()
        priority_ids = set(plan.evidence_ids)
        for fid in plan.feature_ids:
            for node in feature_tree.get_all_nodes():
                if node.id == fid:
                    priority_ids.update(node.evidence_ids)

        result = []
        for chunk in all_chunks:
            chunk_dict = chunk.model_dump() if hasattr(chunk, 'model_dump') else chunk
            eid = chunk_dict.get("evidence_id", "")
            scope = chunk_dict.get("scope", "")
            # Skip REFERENCE scope for invention disclosure
            if scope == "REFERENCE":
                continue
            if eid in priority_ids:
                result.insert(0, chunk_dict)
            else:
                result.append(chunk_dict)

        # Limit evidence per section to avoid prompt overflow
        max_evidence_chars = 8000 if plan.target_detail == "exhaustive" else 4000
        total = 0
        limited = []
        for ev in result:
            text = ev.get("raw_text", "") or ev.get("normalized_text", "")
            total += len(text)
            limited.append(ev)
            if total > max_evidence_chars:
                break
        return limited

    def _generate_chinese_section(
        self, plan, feature_tree, understanding,
        relevant_evidence, terminology, base_text,
    ) -> GroundedSection:
        """Call DeepSeek to generate a single Chinese section."""
        prompt = self._build_chinese_section_prompt(
            plan, feature_tree, relevant_evidence, terminology
        )

        try:
            # Use raw provider for free-text Chinese generation
            if self.provider is not None:
                raw_response = self.provider.generate_text(
                    system_prompt=self.CHINESE_STYLE_RULES,
                    user_prompt=prompt,
                )
                chinese_text = raw_response.text if hasattr(raw_response, 'text') else str(raw_response)
            else:
                chinese_text = base_text or "（待通过DeepSeek生成中文内容）"
        except Exception as e:
            # Fallback to evidence base text
            chinese_text = f"（DeepSeek中文生成异常：{e}。以下为原始技术材料：）\n\n{base_text}" if base_text else f"（DeepSeek中文生成异常：{e}）"

        # Parse paragraphs and build GroundedParagraphs with evidence linking
        paragraphs = self._parse_to_paragraphs(
            chinese_text, plan, relevant_evidence, understanding
        )

        return GroundedSection(
            section_id=plan.section_id,
            title=plan.title_cn,
            paragraphs=paragraphs,
        )

    def _build_chinese_section_prompt(
        self, plan, feature_tree, relevant_evidence, terminology,
    ) -> str:
        """Build a focused Chinese-generation prompt for one section."""
        lines = [
            f"请撰写以下专利技术交底书章节的中文正文：",
            f"",
            f"章节：{plan.title_cn}",
            f"目的：{plan.purpose}",
            f"建议段落数：{plan.estimated_paragraphs}",
            f"",
            f"### 需要覆盖的技术特征",
        ]
        for fid in plan.feature_ids[:8]:
            for node in feature_tree.get_all_nodes():
                if node.id == fid:
                    lines.append(f"- {node.label_cn}")
                    if node.description:
                        lines.append(f"  ({node.description})")
                    break

        lines.append("")
        lines.append("### 术语统一要求")
        for eng, cn in list(terminology.items())[:15]:
            lines.append(f"- {eng} → {cn}")

        lines.append("")
        lines.append("### 参考技术材料（英文原文，请转换为中文专利表达）")
        for ev in relevant_evidence[:6]:
            text = (ev.get("raw_text", "") or ev.get("normalized_text", ""))[:400]
            page = ev.get("page", "?")
            lines.append(f"[p{page}] {text}")
            lines.append("")

        lines.append("### 输出")
        lines.append("输出纯中文正文段落，每段之间用空行分隔。不要输出章节标题。")
        return "\n".join(lines)

    def _parse_to_paragraphs(
        self, text: str, plan, relevant_evidence, understanding
    ) -> list[GroundedParagraph]:
        """Parse LLM output text into GroundedParagraphs with evidence linking."""
        paragraphs = []
        # Split by blank lines
        raw_paras = [p.strip() for p in text.split("\n\n") if p.strip()]
        # Filter out non-content lines
        content_paras = [
            p for p in raw_paras
            if len(p) > 20 and not p.startswith("#") and not p.startswith("```")
        ]

        for i, para_text in enumerate(content_paras, 1):
            # Find relevant evidence for this paragraph by keyword overlap
            evidence_ids = self._match_evidence(para_text, relevant_evidence)
            fact_ids = self._match_facts(para_text, understanding)

            paragraphs.append(GroundedParagraph(
                paragraph_id=f"DISC-CN-{plan.section_id}-P{i:03d}",
                section_id=plan.section_id,
                text=para_text,
                evidence_ids=evidence_ids[:5],
                fact_ids=fact_ids[:5],
                derived_from=fact_ids[:3],
                status=EvidenceStatus.INFERRED,  # LLM-generated
                review_status=ReviewStatus.LOCKED,
                human_modified=False,
            ))

        return paragraphs

    @staticmethod
    def _match_evidence(text: str, evidence_list: list[dict]) -> list[str]:
        """Match paragraph text to evidence by keyword overlap."""
        text_lower = text.lower()
        matched = []
        for ev in evidence_list[:20]:
            ev_text = (ev.get("raw_text", "") or "").lower()
            if not ev_text:
                continue
            # Simple keyword overlap
            words = set(ev_text.split()) & set(text_lower.split())
            if len(words) >= 3:
                matched.append(ev.get("evidence_id", ""))
        return matched[:5]

    @staticmethod
    def _match_facts(text: str, understanding) -> list[str]:
        """Match paragraph to technical facts."""
        if understanding is None:
            return []
        text_lower = text.lower()
        matched = []
        facts = getattr(understanding, 'facts', []) or []
        for fact in facts[:20]:
            stmt = getattr(fact, "statement", "").lower()
            if not stmt:
                continue
            words = set(stmt.split()) & set(text_lower.split())
            if len(words) >= 3:
                matched.append(getattr(fact, "fact_id", ""))
        return matched[:5]
