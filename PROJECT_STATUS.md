# Patent Agent 项目状态

## Current Version

V2-P1 产品化本地工作台。起始基线为 `11f6bc1cb12e5a236c3c6476f55ecdb0ecd5f853`；当前分支包含配置/Provider、细粒度 Evidence、A1 v2、恢复机制、完整本地 UI 和合成端到端验证。

## Completed Capabilities

- 项目 `.env` 自动加载和统一配置入口。
- OpenAI-compatible / DeepSeek 结构化输出、重试、缓存、截断/空内容检测和 usage 归一化。
- PDF 页/章节/逻辑块 Evidence、References 隔离和 Evidence supersession。
- A1/A2/B/C 人工审查、人工修订、锁定、依赖失效和 Publication Gate。
- Dashboard、案件、上传、A1、Evidence、公式、术语、问题、Publication、A2、Prior Art、B、Claims、Disclosure、Traceability、任务恢复、导出、日志和安全设置页面。
- 本机一键启动/安全停止，只绑定 `127.0.0.1:8765`。
- Patent AST、原生 Word OMML、附图、DOCX、XML 与 Word COM 验证。
- 隔离的 synthetic UI E2E 已通过 A1 → A2 → B → C → FINAL。

## Real Case Status

`REAL-PAPER-001`：

- Paper: `A Motor Topology Image Generation Method Based on Latent Diffusion Model`
- A1 v2: 57 Evidence chunks（47 INVENTION_SOURCE / 10 REFERENCE）
- TechnicalFact: 22 SOURCE_FACT；0 INFERRED；0 UNVERIFIED
- Equation: 1；保留原式/规范化表达/变量/Evidence，需人工复核解析警告
- A1: `UNDER_REVIEW`，0/22 已人工审阅
- A2/B/C/FINAL: `NOT_STARTED`
- Product resume status: `WAITING_FOR_HUMAN_REVIEW`

必须保持：`CHECKPOINT_A1_UNDER_REVIEW`。

## Synthetic Status

`SYN-UI-E2E-001` 已通过 A1、A2、B、C 和 FINAL。技术交底书含 5 个 OMML、2 幅图、4 页；权利要求辅助草案 1 页。Word COM、PDF 导出和逐页视觉 QA 通过。

## LLM Status

- Provider: `openai-compatible`
- Model: `deepseek-v4-pro`
- Privacy Mode: `external-approved`
- API configured: true；密钥不输出、不记录、不提交
- REAL-PAPER-001 的真实结构化 A1 v2 调用已成功；`llm-status` 本身只做安全配置检查，不主动发送论文内容

## Tests

- Unit: 45 passed
- Integration: 8 passed
- Contract: 7 passed
- Regression: 1 passed
- Project subtotal: 61 passed
- Independent Equation PoC: 3 passed
- Total automated tests: 64 passed
- Provider: usage/config/schema tests passed；真实 A1 v2 调用历史成功
- UI: API tests passed；桌面/平板/手机宽度与真实案件页面实机验收通过
- Resume: 2 focused tests passed；Human Gate 保持不跨越
- Word: 2 个 synthetic DOCX 通过 Word COM；技术交底书逐页视觉 QA 通过
- Demo: V1、V2-P0、V2-P1 全部通过
- Security: tracked secret/private/PDF 扫描为 0；服务仅监听 127.0.0.1

## Known Limitations

- Prior Art 当前为人工导入，不是穷尽检索，也不产生法律结论。
- 真实案件的技术事实、公式、公开状态、发明点和 Claims 必须由人审查。
- Equation Engine 支持专利常用 LaTeX 子集，不是完整 TeX 引擎。
- 本地 UI 不提供多人实时协作或复杂富文本红线比较。
- Word COM 验收需要 Windows 安装并可正常启动 Microsoft Word。

## Next Human Action

1. 在网页逐项审核 `REAL-PAPER-001` Checkpoint A1 v2。
2. 人工确认 Publication Metadata：publication status、first public date、DOI、是否在公开前申请专利。
3. 只有以上完成并人工批准 A1 后，才进入 A2。
