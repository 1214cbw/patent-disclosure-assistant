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
    p = sub.add_parser("real-case-create"); p.add_argument("case_id"); p.add_argument("--title", default="[待发明人确认]"); p.add_argument("--authorized", action="store_true"); p.add_argument("--llm-mode", choices=["disabled", "local", "external-approved"], default="disabled"); p.add_argument("--external-llm-approved", action="store_true")
    p = sub.add_parser("real-case-ingest"); p.add_argument("case_id"); p.add_argument("path")
    p = sub.add_parser("real-case-a1"); p.add_argument("case_id"); p.add_argument("--llm", action="store_true"); p.add_argument("--auto-approve", action="store_true")
    p = sub.add_parser("checkpoint"); p.add_argument("case_id")
    p = sub.add_parser("checkpoint-review"); p.add_argument("case_id"); p.add_argument("checkpoint", choices=["A1", "A2", "B", "C"])
    p = sub.add_parser("checkpoint-export"); p.add_argument("case_id"); p.add_argument("checkpoint", choices=["A1", "A2", "B", "C"])
    p = sub.add_parser("checkpoint-import"); p.add_argument("case_id"); p.add_argument("json_file")
    p = sub.add_parser("checkpoint-approve"); p.add_argument("case_id"); p.add_argument("checkpoint", choices=["A1", "A2", "B", "C"]); p.add_argument("--ack-risk", action="store_true")
    p = sub.add_parser("checkpoint-continue"); p.add_argument("case_id"); p.add_argument("--prior-art")
    p = sub.add_parser("claim-scope"); p.add_argument("case_id")
    p = sub.add_parser("evaluation-report"); p.add_argument("case_id"); p.add_argument("--run-id")
    p = sub.add_parser("real-case-answer"); p.add_argument("case_id"); p.add_argument("question_id"); p.add_argument("statement")
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
    elif args.command == "real-case-create":
        from patent_agent.real_case import RealCaseManager
        result = RealCaseManager(settings.project_root).create(args.case_id, authorized=args.authorized, llm_mode=args.llm_mode, external_llm_approved=args.external_llm_approved, title=args.title)
        print(result.model_dump_json(indent=2))
    elif args.command == "real-case-ingest":
        from patent_agent.real_case import RealCaseManager
        print(RealCaseManager(settings.project_root).ingest(args.case_id, Path(args.path)))
    elif args.command == "real-case-a1":
        from patent_agent.workflow import RealCaseWorkflow
        provider = None
        if args.llm:
            from patent_agent.llm import OpenAICompatibleProvider
            provider = OpenAICompatibleProvider(settings)
        print(RealCaseWorkflow(settings, provider).run_a1(args.case_id, use_llm=args.llm, auto_approve=args.auto_approve))
    elif args.command in {"checkpoint", "checkpoint-review", "checkpoint-export"}:
        from patent_agent.human_review import HumanReviewManager
        from patent_agent.real_case import RealCaseManager
        case_dir = RealCaseManager(settings.project_root).case_dir(args.case_id); manager = HumanReviewManager(case_dir)
        if args.command == "checkpoint": print(json.dumps({key: value.model_dump(mode="json") for key, value in manager.machine.records.items()}, ensure_ascii=False, indent=2))
        else:
            checkpoint = args.checkpoint; root = case_dir / "review" / f"checkpoint_{checkpoint}"
            print(root if args.command == "checkpoint-review" else root / "review_input.json")
    elif args.command == "checkpoint-import":
        from patent_agent.workflow import RealCaseWorkflow
        print(RealCaseWorkflow(settings).import_review(args.case_id, Path(args.json_file)))
    elif args.command == "checkpoint-approve":
        from patent_agent.workflow import RealCaseWorkflow
        RealCaseWorkflow(settings).approve(args.case_id, args.checkpoint, risk_acknowledged=args.ack_risk); print("approved")
    elif args.command == "checkpoint-continue":
        from patent_agent.workflow import RealCaseWorkflow
        print(RealCaseWorkflow(settings).continue_case(args.case_id, Path(args.prior_art) if args.prior_art else None))
    elif args.command == "claim-scope":
        from patent_agent.real_case import RealCaseManager
        manager = RealCaseManager(settings.project_root); print(manager.case_store.latest_stage_path(args.case_id, "p1_claim_scope").read_text(encoding="utf-8"))
    elif args.command == "evaluation-report":
        from patent_agent.real_case import RealCaseManager
        root = RealCaseManager(settings.project_root).case_dir(args.case_id) / "evaluation_runs"
        run = root / args.run_id if args.run_id else max((path for path in root.iterdir() if path.is_dir()), key=lambda path: path.name)
        print((run / "model_evaluation_report.md").read_text(encoding="utf-8"))
    elif args.command == "real-case-answer":
        from patent_agent.workflow import RealCaseWorkflow
        print(RealCaseWorkflow(settings).answer_inventor_question(args.case_id, args.question_id, args.statement))


if __name__ == "__main__": main()
