from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel

from patent_agent.core.config import Settings
from patent_agent.core.models import DisclosureDraft
from patent_agent.core.state import CaseStore
from patent_agent.ingestion import SourceManager


app = FastAPI(title="Patent Agent Local UI API", version="0.1.0")
settings = Settings.load()
store = CaseStore(settings.workspace_root)
ALLOWED_UPLOADS = {".txt", ".md", ".docx", ".pdf", ".pptx", ".png", ".jpg", ".jpeg"}


class CaseCreate(BaseModel):
    case_id: str
    title: str = ""


class CheckpointDecision(BaseModel):
    decision: str = "approve"
    note: str = ""


class SectionRevision(BaseModel):
    section: str
    text: str


@app.get("/", response_class=HTMLResponse)
def home():
    return HTMLResponse(_HOME)


@app.get("/api/cases")
def list_cases():
    return [store.load(path.name).model_dump() for path in sorted(store.root.iterdir()) if (path / "case.json").exists()]


@app.post("/api/cases")
def create_case(payload: CaseCreate):
    if (store.case_dir(payload.case_id) / "case.json").exists():
        raise HTTPException(409, "case exists")
    return store.create(payload.case_id, payload.title).model_dump()


@app.get("/api/cases/{case_id}")
def get_case(case_id: str):
    try:
        return store.load(case_id).model_dump()
    except FileNotFoundError as exc:
        raise HTTPException(404, "case not found") from exc


@app.put("/api/cases/{case_id}/sources/{filename}")
async def upload_source(case_id: str, filename: str, request: Request):
    _case(case_id)
    safe_name = Path(filename).name
    if not safe_name or Path(safe_name).suffix.lower() not in ALLOWED_UPLOADS:
        raise HTTPException(400, "unsupported source type")
    body = await request.body()
    if not body or len(body) > 50 * 1024 * 1024:
        raise HTTPException(400, "file must be between 1 byte and 50 MB")
    source_dir = store.case_dir(case_id) / "source"
    target = source_dir / safe_name
    target.write_bytes(body)
    records, chunks, images = SourceManager(store).ingest(case_id, [source_dir])
    return {"file": safe_name, "files": len(records), "chunks": len(chunks), "images": len(images)}


@app.post("/api/cases/{case_id}/checkpoints/{name}")
def decide_checkpoint(case_id: str, name: str, payload: CheckpointDecision):
    _case(case_id)
    if name not in {"A", "B", "C"}:
        raise HTTPException(400, "checkpoint must be A, B, or C")
    if payload.decision not in {"approve", "edit", "regenerate", "back"}:
        raise HTTPException(400, "invalid checkpoint decision")
    store.approve_checkpoint(case_id, name, payload.decision, payload.note)
    return store.load(case_id).checkpoints[name]


@app.post("/api/cases/{case_id}/regenerate-section")
def regenerate_section(case_id: str, payload: SectionRevision):
    _case(case_id)
    try:
        draft = DisclosureDraft.model_validate_json(store.latest_stage_path(case_id, "stage_7_disclosure").read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise HTTPException(409, "disclosure draft does not exist") from exc
    if payload.section not in draft.sections:
        raise HTTPException(400, "unknown section")
    draft.sections[payload.section] = [payload.text]
    path = store.save_stage(case_id, "stage_7_disclosure", draft, human_modified=True)
    return {"saved": str(path), "section": payload.section}


@app.get("/api/cases/{case_id}/stages/{stage}")
def latest_stage(case_id: str, stage: str):
    _case(case_id)
    try:
        payload = json.loads(store.latest_stage_path(case_id, stage).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise HTTPException(404, "stage artifact not found") from exc
    return JSONResponse(payload)


@app.get("/api/cases/{case_id}/artifacts")
def list_artifacts(case_id: str):
    case = _case(case_id)
    root = store.case_dir(case_id)
    output_files = [
        {"name": path.name, "path": str(path.relative_to(root)), "size": path.stat().st_size}
        for path in sorted((root / "output").glob("*")) if path.is_file()
    ]
    stages = {}
    for version in case.versions:
        stages.setdefault(version.stage, []).append({"version": version.version, "created_at": version.created_at})
    return {"case": case.model_dump(), "stages": stages, "output_files": output_files}


@app.get("/api/llm/status")
def llm_status():
    from patent_agent.llm import OpenAICompatibleProvider
    result = OpenAICompatibleProvider(settings).health_check()
    result["api_configured"] = bool(settings.llm_api_key)
    return result


@app.get("/api/cases/{case_id}/evidence")
def list_evidence(case_id: str, query: str = "", top_k: int = 20):
    from patent_agent.evidence import EvidenceStore
    _case(case_id)
    evidence_store = EvidenceStore(store.case_dir(case_id) / "evidence")
    items = evidence_store.search(query, top_k) if query else evidence_store.all()[:top_k]
    return [item.model_dump() for item in items]


@app.get("/api/cases/{case_id}/evidence/{evidence_id}")
def get_evidence(case_id: str, evidence_id: str):
    from patent_agent.evidence import EvidenceStore
    _case(case_id)
    try:
        return EvidenceStore(store.case_dir(case_id) / "evidence").get(evidence_id).model_dump()
    except KeyError as exc:
        raise HTTPException(404, "evidence not found") from exc


@app.get("/api/cases/{case_id}/claims-support")
def get_claims_support(case_id: str):
    _case(case_id)
    try:
        return JSONResponse(json.loads(store.latest_stage_path(case_id, "v2_claims_support_matrix").read_text(encoding="utf-8")))
    except FileNotFoundError as exc:
        raise HTTPException(404, "claims support matrix not found") from exc


@app.get("/api/cases/{case_id}/download/{filename}")
def download_output(case_id: str, filename: str):
    _case(case_id)
    output_root = (store.case_dir(case_id) / "output").resolve()
    target = (output_root / Path(filename).name).resolve()
    if not target.is_relative_to(output_root) or not target.is_file():
        raise HTTPException(404, "output not found")
    return FileResponse(target, filename=target.name)


def _case(case_id: str):
    try:
        return store.load(case_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, "case not found") from exc


_HOME = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Patent Agent</title>
<style>
:root{font-family:"Microsoft YaHei",system-ui,sans-serif;color:#17202a;background:#eef2f5}*{box-sizing:border-box}
body{margin:0}header{padding:24px 32px;background:#132b3f;color:white}header h1{margin:0 0 6px;font-size:25px}header p{margin:0;color:#bfd0dc}
main{display:grid;grid-template-columns:300px 1fr;gap:18px;padding:18px;max-width:1400px;margin:auto}.card{background:white;border:1px solid #d8e0e6;border-radius:10px;padding:18px;box-shadow:0 2px 8px #0b243510}
h2{font-size:18px;margin:0 0 14px}label{display:block;font-size:13px;color:#4e6473;margin:9px 0 5px}input,textarea,select,button{font:inherit}input,textarea,select{width:100%;padding:9px;border:1px solid #b9c6cf;border-radius:6px}textarea{min-height:92px}
button{border:0;border-radius:6px;padding:9px 13px;background:#176b87;color:white;cursor:pointer}button.secondary{background:#526976}.case{padding:10px;border:1px solid #dae2e7;border-radius:7px;margin:8px 0;cursor:pointer}.case:hover,.case.active{border-color:#176b87;background:#edf8fb}
.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}.wide{grid-column:1/-1}.muted{color:#667b88;font-size:13px}.badge{display:inline-block;padding:3px 8px;border-radius:99px;background:#e5f2f5;color:#15566c;margin:2px;font-size:12px}
pre{white-space:pre-wrap;max-height:420px;overflow:auto;background:#f6f8fa;padding:12px;border-radius:6px;border:1px solid #e0e5e8}.row{display:flex;gap:8px;flex-wrap:wrap}.row>*{flex:1}.outputs a{display:block;margin:7px 0;color:#176b87}@media(max-width:850px){main{grid-template-columns:1fr}.grid{grid-template-columns:1fr}}
</style></head><body>
<header><h1>Patent Agent</h1><p>案件、证据、Checkpoint、版本和 Word 输出的本地控制台</p></header>
<main><aside class="card"><h2>案件</h2><div id="cases"></div><hr><label>案件编号</label><input id="new-id" placeholder="PAT-2026-001"><label>发明名称</label><input id="new-title"><p><button onclick="createCase()">新建案件</button></p></aside>
<section class="grid">
<div class="card wide"><h2 id="case-title">请选择案件</h2><div id="case-meta" class="muted">不会自动向外部服务发送资料。</div></div>
<div class="card"><h2>资料上传</h2><input id="source" type="file"><p><button onclick="upload()">导入并建立索引</button></p><div id="upload-status" class="muted"></div></div>
<div class="card"><h2>人工 Checkpoint</h2><div class="row"><button onclick="approve('A')">批准 A 发明点</button><button onclick="approve('B')">批准 B 保护策略</button><button onclick="approve('C')">批准 C Claims</button></div><p id="checkpoints" class="muted"></p></div>
<div class="card"><h2>阶段结果</h2><select id="stage"><option>v2_grounded_understanding</option><option>v2_invention_candidates</option><option>v2_protection_strategy</option><option>v2_grounded_disclosure</option><option>v2_grounded_claims</option><option>v2_claims_support_matrix</option><option>stage_2_technical_understanding</option><option>stage_3_invention_mining</option><option>stage_5_novelty</option><option>stage_6_protection_strategy</option><option>stage_7_disclosure</option><option>stage_8_claims</option></select><p><button onclick="loadStage()">查看结构化结果</button></p></div>
<div class="card"><h2>LLM 与 Evidence</h2><p id="llm-status" class="muted">加载中</p><input id="evidence-query" placeholder="检索技术事实或 EV-ID"><p class="row"><button onclick="loadEvidence()">查看 Evidence</button><button class="secondary" onclick="loadClaimsSupport()">Claims Support</button></p></div>
<div class="card"><h2>交底书章节重生成</h2><input id="section" placeholder="6. 技术方案"><label>有来源的修订文本</label><textarea id="section-text"></textarea><p><button onclick="revise()">仅保存该章节新版本</button></p></div>
<div class="card wide"><h2>版本历史与 Word 输出</h2><div id="history"></div><div id="outputs" class="outputs"></div></div>
<div class="card wide"><h2>内容查看</h2><pre id="viewer">选择一个阶段后查看。</pre></div>
</section></main>
<script>
let selected=""; const esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
async function api(url,opt={}){const r=await fetch(url,opt);if(!r.ok)throw new Error(await r.text());return r.json()}
async function refresh(){const items=await api('/api/cases');document.getElementById('cases').innerHTML=items.map(x=>`<div class="case ${x.case_id===selected?'active':''}" onclick="selectCase('${esc(x.case_id)}')"><b>${esc(x.case_id)}</b><br><span class="muted">${esc(x.title||'未命名')} · ${esc(x.status)}</span></div>`).join('')||'<span class="muted">暂无案件</span>'}
async function createCase(){const case_id=document.getElementById('new-id').value.trim(),title=document.getElementById('new-title').value.trim();if(!case_id)return;await api('/api/cases',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({case_id,title})});selected=case_id;await refresh();await loadCase()}
async function selectCase(id){selected=id;await refresh();await loadCase()}
async function loadCase(){if(!selected)return;const a=await api(`/api/cases/${encodeURIComponent(selected)}/artifacts`),c=a.case;document.getElementById('case-title').textContent=`${c.case_id} · ${c.title||'未命名'}`;document.getElementById('case-meta').innerHTML=`状态 <span class="badge">${esc(c.status)}</span> 当前阶段 <span class="badge">${esc(c.current_stage)}</span> 来源文件 ${c.source_files.length}`;document.getElementById('checkpoints').textContent=JSON.stringify(c.checkpoints);document.getElementById('history').innerHTML=Object.entries(a.stages).map(([k,v])=>`<p><b>${esc(k)}</b> ${v.map(x=>`<span class="badge">v${String(x.version).padStart(3,'0')}</span>`).join('')}</p>`).join('')||'<span class="muted">尚无阶段版本</span>';document.getElementById('outputs').innerHTML=a.output_files.map(x=>`<a href="/api/cases/${encodeURIComponent(selected)}/download/${encodeURIComponent(x.name)}">导出 ${esc(x.name)} (${Math.round(x.size/1024)} KB)</a>`).join('')}
async function upload(){if(!selected)return alert('请先选择案件');const f=document.getElementById('source').files[0];if(!f)return;const x=await api(`/api/cases/${encodeURIComponent(selected)}/sources/${encodeURIComponent(f.name)}`,{method:'PUT',headers:{'Content-Type':'application/octet-stream'},body:f});document.getElementById('upload-status').textContent=`已导入：${x.files} 个文件，${x.chunks} 个文本块，${x.images} 张图片`;await loadCase()}
async function approve(name){if(!selected)return;await api(`/api/cases/${encodeURIComponent(selected)}/checkpoints/${name}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({decision:'approve',note:'approved in local UI'})});await loadCase()}
async function loadStage(){if(!selected)return;try{const x=await api(`/api/cases/${encodeURIComponent(selected)}/stages/${document.getElementById('stage').value}`);document.getElementById('viewer').textContent=JSON.stringify(x,null,2)}catch(e){document.getElementById('viewer').textContent=e.message}}
async function revise(){if(!selected)return;await api(`/api/cases/${encodeURIComponent(selected)}/regenerate-section`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({section:document.getElementById('section').value,text:document.getElementById('section-text').value})});await loadCase()}
async function loadEvidence(){if(!selected)return;const q=document.getElementById('evidence-query').value.trim();try{const x=q.startsWith('EV-')?await api(`/api/cases/${encodeURIComponent(selected)}/evidence/${encodeURIComponent(q)}`):await api(`/api/cases/${encodeURIComponent(selected)}/evidence?query=${encodeURIComponent(q)}`);document.getElementById('viewer').textContent=JSON.stringify(x,null,2)}catch(e){document.getElementById('viewer').textContent=e.message}}
async function loadClaimsSupport(){if(!selected)return;const x=await api(`/api/cases/${encodeURIComponent(selected)}/claims-support`);document.getElementById('viewer').textContent=JSON.stringify(x,null,2)}
api('/api/llm/status').then(x=>document.getElementById('llm-status').textContent=`${x.mode||'disabled'} · ${x.provider} · ${x.model||'未配置'} · API ${x.api_configured?'configured':'not configured'}`);refresh();
</script></body></html>"""
