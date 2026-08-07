from patent_agent.core.models import ClaimTree, EvidenceRef, ReviewFinding


def review_claim_support(tree: ClaimTree, evidence: list[EvidenceRef]) -> list[ReviewFinding]:
    valid = {item.id for item in evidence}
    findings = []
    for claim in tree.claims:
        missing = [item for item in claim.evidence_ids if item not in valid]
        if not claim.evidence_ids or missing:
            findings.append(ReviewFinding(code="CLAIM_SUPPORT_FAILED", severity="ERROR", message=f"权利要求{claim.number}缺少有效证据映射：{missing or 'none'}", location=f"claim:{claim.number}"))
    return findings

