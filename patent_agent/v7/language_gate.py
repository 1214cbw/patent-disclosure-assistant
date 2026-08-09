"""V7 Chinese Patent Language Gate.

PATENT_OUTPUT_LANGUAGE=zh-CN: every final patent deliverable must be Chinese
regardless of source material language. This validator runs BEFORE a stage is
saved (p1_disclosure, p1_claims, figure captions, agency notes, pending
questions). An English-bodied disclosure must never reach the DOCX renderer.

English is allowed only for: first-occurrence terms "中文（English，缩写）",
abbreviations, math variables, model numbers, material grades, library names,
units. Whole English sentences are a LANGUAGE_GATE_FAILED.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from patent_agent.document.chinese_validator import ACCEPTABLE_ABBREVIATIONS

# General computing/unit vocabulary. Case technical tokens are injected from
# the current evidence registry through ``registered_tokens``.
GENERAL_ABBREVIATIONS = ACCEPTABLE_ABBREVIATIONS | {
    "GPU", "CPU", "IEEE", "Python", "min", "max", "Hz", "kHz", "MHz",
}

ENGLISH_WORD = re.compile(r"[A-Za-z]{3,}")
CJK_CHAR = re.compile(r"[一-鿿]")
LATIN_CHAR = re.compile(r"[A-Za-z]")
GREEK_CHAR = re.compile(r"[Ͱ-Ͽἀ-῿]")
HTML_TAG = re.compile(r"</?[A-Za-z][^>]*>")
LATEX_MATH = re.compile(r"\\\([^)]*\\\)|\\\[[^]]*\\\]|\$[^$]+\$", re.S)

# First-occurrence term pattern "中文（English Full Name，缩写）": a parenthetical
# group of pure-English content whose final segment (after ，or ,) is a symbol
# (abbreviation, math variable, Greek letter). The mandate allows exactly this
# pattern, so the gate strips it before counting English words.
PAREN_GROUP = re.compile(r"[（(]([^（()）]*)[）)]")
PAREN_SEP = re.compile(r"[，,]")


def _clean_html(text: str) -> str:
    """Convert LLM-escaped sub/sup markup to plain formula notation and drop
    any stray tags: A<sub>z</sub>=0 -> A_z=0, z<sub>1</sub> -> z_1, so tag
    words (sub/sup) never count as English and the docx text stays clean."""
    text = re.sub(r"<sub>([^<]*)</sub>", r"_\1", text)
    text = re.sub(r"<sup>([^<]*)</sup>", r"^\1", text)
    return HTML_TAG.sub("", text)


def _is_symbol_tail(token: str) -> bool:
    """Symbol-like tail of a first-occurrence expansion: abbreviation-like
    (>= 2 letters with >= 2 uppercase: VAE, FiLM, NSGA-II, PMa-SynRM, FlowV AE
    artifacts), subscript math vars (i_d, P_n, z_1), or Greek letters (θ)."""
    letters = re.findall(r"[A-Za-z]", token)
    if len(letters) >= 2 and sum(1 for c in letters if c.isupper()) >= 2:
        return True
    if "_" in token and len(letters) >= 1:
        return True
    return bool(GREEK_CHAR.search(token))


def _strip_first_occurrence(text: str) -> str:
    """Remove 中文（English，缩写） expansions before English-word counting.

    Strips parenthetical groups that are pure English (no CJK) and end in a
    symbol-like segment - exactly the mandated first-occurrence shape - plus
    short CJK-attached glosses like 转子拓扑（rotor topology）. A parenthetical
    English sentence (long, or with a period) stays countable.
    """
    text = _clean_html(text)

    def repl(match: re.Match) -> str:
        inner = match.group(1)
        if CJK_CHAR.search(inner):
            return match.group(0)
        parts = [p.strip() for p in PAREN_SEP.split(inner) if p.strip()]
        if parts and _is_symbol_tail(parts[-1]):
            return ""
        words = ENGLISH_WORD.findall(inner)
        before = text[match.start() - 1] if match.start() > 0 else ""
        if len(words) <= 8 and "." not in inner and CJK_CHAR.match(before):
            return ""  # short CJK-attached gloss without an abbreviation
        return match.group(0)
    return PAREN_GROUP.sub(repl, text)

# A paragraph is "English-bodied" if it has at least this many English words.
EN_BLOCK_MIN_WORDS = 6
# ...and at least this many words that are not whitelisted abbreviations.
# 6 (not 4): LLM output carries a few English artifacts (based/suffix words,
# mangled formula fragments); a genuine English sentence has many more.
EN_BLOCK_MIN_NON_ABBR = 6
# Paragraphs with few letters (formula fragments) are skipped by the ratio check.
MIN_LETTERS_FOR_RATIO = 30
# Minimum CJK ratio for prose paragraphs (formula-bearing Chinese prose still
# stays well above this; pure English prose is far below).
MIN_PROSE_CJK_RATIO = 0.30


@dataclass
class LanguageGateResult:
    passed: bool = True
    english_paragraphs: list[str] = field(default_factory=list)
    english_issues: list[str] = field(default_factory=list)
    cjk_ratio: float = 0.0
    title_cjk_ok: bool = True
    issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "cjk_ratio": round(self.cjk_ratio, 3),
            "english_paragraphs": self.english_paragraphs[:10],
            "issues": self.issues[:20],
        }


class ChinesePatentLanguageValidator:
    """Native-Chinese language gate for patent content (V7)."""

    def __init__(self, min_prose_ratio: float = MIN_PROSE_CJK_RATIO,
                 registered_tokens: set[str] | None = None):
        self.min_prose_ratio = min_prose_ratio
        self.acceptable_abbreviations = GENERAL_ABBREVIATIONS | set(registered_tokens or set())

    def validate_paragraph(self, text: str) -> tuple[bool, str | None]:
        """Return (is_chinese_ok, english_block_text)."""
        if not text.strip():
            return True, None
        # Formula bodies may contain LaTeX command names (mathbf, frac, ...)
        # but are not English prose. Formula integrity is enforced separately.
        cleaned = LATEX_MATH.sub("", _strip_first_occurrence(text))
        words = ENGLISH_WORD.findall(cleaned)
        if len(words) < EN_BLOCK_MIN_WORDS:
            return True, None
        non_abbr = [w for w in words
                    if w not in self.acceptable_abbreviations and not _is_symbol_tail(w)]
        if len(non_abbr) < EN_BLOCK_MIN_NON_ABBR:
            return True, None
        return False, text.strip()[:160]

    def validate_texts(self, texts: list[str], *, context: str = "content") -> LanguageGateResult:
        """Validate a list of paragraph texts."""
        result = LanguageGateResult()
        letters = 0
        cjk = 0
        for text in texts:
            letters += len(LATIN_CHAR.findall(text))
            cjk += len(CJK_CHAR.findall(text))
            ok, block = self.validate_paragraph(text)
            if not ok:
                result.english_paragraphs.append(block)
                result.english_issues.append(
                    f"{context}发现英文正文段落: {block}"
                )
        result.cjk_ratio = cjk / max(1, letters + cjk)
        if result.english_issues:
            result.passed = False
            result.issues.extend(result.english_issues)
        return result

    def validate_title(self, title: str) -> bool:
        """A patent title must contain Chinese characters."""
        return bool(CJK_CHAR.search(title))

    def validate_disclosure(
        self,
        disclosure,
        *,
        context: str = "p1_disclosure",
    ) -> LanguageGateResult:
        """Validate a GroundedDisclosure (sections -> paragraphs + title)."""
        texts: list[str] = []
        heading_issues: list[str] = []
        for section in getattr(disclosure, "sections", []) or []:
            heading = str(section.title)
            texts.append(heading)
            cleaned_heading = _strip_first_occurrence(heading)
            raw_words = [word for word in ENGLISH_WORD.findall(cleaned_heading)
                         if word not in GENERAL_ABBREVIATIONS and not _is_symbol_tail(word)]
            if raw_words:
                heading_issues.append(
                    f"{context}章节标题含未中文化类别词: {heading[:100]}"
                )
            for paragraph in getattr(section, "paragraphs", []) or []:
                texts.append(str(getattr(paragraph, "text", "")))
        result = self.validate_texts(texts, context=context)
        if heading_issues:
            result.passed = False
            result.issues.extend(heading_issues)
        result.title_cjk_ok = self.validate_title(str(getattr(disclosure, "title", "")))
        if not result.title_cjk_ok:
            result.passed = False
            result.issues.append(f"{context}发明名称不是中文: {str(getattr(disclosure, 'title', ''))[:60]}")
        return result

    def validate_claims(self, claims, *, context: str = "p1_claims") -> LanguageGateResult:
        texts: list[str] = []
        for claim in getattr(claims, "claims", []) or []:
            texts.append(str(getattr(claim, "rendered_text", "")))
            for feature in getattr(claim, "features", []) or []:
                texts.append(str(getattr(feature, "text", "")))
        result = self.validate_texts(texts, context=context)
        result.title_cjk_ok = self.validate_title(str(getattr(claims, "title", "")))
        if not result.title_cjk_ok:
            result.passed = False
            result.issues.append(f"{context}发明名称不是中文")
        return result

    def validate_figure_captions(self, figures: list) -> LanguageGateResult:
        texts = [str(getattr(f, "title", "")) for f in figures]
        return self.validate_texts(texts, context="figure_captions")
