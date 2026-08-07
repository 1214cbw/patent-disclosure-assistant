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
