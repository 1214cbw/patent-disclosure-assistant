import asyncio
from pathlib import Path

import pytest
from fastapi import HTTPException
from starlette.requests import Request

import app.web.main as web
from app.web.jobs import JobManager
from patent_agent.core.config import Settings
from patent_agent.core.state import CaseStore
from patent_agent.progress import ProgressManager
from patent_agent.real_case import RealCaseManager
from patent_agent.workflow import RealCaseWorkflow


@pytest.fixture()
def local_web(tmp_path: Path, monkeypatch):
    project = Path(__file__).resolve().parents[2]
    settings = Settings(project_root=tmp_path, workspace_root=tmp_path / "workspace", output_root=tmp_path / "output", template_root=project / "templates")
    monkeypatch.setattr(web, "settings", settings)
    monkeypatch.setattr(web, "store", CaseStore(settings.workspace_root))
    monkeypatch.setattr(web, "real_cases", RealCaseManager(tmp_path))
    monkeypatch.setattr(web, "progress", ProgressManager(tmp_path))
    monkeypatch.setattr(web, "jobs", JobManager(tmp_path))
    return settings


def _request(body: bytes) -> Request:
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.request", "body": b"", "more_body": False}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    return Request({"type": "http", "method": "PUT", "path": "/", "headers": []}, receive)


def test_local_web_home_is_a_real_chinese_spa(local_web):
    response = web.home()
    assert response.status_code == 200
    body = Path(response.path).read_text(encoding="utf-8")
    assert "Patent Agent" in body
    assert "A1 技术理解" in body
    assert "任务与恢复" in body


def test_settings_never_expose_api_key(local_web):
    payload = web.safe_settings()
    assert "api_key" not in payload
    assert set(payload) >= {"provider", "model", "mode", "api_configured", "privacy"}


def test_real_case_create_requires_explicit_authorization(local_web):
    with pytest.raises(HTTPException) as caught:
        web.create_real_case(web.RealCaseCreate(case_id="REAL-WEB-1", authorized=False))
    assert caught.value.status_code == 400
    result = web.create_real_case(web.RealCaseCreate(case_id="REAL-WEB-1", title="Synthetic UI case", authorized=True, synthetic=True))
    assert result["confidential"] is True


def test_upload_validation_rejects_bad_pdf_signature(local_web):
    web.create_real_case(web.RealCaseCreate(case_id="REAL-WEB-2", authorized=True, synthetic=True))
    with pytest.raises(HTTPException, match="PDF 文件签名无效"):
        asyncio.run(web.upload_real_source("REAL-WEB-2", "fake.pdf", _request(b"not a pdf")))


def test_a1_review_api_preserves_human_gate(local_web):
    case_id = "REAL-WEB-A1"
    web.create_real_case(web.RealCaseCreate(case_id=case_id, title="UI test", authorized=True, synthetic=True))
    material = "# 技术方案\n采集电机拓扑图像。\n\n## 编码模块\n将图像编码为潜变量。\n\n## 输出模块\n输出重建图像。"
    asyncio.run(web.upload_real_source(case_id, "material.md", _request(material.encode("utf-8"))))
    RealCaseWorkflow(web.settings).run_a1(case_id)
    a1 = web.get_a1(case_id)
    assert a1["checkpoint"]["status"] == "GENERATED"
    fact_ids = [item["fact_id"] for item in a1["understanding"]["facts"]]
    assert len(fact_ids) > 1
    first = web.review_a1_fact(case_id, web.ReviewAction(target_id=fact_ids[0], action="ACCEPT"))
    assert first["checkpoint"]["reviewed_object_ids"] == [fact_ids[0]]
    with pytest.raises(HTTPException) as caught:
        web.approve_checkpoint(case_id, "A1", web.Approval())
    assert caught.value.status_code == 409
    with pytest.raises(HTTPException) as caught:
        web.review_a1_bulk(case_id, web.BulkReview(target_ids=fact_ids[1:] or fact_ids, confirmed_all=False))
    assert caught.value.status_code == 400


def test_publication_metadata_update_is_explicit(local_web):
    case_id = "REAL-WEB-PUB"
    web.create_real_case(web.RealCaseCreate(case_id=case_id, authorized=True, synthetic=True))
    result = web.update_publication(case_id, web.PublicationMetadata(paper_title="Verified title"))
    assert result["paper_title"] == "Verified title"
