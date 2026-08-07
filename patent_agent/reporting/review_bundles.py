from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from patent_agent.review.claim_scope import render_scope_comparison, render_scope_review
from patent_agent.review.claims_support_matrix import render_claims_support_markdown


class ReviewBundleBuilder:
    def __init__(self, case_dir: Path):
        self.root = Path(case_dir) / "review"

    def a1(self, understanding, evidence_store, questions) -> Path:
        root = self._root("A1")
        lines = ["# Checkpoint A1 — Technical Understanding Review", "", "Every fact must be accepted, edited, rejected, or supplemented before A2.", ""]
        for fact in understanding.facts:
            lines += [f"## {fact.fact_id}", "", f"- Category: {fact.category}", f"- Status: {fact.status.value}", f"- Review: {fact.review_status.value}", f"- Evidence: {', '.join(fact.evidence_ids) or 'none'}", "", fact.statement, ""]
        (root / "technical_understanding_review.md").write_text("\n".join(lines), encoding="utf-8")
        source = [item for item in understanding.facts if item.status.value == "SOURCE_FACT"]
        (root / "evidence_coverage.md").write_text(f"# Evidence Coverage\n\n- Evidence chunks: {len(evidence_store.all())}\n- Source facts: {len(source)}\n- Missing evidence: {sum(not item.evidence_ids for item in source)}\n", encoding="utf-8")
        terms = sorted({item.name for item in understanding.components})
        (root / "terminology_review.md").write_text("# Terminology Review\n\n" + "\n".join(f"- {term}: UNREVIEWED" for term in terms) + "\n", encoding="utf-8")
        (root / "inventor_questions.md").write_text(_questions(questions), encoding="utf-8")
        (root / "review_objects.json").write_text(json.dumps([item.model_dump(mode="json") for item in understanding.facts], ensure_ascii=False, indent=2), encoding="utf-8")
        (root / "patent_knowledge.json").write_text(understanding.model_dump_json(indent=2), encoding="utf-8")
        evidence = evidence_store.all(); scope_counts = Counter(item.scope.value for item in evidence); fact_counts = Counter(item.status.value for item in understanding.facts)
        referenced = {identifier for item in understanding.facts for identifier in item.evidence_ids}; invalid = sorted(referenced - {item.evidence_id for item in evidence})
        coverage = ["# Evidence Coverage Report", "", f"- Evidence chunks: {len(evidence)}", f"- Invention-source chunks: {scope_counts.get('INVENTION_SOURCE', 0)}", f"- Reference/prior-art-candidate chunks: {scope_counts.get('REFERENCE', 0)}", f"- Technical facts: {len(understanding.facts)}", f"- SOURCE_FACT: {fact_counts.get('SOURCE_FACT', 0)}", f"- INFERRED: {fact_counts.get('INFERRED', 0)}", f"- UNVERIFIED: {fact_counts.get('UNVERIFIED', 0)}", f"- SOURCE_FACT_WITHOUT_EVIDENCE: {sum(item.status.value == 'SOURCE_FACT' and not item.evidence_ids for item in understanding.facts)}", f"- INVALID_EVIDENCE_REFERENCE: {len(invalid)}", f"- Referenced chunks: {len(referenced)}", "", "References are isolated as `REFERENCE / PRIOR_ART_CANDIDATE` and cannot support facts of the present paper."]
        (root / "evidence_coverage_report.md").write_text("\n".join(coverage) + "\n", encoding="utf-8")
        term_lines = ["# Terminology Registry", "", "| Source term | Proposed normalized term | Evidence | Review |", "|---|---|---|---|"]
        for item in understanding.components: term_lines.append(f"| {item.name} | {item.name} | {', '.join(item.description.evidence_ids)} | UNREVIEWED |")
        for item in understanding.parameters: term_lines.append(f"| {item.symbol or item.name} | {item.name} | {', '.join(item.evidence_ids)} | UNREVIEWED |")
        (root / "terminology_registry.md").write_text("\n".join(term_lines) + "\n", encoding="utf-8")
        equation_lines = ["# Equation Review", ""]
        for item in understanding.equations: equation_lines += [f"## {item.equation_id}", "", f"- Original: `{item.original_expression}`", f"- Normalized LaTeX: `{item.normalized_latex or 'UNVERIFIED'}`", f"- Status: {item.status.value}", f"- Evidence: {', '.join(item.evidence_ids)}", f"- Symbols: {json.dumps(item.symbols, ensure_ascii=False)}", f"- Review: {item.review_status.value}", ""]
        (root / "equation_review.md").write_text("\n".join(equation_lines), encoding="utf-8")
        question_counts = Counter(item.priority for item in questions); role_counts = Counter(item.question_role for item in questions)
        stats = {"schema_version": "2.0", "evidence_chunk_count": len(evidence), "invention_source_count": scope_counts.get("INVENTION_SOURCE", 0), "reference_count": scope_counts.get("REFERENCE", 0), "source_fact_count": fact_counts.get("SOURCE_FACT", 0), "inferred_count": fact_counts.get("INFERRED", 0), "unverified_count": fact_counts.get("UNVERIFIED", 0), "source_fact_without_evidence": sum(item.status.value == "SOURCE_FACT" and not item.evidence_ids for item in understanding.facts), "invalid_evidence_reference": len(invalid), "equation_count": len(understanding.equations), "p0_questions": question_counts.get("P0", 0), "p1_questions": question_counts.get("P1", 0), "p2_questions": question_counts.get("P2", 0), "question_roles": dict(role_counts), "a1_approved": False}
        (root / "a1_quality_statistics.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
        return root

    def a2(self, candidates, questions) -> Path:
        root = self._root("A2"); lines = ["# Checkpoint A2 — Invention Candidate Review", ""]
        for item in candidates:
            lines += [f"## {item.candidate_id}: {item.title}", "", f"- Review: {item.review_status.value}", f"- Evidence strength: {item.evidence_strength_score}", f"- Merge recommendation: {item.merge_recommendation or 'none'}", f"- Evidence: {', '.join(item.evidence_ids) or 'none'}", "", item.core_idea.text, ""]
        (root / "invention_candidates.md").write_text("\n".join(lines), encoding="utf-8")
        (root / "inventor_questions.md").write_text(_questions(questions), encoding="utf-8")
        (root / "review_objects.json").write_text(json.dumps([item.model_dump(mode="json") for item in candidates], ensure_ascii=False, indent=2), encoding="utf-8")
        return root

    def b(self, strategy, novelty, support_gaps, questions) -> Path:
        root = self._root("B")
        lines = ["# Checkpoint B — Protection Strategy Review", "", f"- Scope strategy: **{strategy.scope_strategy}**", f"- Core inventive concept: {strategy.inventive_concept}", "", "## Mandatory independent features", ""] + [f"- {item.text} | Evidence: {', '.join(item.evidence_ids)}" for item in strategy.independent_claim_core]
        lines += ["", "## Dependent features", ""] + [f"- {item.text}" for item in strategy.dependent_claim_features]
        lines += ["", "## Parameters not to lock", ""] + [f"- {item}" for item in strategy.parameters_to_avoid_locking]
        lines += ["", "## Support gaps", ""] + ([f"- {item}" for item in support_gaps] or ["- none"])
        (root / "protection_strategy.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        (root / "novelty_matrix.md").write_text("# Novelty Matrix\n\n" + "\n".join(f"- {item.feature_id}: {item.assessment} — {item.reasoning}" for item in novelty.assessments) + "\n", encoding="utf-8")
        (root / "feature_support.md").write_text("# Feature Support\n\n" + "\n".join(f"- {item.text}: {', '.join(item.evidence_ids) or 'none'}" for item in strategy.independent_claim_core + strategy.dependent_claim_features) + "\n", encoding="utf-8")
        (root / "terminology_registry.md").write_text(render_terminology_registry(strategy.broad_terms), encoding="utf-8")
        (root / "blocking_questions.md").write_text(_questions([item for item in questions if item.blocking_stage in {"B", "C"} and not item.answered]), encoding="utf-8")
        return root

    def c(self, claims, support, scope_review, questions) -> Path:
        root = self._root("C"); by_feature = {item.feature_id: item for item in support.records}
        lines = ["# Checkpoint C — Claims Review", ""]
        scope = {item.claim_number: item for item in scope_review.assessments}
        for claim in claims.claims:
            assessment = scope.get(claim.claim_number)
            lines += [f"## Claim {claim.claim_number}", "", f"- Parent: {', '.join(map(str, claim.parent_claims)) or 'none'}", f"- Review: {claim.review_status.value}", f"- Scope: {assessment.scope_level if assessment else 'dependent'}", "", claim.rendered_text, "", "### Features", ""]
            for feature in claim.features:
                record = by_feature.get(feature.feature_id)
                lines.append(f"- {feature.feature_id}: {feature.text} | Support: {record.support_status if record else 'UNKNOWN'} | Evidence: {', '.join(feature.evidence_ids) or 'none'}")
            lines.append("")
        (root / "claims_review.md").write_text("\n".join(lines), encoding="utf-8")
        (root / "claims_support_matrix.md").write_text(render_claims_support_markdown(support), encoding="utf-8")
        (root / "claim_scope_comparison.md").write_text(render_scope_comparison(scope_review), encoding="utf-8")
        (root / "claim_scope_risk.md").write_text(render_scope_review(scope_review), encoding="utf-8")
        (root / "blocking_questions.md").write_text(_questions([item for item in questions if item.blocking_stage == "C" and not item.answered]), encoding="utf-8")
        return root

    def _root(self, checkpoint: str) -> Path:
        root = self.root / f"checkpoint_{checkpoint}"; root.mkdir(parents=True, exist_ok=True); return root


def render_terminology_registry(terms) -> str:
    lines = ["# Terminology Registry", "", "| Concept | Source/aliases | Patent term | Human confirmed |", "|---|---|---|---|"]
    for item in terms: lines.append(f"| {item.concept_id} | {', '.join([item.selected_term] + item.alternatives)} | {item.patent_term or item.selected_term} | {'YES' if item.human_confirmed else 'NO'} |")
    return "\n".join(lines) + "\n"


def _questions(questions) -> str:
    lines = ["# Inventor Questions", ""]
    for item in questions: lines += [f"## {item.question_id}", "", f"- Priority: {item.priority}", f"- Role: {item.question_role}", f"- Blocking: {item.blocking_stage or 'none'}", f"- Answered: {item.answered}", "", item.text, ""]
    return "\n".join(lines)
