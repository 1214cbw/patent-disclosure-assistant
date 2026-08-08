"""V7 cross-case isolation validators.

- CrossCaseContaminationValidator: an output may not use concepts that belong
  to ANOTHER case's fingerprint unless the current case's own evidence
  supports them.
- PlaceholderLeakValidator: fixture/demo/template phrases never enter output.
- FigureSemanticValidator: each generated figure's semantic keywords must be
  supported by the current case's detected concepts.
- FormulaScopeValidator: every display equation must originate from the
  current case's understanding (case-local formula registry).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from patent_agent.v7.concepts import (
    CONCEPT_FAMILIES,
    detect_case_concepts,
    fixture_violations,
    forbidden_concepts_for,
)


@dataclass
class ContaminationResult:
    passed: bool = True
    foreign_concepts: list[str] = field(default_factory=list)
    details: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"passed": self.passed, "foreign_concepts": self.foreign_concepts,
                "details": self.details[:20]}


def _texts_of(disclosure=None, claims=None, figures=None) -> list[str]:
    texts: list[str] = []
    if disclosure is not None:
        for section in getattr(disclosure, "sections", []) or []:
            texts.append(str(getattr(section, "title", "")))
            for p in getattr(section, "paragraphs", []) or []:
                texts.append(str(getattr(p, "text", "")))
    if claims is not None:
        for claim in getattr(claims, "claims", []) or []:
            texts.append(str(getattr(claim, "rendered_text", "")))
            for f in getattr(claim, "features", []) or []:
                texts.append(str(getattr(f, "text", "")))
    if figures is not None:
        for figure in figures:
            texts.append(str(getattr(figure, "title", "")))
            for node in getattr(figure, "nodes", []) or []:
                texts.append(str(getattr(node, "label", "")))
    return texts


class CrossCaseContaminationValidator:
    """Detect another case's exclusive concepts in current-case output."""

    def __init__(self, case_concepts: set[str], other_case_fingerprints: dict[str, set[str]]):
        self.case_concepts = case_concepts
        self.forbidden = forbidden_concepts_for(case_concepts, other_case_fingerprints)

    def validate(self, disclosure=None, claims=None, figures=None) -> ContaminationResult:
        result = ContaminationResult()
        joined = "\n".join(_texts_of(disclosure, claims, figures)).lower()
        for concept in sorted(self.forbidden):
            for kw in CONCEPT_FAMILIES[concept]["en"] + CONCEPT_FAMILIES[concept]["zh"]:
                if kw.lower() in joined:
                    result.foreign_concepts.append(concept)
                    result.details.append(
                        f"检测到其他案例独占概念 '{concept}'（关键词: {kw}），"
                        f"当前案例证据不支持"
                    )
                    break
        result.passed = not result.foreign_concepts
        return result


class PlaceholderLeakValidator:
    """Fixture/demo/template phrases must never appear in real-case output."""

    def validate(self, disclosure=None, claims=None, figures=None) -> ContaminationResult:
        result = ContaminationResult()
        joined = "\n".join(_texts_of(disclosure, claims, figures))
        violations = fixture_violations(joined)
        if violations:
            result.passed = False
            result.details = [
                f"检测到模板/演示残留内容: {phrase}" for phrase in violations
            ]
        return result


class FigureSemanticValidator:
    """Every figure's semantic keywords must be supported by case evidence.

    A figure carrying LDM keywords in a case whose evidence has no diffusion
    concept is figure-semantic contamination.
    """

    def __init__(self, case_concepts: set[str]):
        self.case_concepts = case_concepts

    def validate(self, figures) -> ContaminationResult:
        result = ContaminationResult()
        for figure in figures:
            # extracted/omitted source figures carry no generated semantics
            provenance = str(getattr(figure, "provenance", "") or "generated")
            if provenance in ("extracted", "omitted", "uploaded"):
                continue
            title = str(getattr(figure, "title", ""))
            labels = " ".join(
                str(getattr(node, "label", "")) for node in getattr(figure, "nodes", []) or []
            )
            joined = (title + " " + labels).lower()
            for concept, fam in CONCEPT_FAMILIES.items():
                if concept in self.case_concepts:
                    continue
                for kw in fam["en"] + fam["zh"]:
                    if kw.lower() in joined:
                        result.foreign_concepts.append(concept)
                        result.details.append(
                            f"图 '{figure.id}' 含概念 '{concept}'（关键词 {kw}），"
                            f"当前案例证据不支持"
                        )
                        break
        result.passed = not result.foreign_concepts
        return result


class FormulaScopeValidator:
    """All display equations must come from the current case's understanding."""

    def __init__(self, case_equation_ids: set[str]):
        self.case_equation_ids = case_equation_ids

    def validate(self, draft_equations) -> ContaminationResult:
        result = ContaminationResult()
        for equation in draft_equations:
            eid = str(getattr(equation, "id", "") or "")
            if eid and eid not in self.case_equation_ids:
                result.foreign_concepts.append(eid)
                result.details.append(
                    f"公式 {eid} 不在当前案例 understanding.equations 中（非 case-local）"
                )
        result.passed = not result.foreign_concepts
        return result


def _obj_text(obj) -> str:
    """Extract text from a string or any model object (text/description/name/
    statement attributes)."""
    if isinstance(obj, str):
        return obj
    for attr in ("text", "description", "name", "statement"):
        value = getattr(obj, attr, None)
        if value is not None:
            return str(value)
    return str(obj)


def case_concepts_from_understanding(understanding) -> set[str]:
    """Detect concepts from a case's own understanding text (facts/steps/
    components/equations/parameters)."""
    blocks: list[str] = []
    for fact in getattr(understanding, "facts", []) or []:
        blocks.append(_obj_text(fact))
    for step in getattr(understanding, "steps", []) or []:
        blocks.append(_obj_text(step))
    for comp in getattr(understanding, "components", []) or []:
        blocks.append(_obj_text(comp))
    for eq in getattr(understanding, "equations", []) or []:
        blocks.append(str(getattr(eq, "normalized_latex", "") or getattr(eq, "original_expression", "")))
    for p in getattr(understanding, "parameters", []) or []:
        blocks.append(str(getattr(p, "name", "")))
    return detect_case_concepts(blocks)
