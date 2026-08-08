"""V7 quality gates orchestration.

Every gate runs BEFORE its stage is saved:

    Disclosure:  language gate -> completeness -> unsupported-paragraph
                 -> cross-case contamination -> placeholder leak
    Figures:     language gate (captions) -> figure semantic -> formula scope
    Claims:      language gate

Any failed gate raises V7GateError with an explicit code and blocks finalize.
"""
from __future__ import annotations

from dataclasses import dataclass, field


class V7GateError(RuntimeError):
    """A quality gate blocked the artifact from being saved/published."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass
class GateReport:
    """Per-artifact gate run summary."""
    artifact: str                      # e.g. "p1_disclosure"
    case_id: str = ""
    passed: bool = True
    gates: dict[str, bool] = field(default_factory=dict)
    details: list[str] = field(default_factory=list)

    def fail(self, name: str, detail: str) -> None:
        self.passed = False
        self.gates[name] = False
        self.details.append(f"{name}: {detail}")

    def pass_gate(self, name: str) -> None:
        self.gates[name] = True

    def to_dict(self) -> dict:
        return {
            "artifact": self.artifact, "case_id": self.case_id,
            "passed": self.passed, "gates": self.gates,
            "details": self.details[:30],
        }


def run_disclosure_gates(
    *,
    case_id: str,
    disclosure,
    claims,
    figures,
    language_validator,
    completeness_validator,
    unsupported_validator,
    contamination_validator,
    placeholder_validator,
) -> GateReport:
    """Run all disclosure-time gates. Raises V7GateError on first failure."""
    report = GateReport(artifact="p1_disclosure", case_id=case_id)

    lang = language_validator.validate_disclosure(disclosure)
    if not lang.passed:
        detail = "；".join(lang.issues[:8])
        report.fail("language_gate", detail)
        raise V7GateError("LANGUAGE_GATE_FAILED",
                          f"p1_disclosure 非原生中文，阻止保存。{detail}")
    report.pass_gate("language_gate")

    complete = completeness_validator.validate(disclosure)
    if not complete.passed:
        detail = f"缺失章节: {', '.join(complete.missing)}"
        report.fail("completeness", detail)
        raise V7GateError("DISCLOSURE_INCOMPLETE", detail)
    report.pass_gate("completeness")

    grounded = unsupported_validator.validate(disclosure)
    if not grounded.passed:
        detail = f"未接地段落 {len(grounded.unsupported)} 段: {grounded.unsupported[0][:120]}"
        report.fail("unsupported_paragraph", detail)
        raise V7GateError("UNSUPPORTED_DISCLOSURE_PARAGRAPH", detail)
    report.pass_gate("unsupported_paragraph")

    contamination = contamination_validator.validate(
        disclosure=disclosure, claims=claims, figures=figures)
    if not contamination.passed:
        detail = "；".join(contamination.details[:6])
        report.fail("cross_case_contamination", detail)
        raise V7GateError("CROSS_CASE_CONTAMINATION",
                          "检测到与当前材料不一致的技术内容，已阻止生成。")
    report.pass_gate("cross_case_contamination")

    placeholders = placeholder_validator.validate(
        disclosure=disclosure, claims=claims, figures=figures)
    if not placeholders.passed:
        detail = "；".join(placeholders.details[:6])
        report.fail("placeholder_leak", detail)
        raise V7GateError("PLACEHOLDER_LEAK", detail)
    report.pass_gate("placeholder_leak")

    return report


def run_figure_gates(
    *,
    case_id: str,
    figures,
    language_validator,
    figure_semantic_validator,
    formula_scope_validator,
    draft_equations,
) -> GateReport:
    """Run figure-time gates. Raises V7GateError on first failure."""
    report = GateReport(artifact="figures", case_id=case_id)

    lang = language_validator.validate_figure_captions(figures)
    if not lang.passed:
        detail = "；".join(lang.issues[:6])
        report.fail("figure_language_gate", detail)
        raise V7GateError("LANGUAGE_GATE_FAILED", f"图注非中文: {detail}")
    report.pass_gate("figure_language_gate")

    semantic = figure_semantic_validator.validate(figures)
    if not semantic.passed:
        detail = "；".join(semantic.details[:6])
        report.fail("figure_semantic", detail)
        raise V7GateError("FIGURE_SEMANTIC_FAIL", detail)
    report.pass_gate("figure_semantic")

    formula = formula_scope_validator.validate(draft_equations)
    if not formula.passed:
        detail = "；".join(formula.details[:6])
        report.fail("formula_case_scope", detail)
        raise V7GateError("FORMULA_CASE_SCOPE_FAIL", detail)
    report.pass_gate("formula_case_scope")

    return report


def run_claims_gate(*, case_id: str, claims, language_validator) -> GateReport:
    """Claims must be Chinese before save."""
    report = GateReport(artifact="p1_claims", case_id=case_id)
    lang = language_validator.validate_claims(claims)
    if not lang.passed:
        detail = "；".join(lang.issues[:6])
        report.fail("claims_language_gate", detail)
        raise V7GateError("LANGUAGE_GATE_FAILED", f"p1_claims 非中文: {detail}")
    report.pass_gate("claims_language_gate")
    return report
