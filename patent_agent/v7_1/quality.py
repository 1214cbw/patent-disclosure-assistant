"""Case-agnostic content, graph, terminology and delivery validators.

The validators in this module consume declared structure and case-derived
registries.  They deliberately contain no product-domain or demonstration-
case vocabulary.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence


@dataclass(frozen=True)
class QualityFinding:
    code: str
    message: str
    location: str = ""
    severity: str = "ERROR"


@dataclass
class QualityResult:
    findings: list[QualityFinding] = field(default_factory=list)

    @property
    def status(self) -> str:
        return "FAIL" if any(f.severity == "ERROR" for f in self.findings) else "PASS"

    def add(self, code: str, message: str, location: str = "", severity: str = "ERROR") -> None:
        self.findings.append(QualityFinding(code, message, location, severity))


def _value(obj: Any, key: str, default: Any = None) -> Any:
    return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)


class HeadingCompletenessValidator:
    """Reject sentence fragments and structurally incomplete headings."""

    _body_prefix = re.compile(r"^(?:\d+(?:\.\d+)*[.、]?\s*)?(?:本环节|本步骤|本实施例|在本环节中)")
    _incomplete_suffix = re.compile(
        r"(?:以及|并且|或者|及其|通过|采用|基于|用于|所述|包括|包含|与|和|或|的|之|对|多)\s*$"
    )
    _pairs = {"（": "）", "(": ")", "[": "]", "【": "】", "《": "》"}

    def validate(self, headings: Iterable[str]) -> QualityResult:
        result = QualityResult()
        for index, raw in enumerate(headings):
            heading = str(raw or "").strip()
            location = f"heading[{index}]"
            if self._body_prefix.search(heading):
                result.add("TITLE_PREFIX_TRUNCATION", "Heading is a body-sentence fragment.", location)
            for opening, closing in self._pairs.items():
                if heading.count(opening) != heading.count(closing):
                    result.add("TITLE_UNCLOSED_DELIMITER", "Heading has an unclosed delimiter.", location)
                    break
            if self._incomplete_suffix.search(heading):
                result.add("TITLE_INCOMPLETE_SUFFIX", "Heading ends with an incomplete connective.", location)
        return result


class SectionCompletenessValidator:
    """Check body presence and semantic section routing."""

    def __init__(self, min_body_chars: int = 12):
        self.min_body_chars = min_body_chars

    def validate(self, sections: Iterable[Any]) -> QualityResult:
        result = QualityResult()
        values = list(sections)
        for index, section in enumerate(values):
            section_id = str(_value(section, "section_id", ""))
            title = str(_value(section, "title", ""))
            paragraphs = [str(_value(p, "text", p) or "").strip()
                          for p in (_value(section, "paragraphs", []) or [])]
            body = "".join(p for p in paragraphs if p)
            location = section_id or f"section[{index}]"
            is_figure_description = section_id == "06" or bool(
                re.match(r"^\s*6(?:\.|、|\s)", title) and "附图" in title
            )
            is_technical = section_id == "05" or section_id.startswith("05-")
            if is_figure_description and not body:
                result.add("FIGURE_DESCRIPTION_SECTION_EMPTY", "Figure-description section has no body.", location)
            if is_technical and len(body) < self.min_body_chars:
                result.add("TECHNICAL_SECTION_BODY_MISSING", "Technical section has no substantive body.", location)
                if index + 1 < len(values):
                    result.add("CONSECUTIVE_HEADING_WITHOUT_BODY", "A following heading occurs before body content.", location)
            if body and re.fullmatch(r"(?:待补充|TODO|TBD|N/?A|—|[-\s])+[。.]?", body, re.I):
                result.add("SECTION_PLACEHOLDER_ONLY", "Section body contains only a placeholder.", location)
        return result


class FigureGraphValidator:
    def validate(self, figures: Iterable[Any], rendered: dict[str, Any] | None = None) -> QualityResult:
        result = QualityResult()
        rendered = rendered or {}
        for figure in figures:
            figure_id = str(_value(figure, "id", ""))
            nodes = {_value(n, "id", "") for n in (_value(figure, "nodes", []) or [])}
            edges = list(_value(figure, "edges", []) or [])
            edge_ids = {f"{_value(e, 'source', '')}->{_value(e, 'target', '')}" for e in edges}
            for edge in edges:
                if _value(edge, "source", "") not in nodes or _value(edge, "target", "") not in nodes:
                    result.add("DANGLING_ARROW", "Edge endpoint is not a declared node.", figure_id)
            for node_id in _value(figure, "required_node_ids", []) or []:
                if node_id not in nodes:
                    result.add("REQUIRED_NODE_MISSING", f"Required node {node_id} is missing.", figure_id)
            for edge_id in _value(figure, "required_edge_ids", []) or []:
                if edge_id not in edge_ids:
                    result.add("REQUIRED_EDGE_MISSING", f"Required edge {edge_id} is missing.", figure_id)
            rendered_graph = rendered.get(figure_id)
            if rendered_graph is not None:
                rendered_nodes = set(rendered_graph.get("node_ids", []))
                rendered_edges = set(rendered_graph.get("edge_ids", []))
                for node_id in nodes - rendered_nodes:
                    result.add("RENDERED_NODE_MISSING", f"Rendered graph lost node {node_id}.", figure_id)
                for edge_id in edge_ids - rendered_edges:
                    result.add("RENDERED_EDGE_MISSING", f"Rendered graph lost edge {edge_id}.", figure_id)
        return result


class BilingualTermValidator:
    _duplicate = re.compile(r"([^\s，。；：、（）()]{2,32})[（(]\s*\1\s*[）)]", re.I)

    def validate(self, texts: Iterable[str]) -> QualityResult:
        result = QualityResult()
        for index, text in enumerate(texts):
            if self._duplicate.search(str(text)):
                result.add("DUPLICATE_TERM_EXPANSION", "Parenthetical term duplicates its outside term.", f"text[{index}]")
        return result


@dataclass(frozen=True)
class TermRegistry:
    tokens: tuple[str, ...]


class TechnicalTerminologyNormalizer:
    """Normalize only tokens learned from the current case's source text."""

    _token = re.compile(r"(?<![A-Za-z0-9])[A-Za-z][A-Za-z0-9]*(?:[-–][A-Za-z0-9]+)*(?![A-Za-z0-9])")

    def __init__(self, registry: TermRegistry):
        self.registry = registry

    @classmethod
    def from_source_texts(cls, texts: Iterable[str]) -> "TechnicalTerminologyNormalizer":
        tokens: set[str] = set()
        for text in texts:
            for token in cls._token.findall(str(text)):
                upper_count = sum(ch.isupper() for ch in token)
                camel = bool(re.search(r"[a-z][A-Z]", token))
                if upper_count >= 2 or camel or any(ch.isdigit() for ch in token) or "-" in token or "–" in token:
                    tokens.add(token)
        return cls(TermRegistry(tuple(sorted(tokens, key=lambda item: (-len(item), item)))))

    @staticmethod
    def _split_pattern(token: str) -> re.Pattern[str]:
        parts = [re.escape(char) for char in token]
        return re.compile(r"(?<![A-Za-z0-9])" + r"\s*".join(parts) + r"(?![A-Za-z0-9])", re.I)

    def normalize(self, text: str) -> str:
        value = str(text)
        for token in self.registry.tokens:
            pattern = self._split_pattern(token)
            value = pattern.sub(lambda match: token if re.search(r"\s", match.group(0)) else match.group(0), value)
        return value


class TokenIntegrityValidator:
    def __init__(self, registry: TermRegistry):
        self.registry = registry

    def validate(self, texts: Iterable[str]) -> QualityResult:
        result = QualityResult()
        for index, text in enumerate(texts):
            value = str(text)
            for token in self.registry.tokens:
                pattern = TechnicalTerminologyNormalizer._split_pattern(token)
                for match in pattern.finditer(value):
                    if re.search(r"\s", match.group(0)):
                        result.add("TECHNICAL_TOKEN_SPLIT", f"Registered token {token} is split.", f"text[{index}]")
                        break
        return result


def _latex_tokens(value: str) -> list[str]:
    return re.findall(r"\\[A-Za-z]+|[A-Za-z]+|\d+(?:\.\d+)?|[=+\-*/^_]|[(){}\[\]]", value or "")


class EquationIntegrityValidator:
    """Compare ordered IDs and canonical token/structure signatures."""

    def validate(self, expected: Sequence[Any], actual: Sequence[Any]) -> QualityResult:
        result = QualityResult()
        expected_ids = [str(_value(item, "id", _value(item, "equation_id", ""))) for item in expected]
        actual_ids = [str(_value(item, "id", _value(item, "equation_id", ""))) for item in actual]
        if len(expected) != len(actual):
            result.add("EQUATION_COUNT_MISMATCH", "Equation count differs from the canonical registry.")
        if expected_ids != actual_ids:
            result.add("EQUATION_ID_ORDER_MISMATCH", "Equation IDs or order differ from the canonical registry.")
        actual_by_id = {item_id: item for item_id, item in zip(actual_ids, actual)}
        for item_id, expected_item in zip(expected_ids, expected):
            actual_item = actual_by_id.get(item_id)
            if actual_item is None:
                continue
            expected_latex = str(_value(expected_item, "latex", _value(expected_item, "normalized_latex", "")) or "")
            actual_latex = str(_value(actual_item, "latex", _value(actual_item, "normalized_latex", "")) or "")
            expected_tokens = _latex_tokens(expected_latex)
            actual_tokens = _latex_tokens(actual_latex)
            missing = list(expected_tokens)
            for token in actual_tokens:
                if token in missing:
                    missing.remove(token)
            if missing:
                result.add("EQUATION_REQUIRED_TOKEN_MISSING", f"Canonical tokens are missing: {missing}", item_id)
            if re.search(r"[=+\-*/^_]\s*$", actual_latex):
                result.add("EQUATION_TRAILING_OPERATOR", "Equation ends with an operator.", item_id)
            for opening, closing in (("(", ")"), ("[", "]"), ("{", "}")):
                if actual_latex.count(opening) != actual_latex.count(closing):
                    result.add("EQUATION_UNBALANCED_DELIMITER", "Equation delimiters are unbalanced.", item_id)
                    break
        return result


class FigureNarrativeConsistencyValidator:
    _negative = re.compile(r"\b(?:without|no|not|does not|do not|avoids?|omits?)\s+([^.;:]{2,80})", re.I)

    @staticmethod
    def _terms(text: str) -> set[str]:
        return {term.lower() for term in re.findall(r"[A-Za-z][A-Za-z0-9-]*|[\u4e00-\u9fff]{2,}", text)}

    def validate(self, narratives: Iterable[str], figures: Iterable[Any]) -> QualityResult:
        result = QualityResult()
        forbidden_sets: list[set[str]] = []
        for narrative in narratives:
            for match in self._negative.finditer(str(narrative)):
                forbidden_sets.append(self._terms(match.group(1)))
        for figure in figures:
            figure_id = str(_value(figure, "id", ""))
            figure_text = " ".join(
                [str(_value(figure, "title", "")), str(_value(figure, "caption", ""))]
                + [str(_value(node, "label", "")) for node in (_value(figure, "nodes", []) or [])]
            )
            figure_terms = self._terms(figure_text)
            for forbidden in forbidden_sets:
                meaningful = {term for term in forbidden if len(term) > 2}
                if meaningful and meaningful <= figure_terms:
                    result.add("FIGURE_NARRATIVE_CONTRADICTION", "Figure depicts an operation negated by the narrative.", figure_id)
                    break
        return result


class DeliveryQualityGate:
    def validate(
        self,
        component_results: Iterable[QualityResult],
        docx_path: Path,
        pdf_path: Path,
        render_audit: Any | None,
    ) -> QualityResult:
        result = QualityResult()
        for component in component_results:
            result.findings.extend(component.findings)
        if not Path(docx_path).is_file() or not Path(pdf_path).is_file():
            result.add("DELIVERY_ARTIFACT_MISSING", "Required DOCX or PDF artifact is missing.")
        if render_audit is None:
            result.add("RENDER_AUDIT_MISSING", "A successful PDF render audit is required.")
        elif str(_value(render_audit, "status", "FAIL")) != "PASS":
            result.add("RENDER_AUDIT_FAILED", "PDF render audit did not pass.")
        return result

