from patent_agent.core.models import DisclosureDraft, ReviewFinding


def review_terminology(draft: DisclosureDraft) -> list[ReviewFinding]:
    text = "\n".join(p for section in draft.sections.values() for p in section)
    aliases = [("控制模块", "控制单元")]
    findings = []
    for left, right in aliases:
        if left in text and right in text:
            findings.append(ReviewFinding(code="TERMINOLOGY_VARIANT", severity="WARNING", message=f"同时出现“{left}”和“{right}”，需确认是否同一对象。"))
    return findings
