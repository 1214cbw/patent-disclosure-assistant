"""Run a fully synthetic case through the same API functions used by the local UI."""

from __future__ import annotations

import asyncio
import json
import tempfile
import time
from pathlib import Path

from starlette.requests import Request

import app.web.main as web
from app.web.jobs import JobManager
from patent_agent.core.atomic import atomic_write_json, atomic_write_text
from patent_agent.core.config import Settings
from patent_agent.core.state import CaseStore
from patent_agent.document import PatentDocxValidator
from patent_agent.progress import ProgressManager
from patent_agent.real_case import RealCaseManager


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CASE_ID = "SYN-UI-E2E-001"


def _request(body: bytes) -> Request:
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.request", "body": b"", "more_body": False}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    return Request({"type": "http", "method": "PUT", "path": "/", "headers": []}, receive)


def _configure(temp_root: Path) -> Settings:
    settings = Settings(
        project_root=temp_root,
        workspace_root=temp_root / "workspace",
        template_root=PROJECT_ROOT / "templates",
        output_root=PROJECT_ROOT / "output" / "synthetic_ui_e2e",
    )
    web.settings = settings
    web.store = CaseStore(settings.workspace_root)
    web.real_cases = RealCaseManager(temp_root)
    web.progress = ProgressManager(temp_root)
    web.jobs = JobManager(temp_root)
    return settings


def _wait(job: dict, timeout: float = 180.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        record = web.jobs.get(job["job_id"])
        if record and record["status"] in {"COMPLETED", "FAILED", "INTERRUPTED"}:
            if record["status"] != "COMPLETED":
                raise RuntimeError(f"{record['job_id']} {record['status']}: {record['message']}")
            return record
        time.sleep(0.1)
    raise TimeoutError(job["job_id"])


def _stage(alias: str):
    response = web.get_real_stage(CASE_ID, alias)
    return json.loads(response.body.decode("utf-8"))


def run() -> Path:
    with tempfile.TemporaryDirectory(prefix="patent-agent-ui-e2e-") as temporary:
        settings = _configure(Path(temporary))
        web.create_real_case(web.RealCaseCreate(case_id=CASE_ID, title="合成电机控制专利案件", authorized=True, synthetic=True))
        source = PROJECT_ROOT / "demo" / "motor_control" / "materials" / "technical_description.md"
        asyncio.run(web.upload_real_source(CASE_ID, source.name, _request(source.read_bytes())))

        _wait(web.run_a1(CASE_ID, web.RunRequest(use_llm=False)))
        a1 = web.get_a1(CASE_ID)
        fact_ids = [item["fact_id"] for item in a1["understanding"]["facts"]]
        web.review_a1_bulk(CASE_ID, web.BulkReview(target_ids=fact_ids, action="ACCEPT", confirmed_all=True))
        web.update_publication(CASE_ID, web.PublicationMetadata(paper_title="合成电机控制专利案件", publication_review_status="CONFIRMED"))
        web.approve_checkpoint(CASE_ID, "A1", web.Approval())

        _wait(web.continue_case(CASE_ID, web.ContinueRequest()))
        candidates = _stage("candidates")
        candidate_ids = [item["candidate_id"] for item in candidates]
        web.review_checkpoint_bulk(CASE_ID, "A2", web.BulkReview(target_ids=candidate_ids, confirmed_all=True))
        web.approve_checkpoint(CASE_ID, "A2", web.Approval())

        prior = PROJECT_ROOT / "demo" / "motor_control" / "prior_art_demo.json"
        asyncio.run(web.upload_prior_art(CASE_ID, prior.name, _request(prior.read_bytes())))
        _wait(web.continue_case(CASE_ID, web.ContinueRequest(prior_art_filename=prior.name)))
        status = web.real_case_status(CASE_ID)
        b_ids = status["checkpoints"]["B"]["required_object_ids"]
        web.review_checkpoint_bulk(CASE_ID, "B", web.BulkReview(target_ids=b_ids, confirmed_all=True))
        for question in web.get_a1(CASE_ID)["questions"]:
            if question["priority"] == "P0" and not question["answered"]:
                web.answer_question(CASE_ID, question["question_id"], web.QuestionAnswer(statement="合成 E2E 人工确认：仅用于测试。"))
        web.approve_checkpoint(CASE_ID, "B", web.Approval())

        _wait(web.continue_case(CASE_ID, web.ContinueRequest()))
        status = web.real_case_status(CASE_ID)
        c_ids = status["checkpoints"]["C"]["required_object_ids"]
        web.review_checkpoint_bulk(CASE_ID, "C", web.BulkReview(target_ids=c_ids, confirmed_all=True))
        web.approve_checkpoint(CASE_ID, "C", web.Approval(risk_acknowledged=True))
        _wait(web.continue_case(CASE_ID, web.ContinueRequest()), timeout=300)

        final_status = web.real_case_status(CASE_ID)
        output = settings.output_root / "real_case" / CASE_ID
        docx_files = sorted(output.glob("*.docx"))
        validator = PatentDocxValidator()
        validations = {}
        for path in docx_files:
            if path.name == "技术交底书.docx":
                validations[path.name] = validator.validate(path, export_pdf=False)
            else:
                xml = validator.inspect_xml(path)
                word = validator.inspect_word(path, export_pdf=False)
                validations[path.name] = {
                    "xml": xml,
                    "word": word,
                    "pass": not xml["unresolved_variables"] and word.get("pages", 0) > 0 and "error" not in word,
                }
        report = {
            "schema_version": "2.0",
            "case_id": CASE_ID,
            "synthetic": True,
            "api_surface": "app.web.main",
            "facts": len(fact_ids),
            "candidates": len(candidate_ids),
            "checkpoint_statuses": {key: value["status"] for key, value in final_status["checkpoints"].items()},
            "docx_files": [path.name for path in docx_files],
            "docx_validation": validations,
            "success": bool(docx_files) and all(value["pass"] for value in validations.values()) and final_status["checkpoints"]["FINAL"]["status"] == "APPROVED",
        }
        atomic_write_json(output / "synthetic_ui_e2e_report.json", report)
        atomic_write_text(
            output / "synthetic_ui_e2e_report.md",
            "# Synthetic UI E2E Report\n\n"
            f"- Case: {CASE_ID}\n- Synthetic: YES\n- Facts reviewed: {len(fact_ids)}\n"
            f"- Candidates reviewed: {len(candidate_ids)}\n- DOCX: {', '.join(path.name for path in docx_files)}\n"
            f"- FINAL: {final_status['checkpoints']['FINAL']['status']}\n- Result: {'PASS' if report['success'] else 'FAIL'}\n",
        )
        if not report["success"]:
            raise RuntimeError("SYNTHETIC_UI_E2E_FAILED")
        return output


if __name__ == "__main__":
    print(run())
