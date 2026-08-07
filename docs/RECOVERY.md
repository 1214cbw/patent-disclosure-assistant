# Patent Agent 中断与恢复

本项目的恢复依据是 Git 提交、`runtime/progress/` 和持久化任务记录。恢复机制不会越过 Human Checkpoint。

## 普通用户恢复

1. 双击 `start_patent_agent.bat`。
2. 打开“任务与恢复”。
3. 核对 Current phase、Last completed step、Next step 和 Blocking human checkpoint。
4. 点击“恢复当前任务”。

如果状态为 `WAITING_FOR_HUMAN_REVIEW`，恢复按钮只会返回当前状态；必须先由人完成对应 Checkpoint。

## 命令行恢复

在项目目录运行：

```powershell
git log -n 8 --oneline
python -m app.cli resume-status
python -m app.cli resume
```

指定真实案件时：

```powershell
python -m app.cli resume-status --case-id REAL-PAPER-001
python -m app.cli resume --case-id REAL-PAPER-001
```

`FAILED` 或中断的 `STARTED` 任务会变为 `READY_TO_RESUME`；已完成且有效的 Stage 不重复执行；`STALE` 从失效点重跑；A1/A2/B/C 人工 Gate 不会被跳过。

## 开发恢复检查单

```text
last known good commit: git log -n 1 --oneline
current phase: runtime/progress/latest_checkpoint.json
case phase: runtime/progress/<CASE-ID>.json
current failing test: runtime progress / server log / latest test output
```

然后执行：

```powershell
git status --short
git diff --check
python -m pytest tests/unit tests/integration tests/contract tests/regression -q
```

不要使用 `git reset --hard`，不要删除真实案件目录，不要把 `.env` 或私有资料提交 Git。

## 服务无法启动

1. 双击 `stop_patent_agent.bat`，它只会停止已记录且命令行匹配的服务进程。
2. 查看 `runtime/patent_agent_server.log`。
3. 再次双击启动脚本。
4. 默认端口被占用时，可在启动前设置当前终端的 `PATENT_AGENT_PORT`，但仍只监听 `127.0.0.1`。

## Word 生成中断

关闭遗留的 Word 弹窗或只读提示后重试最终导出。Document Renderer 是确定性的；已生成的结构化 AST 和 Checkpoint 数据仍保留。不要手工编辑 OOXML 来绕过校验。

## 当前恢复锚点

- 产品工程：查看 `runtime/progress/latest_checkpoint.json` 和 `PROJECT_STATUS.md`。
- 真实案件：`REAL-PAPER-001` 必须保持 `CHECKPOINT_A1_UNDER_REVIEW`。
- 下一人工动作：审核 A1 v2，并确认 Publication Metadata。
