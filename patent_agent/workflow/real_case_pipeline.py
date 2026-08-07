from __future__ import annotations

import json
import shutil
from pathlib import Path

from patent_agent.agents import DeterministicGroundedAnalyzer, DeterministicGroundedInventionMiner, grounded_claims_to_tree, grounded_disclosure_to_draft, understanding_to_patent_knowledge
from patent_agent.core.config import Settings
from patent_agent.core.models import ClaimFeature, ClaimTerminologyRegistry, GroundedClaimSet, GroundedDisclosure, GroundedParagraph, GroundedProtectionStrategy, GroundedSection, GroundedStatement, PatentClaimV2, ReviewStatus, TerminologyChoice, TechnicalUnderstandingResult
from patent_agent.document import DocumentRenderer, PatentDocxValidator
from patent_agent.document.ast_factory import claims_to_ast, disclosure_to_ast
from patent_agent.evidence import EvidenceStore
from patent_agent.human_review import CandidateReviewEngine, CheckpointStatus, HumanCorrectionEngine, HumanReviewManager, ProtectionStrategyReviewer
from patent_agent.human_review.models import CaseWorkflowState, CorrectionAction, ReviewImport
from patent_agent.ingestion import SourceManager
from patent_agent.real_case import RealCaseManager
from patent_agent.reporting import ReviewBundleBuilder, render_terminology_registry
from patent_agent.review import ClaimFeatureEditor, ClaimScopeEngine, ClaimsSupportMatrixBuilder, generate_inventor_questions, render_claims_support_markdown, render_scope_comparison, render_scope_review
from patent_agent.search import ManualImportProvider
from patent_agent.agents.novelty_analysis_v2 import GroundedNoveltyAnalysisAgent


class RealCaseWorkflow:
    """Human-gated real-case workflow. No method auto-discovers input or auto-approves."""

    def __init__(self, settings: Settings, provider=None):
        self.settings = settings; self.provider = provider
        self.manager = RealCaseManager(settings.project_root); self.store = self.manager.case_store

    def run_a1(self, case_id: str, *, use_llm: bool = False, auto_approve: bool = False) -> Path:
        if auto_approve: raise PermissionError("AUTO_APPROVE_NOT_ALLOWED_FOR_REAL_CASE")
        manifest = self.manager.load(case_id)
        sources = sorted(path for path in (self.manager.case_dir(case_id) / "source").rglob("*") if path.is_file())
        if not sources: raise ValueError("REAL_CASE_EXPLICIT_SOURCE_REQUIRED")
        _, chunks, _ = SourceManager(self.store).ingest(case_id, sources)
        evidence = EvidenceStore(self.manager.case_dir(case_id) / "evidence")
        if use_llm:
            effective = self.manager.assert_llm_allowed(case_id, self.settings.patent_llm_mode, manifest.llm_mode)
            if self.provider is None: raise RuntimeError(f"LLM provider required for approved mode {effective}")
            from patent_agent.agents import GroundedTechnicalUnderstandingAgent
            from patent_agent.llm import StructuredLLMService
            understanding = GroundedTechnicalUnderstandingAgent().run(evidence, StructuredLLMService(self.provider, self.settings, self.manager.case_dir(case_id)))
        else:
            understanding = DeterministicGroundedAnalyzer().run(chunks, evidence)
        questions = generate_inventor_questions(understanding)
        self.store.save_stage(case_id, "p1_technical_understanding", understanding)
        (self.manager.case_dir(case_id) / "review" / "inventor_questions.json").write_text(json.dumps([item.model_dump(mode="json") for item in questions], ensure_ascii=False, indent=2), encoding="utf-8")
        root = ReviewBundleBuilder(self.manager.case_dir(case_id)).a1(understanding, evidence, questions)
        HumanReviewManager(self.manager.case_dir(case_id)).export_review("A1", [item.model_dump(mode="json") for item in understanding.facts])
        manifest.current_checkpoint = "A1"; manifest.case_state = CaseWorkflowState.A1_REVIEW; self.manager.save(manifest)
        return root

    def import_review(self, case_id: str, path: Path) -> Path:
        case_dir = self.manager.case_dir(case_id); review = ReviewImport.model_validate_json(Path(path).read_text(encoding="utf-8"))
        if review.case_id != case_id: raise ValueError("CORRECTION_CASE_MISMATCH")
        HumanReviewManager(case_dir).import_review(path)
        corrections = HumanCorrectionEngine(case_dir)
        if review.checkpoint == "A1":
            understanding = TechnicalUnderstandingResult.model_validate_json(self.store.latest_stage_path(case_id, "p1_technical_understanding").read_text(encoding="utf-8")); evidence = EvidenceStore(case_dir / "evidence")
            for item in review.corrections: understanding, _ = corrections.apply_fact(understanding, item, evidence)
            return self.store.save_stage(case_id, "p1_technical_understanding", understanding, human_modified=True)
        if review.checkpoint == "A2":
            candidates = _load_list(self.store.latest_stage_path(case_id, "p1_invention_candidates"), "candidate")
            from patent_agent.core.models import GroundedInventionCandidate
            candidates = [GroundedInventionCandidate.model_validate(item) for item in candidates]
            for item in review.corrections:
                target = next((candidate for candidate in candidates if candidate.candidate_id == item.target_id), None)
                if item.action == CorrectionAction.ACCEPT and target: target.review_status = ReviewStatus.LOCKED; target.locked = True
                elif item.action in {CorrectionAction.REJECT, CorrectionAction.DELETE} and target: target.review_status = ReviewStatus.REJECTED; target.locked = True
                elif item.action == CorrectionAction.MERGE:
                    ids = item.corrected_value.get("candidate_ids", [item.target_id]); merged = CandidateReviewEngine().merge(candidates, ids, item.corrected_value.get("new_id", "INV-M001")); candidates = [candidate for candidate in candidates if candidate.candidate_id not in ids] + [merged]
                elif item.action == CorrectionAction.SPLIT and target:
                    candidates = [candidate for candidate in candidates if candidate.candidate_id != target.candidate_id] + CandidateReviewEngine().split(target, item.corrected_value["parts"])
                corrections.record_generic(item, [item.target_id])
            return self.store.save_stage(case_id, "p1_invention_candidates", [item.model_dump() for item in candidates], human_modified=True)
        if review.checkpoint == "B":
            strategy = GroundedProtectionStrategy.model_validate_json(self.store.latest_stage_path(case_id, "p1_protection_strategy").read_text(encoding="utf-8"))
            for item in review.corrections:
                if item.target_id == "scope_strategy" and item.action == CorrectionAction.EDIT: strategy = ProtectionStrategyReviewer().select_scope(strategy, str(item.corrected_value))
                elif item.action == CorrectionAction.ACCEPT: strategy.review_status = ReviewStatus.LOCKED; strategy.locked = True
                corrections.record_generic(item, [item.target_id])
            return self.store.save_stage(case_id, "p1_protection_strategy", strategy, human_modified=True)
        claims = GroundedClaimSet.model_validate_json(self.store.latest_stage_path(case_id, "p1_claims").read_text(encoding="utf-8")); pool = {item.feature_id: item for claim in claims.claims for item in claim.features}; editor = ClaimFeatureEditor()
        for item in review.corrections:
            details = item.corrected_value if isinstance(item.corrected_value, dict) else {}
            action = {CorrectionAction.DELETE: "REMOVE", CorrectionAction.REJECT: "REMOVE"}.get(item.action, item.action.value)
            if item.action == CorrectionAction.ACCEPT:
                for claim in claims.claims:
                    for feature in claim.features:
                        if feature.feature_id == item.target_id: feature.review_status = ReviewStatus.LOCKED; feature.locked = True
            else:
                claims = editor.edit(claims, claim_number=int(details["claim_number"]), action=action, feature_id=item.target_id, supported_pool=pool, text=details.get("text"), target_claim=details.get("target_claim"))
            corrections.record_generic(item, [item.target_id])
        self.store.save_stage(case_id, "p1_claims", claims, human_modified=True); self._refresh_c(case_id); return self.store.latest_stage_path(case_id, "p1_claims")

    def approve(self, case_id: str, checkpoint: str, *, risk_acknowledged: bool = False) -> None:
        case_dir = self.manager.case_dir(case_id); review = HumanReviewManager(case_dir)
        statuses = self._review_statuses(case_id, checkpoint)
        questions = _questions(case_dir); blocking = [item.question_id for item in questions if item.priority == "P0" and not item.answered and item.blocking_stage in {checkpoint, "B" if checkpoint in {"B", "C"} else checkpoint}]
        scope_warning = False
        if checkpoint == "C":
            scope_path = self.store.latest_stage_path(case_id, "p1_claim_scope")
            from patent_agent.review.claim_scope import ClaimScopeReview
            scope_warning = any(item.warning_requires_ack for item in ClaimScopeReview.model_validate_json(scope_path.read_text(encoding="utf-8")).assessments)
        review.approve(checkpoint, statuses, blocking_questions=blocking, scope_warning=scope_warning, risk_acknowledged=risk_acknowledged)

    def answer_inventor_question(self, case_id: str, question_id: str, statement: str) -> Path:
        from patent_agent.core.models import InventorAssertion
        case_dir = self.manager.case_dir(case_id); path = case_dir / "review" / "inventor_questions.json"
        questions = _questions(case_dir); found = False
        for index, item in enumerate(questions):
            if item.question_id == question_id:
                questions[index] = item.model_copy(update={"answered": True}); found = True
        if not found: raise KeyError(question_id)
        path.write_text(json.dumps([item.model_dump(mode="json") for item in questions], ensure_ascii=False, indent=2), encoding="utf-8")
        assertion = InventorAssertion(assertion_id=f"IA-{question_id}", question_id=question_id, statement=statement, confirmed_by_user=True, confirmed_by="user")
        return self.store.save_inventor_assertion(case_id, assertion)

    def continue_case(self, case_id: str, prior_art: Path | None = None) -> Path:
        case_dir = self.manager.case_dir(case_id); review = HumanReviewManager(case_dir); manifest = self.manager.load(case_id); bundle = ReviewBundleBuilder(case_dir)
        if manifest.current_checkpoint == "A1":
            if review.machine.records["A1"].status != CheckpointStatus.APPROVED: raise ValueError("CHECKPOINT_A1_NOT_APPROVED")
            if not manifest.synthetic and manifest.publication_review_status != "CONFIRMED":
                raise ValueError("PUBLICATION_STATUS_REQUIRED_BEFORE_A2")
            understanding = TechnicalUnderstandingResult.model_validate_json(self.store.latest_stage_path(case_id, "p1_technical_understanding").read_text(encoding="utf-8")); candidates = DeterministicGroundedInventionMiner().run(understanding)
            self.store.save_stage(case_id, "p1_invention_candidates", [item.model_dump() for item in candidates]); questions = _questions(case_dir); root = bundle.a2(candidates, questions); HumanReviewManager(case_dir).export_review("A2", [item.model_dump(mode="json") for item in candidates]); manifest.current_checkpoint = "A2"; manifest.case_state = CaseWorkflowState.A2_REVIEW
            _mark_current(case_dir, "knowledge", "candidate")
        elif manifest.current_checkpoint == "A2":
            if review.machine.records["A2"].status != CheckpointStatus.APPROVED: raise ValueError("CHECKPOINT_A2_NOT_APPROVED")
            if prior_art is None or not Path(prior_art).exists(): raise ValueError("PRIOR_ART_EXPLICIT_PATH_REQUIRED")
            candidates = _load_candidates(self.store.latest_stage_path(case_id, "p1_invention_candidates")); selected = next((item for item in candidates if item.review_status != ReviewStatus.REJECTED), None)
            if selected is None: raise ValueError("AT_LEAST_ONE_APPROVED_CANDIDATE_REQUIRED")
            prior_store = EvidenceStore(case_dir / "search" / "evidence"); prior_store.build_prior_art(ManualImportProvider(Path(prior_art)).search(selected.title)); novelty = GroundedNoveltyAnalysisAgent().run(selected, prior_store); self.store.save_stage(case_id, "p1_novelty", novelty)
            strategy = _deterministic_strategy(selected); self.store.save_stage(case_id, "p1_protection_strategy", strategy); questions = _questions(case_dir); root = bundle.b(strategy, novelty, strategy.support_gaps, questions); HumanReviewManager(case_dir).export_review("B", [{"id": "scope_strategy", "value": strategy.scope_strategy}] + [{"id": f"mandatory-{i}", "value": item.model_dump(mode="json")} for i, item in enumerate(strategy.independent_claim_core, 1)]); manifest.current_checkpoint = "B"; manifest.case_state = CaseWorkflowState.B_REVIEW
            _mark_current(case_dir, "candidate", "strategy")
        elif manifest.current_checkpoint == "B":
            if review.machine.records["B"].status != CheckpointStatus.APPROVED: raise ValueError("CHECKPOINT_B_NOT_APPROVED")
            self._draft_c(case_id); root = case_dir / "review" / "checkpoint_C"; manifest.current_checkpoint = "C"; manifest.case_state = CaseWorkflowState.C_REVIEW
            _mark_current(case_dir, "strategy", "disclosure", "claim_feature", "claim", "support_matrix", "scope_review")
        else:
            if review.machine.records["C"].status != CheckpointStatus.APPROVED: raise ValueError("CHECKPOINT_C_NOT_APPROVED")
            root = self.finalize(case_id); manifest.current_checkpoint = "FINAL"; manifest.case_state = CaseWorkflowState.VALIDATED
        self.manager.save(manifest); return root

    def _draft_c(self, case_id: str) -> None:
        case_dir = self.manager.case_dir(case_id); understanding = TechnicalUnderstandingResult.model_validate_json(self.store.latest_stage_path(case_id, "p1_technical_understanding").read_text(encoding="utf-8")); strategy = GroundedProtectionStrategy.model_validate_json(self.store.latest_stage_path(case_id, "p1_protection_strategy").read_text(encoding="utf-8")); evidence = EvidenceStore(case_dir / "evidence")
        disclosure = _deterministic_disclosure(self.store.load(case_id).title, understanding); claims = _deterministic_claims(self.store.load(case_id).title, strategy, understanding)
        self.store.save_stage(case_id, "p1_disclosure", disclosure); self.store.save_stage(case_id, "p1_claims", claims); self._refresh_c(case_id, disclosure, claims, evidence)

    def _refresh_c(self, case_id: str, disclosure=None, claims=None, evidence=None) -> None:
        case_dir = self.manager.case_dir(case_id); disclosure = disclosure or GroundedDisclosure.model_validate_json(self.store.latest_stage_path(case_id, "p1_disclosure").read_text(encoding="utf-8")); claims = claims or GroundedClaimSet.model_validate_json(self.store.latest_stage_path(case_id, "p1_claims").read_text(encoding="utf-8")); evidence = evidence or EvidenceStore(case_dir / "evidence"); strategy = GroundedProtectionStrategy.model_validate_json(self.store.latest_stage_path(case_id, "p1_protection_strategy").read_text(encoding="utf-8")); from patent_agent.core.models import GroundedNoveltyMatrix
        novelty = GroundedNoveltyMatrix.model_validate_json(self.store.latest_stage_path(case_id, "p1_novelty").read_text(encoding="utf-8")); support = ClaimsSupportMatrixBuilder().build(claims, disclosure, evidence, draft_mode=True); scope = ClaimScopeEngine().assess(claims, strategy, novelty, support, ClaimTerminologyRegistry(terms=strategy.broad_terms)); self.store.save_stage(case_id, "p1_claim_support", support); self.store.save_stage(case_id, "p1_claim_scope", scope); questions = _questions(case_dir); ReviewBundleBuilder(case_dir).c(claims, support, scope, questions); HumanReviewManager(case_dir).export_review("C", [feature.model_dump(mode="json") for claim in claims.claims for feature in claim.features])

    def finalize(self, case_id: str) -> Path:
        case_dir = self.manager.case_dir(case_id); output = self.settings.output_root / "real_case" / case_id; output.mkdir(parents=True, exist_ok=True); evidence = EvidenceStore(case_dir / "evidence")
        understanding = TechnicalUnderstandingResult.model_validate_json(self.store.latest_stage_path(case_id, "p1_technical_understanding").read_text(encoding="utf-8")); disclosure = GroundedDisclosure.model_validate_json(self.store.latest_stage_path(case_id, "p1_disclosure").read_text(encoding="utf-8")); claims = GroundedClaimSet.model_validate_json(self.store.latest_stage_path(case_id, "p1_claims").read_text(encoding="utf-8")); support = json.loads(self.store.latest_stage_path(case_id, "p1_claim_support").read_text(encoding="utf-8")); from patent_agent.review.claim_scope import ClaimScopeReview
        scope = ClaimScopeReview.model_validate_json(self.store.latest_stage_path(case_id, "p1_claim_scope").read_text(encoding="utf-8")); knowledge = understanding_to_patent_knowledge(understanding, evidence)
        from patent_agent.agents import FigurePlanner
        from patent_agent.document.figure_renderer import PatentFigureRenderer
        from patent_agent.workflow.v2_pipeline import _ground_figure
        figures = [_ground_figure(item, understanding) for item in FigurePlanner().run(knowledge)]
        figures = [PatentFigureRenderer().render(item, output / "figures") for item in figures]
        (output / "figures.json").write_text(json.dumps([item.model_dump(mode="json") for item in figures], ensure_ascii=False, indent=2), encoding="utf-8")
        draft = grounded_disclosure_to_draft(disclosure, knowledge, figures); tree = grounded_claims_to_tree(claims); renderer = DocumentRenderer(self.settings.template_root); disclosure_docx = renderer.render(disclosure_to_ast(case_id, draft), output / "技术交底书.docx"); claims_docx = renderer.render(claims_to_ast(case_id, tree), output / "权利要求草案.docx"); validator = PatentDocxValidator(); validation = validator.validate(disclosure_docx, export_pdf=True); claims_validation = validator.inspect_word(claims_docx, export_pdf=True)
        for name, data in (("technical_understanding_final.json", understanding), ("disclosure_final.json", disclosure), ("claims_final.json", claims)):
            (output / name).write_text(data.model_dump_json(indent=2), encoding="utf-8")
        candidates = _load_candidates(self.store.latest_stage_path(case_id, "p1_invention_candidates")); strategy = GroundedProtectionStrategy.model_validate_json(self.store.latest_stage_path(case_id, "p1_protection_strategy").read_text(encoding="utf-8"))
        (output / "invention_candidates_final.json").write_text(json.dumps([item.model_dump(mode="json") for item in candidates], ensure_ascii=False, indent=2), encoding="utf-8"); (output / "protection_strategy_final.json").write_text(strategy.model_dump_json(indent=2), encoding="utf-8")
        (output / "claims_support_matrix.json").write_text(json.dumps(support, ensure_ascii=False, indent=2), encoding="utf-8"); from patent_agent.core.models import ClaimsSupportMatrix
        (output / "claims_support_matrix.md").write_text(render_claims_support_markdown(ClaimsSupportMatrix.model_validate(support)), encoding="utf-8"); (output / "claim_scope_comparison.md").write_text(render_scope_comparison(scope), encoding="utf-8"); (output / "claim_scope_review.md").write_text(render_scope_review(scope), encoding="utf-8")
        from patent_agent.review import build_traceability, render_traceability_markdown
        traceability = build_traceability(disclosure, claims, understanding, figures); (output / "traceability.json").write_text(traceability.model_dump_json(indent=2), encoding="utf-8"); (output / "traceability_report.md").write_text(render_traceability_markdown(traceability), encoding="utf-8")
        (output / "terminology_registry.md").write_text(render_terminology_registry(strategy.broad_terms), encoding="utf-8")
        questions = _questions(case_dir); (output / "inventor_questions.json").write_text(json.dumps([item.model_dump(mode="json") for item in questions], ensure_ascii=False, indent=2), encoding="utf-8"); (output / "inventor_questions.md").write_text("# Inventor Questions\n\n" + "\n".join(f"- {item.question_id} [{item.priority}] Blocking={item.blocking_stage or 'none'} Answered={item.answered}: {item.text}" for item in questions) + "\n", encoding="utf-8")
        from patent_agent.human_review.models import HumanCorrection
        corrections_path = case_dir / "review" / "human_corrections.jsonl"; corrections = [HumanCorrection.model_validate_json(line) for line in corrections_path.read_text(encoding="utf-8").splitlines() if line.strip()] if corrections_path.exists() else []
        (output / "human_corrections.json").write_text(json.dumps([item.model_dump(mode="json") for item in corrections], ensure_ascii=False, indent=2), encoding="utf-8")
        from patent_agent.evaluation import ModelEvaluationEngine
        evaluator = ModelEvaluationEngine(); eval_root = case_dir / "evaluation_runs"; eval_root.mkdir(parents=True, exist_ok=True); run_id = f"RUN-{1 + len([path for path in eval_root.iterdir() if path.is_dir()]):03d}"
        snapshot = evaluator.create_snapshot(run_id=run_id, case_id=case_id, evidence_file=case_dir / "evidence" / "chunks.jsonl", prompt_versions={"technical_understanding": "v2.2", "invention_mining": "v2.0", "claims": "v2.1", "scope": scope.deterministic_rule_version}, provider=getattr(self.provider, "provider_name", "privacy-safe-deterministic"), model=getattr(self.provider, "model", "deterministic"), checkpoint_starting_state="A1_REVIEW")
        merged_sources = {identifier for item in candidates for identifier in item.merged_from}; generated_candidates = sorted(merged_sources or {item.candidate_id for item in candidates}); proposed_features = sorted({item.feature_id for claim in claims.claims for item in claim.features} | {item.target_id for item in corrections if "claim_feature" in item.target_type})
        summary = evaluator.evaluate(snapshot=snapshot, corrections=corrections, generated_fact_ids=[item.fact_id for item in understanding.facts], generated_candidate_ids=generated_candidates, proposed_feature_ids=proposed_features, final_claims=claims, scope_review=scope, llm_audit_path=case_dir / "logs" / "llm_calls.jsonl")
        eval_run = evaluator.save_run(eval_root, snapshot, summary)
        for name in ("evaluation_summary.json", "model_evaluation_report.md", "technical_understanding_scorecard.md"): shutil.copy2(eval_run / name, output / name)
        (output / "validation_report.md").write_text(f"# Validation\n\n- XML/Word: {'PASS' if validation['pass'] else 'FAIL'}\n- OMML: {validation['xml']['omml_count']}\n- Residual LaTeX: {validation['xml']['residual_latex_in_omml']}\n- Claims Word available: {claims_validation.get('available')}\n", encoding="utf-8")
        (output / "pipeline_report.md").write_text(f"# Real Case Pipeline Report\n\n- Case: {case_id}\n- Checkpoint C: APPROVED\n- Claims support: {support['validation_status']}\n- Scope review: complete\n- Traceability links: {len(traceability.links)}\n- Broken links: {len(traceability.broken_links)}\n- Word validation: {'PASS' if validation['pass'] else 'FAIL'}\n", encoding="utf-8")
        if not validation["pass"] or support["validation_status"] != "PASS" or traceability.broken_links:
            raise RuntimeError("REAL_CASE_FINAL_QUALITY_GATE_FAILED")
        final_review = HumanReviewManager(case_dir)
        final_review.machine.configure("FINAL", [])
        if final_review.machine.records["FINAL"].status == CheckpointStatus.NOT_STARTED: final_review.machine.transition("FINAL", CheckpointStatus.GENERATED)
        final_review.machine.transition("FINAL", CheckpointStatus.UNDER_REVIEW)
        final_review.machine.transition("FINAL", CheckpointStatus.APPROVED, reviewed_ids=[])
        final_review.machine.save(final_review.state_path)
        _mark_current(case_dir, "knowledge", "candidate", "strategy", "disclosure", "claim_feature", "claim", "support_matrix", "scope_review", "figure", "traceability")
        return output

    def _review_statuses(self, case_id: str, checkpoint: str):
        if checkpoint == "A1": return {item.fact_id: item.review_status for item in TechnicalUnderstandingResult.model_validate_json(self.store.latest_stage_path(case_id, "p1_technical_understanding").read_text(encoding="utf-8")).facts}
        if checkpoint == "A2": return {item.candidate_id: item.review_status for item in _load_candidates(self.store.latest_stage_path(case_id, "p1_invention_candidates"))}
        if checkpoint == "B":
            item = GroundedProtectionStrategy.model_validate_json(self.store.latest_stage_path(case_id, "p1_protection_strategy").read_text(encoding="utf-8")); return {"scope_strategy": item.review_status, **{f"mandatory-{i}": item.review_status for i, _ in enumerate(item.independent_claim_core, 1)}}
        claims = GroundedClaimSet.model_validate_json(self.store.latest_stage_path(case_id, "p1_claims").read_text(encoding="utf-8")); return {item.feature_id: item.review_status for claim in claims.claims for item in claim.features}


def _deterministic_strategy(candidate):
    return GroundedProtectionStrategy(inventive_concept=candidate.core_idea.text, independent_claim_core=candidate.mandatory_features, dependent_claim_features=candidate.optional_features, optional_features=[], broad_terms=[TerminologyChoice(concept_id=f"TERM-{i:03d}", selected_term=text.text.split("，", 1)[0][:20], evidence_ids=text.evidence_ids) for i, text in enumerate(candidate.mandatory_features, 1)], narrow_terms=[], parameters_to_avoid_locking=[], alternative_embodiments_needed=[], support_gaps=[], risks=["Prior-art coverage is limited to explicitly imported material."], inventor_questions=candidate.inventor_questions)


def _deterministic_disclosure(title, understanding):
    paragraphs = []
    for i, fact in enumerate(understanding.facts, 1):
        if fact.review_status == ReviewStatus.REJECTED: continue
        cleaned = "\n".join(line for line in fact.statement.splitlines() if not line.strip().startswith(("FORMULA ", "SYMBOL ", "PARAM "))).strip()
        if not cleaned: continue
        paragraphs.append(GroundedParagraph(paragraph_id=f"DISC-06-P{i:03d}", section_id="06", text=cleaned, evidence_ids=fact.evidence_ids, fact_ids=[fact.fact_id], derived_from=[fact.fact_id], status=fact.status, human_modified=fact.human_modified, review_status=fact.review_status, locked=fact.locked))
    anchor = next((fact for fact in understanding.facts if fact.review_status != ReviewStatus.REJECTED), None)
    figure_paragraphs = [GroundedParagraph(paragraph_id="DISC-08-P001", section_id="08", text="附图展示经人工审查的技术流程及系统结构。", evidence_ids=anchor.evidence_ids, fact_ids=[anchor.fact_id], derived_from=[anchor.fact_id], status=anchor.status)] if anchor else []
    return GroundedDisclosure(title=title, sections=[GroundedSection(section_id="06", title="6. 技术方案", paragraphs=paragraphs), GroundedSection(section_id="08", title="8. 附图说明", paragraphs=figure_paragraphs)])


def _deterministic_claims(title, strategy, understanding):
    features = []
    for i, statement in enumerate(strategy.independent_claim_core, 1):
        facts = [fact for fact in understanding.facts if set(fact.evidence_ids) & set(statement.evidence_ids) and fact.review_status != ReviewStatus.REJECTED]
        features.append(ClaimFeature(feature_id=f"CORE-F{i:03d}", text=statement.text, source_fact_ids=[fact.fact_id for fact in facts], evidence_ids=statement.evidence_ids, support_status="SUPPORTED" if facts and statement.evidence_ids else "UNSUPPORTED", mandatory=True))
    text = "一种经人工审查的技术方法，其特征在于，包括：" + "；".join(item.text.rstrip("。；") for item in features) + "。"
    return GroundedClaimSet(title=title, claims=[PatentClaimV2(claim_number=1, claim_type="method", features=features, rendered_text=text, draft_strategy=strategy.scope_strategy.lower())])


def _questions(case_dir):
    from patent_agent.core.models import InventorQuestion
    path = case_dir / "review" / "inventor_questions.json"; return [InventorQuestion.model_validate(item) for item in json.loads(path.read_text(encoding="utf-8"))] if path.exists() else []


def _load_list(path, kind): return json.loads(Path(path).read_text(encoding="utf-8"))
def _load_candidates(path):
    from patent_agent.core.models import GroundedInventionCandidate
    return [GroundedInventionCandidate.model_validate(item) for item in _load_list(path, "candidate")]


def _mark_current(case_dir: Path, *artifact_ids: str) -> None:
    from patent_agent.human_review import DependencyGraph
    path = Path(case_dir) / "review" / "dependency_graph.json"
    if not path.exists(): return
    graph = DependencyGraph.load(path)
    for artifact_id in artifact_ids: graph.mark_current(artifact_id)
    graph.save(path)
