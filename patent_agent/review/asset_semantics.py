from __future__ import annotations

import re

from patent_agent.core.models import EquationKnowledge, GroundedClaimSet, GroundedDisclosure, ReviewFinding, ReviewStatus


def review_figures(figures) -> list[ReviewFinding]:
    findings = []
    for figure in figures:
        for node in figure.nodes:
            if not node.fact_ids and not node.evidence_ids:
                findings.append(ReviewFinding(code="FIGURE_UNSUPPORTED_NODE", severity="ERROR", message=f"Figure {figure.id} node {node.id} has no Knowledge/Evidence support.", location=node.id))
        for edge in figure.edges:
            if not edge.fact_ids and not edge.evidence_ids:
                findings.append(ReviewFinding(code="FIGURE_UNSUPPORTED_EDGE", severity="ERROR", message=f"Figure {figure.id} edge {edge.source}->{edge.target} has no support.", location=figure.id))
    return findings


def review_equations(equations: list[EquationKnowledge]) -> list[ReviewFinding]:
    findings = []
    for equation in equations:
        expression = equation.human_formula or equation.normalized_latex or equation.original_expression
        if equation.status.value == "SOURCE_FACT" and not equation.evidence_ids:
            findings.append(ReviewFinding(code="EQUATION_SOURCE_MISSING", severity="ERROR", message=f"{equation.equation_id} has no source Evidence."))
        variables = set(re.findall(r"(?<!\\)\b[A-Za-z][A-Za-z0-9_]*\b", expression))
        defined = set(equation.symbols)
        missing = sorted(item for item in variables if item not in defined and item not in {"frac", "sum"})
        if missing:
            findings.append(ReviewFinding(code="EQUATION_UNDEFINED_VARIABLE", severity="WARNING", message=f"{equation.equation_id} undefined variables: {', '.join(missing)}"))
    return findings


def confirm_equation(equation: EquationKnowledge, human_formula: str) -> EquationKnowledge:
    return equation.model_copy(update={"original_formula": equation.original_formula or equation.original_expression, "human_formula": human_formula, "normalized_latex": human_formula, "status": "HUMAN_CONFIRMED", "review_status": ReviewStatus.LOCKED, "human_modified": True, "locked": True})


def apply_confirmed_terminology(disclosure: GroundedDisclosure, claims: GroundedClaimSet, figures, registry):
    replacements = {term.selected_term: term.patent_term for term in registry.terms if term.human_confirmed and term.patent_term and term.patent_term != term.selected_term}
    for source, target in replacements.items():
        disclosure = disclosure.model_copy(update={"sections": [section.model_copy(update={"paragraphs": [paragraph.model_copy(update={"text": paragraph.text.replace(source, target)}) for paragraph in section.paragraphs]}) for section in disclosure.sections]})
        claims = claims.model_copy(update={"claims": [claim.model_copy(update={"rendered_text": claim.rendered_text.replace(source, target), "features": [feature.model_copy(update={"text": feature.text.replace(source, target)}) for feature in claim.features]}) for claim in claims.claims]})
        for figure in figures:
            figure.nodes = [node.model_copy(update={"label": node.label.replace(source, target)}) for node in figure.nodes]
    return disclosure, claims, figures
