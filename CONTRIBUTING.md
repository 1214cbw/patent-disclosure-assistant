# 贡献指南

感谢你帮助改进 Patent Disclosure Assistant。我们欢迎缺陷修复、测试、文档和具有通用价值的功能贡献。

## 开始之前

1. 搜索现有 Issues，避免重复工作。
2. 对较大的功能或架构变更，先创建 Issue 说明使用场景、范围和风险。
3. 不要在 Issue、测试夹具或提交中包含真实未公开发明、客户材料、个人信息或 API Key。
4. 参与项目即表示你同意遵守 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)。

## 开发环境

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
python -m pytest -q
```

测试默认不得调用真实模型服务。新增模型集成测试时，必须保持显式 opt-in，并使用环境变量读取凭据。

## 提交要求

- 从 `main` 创建功能分支。
- 保持变更聚焦，并为行为变化补充或更新测试。
- 新增专利领域规则时，说明规则的证据基础、误报风险和人工复核边界。
- 新增演示材料必须是原创、公共领域或许可兼容的内容；优先使用明确标注的合成数据。
- 不得静默降级公式、证据追溯或质量门禁。
- 提交前运行 `python -m pytest -q` 和 `python -m build`。

## Pull Request

PR 描述应包含：问题背景、解决方案、验证结果、隐私/安全影响，以及是否影响输出文件兼容性。维护者可能要求将大型 PR 拆分为更易审阅的提交。

## 贡献许可

除非你明确声明其他安排，你提交并纳入本项目的贡献将按照 Apache License 2.0 发布。请只提交你有权贡献的代码、文档和数据。
