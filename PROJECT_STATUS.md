# Patent Agent 项目状态

## Current Version

V2-P1 → **V2-P2 Disclosure-Only Mode**。产品方向从"完整专利申请系统"收缩为"专利技术交底书智能生成器"。起始基线为 `852151c`。默认模式：`APP_MODE=disclosure_only`。

## Completed Capabilities

### 新增（本轮）
- `APP_MODE=disclosure_only` 默认运行模式
- 全中文 3 步 UI（上传 → AI生成 → 下载Word）
- 中文技术交底书一键生成 pipeline
- Batch Approval（一键审核通过）及审计记录
- ChineseDisclosureValidator（中文化检查）
- 中文 disclosure prompts（4 个文件）
- 简化导航：首页 / 新建交底书 / 我的项目 / 设置
- 简化 README 和中文用户手册

### 保留（已有能力）
- DeepSeek OpenAI-compatible Provider
- Evidence Store（细粒度、References 隔离、Evidence ID、supersession）
- Structured LLM（StructuredLLMService、Schema 解析、缓存）
- Technical Understanding（GroundedTechnicalUnderstandingAgent）
- Human Review（HumanCorrection、HumanReviewManager、Checkpoint 状态机）
- Patent AST → DOCX Renderer
- Word 原生可编辑 OMML 公式
- Figure Renderer（专利风格附图）
- Traceability（可追溯性）
- Resume / Progress（断点恢复）
- 一键启动 / 停止脚本
- Word COM Validation
- 完整测试体系（Unit、Integration、Contract、Regression）
- A1/A2/B/C Pipeline（APP_MODE=full_patent 时可启用）
- Claims Support Matrix、Claim Scope、Novelty Matrix（后台保留）

## 默认用户流程

```text
上传论文/报告
→ 开始生成技术交底书
→ 一键审核通过
→ 下载技术交底书.docx
```

关键改动：
- 用户不再看到 A1/A2/B/C 工程术语
- 不逐条审核 TechnicalFact（默认整体确认，审计记录为 BATCH_APPROVED）
- 不要求 Publication Metadata（选填，不阻断）
- Prior Art 不进入默认流程
- Claims 不进入默认流程
- 只生成一个用户文件：技术交底书.docx
- UI 全中文

## Real Case Status

`REAL-PAPER-001`：
- Paper: `A Motor Topology Image Generation Method Based on Latent Diffusion Model`
- A1 v2: 57 Evidence chunks（47 INVENTION_SOURCE / 10 REFERENCE）
- TechnicalFact: 22 SOURCE_FACT；0 INFERRED；0 UNVERIFIED
- Equation: 1
- 旧状态 `CHECKPOINT_A1_UNDER_REVIEW` 保留不删除
- 新 UI 显示为"AI技术分析已完成"，可一键确认生成交底书

## LLM Status

- Provider: `openai-compatible`
- Model: `deepseek-v4-pro`
- Privacy Mode: `external-approved`
- API configured: true；密钥不输出、不记录、不提交

## Tests

- Unit: 50 passed（含 10 个新 Chinese/Disclosure-only 测试）
- Integration: 8 passed
- Contract: 7 passed
- Regression: 1 passed
- Total automated tests: 65 passed（1 skipped：test_web.py pre-existing FastAPI dep issue）
- 新测试覆盖：Chinese Validator、Disclosure-Only Config、Chinese Ratio、English Block Detection、Academic Tone Detection

## Known Limitations

- Prior Art 当前为人工导入，不是穷尽检索（disclosure_only 模式默认不进入此流程）
- 真实案件的技术事实由用户整体确认（BATCH_APPROVED），非逐条审核
- Equation Engine 支持专利常用 LaTeX 子集
- 本地 UI 不提供多人实时协作
- Word COM 验收需要 Windows 安装 Microsoft Word
- 中文交底书质量依赖 AI 输出，建议人工浏览后交给代理机构
- `APP_MODE=full_patent` 仅开发者通过修改 .env 启用

## Next Actions

1. `REAL-PAPER-001`：在新 UI 中一键确认并生成中文技术交底书
2. 验证最终 Word 文件（OMML、中文、格式）
3. 后续：可选启用 `full_patent` 模式进行完整专利申请流程
