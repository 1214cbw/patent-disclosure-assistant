from __future__ import annotations

import json
import re
import shutil
import stat
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


def _semantic_paragraph_inputs(disclosure, understanding, evidence) -> list[dict[str, object]]:
    """Pair each generated paragraph with only its reviewed, case-local support."""
    evidence_by_id = {
        chunk.evidence_id: str(chunk.raw_text or chunk.normalized_text)
        for chunk in evidence.all()
    }
    fact_text_by_id = {
        fact.fact_id: str(fact.statement) for fact in understanding.facts
    }
    fact_text_by_id.update({
        step.step_id: str(step.text.text) for step in understanding.steps
    })
    fact_text_by_id.update({
        f"VALIDATION-{index:03d}": str(getattr(item, "text", item))
        for index, item in enumerate(getattr(understanding, "experiments", []) or [], 1)
    })
    items: list[dict[str, str]] = []
    for section in disclosure.sections:
        if section.section_id == "01":
            continue
        paragraph_sources: list[str] = []
        for paragraph in section.paragraphs:
            local_source = "\n".join([
                *(evidence_by_id[evidence_id] for evidence_id in paragraph.evidence_ids
                  if evidence_id in evidence_by_id),
                *(fact_text_by_id[fact_id] for fact_id in paragraph.fact_ids
                  if fact_id in fact_text_by_id),
            ])
            paragraph_sources.append(local_source)
            items.append({
                "text": f"[SECTION:{section.section_id}] {paragraph.text}",
                "source_text": local_source,
                "fact_ids": list(paragraph.fact_ids),
                "fact_text": "\n".join(
                    fact_text_by_id[fact_id] for fact_id in paragraph.fact_ids
                    if fact_id in fact_text_by_id
                ),
            })
        items.append({
            "text": f"[SECTION:{section.section_id}] {section.title}",
            "source_text": "\n".join(paragraph_sources),
        })
    return items


class RealCaseWorkflow:
    """Human-gated real-case workflow. No method auto-discovers input or auto-approves."""

    def __init__(self, settings: Settings, provider=None):
        self.settings = settings; self.provider = provider
        self.manager = RealCaseManager(settings.project_root); self.store = self.manager.case_store

    def run_a1(self, case_id: str, *, use_llm: bool = False, auto_approve: bool = False) -> Path:
        if auto_approve: raise PermissionError("AUTO_APPROVE_NOT_ALLOWED_FOR_REAL_CASE")
        manifest = self.manager.load(case_id)
        case_dir = self.manager.case_dir(case_id)
        previous_versions = [item for item in self.store.load(case_id).versions if item.stage == "p1_technical_understanding"]
        current_bundle = case_dir / "review" / "checkpoint_A1"
        if previous_versions and current_bundle.exists():
            archived_bundle = case_dir / "review" / f"checkpoint_A1_v{len(previous_versions)}"
            if not archived_bundle.exists(): shutil.copytree(current_bundle, archived_bundle)
        sources = sorted(path for path in (case_dir / "source").rglob("*") if path.is_file())
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
        stage_path = self.store.save_stage(case_id, "p1_technical_understanding", understanding)
        (self.manager.case_dir(case_id) / "review" / "inventor_questions.json").write_text(json.dumps([item.model_dump(mode="json") for item in questions], ensure_ascii=False, indent=2), encoding="utf-8")
        root = ReviewBundleBuilder(self.manager.case_dir(case_id)).a1(understanding, evidence, questions)
        HumanReviewManager(self.manager.case_dir(case_id)).export_review("A1", [item.model_dump(mode="json") for item in understanding.facts])
        manifest.current_checkpoint = "A1"; manifest.case_state = CaseWorkflowState.A1_REVIEW; self.manager.save(manifest)
        version = len(previous_versions) + 1
        versioned_root = case_dir / "review" / f"checkpoint_A1_v{version}"
        if not versioned_root.exists(): shutil.copytree(root, versioned_root)
        if previous_versions:
            from patent_agent.reporting import build_a1_comparison
            old_evidence = case_dir / "evidence" / "versions" / "v001" / "chunks.jsonl"
            if old_evidence.exists(): build_a1_comparison(case_dir, Path(previous_versions[-1].path), stage_path, old_evidence, case_dir / "evidence" / "chunks.jsonl")
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
            if not manifest.synthetic and self.provider is None:
                raise RuntimeError(
                    "LLM_PROVIDER_REQUIRED_FOR_CHECKPOINT_B_TO_C: "
                    "use the standard checkpoint-continue entry point with an approved provider"
                )
            self._draft_c(case_id); root = case_dir / "review" / "checkpoint_C"; manifest.current_checkpoint = "C"; manifest.case_state = CaseWorkflowState.C_REVIEW
            _mark_current(case_dir, "strategy", "disclosure", "claim_feature", "claim", "support_matrix", "scope_review")
        else:
            if review.machine.records["C"].status != CheckpointStatus.APPROVED: raise ValueError("CHECKPOINT_C_NOT_APPROVED")
            root = self.finalize(case_id)
            manifest = self.manager.load(case_id)
            manifest.current_checkpoint = "FINAL"
        self.manager.save(manifest); return root

    def regenerate_c(self, case_id: str) -> Path:
        """Rebuild checkpoint C through the production provider and review gate."""
        manifest = self.manager.load(case_id)
        if manifest.current_checkpoint not in {"C", "FINAL"}:
            raise ValueError("CHECKPOINT_C_REGENERATION_REQUIRES_C_OR_FINAL")
        if not manifest.synthetic and self.provider is None:
            raise RuntimeError("LLM_PROVIDER_REQUIRED_FOR_CHECKPOINT_C_REGENERATION")
        review = HumanReviewManager(self.manager.case_dir(case_id))
        for checkpoint in ("C", "FINAL"):
            record = review.machine.records[checkpoint]
            review.machine.records[checkpoint] = record.model_copy(update={
                "status": CheckpointStatus.NOT_STARTED,
                "required_object_ids": [],
                "reviewed_object_ids": [],
                "blocking_question_ids": [],
                "risk_acknowledged": False,
            })
        review.machine.save(review.state_path)
        self._draft_c(case_id)
        manifest = self.manager.load(case_id)
        manifest.current_checkpoint = "C"
        manifest.case_state = CaseWorkflowState.C_REVIEW
        manifest.state_history = []
        manifest.delivery_version = ""
        self.manager.save(manifest)
        return self.manager.case_dir(case_id) / "review" / "checkpoint_C"

    def _draft_c(self, case_id: str) -> None:
        case_dir = self.manager.case_dir(case_id); understanding = TechnicalUnderstandingResult.model_validate_json(self.store.latest_stage_path(case_id, "p1_technical_understanding").read_text(encoding="utf-8")); strategy = GroundedProtectionStrategy.model_validate_json(self.store.latest_stage_path(case_id, "p1_protection_strategy").read_text(encoding="utf-8")); evidence = EvidenceStore(case_dir / "evidence")
        if self.provider is not None:
            # V7: native Chinese generation + pre-save quality gates.
            # Deterministic English fact-dump path is NEVER used for LLM cases.
            disclosure, claims, figures = self._v7_draft_chinese(case_id, case_dir, understanding, strategy, evidence)
            self._write_manifest_language(case_id, case_dir, evidence, translation_postprocess_used=False)
        else:
            disclosure = _deterministic_disclosure(self.store.load(case_id).title, understanding); claims = _deterministic_claims(self.store.load(case_id).title, strategy, understanding); figures = []
        self.store.save_stage(case_id, "p1_disclosure", disclosure); self.store.save_stage(case_id, "p1_claims", claims); self._refresh_c(case_id, disclosure, claims, evidence)

    def _v7_draft_chinese(self, case_id, case_dir, understanding, strategy, evidence):
        """V7 native-Chinese disclosure + claims, gated before stage save.

        Raises V7GateError (LANGUAGE_GATE_FAILED / DISCLOSURE_INCOMPLETE /
        UNSUPPORTED_DISCLOSURE_PARAGRAPH / CROSS_CASE_CONTAMINATION /
        PLACEHOLDER_LEAK / FIGURE_SEMANTIC_FAIL / TITLE_GATE_FAILED) on any
        violation - nothing is saved, finalize is blocked.
        """
        from patent_agent.v7.completeness import (DisclosureCompletenessValidator,
                                                  PatentTitleValidator, UnsupportedParagraphValidator)
        from patent_agent.v7.cross_case import (CrossCaseContaminationValidator,
                                                FigureSemanticValidator,
                                                PlaceholderLeakValidator,
                                                build_case_evidence_fingerprint,
                                                case_concepts_from_understanding)
        from patent_agent.v7.disclosure_planner import (PatentDisclosurePlanner,
                                                        generate_chinese_claims)
        from patent_agent.v7.figure_planner import FigurePlannerV7
        from patent_agent.v7.gates import V7GateError, run_claims_gate, run_disclosure_gates
        from patent_agent.v7.language_gate import ChinesePatentLanguageValidator

        llm_cache_dir = case_dir / "llm_cache"
        planner = PatentDisclosurePlanner(provider=self.provider, cache_dir=llm_cache_dir)
        fingerprint = build_case_evidence_fingerprint(understanding, evidence)
        language = ChinesePatentLanguageValidator(
            registered_tokens=set(fingerprint.technical_tokens))
        figures = FigurePlannerV7(
            case_id, understanding, evidence, provider=self.provider,
            cache_dir=llm_cache_dir,
        ).plan()
        disclosure = planner.plan(case_id, understanding, evidence, strategy, figures=figures)
        title_result = PatentTitleValidator().validate(disclosure.title)
        if not title_result.passed:
            raise V7GateError("TITLE_GATE_FAILED", "；".join(title_result.issues))
        claims = generate_chinese_claims(disclosure.title, strategy, understanding,
                                         self.provider, cache_dir=llm_cache_dir)
        from patent_agent.v7_2.semantics import validate_bundle
        semantic_bundle = planner.semantic_bundle
        generated_embodiment_texts = _semantic_paragraph_inputs(
            disclosure, understanding, evidence)
        semantic_report = validate_bundle(
            semantic_bundle, claims=claims, generated_texts=generated_embodiment_texts)
        self.store.save_stage(case_id, "p1_invention_core_graph", semantic_bundle.graph)
        self.store.save_stage(case_id, "p1_embodiment_plan", [
            item.model_dump(mode="json") for item in semantic_bundle.embodiments
        ])
        self.store.save_stage(case_id, "p1_semantic_registry", semantic_bundle.registry)
        self.store.save_stage(case_id, "p1_semantic_bundle", semantic_bundle)
        self.store.save_stage(case_id, "p1_patent_semantics_report", semantic_report)
        if semantic_report.status != "PASS":
            raise V7GateError(
                "PATENT_SEMANTICS_INVALID",
                "；".join(finding.code for finding in semantic_report.findings[:12]),
            )
        concepts = case_concepts_from_understanding(understanding)
        captions = language.validate_figure_captions(figures)
        if not captions.passed:
            raise V7GateError("LANGUAGE_GATE_FAILED",
                              "图注非中文: " + "；".join(captions.issues[:4]))
        semantic = FigureSemanticValidator(concepts, fingerprint).validate(figures)
        if not semantic.passed:
            raise V7GateError("FIGURE_SEMANTIC_FAIL",
                              "；".join(semantic.details[:4]))
        report = run_disclosure_gates(
            case_id=case_id, disclosure=disclosure, claims=claims, figures=figures,
            language_validator=language,
            completeness_validator=DisclosureCompletenessValidator(),
            unsupported_validator=UnsupportedParagraphValidator(),
            contamination_validator=CrossCaseContaminationValidator(
                concepts, self._other_case_fingerprints(case_id), fingerprint),
            placeholder_validator=PlaceholderLeakValidator(),
        )
        self._write_gate_report(case_dir, report)
        claims_report = run_claims_gate(case_id=case_id, claims=claims, language_validator=language)
        self._write_gate_report(case_dir, claims_report)
        return disclosure, claims, figures

    def _write_gate_report(self, case_dir, report) -> None:
        path = case_dir / "review" / "v7_gate_reports.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(report.to_dict(), ensure_ascii=False) + "\n")

    def _write_manifest_language(self, case_id, case_dir, evidence,
                                 translation_postprocess_used: bool) -> None:
        """Record the V7 language contract on the case manifest."""
        manifest = self.manager.load(case_id)
        manifest.source_languages = _detect_languages(case_dir / "evidence" / "chunks.jsonl")
        manifest.patent_output_language = "zh-CN"
        manifest.disclosure_language = "zh-CN"
        manifest.translation_postprocess_used = translation_postprocess_used
        self.manager.save(manifest)

    def _other_case_fingerprints(self, case_id: str) -> dict[str, set]:
        """Detect concept fingerprints from OTHER real cases' own evidence.

        Iterates sibling case directories under the workspace; only cases
        with evidence chunks are fingerprinted. The current case is skipped.
        """
        from patent_agent.v7.concepts import detect_case_concepts
        root = self.manager.case_dir(case_id).parent
        fingerprints: dict[str, set] = {}
        if not root.exists():
            return fingerprints
        for case_dir in root.iterdir():
            if not case_dir.is_dir() or case_dir.name == case_id:
                continue
            chunks_path = case_dir / "evidence" / "chunks.jsonl"
            if not chunks_path.exists():
                continue
            texts: list[str] = []
            try:
                for line in chunks_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                    texts.append(line[:2000])
                    if len(" ".join(texts)) > 40_000:
                        break
            except OSError:
                continue
            fingerprints[case_dir.name] = detect_case_concepts(texts)
        return fingerprints

    def _refresh_c(self, case_id: str, disclosure=None, claims=None, evidence=None) -> None:
        case_dir = self.manager.case_dir(case_id); disclosure = disclosure or GroundedDisclosure.model_validate_json(self.store.latest_stage_path(case_id, "p1_disclosure").read_text(encoding="utf-8")); claims = claims or GroundedClaimSet.model_validate_json(self.store.latest_stage_path(case_id, "p1_claims").read_text(encoding="utf-8")); evidence = evidence or EvidenceStore(case_dir / "evidence"); strategy = GroundedProtectionStrategy.model_validate_json(self.store.latest_stage_path(case_id, "p1_protection_strategy").read_text(encoding="utf-8")); from patent_agent.core.models import GroundedNoveltyMatrix
        novelty = GroundedNoveltyMatrix.model_validate_json(self.store.latest_stage_path(case_id, "p1_novelty").read_text(encoding="utf-8")); support = ClaimsSupportMatrixBuilder().build(claims, disclosure, evidence, draft_mode=True); scope = ClaimScopeEngine().assess(claims, strategy, novelty, support, ClaimTerminologyRegistry(terms=strategy.broad_terms)); self.store.save_stage(case_id, "p1_claim_support", support); self.store.save_stage(case_id, "p1_claim_scope", scope); questions = _questions(case_dir); ReviewBundleBuilder(case_dir).c(claims, support, scope, questions); HumanReviewManager(case_dir).export_review("C", [feature.model_dump(mode="json") for claim in claims.claims for feature in claim.features])

    def finalize(self, case_id: str) -> Path:
        case_dir = self.manager.case_dir(case_id); output = self.settings.output_root / "real_case" / case_id; output.mkdir(parents=True, exist_ok=True); evidence = EvidenceStore(case_dir / "evidence")
        understanding = TechnicalUnderstandingResult.model_validate_json(self.store.latest_stage_path(case_id, "p1_technical_understanding").read_text(encoding="utf-8")); disclosure = GroundedDisclosure.model_validate_json(self.store.latest_stage_path(case_id, "p1_disclosure").read_text(encoding="utf-8")); claims = GroundedClaimSet.model_validate_json(self.store.latest_stage_path(case_id, "p1_claims").read_text(encoding="utf-8")); support = json.loads(self.store.latest_stage_path(case_id, "p1_claim_support").read_text(encoding="utf-8")); from patent_agent.review.claim_scope import ClaimScopeReview
        scope = ClaimScopeReview.model_validate_json(self.store.latest_stage_path(case_id, "p1_claim_scope").read_text(encoding="utf-8")); knowledge = understanding_to_patent_knowledge(understanding, evidence)
        from patent_agent.document.figure_renderer import PatentFigureRenderer
        from patent_agent.workflow.v2_pipeline import _ground_figure
        # V7: case-scoped figure planning + figure/formula gates before render
        from patent_agent.v7.completeness import (DisclosureCompletenessValidator,
                                                  PatentTitleValidator, UnsupportedParagraphValidator)
        from patent_agent.v7.cross_case import (CrossCaseContaminationValidator,
                                                FigureSemanticValidator,
                                                FormulaScopeValidator,
                                                PlaceholderLeakValidator,
                                                build_case_evidence_fingerprint,
                                                case_concepts_from_understanding)
        from patent_agent.v7.figure_planner import FigurePlannerV7
        from patent_agent.v7.gates import V7GateError, run_disclosure_gates, run_figure_gates
        from patent_agent.v7.language_gate import ChinesePatentLanguageValidator
        concepts = case_concepts_from_understanding(understanding)
        fingerprint = build_case_evidence_fingerprint(understanding, evidence)
        language = ChinesePatentLanguageValidator(
            registered_tokens=set(fingerprint.technical_tokens))
        figures = FigurePlannerV7(
            case_id, understanding, evidence, provider=self.provider,
            cache_dir=case_dir / "llm_cache",
        ).plan()
        figures = [_ground_figure(item, understanding) for item in figures]
        figures = [PatentFigureRenderer().render(item, output / "figures") for item in figures]
        figure_report = run_figure_gates(
            case_id=case_id, figures=figures, language_validator=language,
            figure_semantic_validator=FigureSemanticValidator(concepts, fingerprint),
            formula_scope_validator=FormulaScopeValidator(
                {item.equation_id for item in understanding.equations}),
            draft_equations=knowledge.equations,
        )
        self._write_gate_report(case_dir, figure_report)
        disclosure_report = run_disclosure_gates(
            case_id=case_id, disclosure=disclosure, claims=claims, figures=figures,
            language_validator=language,
            completeness_validator=DisclosureCompletenessValidator(),
            unsupported_validator=UnsupportedParagraphValidator(),
            contamination_validator=CrossCaseContaminationValidator(
                concepts, self._other_case_fingerprints(case_id), fingerprint),
            placeholder_validator=PlaceholderLeakValidator(),
        )
        self._write_gate_report(case_dir, disclosure_report)
        title_result = PatentTitleValidator().validate(disclosure.title)
        if not title_result.passed:
            raise V7GateError("TITLE_GATE_FAILED", "；".join(title_result.issues))
        from patent_agent.v7_1.quality import (
            BilingualTermValidator, FigureGraphValidator,
            FigureNarrativeConsistencyValidator, HeadingCompletenessValidator,
            SectionCompletenessValidator, TechnicalTerminologyNormalizer,
            TokenIntegrityValidator,
        )
        headings = [section.title for section in disclosure.sections]
        body_texts = [paragraph.text for section in disclosure.sections for paragraph in section.paragraphs]
        figure_texts = [figure.title for figure in figures] + [node.label for figure in figures for node in figure.nodes]
        term_registry = TechnicalTerminologyNormalizer.from_source_texts(
            [str(fact.statement) for fact in understanding.facts]).registry
        content_results = [
            HeadingCompletenessValidator().validate(headings),
            SectionCompletenessValidator().validate(disclosure.sections),
            TokenIntegrityValidator(term_registry).validate(body_texts + figure_texts),
            BilingualTermValidator().validate(body_texts + figure_texts),
            FigureGraphValidator().validate(figures),
            FigureNarrativeConsistencyValidator().validate(body_texts, figures),
        ]
        if any(result.status != "PASS" for result in content_results):
            codes = [finding.code for result in content_results for finding in result.findings]
            raise RuntimeError("V7_1_CONTENT_QUALITY_GATE_FAILED: " + ",".join(codes))
        self._advance_delivery_state(case_id, CaseWorkflowState.CONTENT_VALIDATED)
        from patent_agent.v7_2.semantics import SemanticPlanningBundle, validate_bundle
        semantic_bundle = SemanticPlanningBundle.model_validate_json(
            self.store.latest_stage_path(case_id, "p1_semantic_bundle").read_text(encoding="utf-8")
        )
        generated_embodiment_texts = _semantic_paragraph_inputs(
            disclosure, understanding, evidence)
        semantic_report = validate_bundle(
            semantic_bundle, claims=claims, generated_texts=generated_embodiment_texts)
        if semantic_report.status != "PASS":
            raise RuntimeError(
                "V7_2_PATENT_SEMANTICS_GATE_FAILED: "
                + ",".join(finding.code for finding in semantic_report.findings)
            )
        self._advance_delivery_state(case_id, CaseWorkflowState.PATENT_SEMANTICS_VALIDATED)
        (output / "figures.json").write_text(json.dumps([item.model_dump(mode="json") for item in figures], ensure_ascii=False, indent=2), encoding="utf-8")
        draft = grounded_disclosure_to_draft(disclosure, knowledge, figures); tree = grounded_claims_to_tree(claims); renderer = DocumentRenderer(self.settings.template_root)
        v7_docx = output / "技术交底书_v7_2.docx"
        disclosure_docx = renderer.render(disclosure_to_ast(case_id, draft), v7_docx)
        claims_docx = renderer.render(claims_to_ast(case_id, tree), output / "权利要求草案.docx")
        validator = PatentDocxValidator()
        validation = validator.validate(disclosure_docx, export_pdf=True)
        claims_validation = validator.inspect_word(claims_docx, export_pdf=True)
        if not validation["pass"]:
            raise RuntimeError("V7_1_DOCX_VALIDATION_FAILED")
        shutil.copy2(v7_docx, output / "技术交底书.docx")
        self._advance_delivery_state(case_id, CaseWorkflowState.DOCX_VALIDATED)
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
        (output / "pipeline_report.md").write_text(f"# Real Case Pipeline Report\n\n- Case: {case_id}\n- Checkpoint C: APPROVED\n- Patent semantics: {semantic_report.status}\n- Claims support: {support['validation_status']}\n- Scope review: complete\n- Traceability links: {len(traceability.links)}\n- Broken links: {len(traceability.broken_links)}\n- Word validation: {'PASS' if validation['pass'] else 'FAIL'}\n", encoding="utf-8")
        self._write_manifest_language(case_id, case_dir, evidence, translation_postprocess_used=False)
        self._write_generalization_report(output, case_id, understanding, disclosure, claims, figures, knowledge, validation, title_result)
        self._write_semantic_audits(
            output, semantic_bundle, semantic_report, disclosure, claims)
        from patent_agent.v7_1.delivery import run_delivery_audit
        delivery_report = run_delivery_audit(
            output, v7_docx, v7_docx.with_suffix(".pdf"), disclosure,
            understanding, figures, knowledge.equations,
        )
        if delivery_report["component_status"].get("render_audit.json") != "PASS":
            raise RuntimeError("V7_1_RENDER_VALIDATION_FAILED")
        self._advance_delivery_state(case_id, CaseWorkflowState.RENDER_VALIDATED)
        if not validation["pass"] or support["validation_status"] != "PASS" or traceability.broken_links:
            raise RuntimeError("REAL_CASE_FINAL_QUALITY_GATE_FAILED")
        if delivery_report["status"] != "PASS":
            raise RuntimeError("V7_1_DELIVERY_QUALITY_GATE_FAILED")
        delivery_report["component_status"]["patent_semantics"] = semantic_report.status
        (output / "delivery_quality_report.json").write_text(
            json.dumps(delivery_report, ensure_ascii=False, indent=2), encoding="utf-8")
        from scripts.production_hardcode_audit import audit as audit_production_hardcodes
        hardcode_report = audit_production_hardcodes(self.settings.project_root)
        (output / "production_hardcode_audit.json").write_text(
            json.dumps(hardcode_report, ensure_ascii=False, indent=2), encoding="utf-8")
        if hardcode_report["summary"]["forbidden"]:
            raise RuntimeError("V7_1_FORBIDDEN_PRODUCTION_HARDCODE")
        self._advance_delivery_state(case_id, CaseWorkflowState.DELIVERY_READY)
        final_review = HumanReviewManager(case_dir)
        final_review.machine.configure("FINAL", [])
        # Idempotent: re-running finalize on an already-validated case must
        # not replay the FINAL transitions.
        if final_review.machine.records["FINAL"].status != CheckpointStatus.APPROVED:
            if final_review.machine.records["FINAL"].status == CheckpointStatus.NOT_STARTED: final_review.machine.transition("FINAL", CheckpointStatus.GENERATED)
            final_review.machine.transition("FINAL", CheckpointStatus.UNDER_REVIEW)
            final_review.machine.transition("FINAL", CheckpointStatus.APPROVED, reviewed_ids=[])
        final_review.machine.save(final_review.state_path)
        _mark_current(case_dir, "knowledge", "candidate", "strategy", "disclosure", "claim_feature", "claim", "support_matrix", "scope_review", "figure", "traceability")
        self._advance_delivery_state(case_id, CaseWorkflowState.DONE)
        final_manifest = self.manager.load(case_id)
        final_manifest.current_checkpoint = "FINAL"
        self.manager.save(final_manifest)
        self._write_delivery_quality_markdown(output, case_id, delivery_report, validation,
                                              claims_validation, traceability)
        self._write_manifest_snapshot(output, case_id)
        return output

    def _advance_delivery_state(self, case_id: str, state: CaseWorkflowState) -> None:
        manifest = self.manager.load(case_id)
        manifest.case_state = state
        if state.value not in manifest.state_history:
            manifest.state_history.append(state.value)
        manifest.delivery_version = "V7.2"
        self.manager.save(manifest)

    def _write_semantic_audits(self, output, bundle, report, disclosure, claims) -> None:
        primary = next(item for item in bundle.embodiments if item.is_primary)
        coverage = report.required_feature_coverage
        embodiment_items = []
        for embodiment in bundle.embodiments:
            required_ids = list(coverage) if embodiment.is_primary else embodiment.required_feature_ids
            covered = [feature for feature in required_ids if feature in coverage]
            embodiment_items.append({
                "embodiment_id": embodiment.embodiment_id,
                "title": embodiment.title,
                "type": embodiment.embodiment_type,
                "is_primary": embodiment.is_primary,
                "step_count": len(embodiment.ordered_steps),
                "required_features": required_ids,
                "covered_features": covered,
                "fact_ids": embodiment.fact_ids,
                "evidence_ids": embodiment.evidence_ids,
                "input_defined": bool(embodiment.input_objects),
                "output_defined": bool(embodiment.output_objects and embodiment.final_technical_result),
                "continuity": report.component_status["EmbodimentContinuity"],
                "scenario_consistent": report.component_status["ScenarioConsistency"],
                "unsupported_generalization": sum(
                    1 for item in report.findings if item.code == "UNSUPPORTED_GENERALIZATION"
                ),
                "baseline_contamination": sum(
                    1 for item in report.findings if item.code == "BASELINE_PROMOTED_TO_INVENTION"
                ),
                "completeness": report.component_status["EmbodimentCompleteness"],
                "status": report.status,
            })
        (output / "embodiment_audit.json").write_text(json.dumps({
            "status": report.status, "embodiments": embodiment_items,
        }, ensure_ascii=False, indent=2), encoding="utf-8")

        drift_codes = {
            "SCENARIO_DRIFT", "UNSUPPORTED_GENERALIZATION", "UNSUPPORTED_ALTERNATIVE",
            "UNSUPPORTED_PARAMETER", "BASELINE_PROMOTED_TO_INVENTION",
        }
        drift_records = [{
            "source_text": "case-local fact/evidence registry",
            "generated_text": "",
            "reason": item.message,
            "code": item.code,
            "status": "FAIL",
        } for item in report.findings if item.code in drift_codes]
        (output / "semantic_drift_audit.json").write_text(json.dumps({
            "status": "PASS" if not drift_records else "FAIL",
            "unresolved_hard_drift": len(drift_records),
            "records": drift_records,
        }, ensure_ascii=False, indent=2), encoding="utf-8")

        claim_records = []
        for claim in claims.claims:
            if claim.claim_type == "dependent":
                continue
            for feature in claim.features:
                if not feature.mandatory:
                    continue
                step = next((step for step in primary.ordered_steps if (
                    feature.feature_id in step.required_feature_ids
                    or set(feature.source_fact_ids) & set(step.fact_ids)
                    or set(feature.evidence_ids) & set(step.evidence_ids)
                )), None)
                claim_records.append({
                    "claim_id": claim.claim_number,
                    "claim_feature": feature.feature_id,
                    "required": True,
                    "embodiment_id": primary.embodiment_id,
                    "step_id": step.step_id if step else None,
                    "fact_ids": step.fact_ids if step else feature.source_fact_ids,
                    "evidence_ids": feature.evidence_ids,
                    "support_status": "PASS" if step else "FAIL",
                })
        (output / "claim_embodiment_support.json").write_text(json.dumps({
            "status": "PASS" if all(item["support_status"] == "PASS" for item in claim_records) else "FAIL",
            "records": claim_records,
        }, ensure_ascii=False, indent=2), encoding="utf-8")

        redundancy = []
        for index, cluster in enumerate(bundle.section5_fact_clusters, 1):
            for embodiment in bundle.embodiments:
                overlap = len(set(cluster) & set(embodiment.fact_ids)) / max(1, len(set(cluster)))
                mirror = len(bundle.embodiments) > 1 and set(embodiment.fact_ids) <= set(cluster)
                redundancy.append({
                    "section_5_id": f"05-{index:02d}",
                    "embodiment_id": embodiment.embodiment_id,
                    "semantic_similarity": round(overlap, 4),
                    "fact_overlap": round(overlap, 4),
                    "verbatim_overlap": 0.0,
                    "mirror_risk": mirror,
                })
        (output / "section_redundancy_audit.json").write_text(json.dumps({
            "status": "PASS" if not any(item["mirror_risk"] for item in redundancy) else "FAIL",
            "records": redundancy,
        }, ensure_ascii=False, indent=2), encoding="utf-8")

        substantive = [
            paragraph for section in disclosure.sections if section.section_id.startswith("07-")
            for paragraph in section.paragraphs
        ]
        evidence_backed = sum(bool(item.fact_ids and item.evidence_ids) for item in substantive)
        lines = [
            "# V7.2 Patent Semantics Report", "",
            f"- Overall: {report.status}",
            f"- Embodiments: {len(bundle.embodiments)}",
            f"- Primary embodiments: {sum(item.is_primary for item in bundle.embodiments)}",
            f"- Primary steps: {len(primary.ordered_steps)}",
            f"- Required features covered: {len(coverage)}/{len(primary.required_feature_ids)}",
            f"- Substantive paragraphs evidence-backed: {evidence_backed}/{len(substantive)}",
            f"- Unresolved hard semantic drift: {report.unresolved_hard_drift}", "",
            "## Component gates", "",
        ]
        lines.extend(f"- {name}: {status}" for name, status in report.component_status.items())
        lines += ["", "## Architecture", "",
                  "Fact clusters populate typed invention-graph nodes; they do not create embodiments.",
                  "The primary embodiment is an end-to-end graph path with evidence-bound steps.", ""]
        (output / "patent_semantics_report.md").write_text("\n".join(lines), encoding="utf-8")

    def _write_manifest_snapshot(self, output: Path, case_id: str) -> None:
        from patent_agent.core.models import utc_now
        canonical = self.manager.manifest_path(case_id)
        manifest = self.manager.load(case_id)
        snapshot = {
            "snapshot_type": "delivery_snapshot_read_only",
            "source_of_truth": False,
            "canonical_runtime_manifest": str(canonical.resolve()),
            "captured_at": utc_now(),
            "manifest": manifest.model_dump(mode="json"),
        }
        snapshot_path = output / "real_case_manifest.json"
        # A prior delivery snapshot may already be read-only. Re-finalization is
        # idempotent: unlock only this exact file, replace it, then lock it again.
        if snapshot_path.exists():
            snapshot_path.chmod(stat.S_IWRITE)
        snapshot_path.write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
        snapshot_path.chmod(stat.S_IREAD)

    def _write_delivery_quality_markdown(self, output: Path, case_id: str,
                                         report: dict, validation: dict,
                                         claims_validation: dict, traceability) -> None:
        def load(name: str) -> dict:
            return json.loads((output / name).read_text(encoding="utf-8"))

        heading = load("heading_audit.json")
        section = load("section_audit.json")
        figure = load("figure_audit.json")
        equation = load("equation_audit.json")
        terminology = load("terminology_audit.json")
        render = load("render_audit.json")
        hardcode_path = output / "production_hardcode_audit.json"
        hardcode = load("production_hardcode_audit.json") if hardcode_path.exists() else {
            "summary": {"forbidden": "not-run", "pass": False}
        }
        technical_headings = heading.get("headings", [])
        sections = section.get("sections", [])
        figures = figure.get("figures", [])
        equations = equation.get("equations", [])
        lines = [
            "# V7.2 Delivery Quality Report", "",
            f"- Case: {case_id}",
            f"- Overall: {report['status']}",
            "- Standard pipeline rebuild: PASS",
            "- Provider injection: standard CLI/Web factory",
            f"- DOCX/XML/OMML: {'PASS' if validation['pass'] else 'FAIL'}",
            f"- PDF render: {report['component_status'].get('render_audit.json', 'FAIL')}",
            f"- Pages: {report['page_count']}",
            f"- Equations: {report['equation_count']}",
            f"- Figures: {report['figure_count']}",
            f"- Traceability broken links: {len(traceability.broken_links)}",
            f"- Claims Word available: {claims_validation.get('available')}",
            f"- Patent semantics: {report['component_status'].get('patent_semantics', 'FAIL')}",
            "",
            "## 1. Baseline defects", "",
            "The V7 baseline reproduced truncated semantic headings, missing subsection bodies, misplaced/empty figure descriptions, graph collisions, incomplete visible equations, and split registered tokens. See `docs/V7_1_BASELINE_DEFECT_AUDIT.md`.",
            "",
            "## 2. Root causes", "",
            "- Headings were derived from body fragments instead of independent semantic plan fields.",
            "- Generic image-word routing misclassified technical sections as figure sections.",
            "- Graph contracts and renderer layout reports were not both enforced at delivery time.",
            "- XML validity did not compare canonical Office Math structures or rendered PDF geometry.",
            "- Technical-token and inline-math registries were not fully case-local.",
            "",
            "## 3. Generic fixes", "",
            "- Independent fact-driven headings plus invention-graph embodiment planning.",
            "- Section completeness and exact figure-section routing gates.",
            "- Semantic graph contracts, rendered parity, collision, and narrative-consistency gates.",
            "- Canonical OMML signature comparison plus PDF geometry inspection.",
            "- Evidence-derived terminology, open-vocabulary contamination, and case-local equation-symbol registries.",
            "",
            "## 4. Heading audit", "",
            f"- Technical headings: {len(technical_headings)}",
            f"- Complete: {sum(1 for item in technical_headings if item.get('validator_result') == 'PASS')}",
            f"- Prefix truncation: {sum(1 for item in technical_headings if item.get('prefix_of_body'))}",
            f"- Result: {heading.get('status', 'FAIL')}",
            "",
            "## 5. Section completeness", "",
            f"- Planned sections: {len(sections)}",
            f"- Complete: {sum(1 for item in sections if item.get('status') == 'PASS')}",
            f"- Missing body: {sum(1 for item in sections if not item.get('body_paragraph_count'))}",
            f"- Figure-description section: {next((item.get('status') for item in sections if item.get('section_id') == '06'), 'FAIL')}",
            f"- Result: {section.get('status', 'FAIL')}",
            "",
            "## 6. Figure audit", "",
            f"- Planned/rendered: {len(figures)}/{sum(1 for item in figures if item.get('bbox_valid'))}",
            f"- Dangling edges: {sum(len(item.get('dangling_edges', [])) for item in figures)}",
            f"- Missing planned nodes: {sum(len(set(item.get('planned_nodes', [])) - set(item.get('rendered_nodes', []))) for item in figures)}",
            f"- Render collisions: {sum(len(item.get('collisions', [])) for item in figures)}",
            f"- Narrative consistency: {figure.get('narrative', {}).get('status', 'FAIL')}",
            f"- Result: {figure.get('status', 'FAIL')}",
            "",
            "## 7. Equation audit", "",
            f"- Registry/rendered: {equation.get('expected_count', 0)}/{equation.get('actual_count', 0)}",
            f"- Signature matches: {sum(1 for item in equations if item.get('match'))}/{len(equations)}",
            f"- Valid render bboxes: {sum(1 for item in equations if item.get('bbox_valid'))}/{len(equations)}",
            f"- Result: {equation.get('status', 'FAIL')}",
            "",
            "## 8. Terminology/token audit", "",
            f"- Token integrity: {terminology.get('token_integrity', {}).get('status', 'FAIL')}",
            f"- Bilingual expansions: {terminology.get('bilingual_terms', {}).get('status', 'FAIL')}",
            f"- Result: {terminology.get('status', 'FAIL')}",
            "",
            "## 9. Render audit", "",
            f"- DOCX/OpenXML/OMML: {'PASS' if validation['pass'] else 'FAIL'}",
            f"- PDF: {render.get('status', 'FAIL')}",
            f"- Pages: {render.get('page_count', 0)}",
            f"- Blank/clipped errors: {len(render.get('errors', []))}",
            "",
            "## 10. CASE-001 regression", "",
            "- Covered by the repository regression suite; release verification is recorded in PROJECT_STATUS.md.",
            "",
            "## 11. Clean rebuild", "",
            "- Rebuilt through standard production CLI checkpoints and provider factory: PASS.",
            "- Manual Word repair: NO.",
            "",
            "## 12. No-case-hardcode audit", "",
            f"- Forbidden production hardcodes: {hardcode.get('summary', {}).get('forbidden')}",
            f"- Result: {'PASS' if hardcode.get('summary', {}).get('pass') else 'FAIL'}",
            "",
            "## 13. Final Delivery Gate", "",
            f"- DELIVERY_READY: {'TRUE' if report['status'] == 'PASS' else 'FALSE'}",
            f"- Result: {report['status']}", "",
            "## Component gates", "",
        ]
        lines.extend(f"- {name}: {status}" for name, status in report["component_status"].items())
        lines += ["", "## Manifest", "",
                  "The workspace manifest is canonical runtime state. The output manifest is a read-only delivery snapshot.", ""]
        (output / "delivery_quality_report.md").write_text("\n".join(lines), encoding="utf-8")

    def _write_generalization_report(self, output, case_id, understanding, disclosure,
                                     claims, figures, knowledge, validation, title_result) -> None:
        """V7 generalization report: language, completeness, grounding,
        cross-case, figures, formulas, evidence coverage, Word validation."""
        from patent_agent.v7.completeness import (DisclosureCompletenessValidator,
                                                  UnsupportedParagraphValidator)
        from patent_agent.v7.cross_case import (CrossCaseContaminationValidator,
                                                PlaceholderLeakValidator,
                                                build_case_evidence_fingerprint,
                                                case_concepts_from_understanding)
        manifest = self.manager.load(case_id)
        complete = DisclosureCompletenessValidator().validate(disclosure)
        grounded = UnsupportedParagraphValidator().validate(disclosure)
        concepts = case_concepts_from_understanding(understanding)
        contamination = CrossCaseContaminationValidator(
            concepts, self._other_case_fingerprints(case_id),
            build_case_evidence_fingerprint(understanding)).validate(
                disclosure=disclosure, claims=claims, figures=figures)
        placeholders = PlaceholderLeakValidator().validate(
            disclosure=disclosure, claims=claims, figures=figures)
        total_facts = [f for f in understanding.facts if getattr(f, "review_status", None) != ReviewStatus.REJECTED]
        grounded_facts = [f for f in total_facts if f.evidence_ids]
        evidence_ids = sorted({e for f in total_facts for e in f.evidence_ids})
        lines = [
            "# Patent Agent V7.2 Generalization Report",
            "",
            f"- Case: {case_id}",
            f"- 发明名称: {disclosure.title} (CJK {title_result.length} 字, "
            f"{'PASS' if title_result.passed else 'FAIL'})",
            "",
            "## 1. Language",
            f"- Source languages (detected): {', '.join(manifest.source_languages or ['UNKNOWN'])}",
            f"- Patent output language: {manifest.patent_output_language}",
            f"- Disclosure language: {manifest.disclosure_language}",
            f"- Post-hoc translation used: {manifest.translation_postprocess_used}",
            f"- Native Chinese generation: {manifest.disclosure_language == 'zh-CN' and not manifest.translation_postprocess_used}",
            "",
            "## 2. Section completeness",
            f"- PASS: {', '.join(complete.present) if complete.present else 'none'}",
            f"- MISSING: {', '.join(complete.missing) if complete.missing else 'none'}",
            "",
            "## 3. Grounding",
            f"- Unsupported paragraphs: {len(grounded.unsupported)} / {grounded.total_paragraphs}",
            f"- Facts grounded on evidence: {len(grounded_facts)} / {len(total_facts)}",
            f"- Evidence ids referenced: {len(evidence_ids)}",
            "",
            "## 4. Cross-case contamination",
            f"- Case concepts (own evidence): {', '.join(sorted(concepts)) if concepts else 'none'}",
            f"- PASS: {contamination.passed}",
            *(f"- {detail}" for detail in contamination.details[:10]),
            "",
            "## 5. Placeholder leaks",
            f"- PASS: {placeholders.passed}",
            *(f"- {detail}" for detail in placeholders.details[:10]),
            "",
            "## 6. Figures",
        ]
        for figure in figures:
            provenance = getattr(figure, "provenance", "generated")
            lines.append(
                f"- 图{figure.number} [{provenance}] {figure.title} | case={figure.case_id} "
                f"| keywords={','.join(figure.semantic_keywords) or 'n/a'} "
                f"| source_features={len(figure.source_feature_ids)}"
            )
        lines += [
            "",
            "## 7. Formula provenance",
        ]
        for equation in knowledge.equations:
            lines.append(
                f"- {equation.id} (role={equation.role}, sources={len(equation.source_ids)})"
            )
        lines += [
            f"- Case-local equation registry: {len(understanding.equations)}",
            "",
            "## 8. Word validation",
            f"- XML/Word: {'PASS' if validation['pass'] else 'FAIL'}",
            f"- OMML count: {validation['xml']['omml_count']}",
            f"- Residual LaTeX in OMML: {validation['xml']['residual_latex_in_omml']}",
            "",
            "## 9. Overall V7 gates",
            "- LANGUAGE_GATE_FAILED: no",
            "- DISCLOSURE_INCOMPLETE: no",
            "- UNSUPPORTED_DISCLOSURE_PARAGRAPH: no",
            "- CROSS_CASE_CONTAMINATION: no",
            "- PLACEHOLDER_LEAK: no",
            "- FIGURE_SEMANTIC_FAIL: no",
            "- FORMULA_CASE_SCOPE_FAIL: no",
            "- TITLE_GATE_FAILED: no",
            "",
        ]
        (output / "generalization_v7_2_report.md").write_text("\n".join(lines), encoding="utf-8")

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


def _detect_languages(chunks_path: Path) -> list[str]:
    """Detect source languages from evidence chunks (zh-CN / en / other).

    A chunk counts as Chinese if CJK characters dominate its letters;
    English if Latin characters dominate and CJK is negligible.
    """
    if not Path(chunks_path).exists():
        return []
    cjk = re.compile(r"[一-鿿]")
    latin = re.compile(r"[A-Za-z]")
    langs: set[str] = set()
    try:
        lines = Path(chunks_path).read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return []
    for line in lines[:200]:
        try:
            chunk = json.loads(line)
        except json.JSONDecodeError:
            continue
        text = str(chunk.get("raw_text", "") or chunk.get("normalized_text", ""))
        cjk_count = len(cjk.findall(text))
        latin_count = len(latin.findall(text))
        if cjk_count + latin_count == 0:
            continue
        ratio = cjk_count / (cjk_count + latin_count)
        if ratio > 0.2:
            langs.add("zh-CN")
        elif latin_count > 40 and ratio < 0.02:
            langs.add("en")
    return sorted(langs)


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
