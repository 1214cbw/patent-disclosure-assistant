import re
from patent_agent.core.models import DisclosureDraft, PatentKnowledge, ReviewFinding


def hallucination_guard(draft: DisclosureDraft, knowledge: PatentKnowledge) -> list[ReviewFinding]:
    findings = []
    source_text = "\n".join(item.claim for item in knowledge.evidence)
    for heading, paragraphs in draft.sections.items():
        for paragraph in paragraphs:
            for value in re.findall(r"\d+(?:\.\d+)?%", paragraph):
                if value not in source_text and "SYNTHETIC DEMO DATA" not in paragraph:
                    findings.append(ReviewFinding(code="UNSUPPORTED_NUMERIC_RESULT", severity="ERROR", message=f"未找到数值结果 {value} 的来源。", location=heading))
    return findings

