// Patent Agent - Simplified Chinese UI for Disclosure-Only Mode
const state = {
  caseId: localStorage.getItem('patentAgentCase') || '',
  currentView: 'home',
  dashboard: null,
  projectDetail: null,
  uploadedFiles: [],
  pollTimer: null,
};

const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

async function api(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) {
    let message = await response.text();
    try { message = JSON.parse(message).detail || message; } catch {}
    throw new Error(message);
  }
  const type = response.headers.get('content-type') || '';
  return type.includes('json') ? response.json() : response.text();
}

function notify(message, error = false) {
  const box = $('notice');
  box.textContent = message;
  box.className = 'notice' + (error ? ' error' : '');
  box.classList.remove('hidden');
  setTimeout(() => box.classList.add('hidden'), 8000);
}

function jsonOptions(method, payload) {
  return { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) };
}

function metric(value, label) {
  return `<div class="metric"><strong>${esc(value)}</strong><span>${esc(label)}</span></div>`;
}

// ── Init ────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  bindNav();
  bindActions();
  loadSystemStatus();
  loadHomePage();
  setInterval(pollJobStatus, 5000);
});

function bindNav() {
  document.querySelectorAll('[data-view]').forEach(btn => {
    btn.addEventListener('click', () => showView(btn.dataset.view));
  });
}

function bindActions() {
  $('#btn-upload').onclick = uploadSourceFiles;
  $('#btn-start-generate').onclick = startGenerate;
  $('#btn-save-project-model')?.addEventListener('click', saveProjectModel);
  $('#btn-batch-approve')?.addEventListener('click', batchApprove);
  $('#btn-view-details')?.addEventListener('click', toggleDetails);
  $('#btn-download')?.addEventListener('click', downloadDisclosure);
  $('#btn-regenerate')?.addEventListener('click', regenerateDisclosure);
  $('#btn-retry')?.addEventListener('click', retryGenerate);
  $('#save-edit')?.addEventListener('click', saveEdit);
}

function showView(name) {
  state.currentView = name;
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  document.querySelectorAll('.nav-btn').forEach(b => b.classList.toggle('active', b.dataset.view === name));
  const view = $(`view-${name}`);
  if (view) view.classList.add('active');

  const loaders = {
    home: loadHomePage,
    projects: loadAllProjects,
    settings: loadSettingsPage,
  };
  if (loaders[name]) loaders[name]();
  if (name === 'new-project') loadAIStatus();
  if (name === 'project-detail' && state.caseId) loadProjectDetail();
}

// ── System ──────────────────────────────────────────────────────
async function loadSystemStatus() {
  try {
    const data = await api('/api/system/status');
    $('#system-dot').classList.add('ok');
    $('#system-text').textContent = `${data.llm.provider} · ${data.llm.model} · ${data.llm.api_configured ? '已连接' : '未配置'}`;
  } catch (err) {
    $('#system-text').textContent = '系统检查失败';
  }
}

async function loadAIStatus() {
  try {
    const data = await api('/api/settings');
    $('#ai-status-card').innerHTML = `
      <p><b>${esc(data.provider)}</b> · ${esc(data.model)} · <span style="color:${data.api_configured?'#087c78':'#a43434'}">${data.api_configured ? '已连接' : '未配置'}</span></p>
      <p class="hint">隐私模式：${esc(data.mode)} · 缓存：${data.cache_enabled ? '启用' : '禁用'}</p>
    `;
  } catch (err) {
    $('#ai-status-card').innerHTML = '<p style="color:#a43434">AI连接检查失败：' + esc(err.message) + '</p>';
  }
}

// ── Home Page ───────────────────────────────────────────────────
async function loadHomePage() {
  try {
    state.dashboard = await api('/api/dashboard');
    const realCases = state.dashboard.real_cases || [];
    $('#home-metrics').innerHTML =
      metric(realCases.length, '项目总数') +
      metric(realCases.filter(c => c.progress?.status === 'completed').length, '已完成') +
      metric(realCases.filter(c => c.progress?.status === 'running').length, '进行中');

    const recentHtml = realCases.length > 0
      ? realCases.map(c => `
          <div class="case-card" data-case="${esc(c.case_id)}">
            <h4>${esc(c.case_id)}</h4>
            <p>${esc(c.paper_title || '未命名项目')}</p>
            <p>状态：${esc(statusLabel(c))} · ${esc(c.current_checkpoint || '')}</p>
          </div>`).join('')
      : '<p class="hint">暂无项目，点击右上角"新建交底书"开始。</p>';

    $('#recent-projects').innerHTML = recentHtml;
    document.querySelectorAll('#recent-projects [data-case]').forEach(card => {
      card.onclick = () => openProject(card.dataset.case);
    });
  } catch (err) {
    notify('加载首页失败：' + err.message, true);
  }
}

function statusLabel(c) {
  if (c.checkpoints?.FINAL === 'APPROVED') return '已完成';
  if (c.current_checkpoint === 'DISCLOSURE_COMPLETE') return '已完成';
  if (c.progress?.status === 'running') return '生成中';
  return '待处理';
}

function openProject(caseId) {
  state.caseId = caseId;
  localStorage.setItem('patentAgentCase', caseId);
  showView('project-detail');
}

// ── New Project / Upload ────────────────────────────────────────
async function createRealCase() {
  const caseId = $('#new-case-id').value.trim() || 'PAPER-' + Date.now().toString(36).toUpperCase();
  const title = $('#new-title').value.trim() || '未命名项目';
  try {
    const model = $('#new-project-model')?.value || 'deepseek-v4-flash';
    await api('/api/real-cases', jsonOptions('POST', {
      case_id: caseId,
      title: title,
      authorized: true,
      llm_mode: 'external-approved',
      external_llm_approved: true,
      synthetic: false,
      llm_model: model,
    }));
    state.caseId = caseId;
    localStorage.setItem('patentAgentCase', caseId);
    notify('项目已创建：' + caseId);
    return caseId;
  } catch (err) {
    if (err.message.includes('已存在')) {
      state.caseId = caseId;
      localStorage.setItem('patentAgentCase', caseId);
      return caseId;
    }
    throw err;
  }
}

async function uploadSourceFiles() {
  const files = $('#source-upload').files;
  if (!files.length) return notify('请先选择文件。', true);
  if (!state.caseId) {
    try { await createRealCase(); } catch (err) { return notify('创建项目失败：' + err.message, true); }
  }
  let uploaded = 0;
  for (const file of files) {
    try {
      const result = await api(
        `/api/real-cases/${encodeURIComponent(state.caseId)}/sources/${encodeURIComponent(file.name)}`,
        { method: 'PUT', headers: { 'Content-Type': 'application/octet-stream' }, body: file }
      );
      state.uploadedFiles.push({ name: result.file, size: result.size });
      uploaded++;
    } catch (err) {
      notify(`上传 ${file.name} 失败：${err.message}`, true);
    }
  }
  if (uploaded > 0) {
    notify(`成功上传 ${uploaded} 个文件。`);
    renderUploadedFiles();
  }
}

function renderUploadedFiles() {
  $('#uploaded-files').innerHTML = state.uploadedFiles.map(f =>
    `<div class="file-item"><span>📄 ${esc(f.name)}</span><span class="hint">${Math.round(f.size/1024)} KB</span></div>`
  ).join('');
}

// ── Generate ────────────────────────────────────────────────────
async function startGenerate() {
  if (!state.caseId && !$('#new-title').value.trim() && !state.uploadedFiles.length) {
    return notify('请先上传至少一份技术材料。', true);
  }
  try {
    if (!state.caseId) await createRealCase();
    // Upload any remaining files
    await uploadSourceFiles();
    if (!state.uploadedFiles.length) {
      // Check if files already exist
      try {
        const status = await api(`/api/real-cases/${encodeURIComponent(state.caseId)}/disclosure-status`);
        if (status.facts_count === 0) return notify('请先上传至少一份技术材料。', true);
      } catch { return notify('请先上传材料。', true); }
    }
    showView('project-detail');
    showGenerationProgress();

    const autoApprove = $('#auto-approve')?.checked ? 'auto_batch' : 'none';
    // Start generation via job
    const job = await api(
      `/api/real-cases/${encodeURIComponent(state.caseId)}/generate-disclosure?use_llm=true&auto_approve=${autoApprove}`,
      { method: 'POST' }
    );
    notify('交底书生成任务已启动：' + job.job_id);
    state.activeJobId = job.job_id;
    pollJobStatus();
  } catch (err) {
    notify('启动生成失败：' + err.message, true);
  }
}

function showGenerationProgress() {
  const stages = [
    { id: 'ingestion', label: '正在读取材料……' },
    { id: 'evidence', label: '正在提取技术内容……' },
    { id: 'technical_understanding', label: '正在理解技术方案……' },
    { id: 'disclosure_writing', label: '正在生成中文技术交底书……' },
    { id: 'figures', label: '正在生成公式和附图……' },
    { id: 'docx', label: '正在生成 Word……' },
    { id: 'validation', label: '正在检查文档……' },
  ];
  $('#generation-progress').classList.remove('hidden');
  $('#stage-list').innerHTML = stages.map((s, i) =>
    `<div class="stage-item" id="stage-${s.id}"><span class="icon">○</span>${s.label}</div>`
  ).join('');
  // V6.5: show the model this run will use
  const selected = $('#project-model-select')?.selectedOptions?.[0]?.textContent ||
    $('#new-project-model')?.selectedOptions?.[0]?.textContent ||
    state.projectDetail?.llm_model_display;
  const model = selected || '系统默认';
  updateProgress(0, `开始生成……（本次使用：${model}）`);
}

function updateProgress(percent, text) {
  $('#progress-fill').style.width = percent + '%';
  $('#progress-text').textContent = text;
}

function updateStage(stageId, done = false) {
  const el = $(`stage-${stageId}`);
  if (!el) return;
  if (done) {
    el.classList.add('done');
    el.querySelector('.icon').textContent = '✅';
  } else {
    el.classList.add('current');
    el.querySelector('.icon').textContent = '⏳';
  }
}

// ── Poll Job Status ─────────────────────────────────────────────
async function pollJobStatus() {
  if (!state.activeJobId && !state.caseId) return;
  if (state.currentView !== 'project-detail') return;
  try {
    if (state.activeJobId) {
      const job = await api(`/api/jobs/${encodeURIComponent(state.activeJobId)}`);
      if (job.status === 'completed') {
        state.activeJobId = null;
        notify('技术交底书生成完成！');
        await loadProjectDetail();
      } else if (job.status === 'failed') {
        state.activeJobId = null;
        showError(job.message || '生成过程中出现错误');
      } else {
        // Update progress
        if (job.progress) {
          updateProgress(job.progress.percent || 50, job.progress.text || '正在生成……');
          if (job.progress.current_stage) updateStage(job.progress.current_stage);
        }
      }
    }
    // Also check disclosure status
    await checkDisclosureStatus();
  } catch (err) {
    // Silently retry
  }
}

async function checkDisclosureStatus() {
  if (!state.caseId) return;
  try {
    const status = await api(`/api/real-cases/${encodeURIComponent(state.caseId)}/disclosure-status`);
    if (status.disclosure_ready) {
      showDisclosurePreview(status);
    } else if (status.status_cn === '待确认' && !state.activeJobId) {
      showAnalysisSummary();
    }
  } catch {}
}

// ── Project Detail ──────────────────────────────────────────────
async function loadProjectDetail() {
  if (!state.caseId) return notify('请先打开一个项目。', true);
  try {
    const status = await api(`/api/real-cases/${encodeURIComponent(state.caseId)}/disclosure-status`);
    state.projectDetail = status;
    $('#project-title').textContent = status.title_cn || status.title || status.case_id;
    $('#project-subtitle').textContent = `项目编号：${status.case_id}`;
    $('#project-status-pill').textContent = status.status_cn;
    $('#project-status-pill').className = 'pill ' + (
      status.status_cn === '已完成' ? 'ok' :
      status.status_cn === '失败' || status.status_cn === '生成失败' ? 'err' : 'warn'
    );

    // V6.5: load project model selection
    loadProjectModel();

    if (status.disclosure_ready) {
      showDisclosurePreview(status);
    } else if (status.batch_approved || status.status_cn === '待确认') {
      showAnalysisSummary();
    } else if (status.status_cn === 'AI分析中' || status.status_cn === '材料处理中') {
      showGenerationProgress();
      if (status.status_cn === 'AI分析中') {
        updateStage('ingestion', true);
        updateStage('evidence', true);
        updateStage('technical_understanding');
        updateProgress(40, 'AI正在分析技术内容……');
      }
    }
  } catch (err) {
    notify('加载项目详情失败：' + err.message, true);
  }
}

// ── Project Model Selection (V6.5) ──────────────────────────────
async function loadProjectModel() {
  const card = $('#project-model-card');
  if (!card) return;
  card.classList.remove('hidden');
  try {
    const [modelInfo, modelsData] = await Promise.all([
      api(`/api/real-cases/${encodeURIComponent(state.caseId)}/model`),
      api('/api/models'),
    ]);
    const select = $('#project-model-select');
    select.innerHTML = (modelsData.models || []).map(m =>
      `<option value="${esc(m.model_id)}" ${m.model_id === modelInfo.llm_model ? 'selected' : ''}>` +
      `${esc(m.display_name)}</option>`
    ).join('') || '<option value="">（无可用模型）</option>';
    const suffix = modelInfo.is_default ? '（系统默认）' : '';
    $('#project-model-current').innerHTML =
      `当前项目使用：<b>${esc(modelInfo.display_name)}${suffix}</b>`;
  } catch (err) {
    $('#project-model-current').textContent = '模型信息加载失败：' + err.message;
  }
}

async function saveProjectModel() {
  const select = $('#project-model-select');
  if (!select || !select.value) return notify('请选择模型。', true);
  try {
    const result = await api(
      `/api/real-cases/${encodeURIComponent(state.caseId)}/model`,
      jsonOptions('PUT', { llm_model: select.value })
    );
    notify(`模型已更新为：${result.llm_model}`);
    loadProjectModel();
  } catch (err) {
    notify('保存模型失败：' + err.message, true);
  }
}

// ── Analysis Summary ────────────────────────────────────────────
async function showAnalysisSummary() {
  try {
    const summary = await api(`/api/real-cases/${encodeURIComponent(state.caseId)}/disclosure-summary`);
    $('#analysis-summary').classList.remove('hidden');
    $('#summary-grid').innerHTML =
      `<div class="summary-item"><strong>${summary.fact_count}</strong><span>核心技术事实</span></div>` +
      `<div class="summary-item"><strong>${summary.step_count}</strong><span>主要技术步骤</span></div>` +
      `<div class="summary-item"><strong>${summary.component_count}</strong><span>技术模块</span></div>` +
      `<div class="summary-item"><strong>${summary.equation_count}</strong><span>关键公式</span></div>` +
      `<div class="summary-item"><strong>${summary.suggested_figures}</strong><span>建议附图</span></div>` +
      `<div class="summary-item"><strong>${summary.uncertainty_count}</strong><span>待确认事项</span></div>`;

    // Load detailed analysis content (collapsed by default)
    try {
      const a1Data = await api(`/api/real-cases/${encodeURIComponent(state.caseId)}/a1`);
      const facts = a1Data.understanding?.facts || [];
      const equations = a1Data.understanding?.equations || [];
      let detailHtml = '<h4>技术事实列表</h4>';
      facts.forEach(f => {
        detailHtml += `<div style="padding:6px 0;border-bottom:1px solid #eee;font-size:13px">
          <b>${esc(f.fact_id)}</b> <span class="pill">${esc(f.category)}</span>
          <p style="margin:4px 0">${esc(f.statement)}</p>
          <span class="hint">证据: ${esc((f.evidence_ids||[]).join(', '))} · 状态: ${esc(f.status)}</span>
        </div>`;
      });
      if (equations.length) {
        detailHtml += '<h4 style="margin-top:14px">公式</h4>';
        equations.forEach(e => {
          detailHtml += `<div style="padding:4px 0;font-size:13px"><b>${esc(e.equation_id)}</b>: <code>${esc(e.original_expression)}</code></div>`;
        });
      }
      $('#detailed-analysis').innerHTML = detailHtml;
    } catch {}
  } catch (err) {
    notify('加载分析摘要失败：' + err.message, true);
  }
}

function toggleDetails() {
  const el = $('#detailed-analysis');
  el.classList.toggle('hidden');
  $('#btn-view-details').textContent = el.classList.contains('hidden') ? '查看详细分析' : '收起详细分析';
}

// ── Batch Approve ───────────────────────────────────────────────
async function batchApprove() {
  if (!confirm('将确认所有AI分析结果并开始生成技术交底书。确认继续？')) return;
  try {
    const result = await api(
      `/api/real-cases/${encodeURIComponent(state.caseId)}/batch-approve`,
      jsonOptions('POST', {})
    );
    notify(result.message || '技术理解已确认。');

    // Now trigger disclosure generation
    const autoApprove = $('#auto-approve')?.checked ? 'batch' : 'none';
    const job = await api(
      `/api/real-cases/${encodeURIComponent(state.caseId)}/generate-disclosure?use_llm=true&auto_approve=batch`,
      { method: 'POST' }
    );
    state.activeJobId = job.job_id;
    $('#analysis-summary').classList.add('hidden');
    showGenerationProgress();
    updateStage('ingestion', true);
    updateStage('evidence', true);
    updateStage('technical_understanding', true);
    updateStage('disclosure_writing');
    updateProgress(50, '正在生成中文技术交底书……');
    pollJobStatus();
  } catch (err) {
    notify('确认失败：' + err.message, true);
  }
}

// ── Disclosure Preview ──────────────────────────────────────────
function showDisclosurePreview(status) {
  $('#generation-progress').classList.add('hidden');
  $('#analysis-summary').classList.add('hidden');
  $('#error-section').classList.add('hidden');

  // Mark all stages done
  ['ingestion','evidence','technical_understanding','disclosure_writing','figures','docx','validation'].forEach(id => {
    const el = $(`stage-${id}`);
    if (el) { el.classList.add('done'); el.querySelector('.icon').textContent = '✅'; }
  });
  updateProgress(100, '生成完成！');

  $('#disclosure-preview-section').classList.remove('hidden');
  $('#project-status-pill').textContent = '已完成';
  $('#project-status-pill').className = 'pill ok';

  // Fetch disclosure content
  loadDisclosureContent();
}

async function loadDisclosureContent() {
  try {
    const data = await api(`/api/real-cases/${encodeURIComponent(state.caseId)}/stage/disclosure`);
    let html = '<div style="max-width:800px;margin:0 auto">';
    if (data.sections) {
      data.sections.forEach(s => {
        html += `<h3>${esc(s.title || '')}</h3>`;
        if (s.paragraphs) {
          s.paragraphs.forEach(p => {
            html += `<p>${esc(p.text || '')}</p>`;
          });
        }
      });
    } else {
      html += '<pre style="white-space:pre-wrap">' + esc(JSON.stringify(data, null, 2)) + '</pre>';
    }
    html += '</div>';
    $('#disclosure-preview-content').innerHTML = html;
  } catch {
    $('#disclosure-preview-content').innerHTML = '<p>技术交底书已生成。点击下方按钮下载或查看。</p>';
  }
}

// ── Download ────────────────────────────────────────────────────
function downloadDisclosure() {
  if (!state.caseId) return notify('请先打开一个项目。', true);
  window.open(`/api/real-cases/${encodeURIComponent(state.caseId)}/download-disclosure`, '_blank');
}

// ── Regenerate ──────────────────────────────────────────────────
async function regenerateDisclosure() {
  if (!confirm('重新生成将覆盖当前技术交底书。确认？')) return;
  try {
    $('#disclosure-preview-section').classList.add('hidden');
    showGenerationProgress();
    const job = await api(
      `/api/real-cases/${encodeURIComponent(state.caseId)}/generate-disclosure?use_llm=true&auto_approve=batch`,
      { method: 'POST' }
    );
    state.activeJobId = job.job_id;
    notify('已开始重新生成。');
    pollJobStatus();
  } catch (err) {
    notify('重新生成失败：' + err.message, true);
  }
}

function retryGenerate() {
  $('#error-section').classList.add('hidden');
  startGenerate();
}

function showError(message) {
  $('#generation-progress').classList.add('hidden');
  $('#error-section').classList.remove('hidden');
  $('#error-message').textContent = message;
  $('#project-status-pill').textContent = '失败';
  $('#project-status-pill').className = 'pill err';
}

// ── Projects List ───────────────────────────────────────────────
async function loadAllProjects() {
  try {
    const data = await api('/api/dashboard');
    const realCases = data.real_cases || [];
    $('#all-projects').innerHTML = realCases.length > 0
      ? realCases.map(c => `
        <div class="case-card" data-case="${esc(c.case_id)}">
          <h4>${esc(c.case_id)}</h4>
          <p>${esc(c.paper_title || '未命名项目')}</p>
          <p>材料：${esc(c.progress?.status || '未知')} · ${esc(c.current_checkpoint || '')}</p>
          <p class="hint">更新：${esc(c.progress?.updated_at || '')}</p>
        </div>`).join('')
      : '<p class="hint">暂无项目</p>';
    document.querySelectorAll('#all-projects [data-case]').forEach(card => {
      card.onclick = () => openProject(card.dataset.case);
    });
  } catch (err) {
    notify('加载项目列表失败：' + err.message, true);
  }
}

// ── Settings ────────────────────────────────────────────────────
async function loadSettingsPage() {
  try {
    const data = await api('/api/settings');
    const models = (data.models_display || []).map(m =>
      `${esc(m.display_name)}${m.recommended ? '（推荐）' : ''}`
    ).join(' / ');
    $('#settings-card').innerHTML = `
      <h3>AI 模型</h3>
      <p>提供商：<b>${esc(data.provider)} · DeepSeek</b></p>
      <p>可选模型：<b>${models}</b></p>
      <p>系统默认：<b>${esc(data.default_model)}</b></p>
      <p>连接：<b style="color:${data.api_configured?'#087c78':'#a43434'}">${data.api_configured ? '正常' : '未配置'}</b></p>
      <p>模式：<b>${esc(data.mode)}</b></p>
      <p>运行模式：<b>${esc(data.app_mode)}</b></p>
      <hr style="margin:18px 0;border-color:#e5eaed">
      <h3>系统信息</h3>
      <p>隐私模式：已授权外部API（仅在用户明确同意时调用）</p>
      <p>缓存：${data.cache_enabled ? '启用' : '禁用'}</p>
      <p>上传上限：${data.max_upload_mb} MB</p>
      <p class="hint">${esc(data.privacy)}</p>
    `;
  } catch (err) {
    notify('加载设置失败：' + err.message, true);
  }
}

// ── Edit Dialog ─────────────────────────────────────────────────
function saveEdit(event) {
  event.preventDefault();
  // Simplified edit - just notify for now
  notify('修改内容功能将在下一版本中完善。');
  $('#edit-dialog').close();
}

// ── Auto-refresh for generation progress ────────────────────────
setInterval(() => {
  if (state.currentView === 'project-detail' && state.activeJobId) {
    pollJobStatus();
  }
}, 3000);
