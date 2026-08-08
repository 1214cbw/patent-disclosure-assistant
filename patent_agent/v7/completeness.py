"""V7 disclosure completeness, grounding and title validators."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# ── TechnicalDisclosureDocument schema (semantic sections) ─────────────────
# Section numbering may vary by template; matching is semantic (keywords).
REQUIRED_SEMANTIC_SECTIONS: list[tuple[str, list[str]]] = [
    ("发明名称", ["发明名称", "发明名"]),
    ("技术领域", ["技术领域"]),
    ("背景技术", ["背景技术", "背景"]),
    ("发明内容", ["发明内容"]),
    ("技术方案", ["技术方案", "技术方案详细说明"]),
    ("附图说明", ["附图说明", "附图"]),
    ("具体实施方式", ["具体实施方式", "实施方式", "实施例"]),
    ("代理机构说明", ["代理机构", "代理师", "重点向专利代理"]),
    ("待确认信息", ["待确认", "待发明人", "进一步确认"]),
]

CJK = re.compile(r"[一-鿿]")


@dataclass
class CompletenessResult:
    passed: bool = True
    missing: list[str] = field(default_factory=list)
    present: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"passed": self.passed, "missing": self.missing, "present": self.present}


class DisclosureCompletenessValidator:
    """All required semantic sections of a TechnicalDisclosureDocument."""

    def validate(self, disclosure) -> CompletenessResult:
        titles = []
        for section in getattr(disclosure, "sections", []) or []:
            title = str(getattr(section, "title", ""))
            titles.append(title)
            # subsections folded into their parent (发明内容 4.x etc.)
            for sub in getattr(section, "subsections", []) or []:
                titles.append(str(getattr(sub, "title", "")))
        titles_text = "\n".join(titles)
        result = CompletenessResult()
        for name, keywords in REQUIRED_SEMANTIC_SECTIONS:
            if any(kw in titles_text for kw in keywords):
                result.present.append(name)
            else:
                result.missing.append(name)
        result.passed = not result.missing
        return result


@dataclass
class GroundingResult:
    passed: bool = True
    unsupported: list[str] = field(default_factory=list)
    total_paragraphs: int = 0

    def to_dict(self) -> dict:
        return {"passed": self.passed, "unsupported": self.unsupported[:20],
                "total_paragraphs": self.total_paragraphs}


class UnsupportedParagraphValidator:
    """Every core technical paragraph must link to fact/evidence/feature ids.

    Section keywords for core technical content: 技术方案 / 具体实施方式 /
    实施例 / 附图说明.
    """

    CORE_SECTION_KEYWORDS = ("技术方案", "具体实施方式", "实施方式", "实施例", "附图说明")

    def validate(self, disclosure) -> GroundingResult:
        result = GroundingResult()
        for section in getattr(disclosure, "sections", []) or []:
            title = str(getattr(section, "title", ""))
            if not any(kw in title for kw in self.CORE_SECTION_KEYWORDS):
                continue
            for paragraph in getattr(section, "paragraphs", []) or []:
                result.total_paragraphs += 1
                text = str(getattr(paragraph, "text", ""))
                # Figure caption paragraphs (附图说明) reference figures, not facts;
                # they are grounded via figure.source_ids - treat as linked.
                if "图" in title and (not text or text.startswith("图")):
                    continue
                fact_ids = getattr(paragraph, "fact_ids", []) or []
                evidence_ids = getattr(paragraph, "evidence_ids", []) or []
                derived = getattr(paragraph, "derived_from", []) or []
                if not (fact_ids or evidence_ids or derived):
                    result.unsupported.append(
                        f"{title}: {text[:120]}"
                    )
        result.passed = not result.unsupported
        return result


@dataclass
class TitleResult:
    passed: bool = True
    title: str = ""
    length: int = 0
    issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"passed": self.passed, "title": self.title, "length": self.length,
                "issues": self.issues}


class PatentTitleValidator:
    """Chinese patent title: concise, technically accurate, <= max chars.

    Default limit follows the agency template convention (25 Chinese chars);
    configurable via Settings.patent_title_max_chars.
    """

    def __init__(self, max_cjk_chars: int = 25):
        self.max_cjk_chars = max_cjk_chars

    def validate(self, title: str) -> TitleResult:
        result = TitleResult(title=title)
        result.length = len(CJK.findall(title))
        if result.length == 0:
            result.passed = False
            result.issues.append("发明名称不包含中文字符")
        if result.length > self.max_cjk_chars:
            result.passed = False
            result.issues.append(
                f"发明名称过长：{result.length} 个汉字（上限 {self.max_cjk_chars}）"
            )
        return result
