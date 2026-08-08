from __future__ import annotations

import json
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from patent_agent.core.atomic import atomic_write_bytes, atomic_write_json
from patent_agent.core.config import Settings
from patent_agent.core.models import TechnicalUnderstandingResult
from patent_agent.core.state import CaseStore
from patent_agent.evidence import EvidenceStore
from patent_agent.human_review import HumanCorrection, HumanReviewManager, ReviewImport
from patent_agent.progress import ProgressManager
from patent_agent.real_case import RealCaseManager
from patent_agent.workflow import RealCaseWorkflow

from .jobs import JobManager


settings = Settings.load()
store = CaseStore(settings.workspace_root)
real_cases = RealCaseManager(settings.project_root)
progress = ProgressManager(settings.project_root)
jobs = JobManager(settings.project_root)
static_root = Path(__file__).with_name("static")

app = FastAPI(title="Patent Agent 本地工作台", version="2.0.0", docs_url="/api/docs", redoc_url=None)
app.mount("/static", StaticFiles(directory=static_root), name="static")

ALLOWED_UPLOADS = {".txt", ".md", ".json", ".csv", ".docx", ".pdf", ".pptx", ".png", ".jpg", ".jpeg"}
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
STAGE_ALIASES = {
    "technical": "p1_technical_understanding",
    "candidates": "p1_invention_candidates",
    "novelty": "p1_novelty",
    "strategy": "p1_protection_strategy",
    "disclosure": "p1_disclosure",
    "claims": "p1_claims",
    "support": "p1_claim_support",
    "scope": "p1_claim_scope",
}


class CaseCreate(BaseModel):
    case_id: str
    title: str = ""


class RealCaseCreate(CaseCreate):
    authorized: bool = False
    llm_mode: str = "disabled"
    external_llm_approved: bool = False
    synthetic: bool = False
    llm_model: str = ""  # V6.5: project-level model selection, empty=system default


class ModelUpdate(BaseModel):
    """Update project model selection."""
    llm_model: str = Field(min_length=1)


class PublicationMetadata(BaseModel):
    paper_title: str = "UNKNOWN"
    publication_status: str = "UNKNOWN"
    first_public_date: str = "UNKNOWN"
    doi: str = "UNKNOWN"
    preprint_status: str = "UNKNOWN"
    patent_filed_before_publication: str = "UNKNOWN"
    publication_review_status: str = "UNREVIEWED"


class ReviewAction(BaseModel):
    target_id: str
    action: str = "ACCEPT"
    corrected_value: Any = None
    reason: str = ""
    lock_after_apply: bool = True
    confirmed_by_user: bool = True


class BulkReview(BaseModel):
    target_ids: list[str] = Field(min_length=1)
    action: str = "ACCEPT"
    confirmed_all: bool = False


class Approval(BaseModel):
    risk_acknowledged: bool = False


class QuestionAnswer(BaseModel):
    statement: str = Field(min_length=1)


class RunRequest(BaseModel):
    use_llm: bool = False


class ContinueRequest(BaseModel):
    prior_art_filename: str | None = None


@app.middleware("http")
async def local_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-src 'self'"
    return response


@app.get("/")
def home():
    return FileResponse(static_root / "index.html")


@app.get("/api/system/status")
def system_status():
    from patent_agent.llm import OpenAICompatibleProvider

    llm = OpenAICompatibleProvider(settings).health_check()
    llm["api_configured"] = bool(settings.llm_api_key)
    return {
        "app": "READY",
        "bind_recommendation": "127.0.0.1",
        "llm": llm,
        "progress": progress.summary(),
        "jobs": jobs.list()[:10],
    }


@app.get("/api/dashboard")
def dashboard():
    real = []
    for path in sorted(real_cases.root.iterdir()) if real_cases.root.exists() else []:
        if not (path / "real_case_manifest.json").exists():
            continue
        manifest = real_cases.load(path.name)
        records = HumanReviewManager(path).machine.records
        real.append({
            **manifest.model_dump(mode="json"),
            "checkpoints": {name: record.status.value for name, record in records.items()},
            "progress": progress.summary(path.name),
        })
    standard = [store.load(path.name).model_dump(mode="json") for path in sorted(store.root.iterdir()) if (path / "case.json").exists()]
    return {"real_cases": real, "synthetic_cases": standard, "counts": {"real": len(real), "synthetic": len(standard)}}


@app.get("/api/cases")
def list_cases():
    return dashboard()["synthetic_cases"]


@app.post("/api/cases")
def create_case(payload: CaseCreate):
    if (store.case_dir(payload.case_id) / "case.json").exists():
        raise HTTPException(409, "案件已存在")
    return store.create(payload.case_id, payload.title).model_dump(mode="json")


@app.get("/api/cases/{case_id}")
def get_case(case_id: str):
    return _standard_case(case_id).model_dump(mode="json")


@app.post("/api/real-cases")
def create_real_case(payload: RealCaseCreate):
    if not payload.authorized:
        raise HTTPException(400, "必须明确确认已获授权处理资料")
    # Validate model if provided
    if payload.llm_model:
        from patent_agent.llm.model_registry import validate_model
        try:
            validate_model(payload.llm_model)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    try:
        manifest = real_cases.create(
            payload.case_id,
            authorized=True,
            llm_mode=payload.llm_mode,
            external_llm_approved=payload.external_llm_approved,
            synthetic=payload.synthetic,
            title=payload.title,
            llm_model=payload.llm_model or "",
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return manifest.model_dump(mode="json")


# ── V6.5 Model Selection API ──

@app.get("/api/models")
def list_models():
    """List available AI models for UI display."""
    from patent_agent.llm.model_registry import allowed_models_display, DEFAULT_MODEL
    return {
        "models": allowed_models_display(),
        "default": DEFAULT_MODEL,
    }


@app.put("/api/real-cases/{case_id}/model")
def update_project_model(case_id: str, payload: ModelUpdate):
    """Update a project's selected AI model."""
    from patent_agent.llm.model_registry import validate_model
    try:
        validated = validate_model(payload.llm_model)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    manifest = _real_manifest(case_id)
    manifest.llm_model = validated
    real_cases.save(manifest)
    return {"case_id": case_id, "llm_model": validated, "status": "UPDATED"}


@app.get("/api/real-cases/{case_id}/model")
def get_project_model(case_id: str):
    """Get a project's current model selection."""
    from patent_agent.llm.model_registry import DEFAULT_MODEL, get_model_info
    manifest = _real_manifest(case_id)
    model_id = manifest.llm_model if hasattr(manifest, 'llm_model') and manifest.llm_model else DEFAULT_MODEL
    info = get_model_info(model_id)
    return {
        "case_id": case_id,
        "llm_model": model_id,
        "display_name": info.display_name if info else model_id,
        "is_default": not (hasattr(manifest, 'llm_model') and manifest.llm_model),
    }


@app.get("/api/real-cases")
def list_real_cases():
    return dashboard()["real_cases"]


@app.get("/api/real-cases/{case_id}/status")
def real_case_status(case_id: str):
    manifest = _real_manifest(case_id)
    records = HumanReviewManager(real_cases.case_dir(case_id)).machine.records
    return {
        "manifest": manifest.model_dump(mode="json"),
        "checkpoints": {key: value.model_dump(mode="json") for key, value in records.items()},
        "progress": progress.summary(case_id),
        "jobs": jobs.list(case_id),
    }


@app.put("/api/real-cases/{case_id}/sources/{filename}")
async def upload_real_source(case_id: str, filename: str, request: Request):
    _real_manifest(case_id)
    safe_name = _safe_filename(filename)
    body = await request.body()
    _validate_upload(safe_name, body)
    target = real_cases.case_dir(case_id) / "source" / safe_name
    atomic_write_bytes(target, body)
    real_cases.ingest(case_id, target)
    return {"file": safe_name, "size": len(body), "status": "INGESTED"}


# ── Supplemental Image Upload ──

SUPPLEMENTAL_IMAGE_TYPES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}
SUPPLEMENTAL_MAX_BYTES = 20 * 1024 * 1024  # 20MB per image


class SupplementalImageMeta(BaseModel):
    caption: str = ""
    image_type: str = "auto"  # auto | structure | flowchart | experiment | other
    use_in_disclosure: bool = True


@app.put("/api/real-cases/{case_id}/supplemental-images/{filename}")
async def upload_supplemental_image(case_id: str, filename: str, request: Request):
    """上传补充技术图片（流程图、结构图、实验图等）。"""
    _real_manifest(case_id)
    safe_name = Path(filename).name
    suffix = Path(safe_name).suffix.lower()
    if suffix not in SUPPLEMENTAL_IMAGE_TYPES:
        raise HTTPException(400, f"不支持的图片格式：{suffix}。支持：{', '.join(SUPPLEMENTAL_IMAGE_TYPES)}")
    body = await request.body()
    if not body or len(body) > SUPPLEMENTAL_MAX_BYTES:
        raise HTTPException(400, f"图片大小必须在1字节至{SUPPLEMENTAL_MAX_BYTES // 1024 // 1024}MB之间")
    target_dir = real_cases.case_dir(case_id) / "supplemental_images"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / safe_name
    atomic_write_bytes(target, body)
    return {"file": safe_name, "size": len(body), "status": "UPLOADED"}


@app.get("/api/real-cases/{case_id}/supplemental-images")
def list_supplemental_images(case_id: str):
    """列出已上传的补充图片。"""
    _real_manifest(case_id)
    target_dir = real_cases.case_dir(case_id) / "supplemental_images"
    if not target_dir.exists():
        return []
    images = []
    for path in sorted(target_dir.rglob("*")):
        if path.is_file() and path.suffix.lower() in SUPPLEMENTAL_IMAGE_TYPES:
            images.append({
                "name": path.name,
                "size": path.stat().st_size,
                "preview_url": f"/api/real-cases/{case_id}/supplemental-images/{path.name}",
            })
    return images


@app.get("/api/real-cases/{case_id}/supplemental-images/{filename}")
def preview_supplemental_image(case_id: str, filename: str):
    """预览补充图片。"""
    _real_manifest(case_id)
    root = (real_cases.case_dir(case_id) / "supplemental_images").resolve()
    target = (root / Path(filename).name).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        raise HTTPException(404, "图片不存在")
    media_types = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                   ".webp": "image/webp", ".gif": "image/gif", ".bmp": "image/bmp"}
    return FileResponse(target, media_type=media_types.get(target.suffix.lower(), "image/png"))


@app.put("/api/real-cases/{case_id}/prior-art/{filename}")
async def upload_prior_art(case_id: str, filename: str, request: Request):
    _real_manifest(case_id)
    safe_name = _safe_filename(filename)
    body = await request.body()
    _validate_upload(safe_name, body)
    target = real_cases.case_dir(case_id) / "search" / "manual_uploads" / safe_name
    atomic_write_bytes(target, body)
    return {"file": safe_name, "size": len(body), "status": "MANUALLY_IMPORTED_PRIOR_ART"}


@app.put("/api/cases/{case_id}/sources/{filename}")
async def upload_source(case_id: str, filename: str, request: Request):
    from patent_agent.ingestion import SourceManager

    _standard_case(case_id)
    safe_name = _safe_filename(filename)
    body = await request.body()
    _validate_upload(safe_name, body)
    source_dir = store.case_dir(case_id) / "source"
    atomic_write_bytes(source_dir / safe_name, body)
    records, chunks, images = SourceManager(store).ingest(case_id, [source_dir])
    return {"file": safe_name, "files": len(records), "chunks": len(chunks), "images": len(images)}


@app.get("/api/real-cases/{case_id}/source/{filename}")
def preview_source(case_id: str, filename: str):
    root = (real_cases.case_dir(case_id) / "source").resolve()
    target = (root / _safe_filename(filename)).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        raise HTTPException(404, "源文件不存在")
    return FileResponse(target, filename=target.name, content_disposition_type="inline")


@app.post("/api/real-cases/{case_id}/run-a1")
def run_a1(case_id: str, payload: RunRequest):
    manifest = _real_manifest(case_id)
    if payload.use_llm and manifest.llm_mode == "disabled":
        raise HTTPException(403, "案件未授权使用 LLM")

    def operation():
        provider = None
        if payload.use_llm:
            from patent_agent.llm import OpenAICompatibleProvider

            provider = OpenAICompatibleProvider(settings)
        return RealCaseWorkflow(settings, provider).run_a1(case_id, use_llm=payload.use_llm)

    return jobs.submit("RUN_A1", case_id, operation)


@app.get("/api/jobs")
def list_jobs(case_id: str | None = None):
    return jobs.list(case_id)


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    record = jobs.get(job_id)
    if record is None:
        raise HTTPException(404, "任务不存在")
    return record


@app.get("/api/real-cases/{case_id}/a1")
def get_a1(case_id: str):
    case_dir = real_cases.case_dir(case_id)
    understanding = _understanding(case_id)
    evidence = EvidenceStore(case_dir / "evidence").all()
    questions_path = case_dir / "review" / "inventor_questions.json"
    questions = json.loads(questions_path.read_text(encoding="utf-8")) if questions_path.exists() else []
    stats_path = case_dir / "review" / "checkpoint_A1" / "a1_quality_statistics.json"
    comparison = case_dir / "review" / "a1_version_comparison.md"
    terms = [
        {"source": item.name, "normalized": item.name, "evidence_ids": item.description.evidence_ids, "review_status": "UNREVIEWED"}
        for item in understanding.components
    ]
    return {
        "understanding": understanding.model_dump(mode="json"),
        "statistics": json.loads(stats_path.read_text(encoding="utf-8")) if stats_path.exists() else {},
        "evidence_scope": dict(Counter(item.scope.value for item in evidence)),
        "questions": questions,
        "terminology": terms,
        "comparison_markdown": comparison.read_text(encoding="utf-8") if comparison.exists() else "",
        "checkpoint": HumanReviewManager(case_dir).machine.records["A1"].model_dump(mode="json"),
    }


@app.get("/api/real-cases/{case_id}/evidence")
def list_real_evidence(case_id: str, query: str = "", top_k: int = 100):
    evidence = EvidenceStore(real_cases.case_dir(case_id) / "evidence")
    items = evidence.search(query, min(top_k, 500)) if query else evidence.all()[: min(top_k, 500)]
    return [item.model_dump(mode="json") for item in items]


@app.get("/api/real-cases/{case_id}/evidence/{evidence_id}")
def get_real_evidence(case_id: str, evidence_id: str):
    try:
        return EvidenceStore(real_cases.case_dir(case_id) / "evidence").get(evidence_id).model_dump(mode="json")
    except KeyError as exc:
        raise HTTPException(404, "Evidence ID 不存在") from exc


@app.post("/api/real-cases/{case_id}/a1/review")
def review_a1_fact(case_id: str, payload: ReviewAction):
    if not payload.confirmed_by_user:
        raise HTTPException(400, "必须明确确认人工操作")
    correction = _correction(case_id, payload)
    return _apply_review(case_id, "A1", [correction])


@app.post("/api/real-cases/{case_id}/a1/review-bulk")
def review_a1_bulk(case_id: str, payload: BulkReview):
    if not payload.confirmed_all:
        raise HTTPException(400, "批量操作需要再次确认")
    if payload.action not in {"ACCEPT", "REJECT"}:
        raise HTTPException(400, "批量操作仅支持 ACCEPT 或 REJECT")
    corrections = [
        _correction(case_id, ReviewAction(target_id=identifier, action=payload.action))
        for identifier in payload.target_ids
    ]
    return _apply_review(case_id, "A1", corrections)


@app.post("/api/real-cases/{case_id}/review/{checkpoint}")
def review_checkpoint_object(case_id: str, checkpoint: str, payload: ReviewAction):
    if checkpoint not in {"A2", "B", "C"}:
        raise HTTPException(400, "该接口仅支持 A2、B、C")
    if not payload.confirmed_by_user:
        raise HTTPException(400, "必须明确确认人工操作")
    return _apply_review(case_id, checkpoint, [_generic_correction(case_id, checkpoint, payload)])


@app.post("/api/real-cases/{case_id}/review/{checkpoint}/bulk")
def review_checkpoint_bulk(case_id: str, checkpoint: str, payload: BulkReview):
    if checkpoint not in {"A2", "B", "C"} or not payload.confirmed_all:
        raise HTTPException(400, "批量操作需要有效 Checkpoint 和再次确认")
    corrections = [
        _generic_correction(case_id, checkpoint, ReviewAction(target_id=identifier, action=payload.action))
        for identifier in payload.target_ids
    ]
    return _apply_review(case_id, checkpoint, corrections)


@app.post("/api/real-cases/{case_id}/questions/{question_id}/answer")
def answer_question(case_id: str, question_id: str, payload: QuestionAnswer):
    try:
        path = RealCaseWorkflow(settings).answer_inventor_question(case_id, question_id, payload.statement)
    except KeyError as exc:
        raise HTTPException(404, "问题不存在") from exc
    return {"status": "ANSWERED", "assertion": path.name}


@app.put("/api/real-cases/{case_id}/publication")
def update_publication(case_id: str, payload: PublicationMetadata):
    try:
        return real_cases.update_publication_metadata(case_id, **payload.model_dump()).model_dump(mode="json")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/real-cases/{case_id}/checkpoints/{checkpoint}/approve")
def approve_checkpoint(case_id: str, checkpoint: str, payload: Approval):
    if checkpoint not in {"A1", "A2", "B", "C"}:
        raise HTTPException(400, "无效 Checkpoint")
    try:
        RealCaseWorkflow(settings).approve(case_id, checkpoint, risk_acknowledged=payload.risk_acknowledged)
    except (ValueError, KeyError, FileNotFoundError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return real_case_status(case_id)


# ── Disclosure-Only API ──────────────────────────────────────────

@app.get("/api/real-cases/{case_id}/disclosure-status")
def disclosure_status(case_id: str):
    """Simplified Chinese status for disclosure-only mode."""
    manifest = _real_manifest(case_id)
    case_dir = real_cases.case_dir(case_id)

    # Determine simplified status
    status_cn = "未开始"
    try:
        understanding_path = real_cases.case_store.latest_stage_path(case_id, "p1_technical_understanding")
        understanding = TechnicalUnderstandingResult.model_validate_json(understanding_path.read_text(encoding="utf-8"))
        facts_count = len(understanding.facts)
        equations_count = len(understanding.equations)
        steps_count = len(understanding.steps)
        uncertainties_count = len(understanding.uncertainties)

        # Check disclosure status
        try:
            disclosure_path = real_cases.case_store.latest_stage_path(case_id, "p1_disclosure")
            status_cn = "已完成"
        except FileNotFoundError:
            # Check if A1 facts are reviewed
            reviewed = sum(1 for f in understanding.facts if f.review_status.value != "UNREVIEWED")
            if reviewed > 0:
                status_cn = "待确认"
            else:
                status_cn = "AI分析中"
    except FileNotFoundError:
        # Check if materials exist
        sources = list((case_dir / "source").rglob("*")) if (case_dir / "source").exists() else []
        if sources:
            status_cn = "材料处理中"

    # Check output
    output_docx = settings.output_root / "real_case" / case_id / "技术交底书.docx"
    if output_docx.exists():
        status_cn = "已完成"

    # Check batch approval
    batch_path = case_dir / "review" / "batch_approval.json"
    batch_info = None
    if batch_path.exists():
        batch_info = json.loads(batch_path.read_text(encoding="utf-8"))

    # V6.5: project model selection for UI display
    from patent_agent.llm.model_registry import get_model_info
    project_model = getattr(manifest, "llm_model", "") or ""
    model_info = get_model_info(project_model) if project_model else None

    return {
        "case_id": case_id,
        "title": manifest.paper_title,
        "title_cn": _auto_chinese_title(manifest),
        "status_cn": status_cn,
        "facts_count": facts_count if 'facts_count' in dir() else 0,
        "equations_count": equations_count if 'equations_count' in dir() else 0,
        "steps_count": steps_count if 'steps_count' in dir() else 0,
        "uncertainties_count": uncertainties_count if 'uncertainties_count' in dir() else 0,
        "batch_approved": batch_info is not None,
        "batch_info": batch_info,
        "disclosure_ready": output_docx.exists(),
        "download_url": f"/api/real-cases/{case_id}/download-disclosure" if output_docx.exists() else None,
        "llm_model": project_model,
        "llm_model_display": model_info.display_name if model_info else (project_model or settings.default_model),
        "llm_model_recommended": model_info.recommended if model_info else False,
    }


@app.post("/api/real-cases/{case_id}/batch-approve")
def batch_approve(case_id: str):
    """一键审核通过：整体确认AI技术理解结果。"""
    _real_manifest(case_id)
    try:
        from patent_agent.workflow.disclosure_only_pipeline import DisclosureOnlyPipeline
        pipeline = DisclosureOnlyPipeline(settings)
        result = pipeline.batch_approve(case_id, review_mode="BATCH_APPROVED", approved_by="local_user")
        return {
            "status": "已确认",
            "message": f"已整体确认 {result['approved_facts']}/{result['total_facts']} 项技术事实。",
            "review_mode": "BATCH_APPROVED",
            **result,
        }
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/real-cases/{case_id}/generate-disclosure")
def generate_disclosure(case_id: str, use_llm: bool = True, auto_approve: str = "none"):
    """生成中文技术交底书。"""
    manifest = _real_manifest(case_id)
    if use_llm and manifest.llm_mode == "disabled":
        raise HTTPException(403, "案件未授权使用 LLM")

    def operation():
        from patent_agent.llm import OpenAICompatibleProvider
        from patent_agent.workflow.disclosure_only_pipeline import DisclosureOnlyPipeline

        provider = OpenAICompatibleProvider(settings) if use_llm else None
        pipeline = DisclosureOnlyPipeline(settings, provider)
        return pipeline.generate(
            case_id,
            use_llm=use_llm,
            auto_approve=auto_approve,
        )

    return jobs.submit("GENERATE_DISCLOSURE", case_id, operation)


@app.get("/api/real-cases/{case_id}/download-disclosure")
def download_disclosure(case_id: str):
    """下载技术交底书。"""
    output_dir = settings.output_root / "real_case" / case_id
    docx_path = output_dir / "技术交底书.docx"
    if not docx_path.exists():
        raise HTTPException(404, "技术交底书尚未生成，请先点击“生成技术交底书”。")
    return FileResponse(
        docx_path,
        filename="技术交底书.docx",
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


@app.get("/api/real-cases/{case_id}/disclosure-summary")
def disclosure_summary(case_id: str):
    """AI分析完成后显示的中文摘要。"""
    _real_manifest(case_id)
    try:
        understanding = _understanding(case_id)
        facts = understanding.facts
        source_facts = [f for f in facts if f.status.value == "SOURCE_FACT"]
        inferred = [f for f in facts if f.status.value == "INFERRED"]
        equations = understanding.equations
        steps = understanding.steps
        components = understanding.components
        uncertainties = understanding.uncertainties

        # Determine suggested figures
        figure_suggestions = min(len(components), 2)

        return {
            "fact_count": len(facts),
            "source_fact_count": len(source_facts),
            "inferred_count": len(inferred),
            "step_count": len(steps),
            "component_count": len(components),
            "equation_count": len(equations),
            "uncertainty_count": len(uncertainties),
            "suggested_figures": figure_suggestions,
            "summary_cn": f"AI已完成技术理解，共识别：\n{len(facts)}项核心技术事实\n{len(steps)}个主要技术步骤\n{len(equations)}个关键公式\n{len(components)}个技术模块\n{len(uncertainties)}个待确认问题",
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, f"获取技术分析摘要失败：{exc}") from exc


@app.post("/api/real-cases/{case_id}/continue")
def continue_case(case_id: str, payload: ContinueRequest):
    case_dir = real_cases.case_dir(case_id)
    prior_art = None
    if payload.prior_art_filename:
        candidate = (case_dir / "search" / "manual_uploads" / _safe_filename(payload.prior_art_filename)).resolve()
        if not candidate.is_file():
            raise HTTPException(404, "先前技术文件不存在")
        prior_art = candidate
    return jobs.submit("CONTINUE_CASE", case_id, lambda: RealCaseWorkflow(settings).continue_case(case_id, prior_art))


@app.get("/api/real-cases/{case_id}/stage/{alias}")
def get_real_stage(case_id: str, alias: str):
    stage = STAGE_ALIASES.get(alias, alias)
    try:
        path = real_cases.case_store.latest_stage_path(case_id, stage)
    except FileNotFoundError as exc:
        raise HTTPException(404, "阶段产物尚未生成") from exc
    return JSONResponse(json.loads(path.read_text(encoding="utf-8")))


@app.get("/api/real-cases/{case_id}/artifacts")
def real_artifacts(case_id: str):
    case_dir = real_cases.case_dir(case_id)
    files = []
    roots = {
        "review": case_dir / "review",
        "case-output": case_dir / "output",
        "final-output": settings.output_root / "real_case" / case_id,
    }
    for group, root in roots.items():
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if path.is_file():
                relative = path.relative_to(root).as_posix()
                files.append({"name": path.name, "group": group, "size": path.stat().st_size, "relative": relative, "download_url": f"/api/real-cases/{case_id}/download/{group}/{relative}"})
    return files


@app.get("/api/real-cases/{case_id}/download/{group}/{relative_path:path}")
def download_real_artifact(case_id: str, group: str, relative_path: str):
    case_dir = real_cases.case_dir(case_id)
    roots = {
        "review": case_dir / "review",
        "case-output": case_dir / "output",
        "final-output": settings.output_root / "real_case" / case_id,
    }
    root = roots.get(group)
    if root is None:
        raise HTTPException(400, "无效产物分组")
    root = root.resolve()
    target = (root / relative_path).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        raise HTTPException(404, "产物不存在")
    return FileResponse(target, filename=target.name)


@app.get("/api/real-cases/{case_id}/logs")
def real_logs(case_id: str):
    path = real_cases.case_dir(case_id) / "logs" / "llm_calls.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


@app.get("/api/resume-status")
def resume_status(case_id: str | None = None):
    return progress.summary(case_id)


@app.post("/api/resume")
def resume(case_id: str | None = None):
    try:
        return progress.resume(case_id).model_dump(mode="json")
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/api/settings")
def safe_settings():
    from patent_agent.llm.model_registry import DEFAULT_MODEL, allowed_models_display
    return {
        "provider": settings.llm_provider,
        "model": settings.default_model,
        "legacy_model": settings.llm_model,
        "mode": settings.patent_llm_mode,
        "api_configured": bool(settings.llm_api_key),
        "cache_enabled": settings.llm_cache_enabled,
        "max_upload_mb": MAX_UPLOAD_BYTES // 1024 // 1024,
        "privacy": "本地单用户；仅显式授权案件可调用外部 LLM。",
        "app_mode": settings.app_mode,
        "default_model": settings.default_model,
        "allowed_models": settings.allowed_models,
        "models_display": allowed_models_display(),
    }


def _standard_case(case_id: str):
    try:
        return store.load(case_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, "案件不存在") from exc


def _real_manifest(case_id: str):
    try:
        return real_cases.load(case_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, "真实案件不存在") from exc


def _understanding(case_id: str) -> TechnicalUnderstandingResult:
    _real_manifest(case_id)
    try:
        path = real_cases.case_store.latest_stage_path(case_id, "p1_technical_understanding")
    except FileNotFoundError as exc:
        raise HTTPException(404, "A1 尚未生成") from exc
    return TechnicalUnderstandingResult.model_validate_json(path.read_text(encoding="utf-8"))


def _safe_filename(filename: str) -> str:
    safe = Path(filename).name
    if not safe or safe != filename or Path(safe).suffix.lower() not in ALLOWED_UPLOADS:
        raise HTTPException(400, "文件名或类型不受支持")
    return safe


def _validate_upload(filename: str, body: bytes) -> None:
    if not body or len(body) > MAX_UPLOAD_BYTES:
        raise HTTPException(400, "文件必须为 1 字节至 50 MB")
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf" and not body.startswith(b"%PDF-"):
        raise HTTPException(400, "PDF 文件签名无效")
    if suffix in {".docx", ".pptx"} and not body.startswith(b"PK"):
        raise HTTPException(400, "Office 文件签名无效")


def _correction(case_id: str, payload: ReviewAction) -> HumanCorrection:
    severity = "NONE" if payload.action == "ACCEPT" else ("REJECT" if payload.action in {"REJECT", "DELETE"} else "MAJOR")
    try:
        return HumanCorrection(
            correction_id=f"HC-WEB-{uuid.uuid4().hex[:12].upper()}",
            case_id=case_id,
            target_type="fact",
            target_id=payload.target_id,
            corrected_value=payload.corrected_value,
            action=payload.action,
            severity=severity,
            reason=payload.reason or "本地 UI 人工审阅",
            confirmed_by_user=payload.confirmed_by_user,
            lock_after_apply=payload.lock_after_apply,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


def _generic_correction(case_id: str, checkpoint: str, payload: ReviewAction) -> HumanCorrection:
    target_type = {"A2": "candidate", "B": "strategy", "C": "claim_feature"}[checkpoint]
    severity = "NONE" if payload.action == "ACCEPT" else ("REJECT" if payload.action in {"REJECT", "DELETE"} else "MAJOR")
    try:
        return HumanCorrection(
            correction_id=f"HC-WEB-{uuid.uuid4().hex[:12].upper()}",
            case_id=case_id,
            target_type=target_type,
            target_id=payload.target_id,
            corrected_value=payload.corrected_value,
            action=payload.action,
            severity=severity,
            reason=payload.reason or "本地 UI 人工审阅",
            confirmed_by_user=True,
            lock_after_apply=payload.lock_after_apply,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


def _auto_chinese_title(manifest) -> str:
    """Generate a Chinese project title from the manifest."""
    title = getattr(manifest, "paper_title", "") or ""
    # If already has Chinese characters, return as-is
    if any("一" <= ch <= "鿿" for ch in title):
        return title
    # Simple heuristics for common English tech terms
    mappings = {
        "Motor Topology": "电机拓扑",
        "Image Generation": "图像生成",
        "Latent Diffusion Model": "潜在扩散模型",
        "Based on": "基于",
        "Method": "方法",
        "A": "一种",
    }
    cn = title
    for eng, chi in mappings.items():
        cn = cn.replace(eng, chi)
    if not any("一" <= ch <= "鿿" for ch in cn):
        cn = f"基于{title}的技术方案"
    return cn


def _apply_review(case_id: str, checkpoint: str, corrections: list[HumanCorrection]):
    _real_manifest(case_id)
    review = ReviewImport(case_id=case_id, checkpoint=checkpoint, corrections=corrections)
    root = real_cases.case_dir(case_id) / "review" / "web_imports"
    path = root / f"{corrections[0].correction_id}.json"
    atomic_write_json(path, review.model_dump(mode="json"))
    try:
        saved = RealCaseWorkflow(settings).import_review(case_id, path)
    except (ValueError, KeyError, PermissionError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"saved_version": saved.name, "checkpoint": HumanReviewManager(real_cases.case_dir(case_id)).machine.records[checkpoint].model_dump(mode="json")}
