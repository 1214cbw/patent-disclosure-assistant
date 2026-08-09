from __future__ import annotations

import json
import time
from contextlib import contextmanager
from pathlib import Path

from patent_agent.agents import ClaimsWriter, DisclosureWriter, FigurePlanner, InventionMiningAgent, NoveltyAnalysisAgent, ProtectionStrategyAgent, TechnicalUnderstandingAgent
from patent_agent.core.config import Settings
from patent_agent.core.models import ClaimTree, DisclosureDraft, FigureSpec, PatentKnowledge, ReviewFinding, SourceChunk, utc_now
from patent_agent.core.state import CaseStore
from patent_agent.document import DocumentRenderer, PatentDocxValidator
from patent_agent.document.ast_factory import claims_to_ast, disclosure_to_ast
from patent_agent.document.figure_renderer import PatentFigureRenderer
from patent_agent.ingestion import SourceManager
from patent_agent.review import hallucination_guard, review_claim_support, review_symbols, review_terminology
from patent_agent.search import ManualImportProvider
from .checkpoints import require_checkpoint


class PipelineLog:
    def __init__(self, path: Path):
        self.path = path; self.path.parent.mkdir(parents=True, exist_ok=True); self.events = []

    @contextmanager
    def stage(self, name: str, inputs: dict):
        started = time.perf_counter(); event = {"stage": name, "start": utc_now(), "input": inputs, "warnings": [], "errors": [], "status": "START"}
        try:
            yield event
            event["status"] = "PASS"
        except Exception as exc:
            event["status"] = "FAIL"; event["errors"].append(f"{type(exc).__name__}: {exc}"); raise
        finally:
            event["duration_seconds"] = round(time.perf_counter() - started, 4); self.events.append(event)
            self.path.write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in self.events) + "\n", encoding="utf-8")


class PatentPipeline:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.store = CaseStore(settings.workspace_root)
        self.sources = SourceManager(self.store)
        self.renderer = DocumentRenderer(settings.template_root)
        self.validator = PatentDocxValidator()

    def run(self, case_id: str, materials: list[Path], prior_art: Path, output_dir: Path, auto_approve_demo: bool = False, use_word_com: bool = True) -> dict:
        if not (self.store.case_dir(case_id) / "case.json").exists(): self.store.create(case_id, "待规划技术方案")
        log = PipelineLog(self.store.case_dir(case_id) / "logs" / "pipeline.jsonl")
        output_dir.mkdir(parents=True, exist_ok=True)
        with log.stage("stage_0_initialization", {"case_id": case_id}) as event:
            event["output"] = {"case_dir": str(self.store.case_dir(case_id))}
        with log.stage("stage_1_ingestion", {"materials": [str(p) for p in materials]}) as event:
            records, chunks, images = self.sources.ingest(case_id, materials); event["output"] = {"files": len(records), "chunks": len(chunks), "images": len(images)}
            self.store.save_stage(case_id, "stage_1_ingestion", {"files": [r.model_dump() for r in records], "chunks": [c.model_dump() for c in chunks], "images": images})
        with log.stage("stage_2_technical_understanding", {"chunks": len(chunks)}) as event:
            knowledge = TechnicalUnderstandingAgent().run(chunks); event["output"] = {"components": len(knowledge.components), "steps": len(knowledge.steps), "equations": len(knowledge.equations)}
            self.store.save_stage(case_id, "stage_2_technical_understanding", knowledge)
            case = self.store.load(case_id); case.technical_field = knowledge.technical_field; self.store.save_case(case)
        with log.stage("stage_3_invention_mining", {"evidence": len(knowledge.evidence)}) as event:
            candidates = InventionMiningAgent().run(knowledge); event["output"] = {"candidates": len(candidates)}
            self.store.save_stage(case_id, "stage_3_invention_mining", [item.model_dump() for item in candidates])
        with log.stage("checkpoint_A", {"candidates": len(candidates)}) as event:
            require_checkpoint(self.store, case_id, "A", auto_approve_demo); event["output"] = self.store.load(case_id).checkpoints["A"]
        with log.stage("stage_4_prior_art", {"provider": "manual_import"}) as event:
            references = ManualImportProvider(prior_art).search(
                f"{knowledge.technical_field} {knowledge.technical_problem}")
            event["output"] = {"references": len(references)}
            self.store.save_stage(case_id, "stage_4_prior_art", [item.model_dump() for item in references])
            (self.store.case_dir(case_id) / "search" / "manual_import.json").write_text(json.dumps([item.model_dump() for item in references], ensure_ascii=False, indent=2), encoding="utf-8")
        with log.stage("stage_5_novelty", {"candidate": candidates[0].id}) as event:
            novelty = NoveltyAnalysisAgent().run(candidates[0], references); event["output"] = {"matrix_cells": len(novelty.matrix)}
            self.store.save_stage(case_id, "stage_5_novelty", novelty)
        with log.stage("stage_6_protection_strategy", {}) as event:
            strategy = ProtectionStrategyAgent().run(candidates[0], knowledge); event["output"] = {"mandatory": len(strategy.mandatory_features), "optional": len(strategy.optional_features)}
            self.store.save_stage(case_id, "stage_6_protection_strategy", strategy)
        with log.stage("checkpoint_B", {"mandatory_features": len(strategy.mandatory_features)}) as event:
            require_checkpoint(self.store, case_id, "B", auto_approve_demo); event["output"] = self.store.load(case_id).checkpoints["B"]
        with log.stage("stage_7_disclosure", {}) as event:
            figure_specs = FigurePlanner().run(knowledge)
            draft = DisclosureWriter().run(self.store.load(case_id).title, knowledge, strategy, figure_specs); event["output"] = {"sections": len(draft.sections), "planned_figures": len(figure_specs)}
            self.store.save_stage(case_id, "stage_7_disclosure", draft)
        with log.stage("stage_8_claims", {}) as event:
            claims = ClaimsWriter().run(draft.title, knowledge, strategy); event["output"] = {"claims": len(claims.claims)}
            self.store.save_stage(case_id, "stage_8_claims", claims)
        with log.stage("checkpoint_C", {"claims": len(claims.claims)}) as event:
            require_checkpoint(self.store, case_id, "C", auto_approve_demo); event["output"] = self.store.load(case_id).checkpoints["C"]
        with log.stage("stage_9_figures", {"planned_figures": len(figure_specs)}) as event:
            figures = [PatentFigureRenderer().render(item, output_dir / "figures") for item in figure_specs]
            draft = draft.model_copy(update={"figures": figures})
            event["output"] = {"figures": len(figures)}
            self.store.save_stage(case_id, "stage_9_figures", [item.model_dump() for item in figures])
            self.store.save_stage(case_id, "stage_7_disclosure", draft)
        with log.stage("stage_10_consistency_review", {}) as event:
            findings = review_claim_support(claims, knowledge.evidence) + review_terminology(draft) + review_symbols(knowledge) + hallucination_guard(draft, knowledge)
            event["warnings"] = [item.message for item in findings if item.severity == "WARNING"]
            event["errors"] = [item.message for item in findings if item.severity == "ERROR"]
            event["output"] = {"findings": len(findings)}
            if event["errors"]: raise RuntimeError("Consistency review contains ERROR findings")
            self.store.save_stage(case_id, "stage_10_consistency_review", [item.model_dump() for item in findings])
        with log.stage("stage_11_docx_rendering", {}) as event:
            disclosure_ast = disclosure_to_ast(case_id, draft); claims_ast = claims_to_ast(case_id, claims)
            disclosure_path = self.renderer.render(disclosure_ast, output_dir / "技术交底书_demo.docx")
            claims_path = self.renderer.render(claims_ast, output_dir / "权利要求草案_demo.docx")
            event["output"] = {"disclosure": str(disclosure_path), "claims": str(claims_path)}
        with log.stage("stage_12_word_validation", {}) as event:
            disclosure_validation = self.validator.validate(disclosure_path, export_pdf=use_word_com) if use_word_com else {"xml": self.validator.inspect_xml(disclosure_path), "word": {"available": False}, "pass": self.validator.inspect_xml(disclosure_path)["xml_pass"]}
            claims_xml = self.validator.inspect_xml(claims_path)
            event["output"] = {"disclosure_pass": disclosure_validation["pass"], "claims_omml": claims_xml["omml_count"]}
            if not disclosure_validation["pass"]: raise RuntimeError("DOCX validation failed")
        self._write_outputs(output_dir, knowledge, candidates, novelty, strategy, claims, figures, disclosure_ast, claims_ast, findings, disclosure_validation, log.events)
        case = self.store.load(case_id); case.status = "completed"; case.current_stage = "final"; self.store.save_case(case)
        return {"case_id": case_id, "output_dir": str(output_dir), "knowledge": knowledge, "candidates": candidates, "claims": claims, "figures": figures, "validation": disclosure_validation, "pipeline_events": log.events}

    @staticmethod
    def _write_outputs(output_dir, knowledge, candidates, novelty, strategy, claims, figures, disclosure_ast, claims_ast, findings, validation, events):
        payloads = {"patent_knowledge.json": knowledge.model_dump(), "invention_candidates.json": [item.model_dump() for item in candidates], "novelty_analysis.json": novelty.model_dump(), "protection_strategy.json": strategy.model_dump(), "claim_tree.json": claims.model_dump(), "figure_manifest.json": [item.model_dump() for item in figures], "patent_ast.json": {"disclosure": disclosure_ast.model_dump(), "claims": claims_ast.model_dump()}}
        for name, payload in payloads.items(): (output_dir / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        lines = ["# Validation Report", "", f"Overall: {'PASS' if validation['pass'] else 'FAIL'}", "", "## DOCX XML", ""] + [f"- {key}: {value}" for key, value in validation["xml"].items()] + ["", "## Microsoft Word COM", ""] + [f"- {key}: {value}" for key, value in validation["word"].items()] + ["", "## Review Findings", ""] + [f"- {item.severity} `{item.code}`: {item.message}" for item in findings]
        (output_dir / "validation_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        report = ["# Pipeline Report", "", "Synthetic demo: YES", "", "| Stage | Status | Duration (s) | Output |", "|---|---:|---:|---|"]
        for item in events: report.append(f"| {item['stage']} | {item['status']} | {item['duration_seconds']} | {json.dumps(item.get('output', {}), ensure_ascii=False)} |")
        (output_dir / "pipeline_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
