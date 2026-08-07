from __future__ import annotations

from patent_agent.core.models import ClaimsSupportMatrix, QualityGateResult, TraceabilityReport


def evaluate_quality_gates(*, evidence_errors: list[str], technical_errors: list[str], candidate_errors: list[str], support_matrix: ClaimsSupportMatrix, traceability: TraceabilityReport, document_pass: bool) -> list[QualityGateResult]:
    return [
        _gate("Gate 1 Evidence Integrity", evidence_errors),
        _gate("Gate 2 Technical Understanding", technical_errors),
        _gate("Gate 3 Invention Candidate", candidate_errors),
        _gate("Gate 4 Claim Support", [] if support_matrix.validation_status == "PASS" else [support_matrix.validation_status]),
        _gate("Gate 5 Traceability", traceability.broken_links),
        _gate("Gate 6 Document Validation", [] if document_pass else ["DOCX_VALIDATION_FAILED"]),
    ]


def _gate(name: str, errors: list[str]) -> QualityGateResult:
    return QualityGateResult(gate=name, status="FAIL" if errors else "PASS", errors=errors)
