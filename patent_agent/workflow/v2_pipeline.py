from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from patent_agent.agents import (
    DeterministicGroundedAnalyzer,
    DeterministicGroundedInventionMiner,
    FigurePlanner,
    GroundedClaimsWriter,
    GroundedDisclosureWriter,
    GroundedInventionMiningAgent,
    GroundedNoveltyAnalysisAgent,
    GroundedProtectionStrategyAgent,
    GroundedSemanticReviewAgent,
    GroundedTechnicalUnderstandingAgent,
    grounded_claims_to_tree,
    grounded_disclosure_to_draft,
    understanding_to_patent_knowledge,
)
from patent_agent.core.config import Settings
from patent_agent.core.models import ClaimTerminologyRegistry
from patent_agent.core.state import CaseStore
from patent_agent.document import DocumentRenderer, PatentDocxValidator
from patent_agent.document.ast_factory import claims_to_ast, disclosure_to_ast
from patent_agent.document.figure_renderer import PatentFigureRenderer
from patent_agent.evidence import EvidenceStore
from patent_agent.ingestion import SourceManager
from patent_agent.llm import LLMProvider, StructuredLLMService
from patent_agent.reporting import write_dry_run_reports, write_grounding_reports
from patent_agent.review import ClaimsSupportMatrixBuilder, build_traceability, evaluate_quality_gates, generate_inventor_questions, review_grounding
from patent_agent.search import ManualImportProvider

from .checkpoints import require_checkpoint
from .pipeline import PipelineLog


class PatentPipelineV2:
    def __init__(self, settings: Settings, provider: LLMProvider | None = None):
        self.settings = settings
        self.provider = provider
        self.store = CaseStore(settings.workspace_root)
        self.sources = SourceManager(self.store)
        self.renderer = DocumentRenderer(settings.template_root)
        self.validator = PatentDocxValidator()

    def run(self, case_id: str, materials: list[Path], prior_art: Path, output_dir: Path, *, auto_approve_demo: bool = False, use_word_com: bool = True, use_cache: bool = True) -> dict:
        if self.provider is None:
            raise RuntimeError("LLM_DISABLED: V2 full pipeline requires an approved provider or MockLLMProvider")
        if not (self.store.case_dir(case_id) / "case.json").exists():
            self.store.create(case_id, "一种基于多源传感信息的电机状态监测与自适应控制方法")
        output_dir.mkdir(parents=True, exist_ok=True)
        log = PipelineLog(self.store.case_dir(case_id) / "logs" / "pipeline_v2.jsonl")
        self.store.migrate_to_v2(case_id)
        effective_settings = replace(self.settings, llm_cache_enabled=use_cache)
        llm = StructuredLLMService(self.provider, effective_settings, self.store.case_dir(case_id))

        with log.stage("v2_stage_1_ingestion", {"materials": [str(path) for path in materials]}) as event:
            records, source_chunks, images = self.sources.ingest(case_id, materials)
            evidence_store = EvidenceStore(self.store.case_dir(case_id) / "evidence")
            event["output"] = {"files": len(records), "source_chunks": len(source_chunks), "evidence_chunks": len(evidence_store.all()), "images": len(images)}
        with log.stage("v2_stage_2_grounded_understanding", {"prompt_version": GroundedTechnicalUnderstandingAgent.prompt_version}) as event:
            understanding = GroundedTechnicalUnderstandingAgent().run(evidence_store, llm)
            self.store.save_stage(case_id, "v2_grounded_understanding", understanding)
            event["output"] = {"facts": len(understanding.facts), "equations": len(understanding.equations), "uncertainties": len(understanding.uncertainties)}
        with log.stage("v2_stage_3_grounded_invention_mining", {"prompt_version": GroundedInventionMiningAgent.prompt_version}) as event:
            candidates = GroundedInventionMiningAgent().run(understanding, evidence_store, llm)
            self.store.save_stage(case_id, "v2_invention_candidates", [item.model_dump() for item in candidates])
            event["output"] = {"candidates": len(candidates), "selected": candidates[0].candidate_id}
        with log.stage("checkpoint_A_v2", {"candidate": candidates[0].candidate_id}) as event:
            require_checkpoint(self.store, case_id, "A", auto_approve_demo)
            event["output"] = self.store.load(case_id).checkpoints["A"]
        with log.stage("v2_stage_4_manual_prior_art", {"path": str(prior_art)}) as event:
            references = ManualImportProvider(prior_art).search("电机 多源 传感 状态 控制")
            prior_store = EvidenceStore(self.store.case_dir(case_id) / "search" / "evidence")
            prior_store.build_prior_art(references)
            novelty = GroundedNoveltyAnalysisAgent().run(candidates[0], prior_store)
            self.store.save_stage(case_id, "v2_novelty_matrix", novelty)
            event["output"] = {"references": len(references), "prior_art_evidence": len(prior_store.all()), "assessments": len(novelty.assessments)}
        with log.stage("v2_stage_5_protection_strategy", {"prompt_version": GroundedProtectionStrategyAgent.prompt_version}) as event:
            strategy = GroundedProtectionStrategyAgent().run(candidates[0], understanding, evidence_store, llm, novelty.model_dump())
            self.store.save_stage(case_id, "v2_protection_strategy", strategy)
            event["output"] = {"independent_core": len(strategy.independent_claim_core), "dependent_features": len(strategy.dependent_claim_features), "support_gaps": len(strategy.support_gaps)}
        with log.stage("checkpoint_B_v2", {}) as event:
            require_checkpoint(self.store, case_id, "B", auto_approve_demo); event["output"] = self.store.load(case_id).checkpoints["B"]
        with log.stage("v2_stage_6_grounded_disclosure", {"prompt_version": GroundedDisclosureWriter.prompt_version}) as event:
            disclosure = GroundedDisclosureWriter().run(self.store.load(case_id).title, understanding, candidates[0], strategy, evidence_store, llm, self.store.load_inventor_assertions(case_id))
            self.store.save_stage(case_id, "v2_grounded_disclosure", disclosure)
            _persist_disclosure_sections(self.store.case_dir(case_id), disclosure)
            event["output"] = {"sections": len(disclosure.sections), "paragraphs": sum(len(section.paragraphs) for section in disclosure.sections)}
        with log.stage("v2_stage_7_claim_features", {"prompt_version": GroundedClaimsWriter.prompt_version}) as event:
            claims = GroundedClaimsWriter().run(disclosure.title, strategy, understanding, disclosure, evidence_store, llm)
            self.store.save_stage(case_id, "v2_grounded_claims", claims)
            event["output"] = {"claims": len(claims.claims), "claim_features": sum(len(claim.features) for claim in claims.claims)}
        with log.stage("checkpoint_C_v2", {}) as event:
            require_checkpoint(self.store, case_id, "C", auto_approve_demo); event["output"] = self.store.load(case_id).checkpoints["C"]
        with log.stage("v2_stage_8_claim_support", {}) as event:
            support_matrix = ClaimsSupportMatrixBuilder().build(claims, disclosure, evidence_store)
            self.store.save_stage(case_id, "v2_claims_support_matrix", support_matrix)
            event["output"] = {"records": len(support_matrix.records), "status": support_matrix.validation_status, "unsupported_independent": len(support_matrix.unsupported_independent_features)}
            if support_matrix.validation_status != "PASS":
                raise RuntimeError("CLAIM_FEATURE_UNSUPPORTED: independent claim support gate failed")
        with log.stage("v2_stage_9_figures_traceability", {}) as event:
            knowledge = understanding_to_patent_knowledge(understanding, evidence_store)
            figures = [_ground_figure(item, understanding) for item in FigurePlanner().run(knowledge)]
            figures = [PatentFigureRenderer().render(item, output_dir / "figures") for item in figures]
            traceability = build_traceability(disclosure, claims, understanding, figures)
            event["output"] = {"figures": len(figures), "traceability_links": len(traceability.links), "broken": len(traceability.broken_links)}
            if traceability.broken_links:
                raise RuntimeError("TRACEABILITY_BROKEN: " + ", ".join(traceability.broken_links))
        with log.stage("v2_stage_10_grounded_review", {}) as event:
            deterministic_findings = review_grounding(understanding, disclosure, claims, evidence_store)
            semantic_findings = GroundedSemanticReviewAgent().run(disclosure, claims, support_matrix, llm)
            findings = deterministic_findings + semantic_findings
            errors = [item.code for item in findings if item.severity == "ERROR"]
            event["warnings"] = [item.message for item in findings if item.severity == "WARNING"]
            event["errors"] = [item.message for item in findings if item.severity == "ERROR"]
            event["output"] = {"deterministic_findings": len(deterministic_findings), "semantic_findings": len(semantic_findings), "errors": len(errors)}
            if errors: raise RuntimeError("Grounded review failed: " + ", ".join(errors))
        with log.stage("v2_stage_11_document_rendering", {}) as event:
            draft = grounded_disclosure_to_draft(disclosure, knowledge, figures)
            claim_tree = grounded_claims_to_tree(claims)
            disclosure_ast = disclosure_to_ast(case_id, draft); claims_ast = claims_to_ast(case_id, claim_tree)
            disclosure_docx = self.renderer.render(disclosure_ast, output_dir / "技术交底书_v2_demo.docx")
            claims_docx = self.renderer.render(claims_ast, output_dir / "权利要求草案_v2_demo.docx")
            event["output"] = {"disclosure": str(disclosure_docx), "claims": str(claims_docx)}
        with log.stage("v2_stage_12_validation", {}) as event:
            disclosure_validation = self.validator.validate(disclosure_docx, export_pdf=use_word_com) if use_word_com else {"xml": self.validator.inspect_xml(disclosure_docx), "word": {"available": False}, "pass": self.validator.inspect_xml(disclosure_docx)["xml_pass"]}
            claims_word = self.validator.inspect_word(claims_docx, export_pdf=use_word_com) if use_word_com else {"available": False}
            document_pass = disclosure_validation["pass"] and (not use_word_com or "error" not in claims_word)
            gates = evaluate_quality_gates(evidence_errors=[], technical_errors=[], candidate_errors=[], support_matrix=support_matrix, traceability=traceability, document_pass=document_pass)
            event["output"] = {"document_pass": document_pass, "omml": disclosure_validation["xml"]["omml_count"], "quality_gates": {item.gate: item.status for item in gates}}
            if not document_pass or any(item.status == "FAIL" for item in gates): raise RuntimeError("V2 quality gate failed")
        questions = generate_inventor_questions(understanding, strategy.support_gaps)
        write_grounding_reports(output_dir, understanding=understanding, candidates=candidates, strategy=strategy, disclosure=disclosure, claims=claims, support_matrix=support_matrix, traceability=traceability, questions=questions, findings=findings, gates=gates, evidence_store=evidence_store)
        (output_dir / "patent_knowledge.json").write_text(knowledge.model_dump_json(indent=2), encoding="utf-8")
        (output_dir / "claim_tree.json").write_text(claim_tree.model_dump_json(indent=2), encoding="utf-8")
        (output_dir / "patent_ast.json").write_text(json.dumps({"disclosure": disclosure_ast.model_dump(), "claims": claims_ast.model_dump()}, ensure_ascii=False, indent=2), encoding="utf-8")
        (output_dir / "novelty_analysis.json").write_text(novelty.model_dump_json(indent=2), encoding="utf-8")
        (output_dir / "claim_terminology_registry.json").write_text(ClaimTerminologyRegistry(terms=strategy.broad_terms).model_dump_json(indent=2), encoding="utf-8")
        _write_validation_report(output_dir / "validation_report.md", understanding, support_matrix, traceability, disclosure_validation, claims_word, findings, gates, evidence_store)
        _write_pipeline_report(output_dir / "pipeline_report.md", log.events)
        case = self.store.load(case_id); case.status = "completed"; case.current_stage = "v2_final"; self.store.save_case(case)
        return {"case_id": case_id, "understanding": understanding, "candidates": candidates, "strategy": strategy, "disclosure": disclosure, "claims": claims, "support_matrix": support_matrix, "traceability": traceability, "figures": figures, "validation": disclosure_validation, "claims_word": claims_word, "gates": gates, "output_dir": str(output_dir)}

    def dry_run_real(self, case_id: str, materials: list[Path], output_dir: Path, *, use_llm: bool = False, use_cache: bool = True) -> dict:
        if not materials:
            raise ValueError("Real-case dry-run requires an explicitly specified materials path")
        if not (self.store.case_dir(case_id) / "case.json").exists(): self.store.create(case_id, "[待发明人确认]")
        records, source_chunks, _ = self.sources.ingest(case_id, materials)
        evidence_store = EvidenceStore(self.store.case_dir(case_id) / "evidence")
        if use_llm:
            if self.provider is None: raise RuntimeError("LLM_DISABLED: configure an approved provider before --llm")
            effective_settings = replace(self.settings, llm_cache_enabled=use_cache)
            llm = StructuredLLMService(self.provider, effective_settings, self.store.case_dir(case_id))
            understanding = GroundedTechnicalUnderstandingAgent().run(evidence_store, llm)
            candidates = GroundedInventionMiningAgent().run(understanding, evidence_store, llm)
        else:
            understanding = DeterministicGroundedAnalyzer().run(source_chunks, evidence_store)
            candidates = DeterministicGroundedInventionMiner().run(understanding)
        questions = generate_inventor_questions(understanding)
        self.store.save_stage(case_id, "v2_dry_run_understanding", understanding)
        self.store.save_stage(case_id, "v2_dry_run_candidates", [item.model_dump() for item in candidates])
        case = self.store.load(case_id); case.current_stage = "checkpoint_A_preview"; case.status = "awaiting_checkpoint_A"; self.store.save_case(case)
        write_dry_run_reports(output_dir, case=case, understanding=understanding, candidates=candidates, questions=questions, evidence_store=evidence_store)
        return {"case_id": case_id, "files": len(records), "evidence_chunks": len(evidence_store.all()), "understanding": understanding, "candidates": candidates, "questions": questions, "stop_point": "Checkpoint A preview", "output_dir": str(output_dir)}


def _ground_figure(figure, understanding):
    if figure.type == "flowchart":
        sources = [item.text for item in understanding.steps]
    else:
        sources = [item.description for item in understanding.components]
    nodes = []
    for index, node in enumerate(figure.nodes):
        statement = sources[min(index, len(sources) - 1)] if sources else None
        evidence_ids = statement.evidence_ids if statement else []
        fact_ids = [fact.fact_id for fact in understanding.facts if set(fact.evidence_ids) & set(evidence_ids)]
        nodes.append(node.model_copy(update={"evidence_ids": evidence_ids, "fact_ids": fact_ids}))
    edges = []
    for edge in figure.edges:
        related = [node for node in nodes if node.id in {edge.source, edge.target}]
        edges.append(edge.model_copy(update={"evidence_ids": sorted({identifier for node in related for identifier in node.evidence_ids}), "fact_ids": sorted({identifier for node in related for identifier in node.fact_ids})}))
    return figure.model_copy(update={"nodes": nodes, "edges": edges})


def _write_validation_report(path: Path, understanding, matrix, traceability, validation, claims_word, findings, gates, evidence_store):
    source_facts = [fact for fact in understanding.facts if fact.status.value == "SOURCE_FACT"]
    missing = [fact.fact_id for fact in source_facts if not fact.evidence_ids]
    invalid = sorted({identifier for fact in understanding.facts for identifier in fact.evidence_ids if not evidence_store.contains(identifier)})
    lines = ["# V2 Validation Report", "", f"Overall: **{'PASS' if validation['pass'] and matrix.validation_status == 'PASS' and not traceability.broken_links else 'FAIL'}**", "", "## Grounding", "", f"- SOURCE_FACT_WITHOUT_EVIDENCE: {len(missing)}", f"- INVALID_EVIDENCE_REFERENCE: {len(invalid)}", f"- UNSUPPORTED_INDEPENDENT_CLAIM_FEATURE: {len(matrix.unsupported_independent_features)}", f"- BROKEN_TRACEABILITY_LINK: {len(traceability.broken_links)}", "", "## DOCX XML", ""]
    lines += [f"- {key}: {value}" for key, value in validation["xml"].items()]
    lines += ["", "## Word COM - Disclosure", ""] + [f"- {key}: {value}" for key, value in validation["word"].items()]
    lines += ["", "## Word COM - Claims", ""] + [f"- {key}: {value}" for key, value in claims_word.items()]
    lines += ["", "## Quality Gates", ""] + [f"- {item.gate}: {item.status}" for item in gates]
    lines += ["", "## Grounded Review", ""] + ([f"- {item.severity} `{item.code}`: {item.message}" for item in findings] or ["- none"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_pipeline_report(path: Path, events: list[dict]):
    lines = ["# V2 Pipeline Report", "", "Synthetic demo: YES", "", "| Stage | Status | Duration (s) | Output |", "|---|---:|---:|---|"]
    for item in events: lines.append(f"| {item['stage']} | {item['status']} | {item['duration_seconds']} | {json.dumps(item.get('output', {}), ensure_ascii=False)} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _persist_disclosure_sections(case_dir: Path, disclosure) -> Path:
    root = case_dir / "drafts" / "disclosure"
    root.mkdir(parents=True, exist_ok=True)
    version = 1 + max((int(path.name[1:]) for path in root.glob("v[0-9][0-9][0-9]") if path.name[1:].isdigit()), default=0)
    target = root / f"v{version:03d}"; target.mkdir(parents=True, exist_ok=True)
    for section in disclosure.sections:
        safe_name = section.title.split(".", 1)[0].zfill(2)
        (target / f"{safe_name}_{section.section_id}.json").write_text(section.model_dump_json(indent=2), encoding="utf-8")
    (target / "disclosure.json").write_text(disclosure.model_dump_json(indent=2), encoding="utf-8")
    return target
