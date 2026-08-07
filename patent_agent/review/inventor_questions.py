from __future__ import annotations

from patent_agent.core.models import InventorQuestion, TechnicalUnderstandingResult


def generate_inventor_questions(understanding: TechnicalUnderstandingResult, support_gaps: list[str] | None = None) -> list[InventorQuestion]:
    questions = list(understanding.uncertainties)
    existing = {item.text for item in questions}
    for parameter in understanding.parameters:
        if parameter.value is not None and not parameter.unit:
            text = f"参数“{parameter.name}”给出了数值但未给出单位，请确认。"
            if text not in existing:
                questions.append(InventorQuestion(question_id=f"Q-AUTO-{len(questions)+1:03d}", text=text, priority="P1", related_evidence_ids=parameter.evidence_ids, blocking_stage="C")); existing.add(text)
    for equation in understanding.equations:
        if equation.status.value == "UNVERIFIED":
            text = f"公式 {equation.equation_id} 无法可靠规范化，请发明人核对原式与变量定义。"
            if text not in existing:
                questions.append(InventorQuestion(question_id=f"Q-AUTO-{len(questions)+1:03d}", text=text, priority="P0", related_evidence_ids=equation.evidence_ids, blocking_stage="B")); existing.add(text)
    for gap in support_gaps or []:
        text = f"独立权利要求支持存在缺口：{gap}，请补充材料或确认删除该特征。"
        if text not in existing:
            questions.append(InventorQuestion(question_id=f"Q-AUTO-{len(questions)+1:03d}", text=text, priority="P0", blocking_stage="B")); existing.add(text)
    questions = [item if item.blocking_stage or item.priority != "P0" else item.model_copy(update={"blocking_stage": "B"}) for item in questions]
    return sorted(questions, key=lambda item: (item.priority, item.question_id))
