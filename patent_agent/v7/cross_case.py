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


@dataclass(frozen=True)
class EvidenceFingerprint:
    """Current-case fingerprint derived from source/facts, not a fixed lexicon."""

    technical_tokens: frozenset[str] = frozenset()
    fact_ids: frozenset[str] = frozenset()
    evidence_ids: frozenset[str] = frozenset()


_COMMON_LATIN = {
    "about", "after", "also", "and", "are", "based", "before", "between",
    "case", "current", "data", "each", "figure", "from", "have", "into",
    "method", "model", "output", "process", "system", "that", "the", "their",
    "then", "this", "through", "using", "with", "without", "input", "step",
    "training", "value", "values", "result", "results", "technical", "technology",
    "context", "element", "elements", "estimation", "experiment", "experiments",
    "finite", "formula", "function", "implementation", "limitation", "limitations",
    "moment", "specification", "specifications", "trick",
}


def _latin_tokens(text: str) -> set[str]:
    text = re.sub(r"(?<=[A-Za-z0-9])_(?=[A-Za-z0-9])", "", text)
    tokens: set[str] = set()
    for raw in re.findall(r"[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)*", text):
        canonical = raw.lower().replace("-", "")
        variants = {canonical}
        if len(canonical) > 5 and canonical.endswith("s"):
            variants.add(canonical[:-1])
        tokens.update(token for token in variants if len(token) >= 4 and token not in _COMMON_LATIN)
    return tokens


def _all_strings(value) -> list[str]:
    """Collect source-derived strings from a model without knowing its schema.

    TechnicalUnderstanding evolves between releases.  A recursive walk keeps
    equations, parameters, experiments and limitations in the case-local
    fingerprint instead of silently reducing it to only facts and steps.
    """
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for item in value.values() for text in _all_strings(item)]
    if isinstance(value, (list, tuple, set)):
        return [text for item in value for text in _all_strings(item)]
    if hasattr(value, "model_dump"):
        return _all_strings(value.model_dump())
    if hasattr(value, "__dict__"):
        return _all_strings(vars(value))
    return []


def build_case_evidence_fingerprint(understanding, evidence_store=None) -> EvidenceFingerprint:
    blocks: list[str] = _all_strings(understanding)
    facts = list(getattr(understanding, "facts", []) or [])
    if evidence_store is not None:
        blocks.extend(str(chunk.raw_text or chunk.normalized_text) for chunk in evidence_store.all())
    return EvidenceFingerprint(
        technical_tokens=frozenset().union(*(_latin_tokens(block) for block in blocks)) if blocks else frozenset(),
        fact_ids=frozenset(str(getattr(fact, "fact_id", "")) for fact in facts),
        evidence_ids=frozenset(
            str(evidence_id) for fact in facts
            for evidence_id in (getattr(fact, "evidence_ids", []) or [])
        ),
    )


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

    def __init__(self, case_concepts: set[str], other_case_fingerprints: dict[str, set[str]],
                 evidence_fingerprint: EvidenceFingerprint | None = None):
        self.case_concepts = case_concepts
        self.forbidden = forbidden_concepts_for(case_concepts, other_case_fingerprints)
        self.evidence_fingerprint = evidence_fingerprint

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
        # Fixed concept families above are only an auxiliary signal.  The
        # primary open-vocabulary signal checks distinctive Latin technical
        # tokens against the current case's own evidence-derived fingerprint.
        if self.evidence_fingerprint is not None:
            output_tokens = set().union(*(_latin_tokens(text) for text in _texts_of(
                disclosure, claims, figures)))
            unsupported = sorted(output_tokens - set(self.evidence_fingerprint.technical_tokens))
            for token in unsupported:
                result.foreign_concepts.append(token)
                result.details.append(
                    f"检测到当前案例证据指纹未支持的开放词汇技术概念: {token}"
                )
            for figure in figures or []:
                if str(getattr(figure, "provenance", "generated")) != "generated":
                    continue
                fact_ids = set(getattr(figure, "source_fact_ids", []) or [])
                if not fact_ids or not fact_ids <= set(self.evidence_fingerprint.fact_ids):
                    result.foreign_concepts.append(str(getattr(figure, "id", "figure")))
                    result.details.append("生成图缺少有效的当前案例 source_fact_ids")
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

    def __init__(self, case_concepts: set[str], evidence_fingerprint: EvidenceFingerprint | None = None):
        self.case_concepts = case_concepts
        self.evidence_fingerprint = evidence_fingerprint

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
            if self.evidence_fingerprint is not None:
                unsupported = _latin_tokens(joined) - set(self.evidence_fingerprint.technical_tokens)
                if unsupported:
                    result.foreign_concepts.extend(sorted(unsupported))
                    result.details.append(
                        f"图 '{figure.id}' 含当前案例证据指纹未支持的技术词: "
                        + ", ".join(sorted(unsupported))
                    )
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
