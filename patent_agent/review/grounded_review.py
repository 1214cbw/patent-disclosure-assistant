from __future__ import annotations

import re

from patent_agent.core.models import EvidenceStatus, GroundedClaimSet, GroundedDisclosure, ReviewFinding, TechnicalUnderstandingResult
from patent_agent.evidence import collect_evidence_ids


def review_grounding(understanding: TechnicalUnderstandingResult, disclosure: GroundedDisclosure, claims: GroundedClaimSet, evidence_store) -> list[ReviewFinding]:
    findings: list[ReviewFinding] = []
    all_objects = [understanding, disclosure, claims]
    for identifier in sorted(set().union(*(collect_evidence_ids(item) for item in all_objects))):
        if not evidence_store.contains(identifier):
            findings.append(ReviewFinding(code="INVALID_EVIDENCE_REFERENCE", severity="ERROR", message=f"不存在的 Evidence ID：{identifier}"))
    for fact in understanding.facts:
        if fact.status == EvidenceStatus.SOURCE_FACT and not fact.evidence_ids:
            findings.append(ReviewFinding(code="SOURCE_FACT_WITHOUT_EVIDENCE", severity="ERROR", message=f"{fact.fact_id} 缺少 Evidence"))
    risky = re.compile(r"显著|大幅|明显|有效提高|降低\s*\d+(?:\.\d+)?%|提高\s*\d+(?:\.\d+)?%")
    for section in disclosure.sections:
        for paragraph in section.paragraphs:
            if risky.search(paragraph.text) and paragraph.status != EvidenceStatus.SOURCE_FACT:
                findings.append(ReviewFinding(code="UNVERIFIED_EFFECT_CLAIM", severity="ERROR", message="无已验证 Evidence 的强效果表述", location=paragraph.paragraph_id))
            if paragraph.status in {EvidenceStatus.INFERRED, EvidenceStatus.AI_SUGGESTION, EvidenceStatus.UNVERIFIED} and not paragraph.text.startswith(("预期", "可能", "[待发明人确认]")):
                findings.append(ReviewFinding(code="INFERENCE_PRESENTED_AS_FACT", severity="WARNING", message="推断段落应使用预期/可能/待确认措辞", location=paragraph.paragraph_id))
    return findings
