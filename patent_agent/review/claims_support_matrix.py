from __future__ import annotations

from patent_agent.core.models import ClaimSupportRecord, ClaimsSupportMatrix, GroundedClaimSet, GroundedDisclosure


class ClaimsSupportMatrixBuilder:
    def build(self, claims: GroundedClaimSet, disclosure: GroundedDisclosure, evidence_store, draft_mode: bool = False) -> ClaimsSupportMatrix:
        paragraphs = [paragraph for section in disclosure.sections for paragraph in section.paragraphs]
        records: list[ClaimSupportRecord] = []
        unsupported_independent: list[str] = []
        for claim in claims.claims:
            independent = not claim.parent_claims and claim.claim_type in {"method", "system"}
            for feature in claim.features:
                matched = [paragraph.paragraph_id for paragraph in paragraphs if set(paragraph.fact_ids) & set(feature.source_fact_ids) or set(paragraph.evidence_ids) & set(feature.evidence_ids)]
                valid_evidence = [identifier for identifier in feature.evidence_ids if evidence_store.contains(identifier)]
                if matched and feature.source_fact_ids and valid_evidence:
                    status, notes = "SUPPORTED", "说明书段落、技术事实和原始 Evidence 链路完整。"
                elif valid_evidence and (matched or feature.source_fact_ids):
                    status, notes = "PARTIALLY_SUPPORTED", "存在来源支持，但说明书段落或技术事实映射不完整。"
                elif valid_evidence:
                    status, notes = "UNCERTAIN", "存在原始 Evidence，但尚未建立说明书/Fact 支持。"
                else:
                    status, notes = "UNSUPPORTED", "未找到有效原始 Evidence。"
                if independent and feature.mandatory and status == "UNSUPPORTED":
                    unsupported_independent.append(feature.feature_id)
                records.append(ClaimSupportRecord(claim_number=claim.claim_number, feature_id=feature.feature_id, feature_text=feature.text, disclosure_paragraph_ids=matched, fact_ids=feature.source_fact_ids, evidence_ids=valid_evidence, support_status=status, notes=notes))
        if unsupported_independent:
            validation = "INVENTOR_CONFIRMATION_REQUIRED" if draft_mode else "FAIL"
        else:
            validation = "PASS"
        return ClaimsSupportMatrix(records=records, validation_status=validation, unsupported_independent_features=unsupported_independent)


def render_claims_support_markdown(matrix: ClaimsSupportMatrix) -> str:
    lines = ["# Claims Support Matrix", "", f"Validation: **{matrix.validation_status}**", ""]
    current = None
    for record in matrix.records:
        if current != record.claim_number:
            current = record.claim_number; lines += [f"## Claim {current}", ""]
        lines += [f"### {record.feature_id}：{record.feature_text}", "", f"- Status: **{record.support_status}**", f"- Disclosure: {', '.join(record.disclosure_paragraph_ids) or 'none'}", f"- Fact: {', '.join(record.fact_ids) or 'none'}", f"- Evidence: {', '.join(record.evidence_ids) or 'none'}", f"- Notes: {record.notes}", ""]
    return "\n".join(lines)
