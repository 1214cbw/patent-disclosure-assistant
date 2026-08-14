# Patent Disclosure Assistant / 中文专利技术交底助手

[![CI](https://github.com/1214cbw/patent-disclosure-assistant/actions/workflows/ci.yml/badge.svg)](https://github.com/1214cbw/patent-disclosure-assistant/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-3776AB.svg)](pyproject.toml)

一个本地优先、基于证据追溯的中文专利技术交底辅助工具。它将论文、项目报告和技术资料整理成结构化技术事实，经人工确认后生成带有原生 Word 公式、附图和证据链的技术交底书。

An evidence-grounded, local-first assistant that turns papers and technical reports into reviewable Chinese patent disclosure drafts with traceable evidence and editable Word equations.

```text
技术资料 → 事实与证据提取 → 人工审阅 → 专利语义校验 → DOCX/PDF
```

> [!IMPORTANT]
> 本项目是文档起草与研究辅助软件，不是专利代理机构，不提供法律意见，也不保证可专利性、新颖性、无侵权或最终授权。任何输出都必须由发明人及合格的专利专业人员复核后才能使用。

## 核心能力

- 支持 PDF、DOCX、PPTX、TXT、MD、PNG、JPG 等输入材料
- 提取技术事实、步骤、参数、公式、模块关系与验证证据
- 使用 `InventionCoreGraph`、Patent AST 和 Claims Support Matrix 维持结构化证据链
- 对术语漂移、无证据泛化、实施方式完整性和权利要求支持关系执行质量门禁
- 将 LaTeX 子集转换为可在 Microsoft Word 中继续编辑的原生 OMML 公式
- 生成中文技术交底书、附图、审阅报告和可追溯性清单
- 支持中断恢复、人工检查点和离线合成演示
- 默认仅监听 `127.0.0.1`，真实项目材料不进入 Git 仓库

## 项目状态

当前版本为 `0.1.0` Alpha。自动化测试覆盖证据模型、公式、文档生成、语义质量门禁、Web 工作流及回归案例。Windows 与 Microsoft Word 可提供完整的 DOCX/PDF 实际渲染校验；不具备 Word 的环境仍可运行大部分核心流程和测试。

详细状态见 [PROJECT_STATUS.md](PROJECT_STATUS.md)，架构决策见 [docs/architecture_decisions.md](docs/architecture_decisions.md)。

## 快速开始

### 环境要求

- Python 3.11 或 3.12
- Windows 10/11（推荐；Word COM 校验仅支持 Windows）
- Microsoft Word（仅完整渲染验收需要）
- 一个兼容 OpenAI Chat Completions 请求格式的模型服务（仅在启用外部模型时需要）

### 安装

```powershell
git clone https://github.com/1214cbw/patent-disclosure-assistant.git
cd patent-disclosure-assistant
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

如果只想验证本地流程，不需要填写 API Key，保持 `PATENT_LLM_MODE=disabled` 即可。

### 启动 Web 界面

```powershell
.\start_patent_agent.bat
```

程序默认监听 `http://127.0.0.1:8765`。关闭时运行：

```powershell
.\stop_patent_agent.bat
```

### 运行合成演示与测试

```powershell
python scripts/run_demo.py
python -m pytest -q
```

`demo/` 中的输入和 `output/*demo*/` 中的产物均为合成测试数据，不代表任何真实、未公开的发明或实验结果。

## 外部模型配置

复制 `.env.example` 为 `.env`，再按模型提供商填写：

```dotenv
LLM_PROVIDER=openai-compatible
LLM_BASE_URL=https://your-provider.example/v1
LLM_API_KEY=your-api-key
LLM_MODEL=your-model
PATENT_LLM_MODE=external-approved
APP_MODE=disclosure_only
```

- `PATENT_LLM_MODE=disabled`：不调用外部模型，适合测试和本地演示
- `PATENT_LLM_MODE=external-approved`：只有用户明确授权后才允许外部模型调用
- `APP_MODE=disclosure_only`：默认只生成技术交底书
- `APP_MODE=full_patent`：启用开发中的完整审阅工作流

不同兼容服务对 URL、模型名称和数据保留策略的要求不同，请以你选择的服务商文档为准。

## 隐私与安全边界

- `.env`、真实案例、参考材料、模型调用缓存、日志和临时文件均由 `.gitignore` 排除
- 服务默认仅绑定本机回环地址，不应直接暴露到公网
- 当外部模型功能关闭时，材料解析和文档处理在本机执行
- 当用户授权调用外部模型时，完成请求所需的材料内容会发送给所配置的模型提供商；请先确认其隐私、数据保留和合规政策
- 不要上传包含第三方商业秘密、未公开专利材料或个人敏感信息的 Issue、日志和复现样例
- 发现安全问题请遵循 [SECURITY.md](SECURITY.md)，不要公开披露敏感漏洞

## 仓库结构

```text
app/                    CLI 与本地 Web 入口
patent_agent/           核心领域模型、工作流、校验和文档生成
demo/                   可公开的合成演示材料
templates/              技术交底书模板
tests/                  单元、集成、契约、回归和冒烟测试
docs/                   架构、恢复流程和用户文档
scripts/                演示、审计和运行脚本
```

真实案例目录 `workspace/private_cases/`、`output/real_case/` 和 `reference/` 不属于开源仓库内容。

## 路线图

- 提供更易复现的跨平台核心工作流
- 增加更多经过许可的合成回归案例
- 完善模型提供商适配、成本记录和离线模式
- 建立可插拔的现有技术检索接口
- 改进无 Microsoft Word 环境下的渲染验收
- 增加中英文开发者文档

路线图不代表交付承诺，欢迎通过 Issue 讨论优先级。

## 参与贡献

欢迎提交缺陷报告、文档修正、测试用例和功能改进。开始前请阅读 [CONTRIBUTING.md](CONTRIBUTING.md) 和 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)。第三方组件与架构参考见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## 许可证

本项目采用 [Apache License 2.0](LICENSE) 开源。该许可证不授予项目名称或标识的商标使用权，也不改变你对输入材料和生成内容进行权利审查的责任。
