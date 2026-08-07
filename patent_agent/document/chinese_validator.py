"""Chinese Disclosure Validator - 中文技术交底书质量检查器。

Checks generated disclosure DOCX for:
1. Chinese section titles (no English residue)
2. Chinese text ratio in body
3. Large English block residue detection
4. Academic paper tone detection
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# Acceptable English abbreviations in Chinese technical disclosure
ACCEPTABLE_ABBREVIATIONS = {
    "GAN", "VAE", "U-Net", "LDM", "FID", "PCA", "t-SNE", "RGB",
    "CNN", "RNN", "LSTM", "BERT", "GPT", "ResNet", "Adam", "SGD",
    "ReLU", "GPU", "CPU", "API", "CSV", "JSON", "XML", "PDF",
    "PNG", "JPG", "SVG", "DOI", "URL", "HTTP", "SSH", "OMML",
    "LaTeX", "Softmax", "Tanh", "Sigmoid", "BatchNorm", "Dropout",
    "MSE", "MAE", "PSNR", "SSIM", "IS", "KL", "ELBO", "MCMC",
    "DDPM", "DDIM", "NCSN", "ViT", "CLIP", "LLM",
}

# Forbidden English section title words
FORBIDDEN_ENGLISH_TITLES = [
    "Technical Field", "Background", "Method", "Results", "Conclusion",
    "Invention Candidate", "Claim", "Evidence", "Technical Understanding",
    "Abstract", "Introduction", "Related Work", "Experiment", "Discussion",
    "Implementation", "Evaluation", "Future Work", "Acknowledgement",
    "References", "Appendix", "Supplementary",
]

# Academic tone patterns to avoid
ACADEMIC_PATTERNS_CN = [
    (r"本文(提出|设计|采用|使用|实现|开发|构建)", "学术论文口吻：'本文...' → 建议改为'本技术方案...'或'本发明...'"),
    (r"本研究(表明|发现|提出|采用)", "学术论文口吻：'本研究...' → 建议改为专利表达"),
    (r"我们(提出|设计|开发|实现|采用|使用)", "学术论文口吻：'我们...' → 建议改为'本方案...'"),
    (r"实验表明", "学术论文口吻：'实验表明...' 可保留在有益效果/具体实施方式中，但避免作为主要论述方式"),
    (r"贡献(在于|包括|如下)", "学术论文口吻：避免讨论'贡献'，改为描述技术方案"),
    (r"本(文|节|章)", "学术论文口吻：避免'本文/本节/本章'等学术表达"),
]

# Patent-style replacements
PATENT_STYLE_PATTERNS = [
    (r"^[（(]\d+[）)]\s*", ""),  # Remove paper-style numbering like (1) (2)
]


@dataclass
class ChineseDisclosureCheckResult:
    """Result of Chinese disclosure quality check."""

    overall: str = "PASS"  # PASS | NEEDS_REVIEW | FAIL
    chinese_title_check: str = "PASS"
    chinese_body_ratio: float = 1.0
    english_residue_blocks: list[str] = field(default_factory=list)
    academic_tone_issues: list[str] = field(default_factory=list)
    missing_sections: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall": self.overall,
            "chinese_title_check": self.chinese_title_check,
            "chinese_body_ratio": round(self.chinese_body_ratio, 3),
            "english_residue_blocks": self.english_residue_blocks[:20],
            "academic_tone_issues": self.academic_tone_issues[:20],
            "missing_sections": self.missing_sections,
            "issues": self.issues[:50],
        }


class ChineseDisclosureValidator:
    """Validate Chinese quality of generated technical disclosure."""

    # Required section titles in Chinese
    REQUIRED_SECTIONS = [
        "发明名称",
        "技术领域",
        "背景技术",
        "技术方案",
        "具体实施方式",
        "有益效果",
    ]

    def __init__(self):
        pass

    def validate_text(self, sections: list[dict]) -> ChineseDisclosureCheckResult:
        """Validate disclosure from structured section data.

        Each section dict should have: title (str), paragraphs (list of {text: str})
        """
        result = ChineseDisclosureCheckResult()

        all_text = ""
        section_titles = []

        for section in sections:
            title = section.get("title", "")
            section_titles.append(title)
            for para in section.get("paragraphs", []):
                text = para.get("text", "") if isinstance(para, dict) else str(para)
                all_text += text + "\n"

        # 1. Check section titles
        english_title_issues = []
        for title in section_titles:
            for forbidden in FORBIDDEN_ENGLISH_TITLES:
                if forbidden.lower() in title.lower():
                    english_title_issues.append(f"英文章节标题残留: '{title}' 包含 '{forbidden}'")

        if english_title_issues:
            result.chinese_title_check = "FAIL"
            result.issues.extend(english_title_issues)
        else:
            result.chinese_title_check = "PASS"

        # 2. Check Chinese body ratio
        result.chinese_body_ratio = self._chinese_ratio(all_text)
        if result.chinese_body_ratio < 0.85:
            result.issues.append(
                f"正文中文比例过低：{result.chinese_body_ratio:.1%}（建议 ≥95%）"
            )

        # 3. Check English residue blocks
        residue = self._find_english_blocks(all_text)
        if residue:
            result.english_residue_blocks = residue
            result.issues.append(f"发现 {len(residue)} 处英文大段残留")

        # 4. Check academic tone
        academic_issues = self._check_academic_tone(all_text)
        if academic_issues:
            result.academic_tone_issues = academic_issues
            result.issues.extend(academic_issues)

        # 5. Check required sections
        missing = self._check_required_sections(section_titles)
        if missing:
            result.missing_sections = missing
            result.issues.append(f"缺少必要章节：{', '.join(missing)}")

        # Determine overall
        if result.chinese_title_check == "FAIL" or result.chinese_body_ratio < 0.70:
            result.overall = "FAIL"
        elif result.issues:
            result.overall = "NEEDS_REVIEW"
        else:
            result.overall = "PASS"

        return result

    def validate_docx_text(self, text: str) -> ChineseDisclosureCheckResult:
        """Validate disclosure from extracted DOCX plain text."""
        # Split text into pseudo-sections
        sections = [{"title": "extracted", "paragraphs": [{"text": text}]}]
        return self.validate_text(sections)

    def _chinese_ratio(self, text: str) -> float:
        """Calculate ratio of Chinese characters in text."""
        if not text:
            return 1.0
        # Count Chinese characters (CJK Unified Ideographs range)
        chinese_chars = sum(1 for ch in text if "一" <= ch <= "鿿" or "㐀" <= ch <= "䶿")
        # Count all meaningful characters (exclude whitespace, punctuation)
        total_chars = sum(1 for ch in text if ch.isalpha() or "一" <= ch <= "鿿")
        if total_chars == 0:
            return 1.0
        return chinese_chars / total_chars

    def _find_english_blocks(self, text: str) -> list[str]:
        """Find large English text blocks (not acceptable abbreviations)."""
        # Split by newlines and find lines with mostly English
        issues = []
        for line in text.splitlines():
            stripped = line.strip()
            if len(stripped) < 20:
                continue
            # Count English words
            words = re.findall(r"[a-zA-Z]{3,}", stripped)
            if len(words) >= 8:
                # Check if these are mostly acceptable abbreviations
                non_abbr = [w for w in words if w not in ACCEPTABLE_ABBREVIATIONS]
                if len(non_abbr) >= 5:
                    issues.append(stripped[:120] + ("..." if len(stripped) > 120 else ""))
        return issues[:10]

    def _check_academic_tone(self, text: str) -> list[str]:
        """Check for academic paper tone patterns."""
        issues = []
        for pattern, message in ACADEMIC_PATTERNS_CN:
            matches = re.findall(pattern, text)
            if matches:
                if isinstance(matches[0], tuple):
                    matched_text = matches[0][0] if matches[0] else str(matches[0])
                else:
                    matched_text = str(matches[0])
                issues.append(f"{message} (匹配: '{matched_text}')")
        return issues

    def _check_required_sections(self, titles: list[str]) -> list[str]:
        """Check that required Chinese section titles are present."""
        titles_text = " ".join(titles)
        missing = []
        for required in self.REQUIRED_SECTIONS:
            if required not in titles_text:
                missing.append(required)
        return missing


def validate_chinese_disclosure(sections: list[dict]) -> dict:
    """Convenience function for Chinese disclosure validation.

    Returns a dict suitable for JSON serialization.
    """
    validator = ChineseDisclosureValidator()
    result = validator.validate_text(sections)
    return result.to_dict()
