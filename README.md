# 专利技术交底书智能生成器

上传论文、项目报告或技术资料，自动整理为中文专利技术交底书。

```text
上传材料 → AI理解技术 → 一键确认 → 下载技术交底书.docx
```

最终得到一份高质量中文《技术交底书》，可直接交给专利代理机构。

> 本系统不提供可专利性、侵权或授权保证。AI 输出必须由发明人和专利专业人员复核。

## 它能做什么

1. **上传材料**：支持 PDF、DOCX、PPTX、TXT、MD、PNG、JPG 格式
2. **AI 理解技术**：自动提取技术事实、步骤、公式、模块关系
3. **一键生成**：整体确认后，自动生成中文技术交底书
4. **导出 Word**：含原生 OMML 公式、中文附图、完整章节

## 一键启动

在项目目录双击 `start_patent_agent.bat`。程序只监听本机 `127.0.0.1:8765`，就绪后自动打开浏览器。

关闭时双击 `stop_patent_agent.bat`。

## 使用步骤

### 第一步：启动
双击 `start_patent_agent.bat`，浏览器自动打开首页。

### 第二步：新建技术交底书
点击"新建技术交底书"，填写项目名称，上传论文或技术资料。

### 第三步：开始生成
点击"开始生成技术交底书"，AI 将自动：
- 解析材料
- 理解技术方案
- 提取关键技术事实
- 生成中文技术交底书
- 生成公式和附图
- 导出 Word 文档

### 第四步：确认并下载
查看生成的技术交底书预览，点击"下载技术交底书"。

如对结果不满意，可以点击"重新生成"或"修改内容"。

## DeepSeek 配置

项目根目录 `.env` 是唯一配置入口，启动时自动读取：

```dotenv
LLM_PROVIDER=openai-compatible
LLM_BASE_URL=https://api.deepseek.com
LLM_API_KEY=your-key
LLM_MODEL=deepseek-v4-pro
PATENT_LLM_MODE=external-approved
APP_MODE=disclosure_only
```

- `APP_MODE=disclosure_only`：默认模式，仅生成技术交底书
- `APP_MODE=full_patent`：（开发者）启用完整专利申请流程

## 中断恢复

生成过程中关闭页面？再次启动后，首页会显示未完成的任务。点击项目可直接继续。

## 隐私与安全

- 服务只绑定 `127.0.0.1`，不对局域网或公网开放
- 数据和 API Key 不会离开本机（LLM 调用使用已配置的 DeepSeek API）
- `.env`、API Key、真实材料均被 Git 排除
- 所有 LLM 调用需用户明确授权

## 用户手册

详细操作说明请阅读 [用户使用手册](docs/用户使用手册.md)。

---

## 高级功能（开发者）

以下能力已保留但默认隐藏，可通过 `APP_MODE=full_patent` 启用：

- A1/A2/B/C 人工审阅流程
- Claims Support Matrix（权利要求支持矩阵）
- Patent AST（专利抽象语法树）
- Prior Art Search（现有技术检索）
- Novelty Matrix（新颖性矩阵）
- Claim Scope Review（权利要求范围审核）
- Traceability（可追溯性链）
- Model Evaluation（模型评估）

### 开发与测试

```powershell
python -m pip install -e .
python -m pytest tests/ -q
python scripts/run_demo.py
```

### 故障排查

- 页面打不开：检查 `runtime/patent_agent_server.log`，运行停止脚本后重新启动
- LLM 不可用：检查 `.env` 中的 API Key 和 Base URL 配置
- Word 校验失败：确认 Microsoft Word 可正常启动

---

*当前版本专注于"论文/技术资料 → 中文技术交底书"这一核心流程。*
