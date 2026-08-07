from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from patent_agent.core.atomic import atomic_write_json
from patent_agent.core.models import utc_now


STATE_PATH = PROJECT_ROOT / "runtime" / "patent_agent_server.json"


def _command_line(pid: int) -> str:
    if os.name != "nt":
        return "app.web.main:app"
    command = f"(Get-CimInstance Win32_Process -Filter 'ProcessId = {pid}').CommandLine"
    result = subprocess.run(["powershell", "-NoProfile", "-Command", command], capture_output=True, text=True, timeout=10)
    return result.stdout.strip()


def main() -> int:
    if not STATE_PATH.exists():
        print("没有已记录的 Patent Agent 服务。")
        return 0
    record = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    pid = int(record.get("pid", 0))
    command_line = _command_line(pid)
    if "uvicorn" not in command_line or "app.web.main:app" not in command_line:
        record.update(status="STALE", stopped_at=utc_now())
        atomic_write_json(STATE_PATH, record)
        print("PID 不再属于 Patent Agent，未终止任何进程。")
        return 0
    os.kill(pid, signal.SIGTERM)
    for _ in range(20):
        try:
            os.kill(pid, 0)
        except OSError:
            break
        time.sleep(0.1)
    record.update(status="STOPPED", stopped_at=utc_now())
    atomic_write_json(STATE_PATH, record)
    print(f"Patent Agent 服务已停止（PID {pid}）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
