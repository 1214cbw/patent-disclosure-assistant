# Patent Agent

面向中国技术研发场景的、可追溯和可验证的专利辅助工程。V1 重点生成技术交底书和权利要求辅助草案；输出需要发明人和中国专利专业人员复核，不构成可专利性、侵权或授权保证。

## 功能

- 建立独立 `PatentCase` 工作区、阶段版本、回滚和章节级重生成。
- 读取 TXT、MD、DOCX、PDF、PPTX，并为 PNG/JPG 建立图片清单。
- 建立带来源 ID 的 `PatentKnowledge`、证据状态、候选发明点、保护策略和 Claim Tree。
- 通过 A（发明点）、B（保护策略）、C（Claims）三个 Checkpoint 阻止真实案件无人确认地直跑到底。
- 生成结构化 Patent AST、黑白专利流程图、技术交底书和权利要求草案。
- 复用 Word 原生 OMML Equation Engine，公式可在 Microsoft Word 中继续编辑。
- 自动检查 Claims 支持、术语、符号、引用、未解析变量和无来源数值结果。
- ZIP/XML 与 Word COM 双重验收；统计 OMaths、表格、图片和页数。

## 架构

```text
Source Materials -> PatentKnowledge -> Invention Model -> Protection Strategy
                 -> Patent AST -> Document Engine -> DOCX -> Validation
```

Agent 层只读写 Pydantic 模型；Document Renderer 只接受 Patent AST，不调用 LLM，也不让 LLM 操纵 Word XML。

## 安装

使用 Codex 工作区提供的 Python：

```powershell
python -m pip install -e .
python -m pytest tests -q
```

若 Windows 用户级 Scripts 目录尚未加入 `PATH`，可将下文的 `patent-agent` 等价替换为 `python -m app.cli`，无需修改系统配置。

安装后可运行 `uvicorn app.web.main:app --host 127.0.0.1 --port 8000`，浏览器打开 `http://127.0.0.1:8000`。界面支持案件创建/选择、资料上传与索引、阶段结果查看、A/B/C Checkpoint、章节级版本重生成、版本历史和 Word 输出下载。

## 模型配置

复制 `.env.example` 为 `.env`，配置 `LLM_BASE_URL`、`LLM_API_KEY` 和 `LLM_MODEL`。默认 `PATENT_AGENT_ALLOW_EXTERNAL_LLM=false`，避免未公开资料被意外发送到外部模型。API Key 不写日志、不写案件 JSON。

Demo 使用确定性本地 Agent，不调用外部 LLM。OpenAI-compatible Provider 已保留，启用前必须完成保密审查。

## 创建案件与导入资料

```powershell
patent-agent new PAT-2026-001 --title "一种……方法"
patent-agent ingest PAT-2026-001 .\materials
patent-agent analyze PAT-2026-001
patent-agent mine PAT-2026-001
patent-agent approve PAT-2026-001 A
```

每个案件位于 `workspace/cases/<case_id>/`，包含 `source/ working/ figures/ search/ drafts/ review/ output/ logs/ case.json`。

## Patent Pipeline 与 Checkpoint

Pipeline 覆盖初始化、材料读取、技术理解、发明挖掘、查新导入、特征级对比、保护策略、交底书、Claims、附图、审查、DOCX、Word 验收。真实案件默认不能越过 A/B/C；合成 Demo 可使用 `--auto-approve-demo`。

```powershell
patent-agent run PAT-2026-001 .\materials --prior-art .\search.json --output .\output --auto-approve-demo
patent-agent rollback PAT-2026-001 stage_7_disclosure 1
patent-agent regenerate-section PAT-2026-001 "6. 技术方案" "修订后的有来源文本"
```

## Word生成与 OMML公式

默认模板位于 `templates/disclosure/default_cn_disclosure.docx`，可替换。公式路线为：

```text
LaTeX subset -> native OMML -> python-docx -> DOCX -> Microsoft Word COM
```

公式不是 PNG。附图可以是 PNG/SVG，且由结构化 `FigureSpec` 确定性生成。

## 查新

`PatentSearchProvider` 抽象支持 `search()`/`fetch()`。V1 提供人工导入 Provider；CNIPA、Google Patents、Espacenet 和 PQAI 是后续插件。系统不绕过验证码、登录或访问控制，也不会默认把整份未公开交底资料发送给搜索网站。

## Validation

XML 检查包括 OMML 数量、空求和/积分主体、残余 LaTeX、图/式引用、未解析变量和媒体数量。Word COM 检查 `OMaths.Count`、`Tables.Count`、`InlineShapes.Count` 和页数，并在 `finally` 中关闭文档和 Word 实例。

## 隐私与保密

- 项目默认按 PRIVATE 处理；没有远程仓库。
- `.env`、源材料、缓存和 Office 临时文件被 `.gitignore` 排除。
- LLM 调用与 prior-art 搜索分离；搜索仅应使用抽象关键词和技术特征。
- Demo 数据均明确标记为 `SYNTHETIC DEMO DATA`。

## Demo

```powershell
python scripts/run_demo.py
```

输出位于 `output/demo/`：技术交底书、权利要求草案、Patent AST、Knowledge、发明点、Claim Tree、附图清单和验证报告。

## 已知限制

- V1 的本地结构化 Agent 为确定性规则实现；真实资料的高质量语义分析需要经保密批准的 LLM Provider。
- prior-art V1 仅支持人工导入；不作穷尽性检索或法律结论。
- Claims 是辅助草案，尚未覆盖全部中国审查实践和复杂多项从属关系。
- Equation Engine 支持专利常用 LaTeX 子集，不是完整 TeX 引擎；不支持的命令会明确失败。
- Local Web UI 是功能优先的轻量控制台，尚未提供逐字红线比较、多人协作或复杂富文本编辑。

## 后续路线

- P0：接入经过保密审查的结构化 LLM、CNIPA/PQAI Provider、Claims 支持矩阵人工编辑。
- P1：完整本地 Web 章节编辑、版本比较、Checkpoint UI、模板管理。
- P2：说明书/摘要正式分件、更多专利附图类型和司法辖区格式扩展。

## Structured LLM（V2-P0）

核心阶段通过 `LLMProvider.generate_structured()` 返回严格 Pydantic Schema。V2 内置 OpenAI-compatible Provider、离线 `MockLLMProvider`、有限重试、案例级缓存、Prompt 版本和不保存完整敏感 Prompt 的调用审计。Provider 和模型由 `.env` 中的 `LLM_PROVIDER`、`LLM_BASE_URL`、`LLM_MODEL`、`LLM_TIMEOUT`、`LLM_MAX_RETRIES` 配置，代码不写死模型名。

```powershell
python -m app.cli llm-status
python -m app.cli analyze PAT-2026-001 --llm
```

默认 `PATENT_LLM_MODE=disabled`。只有经过保密审批后才切换为 `external-approved`；本机或内网端点使用 `local`。本地模式允许无 API Key，外部模式要求凭据。CLI 和报告只显示是否配置，不显示 Key。

## Evidence Grounding

V2 在每个案件的 `evidence/` 中保存稳定的 `EvidenceChunk`、索引和来源清单。Evidence ID 由来源身份、逻辑位置及内容哈希构成；相同材料重复 ingest 不会随机改变 ID。`TechnicalFact` 和 `GroundedStatement` 统一区分 `SOURCE_FACT`、`INFERRED`、`AI_SUGGESTION`、`UNVERIFIED`，其中 SOURCE_FACT 无 Evidence 会直接验证失败。

系统使用无需 embedding API 的 BM25 类检索和章节加权，只向 LLM 发送当前任务需要的 Evidence。上传资料被标记为不可信数据，资料中的 “Ignore previous instructions” 等文字不会成为系统指令。

```powershell
python -m app.cli evidence PAT-2026-001 --query "状态融合"
```

## Claims Support Matrix

Claims V2 遵循 `Protection Strategy -> Claim Feature Set -> Claim Tree -> Claim Text`，不从完整权利要求反推特征。矩阵建立以下链路：

```text
Claim -> Claim Feature -> Disclosure Paragraph -> TechnicalFact -> Evidence -> Original Source
```

独立权利要求中的 mandatory feature 为 `UNSUPPORTED` 时 Gate 4 硬失败。Broad/Conservative Draft 使用相同的支持特征池。

```powershell
python -m app.cli claims-support PAT-V2-DEMO-001
```

## Real Case Dry Run

真实案件首次运行必须显式指定材料目录，默认仅执行 ingest、Evidence、Technical Understanding、Invention Mining 和 Checkpoint A preview；不会生成保护策略、Claims 或 Word。

```powershell
python -m app.cli dry-run-real REAL-CASE-001 D:\explicitly-approved-materials --output D:\safe-review-output
```

经过明确外部/本地模型授权后可增加 `--llm`；否则运行确定性 grounded fallback。合成 E2E 使用：

```powershell
python scripts/run_v2_demo.py
```

## Confidentiality

- `disabled`：默认，不调用 LLM。
- `external-approved`：用户已明确批准发送最小 Evidence 上下文到配置的外部 Provider。
- `local`：调用本机/内网 OpenAI-compatible API。

`.env`、`.env.*`、`private_cases/` 和运行时案件目录不提交 Git。真实资料不会复制到 fixture、README 或错误日志；真实模型 Smoke Test 只有设置 `RUN_LLM_SMOKE_TESTS=1` 才运行。

## LLM Limitations

LLM 是推理引擎，不是事实来源、正式查新结论或法律判断。关键词语义验证是轻量第一层，不等于专利专业人员的技术等同/充分公开判断。所有 AI 输出仍需发明人和专利专业人员复核。

## Real Case Workflow（V2-P1）

V2-P1 的真实案件保存在 Git 隔离的 `workspace/private_cases/REAL-*`。系统不会扫描桌面或论文目录；必须依次显式执行 `real-case-create --authorized`、`real-case-ingest CASE PATH` 和 `real-case-a1 CASE`。真实案件首次运行固定停在 A1，不生成发明点、Claims 或 Word。

```powershell
python -m app.cli real-case-create REAL-2026-001 --title "一种……方法" --authorized
python -m app.cli real-case-ingest REAL-2026-001 D:\approved-materials
python -m app.cli real-case-a1 REAL-2026-001
python -m app.cli checkpoint REAL-2026-001
```

完整 A1→A2→B→C 操作见 [docs/real_case_workflow.md](docs/real_case_workflow.md)。

## Human Correction Loop

人工审查使用严格 Pydantic JSON，而不是只改 Markdown：

```text
AI/规则输出 -> HumanCorrection -> Revision Graph -> Human Lock
            -> Dependency STALE -> 最小范围重生成
```

人工编辑不会自动冒充 `SOURCE_FACT`；新增而未被原 Evidence 完整支持的内容标记为 `HUMAN_CONFIRMED`。人工锁定对象不会被后续模型覆盖，除非显式 `UNLOCK`。审计日志只保存目标、动作、时间和内容哈希。

## Human-confirmed Facts

事实状态包括 `SOURCE_FACT`、`HUMAN_CONFIRMED`、`INFERRED`、`AI_SUGGESTION` 和 `UNVERIFIED`。发明人后续补充仍单独保存为 `INVENTOR_ASSERTION`。每次重要修订保留 `previous_version_id`、原因、确认ID和时间戳。

## Checkpoints A1 / A2 / B / C

- A1：逐项审核技术理解；未完成不能进入发明挖掘。
- A2：批准、拒绝、编辑、合并、拆分或重排候选发明点。
- B：审核保护策略、必要特征、术语、支持缺口，并选择 Broad/Balanced/Conservative。
- C：同时审核 Claim 长句和 Feature Graph；Feature 修改后自动重写 Claim、支持矩阵和范围评估。

所有对象必须脱离 `UNREVIEWED` 才可批准。P0 发明人问题会阻断 B/C，真实案件禁止自动批准。

## Claim Scope Review

范围审查组合 Feature Count、Protection Strategy、Novelty Matrix、Support Matrix、Parameter Usage 和 Terminology Registry，确定性检测 `PARAMETER_LOCKING_RISK`、`IMPLEMENTATION_NARROWING`、`ENABLEMENT_RISK`、`SUPPORT_SCOPE_RISK` 与 `NOVELTY_RISK`。三种宽窄版本由同一个 Feature Pool 渲染，不允许为“写宽”添加不存在的特征。

```powershell
python -m app.cli claim-scope REAL-2026-001
```

## Model Evaluation

`evaluation_runs/RUN-*` 固定保存 Evidence 哈希、Prompt/Schema版本、Provider、Model、temperature 和起始检查点。报告包含 Fact 直接接受率、Minor/Major/Reject/Omission、候选接受代理指标、Claim Feature 接受率、不支持特征、范围缩窄、调用次数、Tokens和成本。

```powershell
python -m app.cli evaluation-report REAL-2026-001 --run-id RUN-001
```

## Confidential Processing and LLM Approval

真实案件 LLM 权限由全局 `PATENT_LLM_MODE` 与 `real_case_manifest.json` 的案件策略共同决定，取更严格结果。外部模式还必须设置 `external_llm_approved=true`；仅存在 API Key 不构成授权。本地模型要求全局和案件均为 `local`。真实材料、缓存、评审记录、`output/real_case/` 和 API Key 均不提交 Git。

架构细节见 [docs/architecture/v2_p1.md](docs/architecture/v2_p1.md)。
