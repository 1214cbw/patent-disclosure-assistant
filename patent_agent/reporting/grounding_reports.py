from __future__ import annotations

import json
from pathlib import Path

from patent_agent.core.models import EvidenceStatus


def write_grounding_reports(output_dir: Path, *, understanding, candidates, strategy, disclosure, claims, support_matrix, traceability, questions, findings, gates, evidence_store) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    payloads = {"technical_understanding.json": understanding.model_dump(), "invention_candidates.json": [item.model_dump() for item in candidates], "protection_strategy.json": strategy.model_dump(), "disclosure.json": disclosure.model_dump(), "claims.json": claims.model_dump(), "claim_tree.json": claims.model_dump(), "claims_support_matrix.json": support_matrix.model_dump(), "traceability.json": traceability.model_dump(), "quality_gates.json": [item.model_dump() for item in gates]}
    for name, payload in payloads.items():
        (output_dir / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    from patent_agent.review import render_claims_support_markdown, render_traceability_markdown
    (output_dir / "claims_support_matrix.md").write_text(render_claims_support_markdown(support_matrix), encoding="utf-8")
    (output_dir / "traceability_report.md").write_text(render_traceability_markdown(traceability), encoding="utf-8")
    _write_coverage(output_dir / "evidence_coverage_report.md", understanding, evidence_store)
    _write_questions(output_dir / "inventor_questions.md", questions)
    _write_technical_review(output_dir / "technical_understanding_review.md", understanding, evidence_store)
    (output_dir / "grounded_review.md").write_text("# Grounded Review\n\n" + ("No findings.\n" if not findings else "\n".join(f"- {item.severity} `{item.code}`: {item.message}" for item in findings) + "\n"), encoding="utf-8")


def write_dry_run_reports(output_dir: Path, *, case, understanding, candidates, questions, evidence_store) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "material_summary.md").write_text(f"# Material Summary\n\n- Case: {case.case_id}\n- Title: {case.title}\n- Source files: {len(case.source_files)}\n- Evidence chunks: {len(evidence_store.all())}\n- Stop point: Checkpoint A preview\n", encoding="utf-8")
    (output_dir / "patent_knowledge.json").write_text(understanding.model_dump_json(indent=2), encoding="utf-8")
    (output_dir / "invention_candidates.json").write_text(json.dumps([item.model_dump() for item in candidates], ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    _write_technical_review(output_dir / "technical_understanding_review.md", understanding, evidence_store)
    _write_coverage(output_dir / "evidence_coverage_report.md", understanding, evidence_store)
    _write_questions(output_dir / "inventor_questions.md", questions)
    lines = ["# Invention Candidates Review", "", "Dry-run stops here. No strategy, claims or Word document was generated.", ""]
    for candidate in candidates:
        lines += [f"## {candidate.candidate_id} {candidate.title}", "", f"- Core idea: {candidate.core_idea.text}", f"- Evidence strength: {candidate.evidence_strength_score:.2f}", f"- Protection value: {candidate.protection_value_score:.2f}", f"- Risk: {candidate.risk_score:.2f}", f"- Evidence: {', '.join(candidate.evidence_ids)}", f"- Inferred: {candidate.core_idea.status.value}", f"- Questions: {'；'.join(candidate.inventor_questions) or 'none'}", ""]
    (output_dir / "invention_candidates_review.md").write_text("\n".join(lines), encoding="utf-8")


def _write_coverage(path: Path, understanding, evidence_store) -> None:
    source_facts = [fact for fact in understanding.facts if fact.status == EvidenceStatus.SOURCE_FACT]
    missing = [fact.fact_id for fact in source_facts if not fact.evidence_ids]
    invalid = sorted({identifier for fact in understanding.facts for identifier in fact.evidence_ids if not evidence_store.contains(identifier)})
    inferred = [fact for fact in understanding.facts if fact.status == EvidenceStatus.INFERRED]
    unverified = [fact for fact in understanding.facts if fact.status == EvidenceStatus.UNVERIFIED]
    path.write_text("\n".join(["# Evidence Coverage Report", "", f"- Evidence chunks: {len(evidence_store.all())}", f"- Source Facts: {len(source_facts)}", f"- SOURCE_FACT with Evidence: {len(source_facts) - len(missing)}", f"- SOURCE_FACT_WITHOUT_EVIDENCE: {len(missing)}", f"- INVALID_EVIDENCE_REFERENCE: {len(invalid)}", f"- Inferred: {len(inferred)}", f"- Unverified: {len(unverified)}", ""]), encoding="utf-8")


def _write_questions(path: Path, questions) -> None:
    lines = ["# Inventor Questions", ""]
    for priority in ("P0", "P1", "P2"):
        selected = [item for item in questions if item.priority == priority]
        lines += [f"## {priority}", ""] + ([f"- [{item.question_id}] {item.text}" for item in selected] or ["- none"]) + [""]
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_technical_review(path: Path, understanding, evidence_store) -> None:
    def gs(items): return [f"- {item.text} 〔{', '.join(item.evidence_ids) or item.status.value}〕" for item in items] or ["- 无"]
    lines = ["# Technical Understanding Review", "", "## 一、Agent认为这个项目是做什么的", *gs(understanding.system_overview), "", "## 二、它识别出的技术问题", *gs(understanding.technical_problems), "", "## 三、系统组成"]
    lines += [f"- {item.name}：{item.description.text} 〔{', '.join(item.description.evidence_ids)}〕" for item in understanding.components] or ["- 无"]
    lines += ["", "## 四、核心流程"] + [f"- {item.step_id}：{item.text.text} 〔{', '.join(item.text.evidence_ids)}〕" for item in understanding.steps]
    lines += ["", "## 五、关键技术特征"] + [f"- {fact.statement} 〔{', '.join(fact.evidence_ids)}〕" for fact in understanding.facts if fact.category in {"component", "method_step"}]
    lines += ["", "## 六、关键参数"] + [f"- {item.name}: {item.value or '[待确认]'} {item.unit or '[单位待确认]'} 〔{', '.join(item.evidence_ids)}〕" for item in understanding.parameters]
    lines += ["", "## 七、关键公式"] + [f"- {item.equation_id}: `{item.original_expression}` 〔{', '.join(item.evidence_ids)}〕" for item in understanding.equations]
    lines += ["", "## 八、实验/验证", *gs(understanding.experiments), "", "## 九、Agent做出的推断", *gs([item for item in understanding.technical_effects + understanding.outputs if item.status == EvidenceStatus.INFERRED]), "", "## 十、Agent不确定的地方", *[f"- {item.text}" for item in understanding.uncertainties], "", "## 十一、需要发明人确认的问题", *[f"- [{item.priority}] {item.text}" for item in understanding.uncertainties], ""]
    path.write_text("\n".join(lines), encoding="utf-8")
