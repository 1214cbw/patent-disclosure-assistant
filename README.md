# Patent Agent

Patent Agent 是一个本机运行、证据约束、人工决策的中文专利辅助工作台。它把论文、技术报告和研发材料转换为可审阅的技术理解、发明候选、保护策略、权利要求辅助草案和 Word 文档；所有真实案件都受 A1/A2/B/C 人工 Checkpoint 约束。

> 本系统不提供可专利性、侵权或授权保证。AI 输出必须由发明人和专利专业人员复核。

## 一键启动

在项目目录双击 `start_patent_agent.bat`。程序只监听本机 `127.0.0.1:8765`，就绪后自动打开：

```text
http://127.0.0.1:8765
```

关闭时双击 `stop_patent_agent.bat`。停止脚本只终止由本项目记录的确切服务进程。

## 第一次使用

1. 双击启动脚本，进入“案件总览”。
2. 新建 PRIVATE 真实案件，或选择现有案件。
3. 只上传已明确授权处理的 PDF、DOCX、PPTX、TXT、MD 或图片。
4. 检查“设置与隐私”中的 Provider、Model 和 Privacy Mode。
5. 运行 A1，在“技术理解审阅”逐项接受、编辑或拒绝。
6. 人工确认公开信息后，才按 A2 → B → C 顺序继续。
7. 最终从“产物与导出”下载 DOCX 和审阅报告。

普通用户请阅读 [用户使用手册](docs/用户使用手册.md)；中断或故障恢复请阅读 [RECOVERY](docs/RECOVERY.md)。

## DeepSeek 配置

项目根目录 `.env` 是 CLI、Web 和 Provider 的唯一配置入口，启动时自动读取，无需修改 Windows 全局环境变量。示例：

```dotenv
LLM_PROVIDER=openai-compatible
LLM_BASE_URL=https://example.invalid/v1
LLM_API_KEY=your-key
LLM_MODEL=your-model
PATENT_LLM_MODE=disabled
```

隐私模式：

- `disabled`：不调用 LLM。
- `local`：仅调用本机或内网 OpenAI-compatible 服务。
- `external-approved`：只有案件 Manifest 同时明确批准外部 LLM 时才可发送最小 Evidence 上下文。

仅配置 API Key 不构成外部发送授权。状态检查不会显示密钥：

```powershell
python -m app.cli llm-status
```

## 创建案件与上传资料

Web 是推荐入口。真实案件使用 Git 隔离的 `workspace/private_cases/REAL-*`，只接收用户明确选择的文件，不扫描其他目录。上传端限制文件类型、大小与文件签名，并清理文件名。

CLI 仍可用于自动化：

```powershell
python -m app.cli real-case-create REAL-2026-001 --title "一种……方法" --authorized
python -m app.cli real-case-ingest REAL-2026-001 D:\approved-materials
python -m app.cli real-case-a1 REAL-2026-001
python -m app.cli checkpoint REAL-2026-001
```

详细命令见 [真实案件工作流](docs/real_case_workflow.md)。

## A1 / A2 / B / C 审阅

- A1：核对技术事实、Evidence、公式、术语和不确定内容。
- A2：审核发明候选；学术贡献不会自动变成发明点。
- B：审核保护策略、必要/可选特征、范围和支持缺口。
- C：同时审核 Claim 文本、Feature Graph、支持矩阵和范围风险。

真实案件禁止自动批准。所有必审对象必须脱离 `UNREVIEWED`，P0 问题及公开信息 Gate 必须人工处理，系统才允许进入下一阶段。批量审阅和批准均有显式确认。

## 人工修改与自动保存

人工修改写入结构化审查数据和审计链，而不是只修改 Markdown。人工新增但没有原始证据完整支持的内容不会冒充 `SOURCE_FACT`；锁定对象不会被后续模型覆盖。网页保存后显示成功或错误状态。

## Evidence

Evidence Store 按文档、页、章节、段落/逻辑块建立稳定 ID。事实区分 `SOURCE_FACT`、`HUMAN_CONFIRMED`、`INFERRED`、`AI_SUGGESTION` 和 `UNVERIFIED`。References 被隔离为 `REFERENCE`，不能作为本论文发明事实。

## Claims Support Matrix

支持链为：

```text
Claim → Claim Feature → Disclosure Paragraph → TechnicalFact → Evidence → Source
```

独立权利要求必要特征为 `UNSUPPORTED` 时，系统会阻止继续。Broad、Balanced、Conservative 版本使用同一个有证据的 Feature Pool。

## Word 与 OMML

文档路线为：

```text
Structured Patent AST → deterministic renderer → DOCX → Word COM validation
```

公式由确定性的 Equation Engine 写成 Word 原生 OMML，可继续编辑，不是图片。附图来自结构化 `FigureSpec`。XML 验证检查公式、空运算主体、残余 LaTeX、引用、变量和媒体；Word COM 再检查 OMaths、图片和页数。

## 中断恢复

进度保存在 `runtime/progress/`，任务记录保存在 `runtime/jobs/`。网页“任务与恢复”可查看当前阶段并恢复；CLI 等效命令：

```powershell
python -m app.cli resume-status
python -m app.cli resume
```

恢复不会越过 Human Checkpoint，也不会重复已成功且仍有效的阶段。完整步骤见 [RECOVERY](docs/RECOVERY.md)。

## 隐私、安全与备份

- 服务只绑定 `127.0.0.1`，不对局域网或公网开放。
- `.env`、API Key、真实材料、私有案件、LLM 缓存和真实输出均被 Git 排除。
- Manifest 只记录必要的相对身份/哈希，不公开原始外部绝对路径。
- 不绕过验证码、登录或访问控制；先前技术只处理人工显式导入资料。
- 备份时复制整个 `workspace/private_cases/<CASE-ID>` 到受控加密位置；不要把真实案件加入 Git。

## 开发与测试

```powershell
python -m pip install -e .
python -m pytest tests/unit tests/integration tests/contract tests/regression -q
python scripts/run_demo.py
python scripts/run_v2_demo.py
python scripts/run_v2_p1_demo.py
```

合成 Web E2E：

```powershell
python scripts/run_synthetic_ui_e2e.py
```

真实 LLM smoke test 默认跳过，仅在明确允许时设置 `RUN_LLM_SMOKE_TESTS=1`。当前能力和已知限制见 [PROJECT_STATUS](PROJECT_STATUS.md)。

## 故障排查

- 页面打不开：检查 `runtime/patent_agent_server.log`，然后运行停止脚本再启动。
- LLM 不可用：运行 `python -m app.cli llm-status`，核对 `.env` 与案件隐私授权。
- 无法继续：检查 A1/A2/B/C 未审对象、P0 问题和 Publication Metadata。
- Word 校验失败：确认 Microsoft Word 可启动且没有遗留弹窗，再重试导出。
- 任务中断：进入“任务与恢复”，或按 [RECOVERY](docs/RECOVERY.md) 操作。
