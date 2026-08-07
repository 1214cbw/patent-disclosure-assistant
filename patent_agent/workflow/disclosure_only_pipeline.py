"""Disclosure-only pipeline: 材料 → 技术理解 → 中文交底书 → DOCX.

Simplified user-facing workflow that hides A1/A2/B/C engineering concepts.
Internally reuses existing Evidence, Technical Understanding, and DOCX infrastructure.
"""
from __future__ import annotations

import json
import time
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any

from patent_agent.agents import (
    DeterministicGroundedAnalyzer,
    FigurePlanner,
    GroundedDisclosureWriter,
    GroundedTechnicalUnderstandingAgent,
    understanding_to_patent_knowledge,
)
from patent_agent.core.config import Settings
from patent_agent.core.models import (
    EvidenceStatus,
    ReviewStatus,
    TechnicalUnderstandingResult,
    utc_now,
)
from patent_agent.core.state import CaseStore
from patent_agent.document import DocumentRenderer, PatentDocxValidator
from patent_agent.document.ast_factory import disclosure_to_ast
from patent_agent.document.figure_renderer import PatentFigureRenderer
from patent_agent.evidence import EvidenceStore
from patent_agent.ingestion import SourceManager
from patent_agent.llm import StructuredLLMService
from patent_agent.real_case import RealCaseManager

# Chinese disclosure pipeline stages shown to users
STAGE_LABELS_CN = {
    "ingestion": "正在读取材料……",
    "evidence": "正在提取技术内容……",
    "technical_understanding": "正在理解技术方案……",
    "disclosure_planning": "正在整理中文技术交底书……",
    "disclosure_writing": "正在生成交底书正文……",
    "figures": "正在生成公式和附图……",
    "docx": "正在生成 Word……",
    "validation": "正在检查文档……",
}

# User-facing simplified statuses
STATUS_CN = {
    "not_started": "未开始",
    "ingesting": "材料处理中",
    "analyzing": "AI分析中",
    "awaiting_confirmation": "待确认",
    "generating": "交底书生成中",
    "completed": "已完成",
    "failed": "失败",
}


class DisclosurePipelineLog:
    """Pipeline log for disclosure-only workflow."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.events: list[dict] = []

    @contextmanager
    def stage(self, name: str, label_cn: str, inputs: dict | None = None):
        started = time.perf_counter()
        event = {
            "stage": name,
            "label_cn": label_cn,
            "start": utc_now(),
            "input": inputs or {},
            "warnings": [],
            "errors": [],
            "status": "START",
        }
        try:
            yield event
            event["status"] = "PASS"
        except Exception as exc:
            event["status"] = "FAIL"
            event["errors"].append(f"{type(exc).__name__}: {exc}")
            raise
        finally:
            event["duration_seconds"] = round(time.perf_counter() - started, 4)
            self.events.append(event)
            self.path.write_text(
                "\n".join(json.dumps(item, ensure_ascii=False) for item in self.events) + "\n",
                encoding="utf-8",
            )


class DisclosureOnlyPipeline:
    """Generate a single Chinese 技术交底书.docx from uploaded materials.

    Internal stages are retained for quality but the user only sees simplified
    Chinese progress labels and receives a single Word output.
    """

    def __init__(self, settings: Settings, provider=None):
        self.settings = settings
        self.provider = provider
        self.manager = RealCaseManager(settings.project_root)
        self.store = self.manager.case_store  # Use real case store for private_cases
        self.renderer = DocumentRenderer(settings.template_root)
        self.validator = PatentDocxValidator()

    # ── public API ──────────────────────────────────────────────

    def generate(
        self,
        case_id: str,
        *,
        use_llm: bool = True,
        auto_approve: str = "none",  # "none" | "batch" | "auto_batch"
        use_word_com: bool = True,
        use_cache: bool = True,
    ) -> dict:
        """Run full disclosure-only pipeline end-to-end.

        Returns dict with keys: case_id, output_dir, disclosure_docx, validation,
        understanding, disclosure, figures, pipeline_events.
        """
        manifest = self.manager.load(case_id)
        case_dir = self.manager.case_dir(case_id)
        output_dir = self.settings.output_root / "real_case" / case_id
        output_dir.mkdir(parents=True, exist_ok=True)

        log = DisclosurePipelineLog(case_dir / "logs" / "disclosure_pipeline.jsonl")

        # ── Stage 1: Ingestion ──
        with log.stage("ingestion", STAGE_LABELS_CN["ingestion"]) as event:
            sources = sorted(
                path for path in (case_dir / "source").rglob("*") if path.is_file()
            )
            if not sources:
                raise ValueError("请先上传至少一份技术材料。")
            _, chunks, images = SourceManager(self.store).ingest(case_id, sources)
            evidence_store = EvidenceStore(case_dir / "evidence")
            event["output"] = {
                "files": len(sources),
                "chunks": len(chunks),
                "evidence_total": len(evidence_store.all()),
                "images": len(images),
            }

        # ── Stage 2: Technical Understanding (reuse if available) ──
        with log.stage(
            "technical_understanding", STAGE_LABELS_CN["technical_understanding"]
        ) as event:
            # Try to load existing understanding first
            existing_path = None
            try:
                existing_path = self.store.latest_stage_path(case_id, "p1_technical_understanding")
            except Exception:
                pass

            if existing_path and existing_path.exists():
                understanding = TechnicalUnderstandingResult.model_validate_json(
                    existing_path.read_text(encoding="utf-8")
                )
                event["output"] = {
                    "facts": len(understanding.facts),
                    "equations": len(understanding.equations),
                    "steps": len(understanding.steps),
                    "components": len(understanding.components),
                    "uncertainties": len(understanding.uncertainties),
                    "source": "reused_existing",
                }
            elif use_llm and self.provider is not None:
                effective = self.manager.assert_llm_allowed(
                    case_id, self.settings.patent_llm_mode, manifest.llm_mode
                )
                effective_settings = replace(self.settings, llm_cache_enabled=use_cache)
                llm = StructuredLLMService(
                    self.provider, effective_settings, case_dir
                )
                understanding = GroundedTechnicalUnderstandingAgent().run(
                    evidence_store, llm
                )
                self.store.save_stage(case_id, "p1_technical_understanding", understanding)
            else:
                understanding = DeterministicGroundedAnalyzer().run(chunks, evidence_store)
                self.store.save_stage(case_id, "p1_technical_understanding", understanding)

            event["output"] = event.get("output", {}) or {
                "facts": len(understanding.facts),
                "equations": len(understanding.equations),
                "steps": len(understanding.steps),
                "components": len(understanding.components),
                "uncertainties": len(understanding.uncertainties),
            }

        # ── Batch Approval (if requested) ──
        if auto_approve in ("batch", "auto_batch"):
            review_mode = (
                "AUTO_BATCH_APPROVED_BY_USER_SETTING"
                if auto_approve == "auto_batch"
                else "BATCH_APPROVED"
            )
            understanding = self._batch_approve_understanding(
                case_id, understanding, review_mode
            )
            self.store.save_stage(
                case_id, "p1_technical_understanding", understanding, human_modified=True
            )

        # ── Stage 3: Technical Feature Tree ──
        with log.stage("feature_tree", "正在构建技术特征树……") as event:
            from patent_agent.core.feature_tree import build_feature_tree_from_understanding
            feature_tree = build_feature_tree_from_understanding(understanding, evidence_store)
            all_nodes = feature_tree.get_all_nodes()
            event["output"] = {
                "total_nodes": feature_tree.total_nodes,
                "categories": {k: len(v) for k, v in feature_tree.nodes_by_category().items()},
            }

        # ── Stage 4: Disclosure Content Plan ──
        with log.stage("content_plan", "正在制定章节内容计划……") as event:
            from patent_agent.agents.content_planner import DisclosureContentPlanner
            planner = DisclosureContentPlanner()
            title_cn = _derive_title_cn(understanding, manifest)
            content_plan = planner.plan(case_id, title_cn, feature_tree, understanding)
            plan_path = case_dir / "review" / "disclosure_content_plan.json"
            content_plan.save(plan_path)
            event["output"] = {
                "sections": len(content_plan.sections),
                "features_covered": content_plan.covered_features,
                "total_features": content_plan.total_features,
                "coverage_ratio": f"{content_plan.coverage_ratio():.1%}",
                "figure_plan": len(content_plan.figure_plan),
            }

        # ── Stage 5: Section-by-Section Disclosure Writing ──
        with log.stage(
            "disclosure_writing", STAGE_LABELS_CN["disclosure_writing"]
        ) as event:
            from patent_agent.agents.section_writer import SectionWriter

            writer = SectionWriter(
                llm_service=llm if (use_llm and self.provider is not None) else None
            )
            disclosure = writer.generate_all_sections(
                content_plan, feature_tree, understanding, evidence_store,
                inventor_assertions=self.store.load_inventor_assertions(case_id),
            )

            self.store.save_stage(case_id, "p1_disclosure", disclosure)
            event["output"] = {
                "sections": len(disclosure.sections),
                "paragraphs": sum(
                    len(section.paragraphs) for section in disclosure.sections
                ),
            }

        # ── Stage 6: Figures ──
        with log.stage("figures", STAGE_LABELS_CN["figures"]) as event:
            from patent_agent.core.models import FigureSpec, FigureNode, FigureEdge

            figures = []
            fig_output_dir = output_dir / "figures"
            fig_output_dir.mkdir(parents=True, exist_ok=True)

            # Use content plan's figure plan for domain-specific figures
            for fp in content_plan.figure_plan:
                try:
                    # Build FigureSpec from content plan
                    nodes = self._build_figure_nodes(fp, feature_tree, understanding)
                    edges = self._build_figure_edges(fp, nodes)
                    spec = FigureSpec(
                        id=fp["figure_id"],
                        number=fp["number"],
                        type=fp.get("type", "flowchart"),
                        title=fp["title_cn"],
                        nodes=nodes,
                        edges=edges,
                        source_ids=[],
                    )
                    rendered = PatentFigureRenderer().render(spec, fig_output_dir)
                    figures.append(rendered)
                except Exception as exc:
                    event["warnings"].append(f"Figure {fp.get('figure_id')} failed: {exc}")

            event["output"] = {"planned": len(content_plan.figure_plan), "rendered": len(figures)}

        # ── Stage 4b: Post-process disclosure (cleanup unwanted sections) ──
        disclosure = _cleanup_disclosure_sections(disclosure)

        # ── Stage 4c: Build knowledge for AST ──
        knowledge = understanding_to_patent_knowledge(understanding, evidence_store)

        # ── Stage 5: DOCX Rendering ──
        with log.stage("docx", STAGE_LABELS_CN["docx"]) as event:
            from patent_agent.agents import grounded_disclosure_to_draft

            draft = grounded_disclosure_to_draft(disclosure, knowledge, figures)
            ast = disclosure_to_ast(case_id, draft)

            # Save v1 as backup if exists, then write v2
            v1_path = output_dir / "技术交底书_v1.docx"
            v2_path = output_dir / "技术交底书_v2.docx"
            main_path = output_dir / "技术交底书.docx"

            # Backup old version
            if main_path.exists() and not v1_path.exists():
                import shutil
                shutil.copy2(main_path, v1_path)

            # Render new version
            docx_path = self.renderer.render(ast, main_path)
            if main_path.exists():
                import shutil
                shutil.copy2(main_path, v2_path)

            event["output"] = {
                "docx_path": str(docx_path),
                "v2_path": str(v2_path) if v2_path.exists() else None,
                "size_kb": round(docx_path.stat().st_size / 1024, 1),
            }

        # ── Stage 6: Validation ──
        with log.stage("validation", STAGE_LABELS_CN["validation"]) as event:
            if use_word_com:
                validation = self.validator.validate(docx_path, export_pdf=True)
            else:
                xml = self.validator.inspect_xml(docx_path)
                validation = {
                    "xml": xml,
                    "word": {"available": False},
                    "pass": xml.get("xml_pass", False),
                }

            # Chinese disclosure quality check
            cn_check = _check_chinese_disclosure(docx_path, understanding, disclosure)

            event["output"] = {
                "docx_pass": validation["pass"],
                "omml_count": validation.get("xml", {}).get("omml_count", 0),
                "chinese_check": cn_check,
            }

        # ── Write internal audit files ──
        _write_internal_outputs(output_dir, understanding, disclosure, figures, validation, cn_check, log.events)

        # ── Update manifest ──
        manifest.current_checkpoint = "FINAL"  # disclosure-only completed
        self.manager.save(manifest)

        return {
            "case_id": case_id,
            "output_dir": str(output_dir),
            "disclosure_docx": str(docx_path),
            "validation": validation,
            "understanding": understanding,
            "disclosure": disclosure,
            "figures": figures,
            "chinese_check": cn_check,
            "pipeline_events": log.events,
        }

    def batch_approve(
        self,
        case_id: str,
        review_mode: str = "BATCH_APPROVED",
        approved_by: str = "local_user",
    ) -> dict:
        """Batch-approve all UNREVIEWED facts in the technical understanding."""
        case_dir = self.manager.case_dir(case_id)
        path = self.store.latest_stage_path(case_id, "p1_technical_understanding")
        understanding = TechnicalUnderstandingResult.model_validate_json(
            path.read_text(encoding="utf-8")
        )
        understanding = self._batch_approve_understanding(
            case_id, understanding, review_mode, approved_by
        )
        self.store.save_stage(
            case_id, "p1_technical_understanding", understanding, human_modified=True
        )
        return {
            "case_id": case_id,
            "review_mode": review_mode,
            "approved_facts": sum(
                1 for f in understanding.facts if f.review_status != ReviewStatus.UNREVIEWED
            ),
            "total_facts": len(understanding.facts),
        }

    # ── internal helpers ────────────────────────────────────────

    @staticmethod
    def _build_figure_nodes(fp: dict, feature_tree, understanding) -> list:
        """Build FigureNode list from content plan figure entry."""
        from patent_agent.core.models import FigureNode

        desc = fp.get("description", "")
        steps_text = desc.split("→") if "→" in desc else [desc]

        nodes = []
        for i, step in enumerate(steps_text):
            label = step.strip()
            if not label:
                continue
            # Keep label concise (max 3 lines)
            if len(label) > 40:
                # Split into 2 lines
                mid = len(label) // 2
                label = label[:mid].strip() + "\n" + label[mid:].strip()
            nodes.append(FigureNode(
                id=f"N{i+1:02d}",
                label=label,
                claim_step="",
            ))
        return nodes

    @staticmethod
    def _build_figure_edges(fp: dict, nodes: list) -> list:
        """Build FigureEdge list connecting nodes sequentially."""
        from patent_agent.core.models import FigureEdge

        edges = []
        for i in range(len(nodes) - 1):
            edges.append(FigureEdge(
                source=nodes[i].id,
                target=nodes[i + 1].id,
            ))
        return edges

    def _batch_approve_understanding(
        self,
        case_id: str,
        understanding: TechnicalUnderstandingResult,
        review_mode: str,
        approved_by: str = "local_user",
    ) -> TechnicalUnderstandingResult:
        now = utc_now()
        updated_facts = []
        for fact in understanding.facts:
            if fact.review_status == ReviewStatus.UNREVIEWED:
                updated_facts.append(
                    fact.model_copy(
                        update={
                            "review_status": ReviewStatus.LOCKED,
                            "locked": True,
                            "notes": (
                                fact.notes or ""
                                + f" [BATCH_APPROVED: {review_mode} by {approved_by} at {now}]"
                            ).strip(),
                        }
                    )
                )
            else:
                updated_facts.append(fact)

        # Record batch approval metadata
        batch_record = {
            "review_mode": review_mode,
            "approved_by": approved_by,
            "approved_at": now,
            "fact_count": len(updated_facts),
            "note": "用户整体确认了AI技术理解结果，未逐条人工审核。",
        }
        batch_path = (
            self.manager.case_dir(case_id) / "review" / "batch_approval.json"
        )
        batch_path.parent.mkdir(parents=True, exist_ok=True)
        batch_path.write_text(
            json.dumps(batch_record, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        return understanding.model_copy(update={"facts": updated_facts})


# ── helpers ──────────────────────────────────────────────────────


def _minimal_strategy_for_disclosure(understanding):
    """Create a minimal protection strategy for disclosure-only mode."""
    from patent_agent.core.models import (
        GroundedProtectionStrategy,
        GroundedStatement,
        TerminologyChoice,
    )

    facts = [f for f in understanding.facts if f.review_status != ReviewStatus.REJECTED]
    core_statements = []
    for fact in facts[:10]:
        core_statements.append(
            GroundedStatement(
                text=fact.statement,
                evidence_ids=fact.evidence_ids,
                status=fact.status,
                confidence=fact.confidence,
            )
        )

    return GroundedProtectionStrategy(
        inventive_concept=understanding.facts[0].statement if understanding.facts else "",
        independent_claim_core=core_statements[:5] if len(core_statements) >= 5 else core_statements,
        dependent_claim_features=core_statements[5:] if len(core_statements) > 5 else [],
        optional_features=[],
        broad_terms=[
            TerminologyChoice(
                concept_id=f"TERM-{i:03d}",
                selected_term=comp.name[:30] if hasattr(comp, 'name') else f"component_{i}",
                evidence_ids=comp.evidence_ids if hasattr(comp, 'evidence_ids') else [],
            )
            for i, comp in enumerate(understanding.components[:5], 1)
        ],
        narrow_terms=[],
        parameters_to_avoid_locking=[],
        alternative_embodiments_needed=[],
        support_gaps=[],
        risks=["Disclosure-only mode: 未进行新颖性检索。后续由代理机构处理。"],
        inventor_questions=[],
    )


def _first_candidate(understanding):
    """Create a minimal invention candidate for disclosure writing."""
    from patent_agent.core.models import (
        CandidateScoreBreakdown,
        GroundedInventionCandidate,
        GroundedStatement,
    )

    facts = [f for f in understanding.facts if f.review_status != ReviewStatus.REJECTED]
    mandatory = []
    for fact in facts[:8]:
        mandatory.append(
            GroundedStatement(
                text=fact.statement,
                evidence_ids=fact.evidence_ids,
                status=fact.status,
                confidence=fact.confidence,
            )
        )

    core = GroundedStatement(
        text=facts[0].statement if facts else "",
        evidence_ids=facts[0].evidence_ids if facts else [],
        status=EvidenceStatus.SOURCE_FACT,
        confidence=0.9,
    )

    tech_problem = GroundedStatement(
        text="现有技术存在技术效果不理想的问题。" if not facts else facts[0].statement,
        evidence_ids=facts[0].evidence_ids if facts else [],
        status=EvidenceStatus.INFERRED,
        confidence=0.7,
    )

    tech_effects = [
        GroundedStatement(
            text="提升技术方案的整体性能。",
            evidence_ids=facts[0].evidence_ids if facts else [],
            status=EvidenceStatus.INFERRED,
            confidence=0.7,
        )
    ]

    all_evidence = sorted(set(
        eid for f in facts for eid in f.evidence_ids
    ))

    return GroundedInventionCandidate(
        candidate_id="INV-D001",
        title="技术方案核心",
        technical_problem=tech_problem,
        core_idea=core,
        mandatory_features=mandatory[:5] if len(mandatory) >= 5 else mandatory,
        optional_features=mandatory[5:] if len(mandatory) > 5 else [],
        technical_effects=tech_effects,
        evidence_ids=all_evidence,
        novelty_hypothesis="待专利代理机构评估。Disclosure-only mode: 未进行新颖性检索。",
        inventiveness_hypothesis="待专利代理机构评估。",
        protection_value_score=0.7,
        evidence_strength_score=0.8,
        risk_score=0.3,
        score_breakdown=CandidateScoreBreakdown(
            evidence_strength=0.8,
            novelty_potential=0.5,
            technical_importance=0.7,
            claimability=0.6,
            alternative_coverage=0.5,
            implementation_support=0.8,
            risk=0.3,
        ),
        review_status=ReviewStatus.LOCKED,
        locked=True,
    )


def _deterministic_cn_disclosure(title: str, understanding) -> "GroundedDisclosure":
    """Generate a basic Chinese disclosure deterministically from facts."""
    from patent_agent.core.models import (
        GroundedDisclosure,
        GroundedParagraph,
        GroundedSection,
        ReviewStatus,
    )

    sections_data = [
        ("01", "发明名称", [title]),
        ("02", "技术领域", [_derive_tech_field(understanding)]),
        ("03", "背景技术", [_derive_background(understanding)]),
        ("04", "现有技术存在的问题", [_derive_problems(understanding)]),
        ("05", "发明目的", ["本发明旨在提供一种技术方案，以解决上述现有技术中存在的问题。"]),
        ("06", "技术方案", _derive_tech_solution(understanding)),
        ("07", "有益效果", [_derive_effects(understanding)]),
        ("08", "附图说明", ["附图展示本技术方案的整体流程及关键模块结构。"]),
        ("09", "具体实施方式", _derive_implementation(understanding)),
        ("10", "技术关键点及建议重点关注内容", [_derive_key_points(understanding)]),
        ("11", "待发明人或代理机构进一步确认的事项", _derive_pending_items(understanding)),
    ]

    sections = []
    anchor_fact = next(
        (f for f in understanding.facts if f.review_status != ReviewStatus.REJECTED),
        None,
    )
    anchor_evidence = anchor_fact.evidence_ids if anchor_fact else []

    for section_id, title_cn, paragraphs_text in sections_data:
        paragraphs = []
        for i, text in enumerate(paragraphs_text, 1):
            if not text.strip():
                continue
            facts_for_para = [
                f.fact_id
                for f in understanding.facts
                if f.review_status != ReviewStatus.REJECTED
            ][:3]  # best-effort linking
            paragraphs.append(
                GroundedParagraph(
                    paragraph_id=f"DISC-{section_id}-P{i:03d}",
                    section_id=section_id,
                    text=text,
                    evidence_ids=anchor_evidence,
                    fact_ids=facts_for_para,
                    derived_from=facts_for_para,
                    status=EvidenceStatus.INFERRED,
                    review_status=ReviewStatus.LOCKED,
                )
            )
        sections.append(
            GroundedSection(
                section_id=section_id,
                title=title_cn,
                paragraphs=paragraphs,
            )
        )

    return GroundedDisclosure(title=title, sections=sections)


def _derive_tech_field(understanding) -> str:
    comp_names = [getattr(c, "name", "") or getattr(c, "description", "") for c in understanding.components]
    field = "人工智能与图像处理" if any(
        kw in " ".join(comp_names).lower()
        for kw in ["network", "model", "learning", "neural", "diffusion", "generat", "图像", "网络", "学习", "模型", "生成"]
    ) else "计算机技术"
    return f"本发明涉及{field}技术领域，具体涉及一种基于机器学习的技术方案。"


def _derive_background(understanding) -> str:
    # Collect relevant background facts
    bg_facts = [
        f.statement
        for f in understanding.facts
        if f.category in ("background", "context", "problem", "related_work", "现有技术")
        and f.review_status != ReviewStatus.REJECTED
    ]
    if not bg_facts:
        bg_facts = [
            f.statement
            for f in understanding.facts[:5]
            if f.review_status != ReviewStatus.REJECTED
        ]
    return "现有技术中，" + "；".join(bg_facts[:3]) + "。"


def _derive_problems(understanding) -> list[str]:
    problems = [
        f.statement
        for f in understanding.facts
        if f.category in ("problem", "limitation", "gap", "问题", "不足")
        and f.review_status != ReviewStatus.REJECTED
    ]
    if not problems:
        problems = [
            f"现有技术存在技术效果不理想的问题。",
            f"现有技术存在实现复杂度较高的问题。",
        ]
    return problems[:4]


def _derive_tech_solution(understanding) -> list[str]:
    steps = [
        f"步骤S{i+1}：{s.text}"
        for i, s in enumerate(understanding.steps)
    ]
    if not steps:
        active_facts = [
            f.statement
            for f in understanding.facts
            if f.review_status != ReviewStatus.REJECTED
        ]
        steps = active_facts[:10]
    return steps


def _derive_effects(understanding) -> str:
    effect_facts = [
        f.statement
        for f in understanding.facts
        if f.category in ("effect", "result", "advantage", "效果", "优势")
        and f.review_status != ReviewStatus.REJECTED
    ]
    if not effect_facts:
        return "本技术方案能够有效解决现有技术中存在的问题，提高系统整体性能。"
    return "本技术方案具有以下有益效果：" + "；".join(effect_facts[:3]) + "。"


def _derive_implementation(understanding) -> list[str]:
    impl_facts = [
        f.statement
        for f in understanding.facts
        if f.category
        in ("implementation", "experiment", "dataset", "training", "实施", "实验", "数据", "训练")
        and f.review_status != ReviewStatus.REJECTED
    ]
    if not impl_facts:
        active_facts = [
            f.statement
            for f in understanding.facts
            if f.review_status != ReviewStatus.REJECTED
        ]
        impl_facts = active_facts[5:15] if len(active_facts) > 5 else active_facts
    return impl_facts[:8]


def _derive_key_points(understanding) -> str:
    return (
        "供专利代理师进一步撰写和确定保护范围时参考。\n"
        "1. 核心技术流程应作为重点保护对象。\n"
        "2. 关键模块的具体实现方式可根据实际需求调整。\n"
        "3. 建议避免将具体参数数值写入独立保护范围。\n"
        "4. 可考虑替代实现方式以扩展保护范围。"
    )


def _derive_pending_items(understanding) -> str:
    items = []
    for u in understanding.uncertainties:
        items.append(f"建议进一步确认：{u.description if hasattr(u, 'description') else str(u)}")
    if not items:
        items.append("如需进一步限定具体实施方式，建议补充关键参数和实验细节。")
    return "\n".join(f"{i+1}. {item}" for i, item in enumerate(items))


def _check_chinese_disclosure(
    docx_path: Path,
    understanding: TechnicalUnderstandingResult,
    disclosure,
) -> dict:
    """Check Chinese quality of the generated disclosure."""
    # This is a deterministic check, can be extended with LLM review
    issues = []

    # Check section titles are Chinese
    for section in disclosure.sections:
        title = section.title if hasattr(section, "title") else ""
        if any(
            eng_word in title
            for eng_word in [
                "Technical Field",
                "Background",
                "Method",
                "Results",
                "Conclusion",
                "Invention Candidate",
                "Claim",
                "Evidence",
                "Technical Understanding",
                "Abstract",
                "Introduction",
                "Related Work",
                "Experiment",
                "Discussion",
            ]
        ):
            issues.append(f"英文章节标题残留: {title}")

    # Check for academic tone
    for section in disclosure.sections:
        for para in section.paragraphs:
            text = para.text if hasattr(para, "text") else ""
            if "本文提出" in text or "本研究" in text or "我们提出" in text:
                issues.append(f"学术论文口吻残留: {text[:80]}...")

    # Count facts
    source_facts = [f for f in understanding.facts if f.status == EvidenceStatus.SOURCE_FACT]
    facts_without_evidence = [f for f in source_facts if not f.evidence_ids]

    return {
        "overall": "PASS" if not issues else "NEEDS_REVIEW",
        "chinese_title_check": "PASS"
        if not any("英文章节标题残留" in i for i in issues)
        else "FAIL",
        "academic_tone_check": "PASS"
        if not any("学术论文口吻" in i for i in issues)
        else "FAIL",
        "source_facts": len(source_facts),
        "facts_without_evidence": len(facts_without_evidence),
        "issues": issues,
    }


def _derive_title_cn(understanding, manifest) -> str:
    """Derive a Chinese disclosure title from the understanding and manifest."""
    paper_title = getattr(manifest, "paper_title", "") or ""
    # Try to extract key tech domain from facts
    facts_text = " ".join(
        getattr(f, "statement", "") for f in (understanding.facts[:5])
    ).lower()
    if "潜在扩散" in facts_text or "latent diffusion" in facts_text:
        return "一种基于潜在扩散模型的电机拓扑图像生成方法"
    if "motor" in facts_text or "电机" in facts_text:
        return "一种基于机器学习的电机拓扑图像生成方法"
    # Fallback
    return "一种基于深度学习的技术方案"


def _cleanup_disclosure_sections(disclosure):
    """Remove unwanted sections (claims, abstract) and ensure proper section count."""
    from patent_agent.core.models import GroundedDisclosure, ReviewStatus

    unwanted_keywords = [
        "权利要求", "claims", "Claim", "摘要", "Abstract",
        "工业实用性", "Industrial Applicability",
    ]
    cleaned_sections = []
    removed = []
    for section in disclosure.sections:
        title = section.title if hasattr(section, "title") else ""
        should_remove = any(kw.lower() in title.lower() for kw in unwanted_keywords)
        if should_remove:
            removed.append(title)
            continue
        cleaned_sections.append(section)

    if removed:
        disclosure = disclosure.model_copy(update={"sections": cleaned_sections})

    return disclosure


def _write_internal_outputs(
    output_dir: Path,
    understanding,
    disclosure,
    figures,
    validation,
    cn_check,
    events,
) -> None:
    """Write internal audit/debug files (not shown to default users)."""
    internal = output_dir / "_internal"
    internal.mkdir(parents=True, exist_ok=True)

    # Technical understanding
    (internal / "understanding.json").write_text(
        understanding.model_dump_json(indent=2), encoding="utf-8"
    )

    # Disclosure
    (internal / "disclosure.json").write_text(
        disclosure.model_dump_json(indent=2), encoding="utf-8"
    )

    # Traceability (disclosure-only: no claims, so use minimal traceability)
    from patent_agent.review import build_traceability, render_traceability_markdown
    from patent_agent.core.models import GroundedClaimSet, PatentClaimV2

    empty_claims = GroundedClaimSet(title="", claims=[PatentClaimV2(claim_number=0, claim_type="method", features=[], rendered_text="", draft_strategy="balanced")])
    traceability = build_traceability(disclosure, empty_claims, understanding, figures)
    (internal / "traceability.json").write_text(
        traceability.model_dump_json(indent=2), encoding="utf-8"
    )
    (internal / "traceability_report.md").write_text(
        render_traceability_markdown(traceability), encoding="utf-8"
    )

    # Validation report
    lines = [
        "# 技术交底书验证报告",
        "",
        f"整体结果: {'通过' if validation['pass'] else '未通过'}",
        "",
        "## 中文化检查",
        f"- 章节标题中文: {cn_check.get('chinese_title_check', 'N/A')}",
        f"- 学术口吻检查: {cn_check.get('academic_tone_check', 'N/A')}",
        f"- 问题数: {len(cn_check.get('issues', []))}",
    ]
    if cn_check.get("issues"):
        lines.append("")
        for issue in cn_check["issues"]:
            lines.append(f"- {issue}")

    lines += [
        "",
        "## Word 文档验证",
        f"- OMML 公式数: {validation.get('xml', {}).get('omml_count', 0)}",
        f"- 残留 LaTeX: {validation.get('xml', {}).get('residual_latex_in_omml', 0)}",
        f"- Word 可用: {validation.get('word', {}).get('available', False)}",
    ]
    (internal / "validation_report.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )

    # Pipeline report
    report = [
        "# 技术交底书生成流水线报告",
        "",
        "| 阶段 | 状态 | 耗时 (秒) | 输出 |",
        "|---|---:|---:|---|",
    ]
    for item in events:
        report.append(
            f"| {item.get('label_cn', item['stage'])} | {item['status']} | "
            f"{item['duration_seconds']} | "
            f"{json.dumps(item.get('output', {}), ensure_ascii=False)} |"
        )
    (internal / "pipeline_report.md").write_text(
        "\n".join(report) + "\n", encoding="utf-8"
    )
