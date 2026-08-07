from __future__ import annotations

from patent_agent.core.models import InventorQuestion, TechnicalUnderstandingResult


def generate_inventor_questions(understanding: TechnicalUnderstandingResult, support_gaps: list[str] | None = None) -> list[InventorQuestion]:
    questions = [_classify_question(item) for item in understanding.uncertainties]
    existing = {item.text for item in questions}
    for parameter in understanding.parameters:
        if parameter.value is not None and not parameter.unit and _unit_expected(parameter):
            text = f"参数“{parameter.name}”给出了数值但未给出单位，请确认。"
            if text not in existing:
                questions.append(InventorQuestion(question_id=f"Q-AUTO-{len(questions)+1:03d}", text=text, priority="P1", question_role="EMBODIMENT_DETAIL", related_evidence_ids=parameter.evidence_ids, blocking_stage="C")); existing.add(text)
    for equation in understanding.equations:
        if equation.status.value == "UNVERIFIED":
            text = f"公式 {equation.equation_id} 无法可靠规范化，请发明人核对原式与变量定义。"
            if text not in existing:
                questions.append(InventorQuestion(question_id=f"Q-AUTO-{len(questions)+1:03d}", text=text, priority="P0", question_role="CLAIM_BLOCKING", related_evidence_ids=equation.evidence_ids, blocking_stage="B")); existing.add(text)
    for gap in support_gaps or []:
        text = f"独立权利要求支持存在缺口：{gap}，请补充材料或确认删除该特征。"
        if text not in existing:
            questions.append(InventorQuestion(question_id=f"Q-AUTO-{len(questions)+1:03d}", text=text, priority="P0", question_role="CLAIM_BLOCKING", blocking_stage="B")); existing.add(text)
    questions = [item if item.blocking_stage or item.priority != "P0" else item.model_copy(update={"blocking_stage": "B"}) for item in questions]
    return sorted(questions, key=lambda item: (item.priority, item.question_id))


def _classify_question(question: InventorQuestion) -> InventorQuestion:
    text = question.text.lower()
    optional_markers = ("batch size", "learning rate", "epoch", "layer", "channel", "attention", "diffusion timestep", "noise schedule", "loss function", "hyperparameter")
    enablement_markers = ("image resolution", "bounds", "range", "unit", "manufactur")
    if any(marker in text for marker in optional_markers):
        return question.model_copy(update={"priority": "P2", "question_role": "EMBODIMENT_DETAIL", "blocking_stage": None})
    if any(marker in text for marker in enablement_markers):
        return question.model_copy(update={"priority": "P1", "question_role": "ENABLEMENT", "blocking_stage": question.blocking_stage if question.blocking_stage not in {"A1", "A2"} else None})
    if question.priority == "P0":
        return question.model_copy(update={"question_role": "CLAIM_BLOCKING"})
    return question.model_copy(update={"question_role": "OPTIONAL_DETAIL"})


def _unit_expected(parameter) -> bool:
    name = parameter.name.lower()
    dimensionless = ("learning rate", "latent space dimension", "count", "epoch", "batch", "timestep", "score", "coefficient")
    return not any(marker in name for marker in dimensionless)
