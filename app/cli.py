from __future__ import annotations

import argparse
import json
from pathlib import Path

from patent_agent.core.config import Settings
from patent_agent.core.models import SourceChunk
from patent_agent.core.state import CaseStore
from patent_agent.ingestion import SourceManager
from patent_agent.agents import TechnicalUnderstandingAgent, InventionMiningAgent
from patent_agent.document import PatentDocxValidator
from patent_agent.workflow import PatentPipeline


def main(argv=None):
    parser = argparse.ArgumentParser(prog="patent-agent")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("new"); p.add_argument("case_id"); p.add_argument("--title", default="")
    p = sub.add_parser("ingest"); p.add_argument("case_id"); p.add_argument("paths", nargs="+")
    p = sub.add_parser("analyze"); p.add_argument("case_id"); p.add_argument("--llm", action="store_true")
    p = sub.add_parser("mine"); p.add_argument("case_id")
    for name in ("draft-disclosure", "draft-claims", "render"):
        p = sub.add_parser(name); p.add_argument("case_id")
    p = sub.add_parser("rollback"); p.add_argument("case_id"); p.add_argument("stage"); p.add_argument("version", type=int)
    p = sub.add_parser("regenerate-section"); p.add_argument("case_id"); p.add_argument("section"); p.add_argument("text")
    p = sub.add_parser("validate"); p.add_argument("docx")
    p = sub.add_parser("approve"); p.add_argument("case_id"); p.add_argument("checkpoint", choices=["A", "B", "C"]); p.add_argument("--note", default="")
    p = sub.add_parser("run"); p.add_argument("case_id"); p.add_argument("materials"); p.add_argument("--prior-art", required=True); p.add_argument("--output", required=True); p.add_argument("--auto-approve-demo", action="store_true")
    sub.add_parser("llm-status")
    p = sub.add_parser("evidence"); p.add_argument("case_id"); p.add_argument("--query", default=""); p.add_argument("--top-k", type=int, default=10)
    p = sub.add_parser("claims-support"); p.add_argument("case_id")
    p = sub.add_parser("dry-run-real"); p.add_argument("case_id"); p.add_argument("materials"); p.add_argument("--output", required=True); p.add_argument("--llm", action="store_true"); p.add_argument("--no-cache", action="store_true")
    p = sub.add_parser("confirm-inventor"); p.add_argument("case_id"); p.add_argument("question_id"); p.add_argument("statement")
    args = parser.parse_args(argv); settings = Settings.load(); store = CaseStore(settings.workspace_root)
    if args.command == "new": print(store.create(args.case_id, args.title).model_dump_json(indent=2))
    elif args.command == "ingest": print(SourceManager(store).ingest(args.case_id, [Path(p) for p in args.paths])[0])
    elif args.command == "analyze":
        chunks = [SourceChunk.model_validate(x) for x in json.loads((store.case_dir(args.case_id)/"working"/"source_chunks.json").read_text(encoding="utf-8"))]
        if args.llm:
            from patent_agent.agents import GroundedTechnicalUnderstandingAgent
            from patent_agent.evidence import EvidenceStore
            from patent_agent.llm import OpenAICompatibleProvider, StructuredLLMService
            if settings.patent_llm_mode == "disabled": raise RuntimeError("LLM_DISABLED: set PATENT_LLM_MODE only after confidentiality approval")
            service = StructuredLLMService(OpenAICompatibleProvider(settings), settings, store.case_dir(args.case_id))
            result = GroundedTechnicalUnderstandingAgent().run(EvidenceStore(store.case_dir(args.case_id)/"evidence"), service); print(store.save_stage(args.case_id, "v2_grounded_understanding", result))
        else:
            result = TechnicalUnderstandingAgent().run(chunks); print(store.save_stage(args.case_id, "stage_2_technical_understanding", result))
    elif args.command == "mine":
        from patent_agent.core.models import PatentKnowledge
        knowledge = PatentKnowledge.model_validate_json(store.latest_stage_path(args.case_id, "stage_2_technical_understanding").read_text(encoding="utf-8")); result = InventionMiningAgent().run(knowledge); print(store.save_stage(args.case_id, "stage_3_invention_mining", [x.model_dump() for x in result]))
    elif args.command == "approve": store.approve_checkpoint(args.case_id, args.checkpoint, "approve", args.note); print("approved")
    elif args.command == "rollback": print(store.restore_stage(args.case_id, args.stage, args.version))
    elif args.command == "regenerate-section":
        from patent_agent.core.models import DisclosureDraft
        draft = DisclosureDraft.model_validate_json(store.latest_stage_path(args.case_id, "stage_7_disclosure").read_text(encoding="utf-8")); draft.sections[args.section] = [args.text]; print(store.save_stage(args.case_id, "stage_7_disclosure", draft, human_modified=True))
    elif args.command == "draft-disclosure":
        from patent_agent.core.models import PatentKnowledge, ProtectionStrategy, FigureSpec
        from patent_agent.agents import DisclosureWriter
        knowledge = PatentKnowledge.model_validate_json(store.latest_stage_path(args.case_id, "stage_2_technical_understanding").read_text(encoding="utf-8")); strategy = ProtectionStrategy.model_validate_json(store.latest_stage_path(args.case_id, "stage_6_protection_strategy").read_text(encoding="utf-8")); figures = [FigureSpec.model_validate(x) for x in json.loads(store.latest_stage_path(args.case_id, "stage_9_figures").read_text(encoding="utf-8"))]; print(store.save_stage(args.case_id, "stage_7_disclosure", DisclosureWriter().run(store.load(args.case_id).title, knowledge, strategy, figures)))
    elif args.command == "draft-claims":
        from patent_agent.core.models import PatentKnowledge, ProtectionStrategy
        from patent_agent.agents import ClaimsWriter
        knowledge = PatentKnowledge.model_validate_json(store.latest_stage_path(args.case_id, "stage_2_technical_understanding").read_text(encoding="utf-8")); strategy = ProtectionStrategy.model_validate_json(store.latest_stage_path(args.case_id, "stage_6_protection_strategy").read_text(encoding="utf-8")); print(store.save_stage(args.case_id, "stage_8_claims", ClaimsWriter().run(store.load(args.case_id).title, knowledge, strategy)))
    elif args.command == "render":
        from patent_agent.core.models import ClaimTree, DisclosureDraft
        from patent_agent.document import DocumentRenderer
        from patent_agent.document.ast_factory import claims_to_ast, disclosure_to_ast
        draft = DisclosureDraft.model_validate_json(store.latest_stage_path(args.case_id, "stage_7_disclosure").read_text(encoding="utf-8")); claims = ClaimTree.model_validate_json(store.latest_stage_path(args.case_id, "stage_8_claims").read_text(encoding="utf-8")); output = store.case_dir(args.case_id)/"output"; renderer = DocumentRenderer(settings.template_root); print(renderer.render(disclosure_to_ast(args.case_id, draft), output/"技术交底书.docx")); print(renderer.render(claims_to_ast(args.case_id, claims), output/"权利要求草案.docx"))
    elif args.command == "validate": print(json.dumps(PatentDocxValidator().validate(Path(args.docx)), ensure_ascii=False, indent=2))
    elif args.command == "run":
        result = PatentPipeline(settings).run(args.case_id, [Path(args.materials)], Path(args.prior_art), Path(args.output), auto_approve_demo=args.auto_approve_demo); print(result["output_dir"])
    elif args.command == "llm-status":
        from patent_agent.llm import OpenAICompatibleProvider
        status = OpenAICompatibleProvider(settings).health_check(); status["api_configured"] = bool(settings.llm_api_key); print(json.dumps(status, ensure_ascii=False, indent=2))
    elif args.command == "evidence":
        from patent_agent.evidence import EvidenceStore
        evidence_store = EvidenceStore(store.case_dir(args.case_id)/"evidence"); items = evidence_store.search(args.query, args.top_k) if args.query else evidence_store.all()[:args.top_k]; print(json.dumps([item.model_dump() for item in items], ensure_ascii=False, indent=2, default=str))
    elif args.command == "claims-support":
        print(store.latest_stage_path(args.case_id, "v2_claims_support_matrix").read_text(encoding="utf-8"))
    elif args.command == "dry-run-real":
        from patent_agent.llm import OpenAICompatibleProvider
        from patent_agent.workflow import PatentPipelineV2
        provider = OpenAICompatibleProvider(settings) if args.llm else None
        result = PatentPipelineV2(settings, provider).dry_run_real(args.case_id, [Path(args.materials)], Path(args.output), use_llm=args.llm, use_cache=not args.no_cache); print(json.dumps({key: value for key, value in result.items() if key not in {"understanding", "candidates", "questions"}}, ensure_ascii=False, indent=2))
    elif args.command == "confirm-inventor":
        from patent_agent.core.models import InventorAssertion
        assertion = InventorAssertion(assertion_id=f"IA-{args.question_id}", question_id=args.question_id, statement=args.statement, confirmed_by_user=True, confirmed_by="user")
        print(store.save_inventor_assertion(args.case_id, assertion))


if __name__ == "__main__": main()
