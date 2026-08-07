from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from patent_agent.core.atomic import atomic_write_json
from patent_agent.core.models import utc_now


STATE_PATH = PROJECT_ROOT / "runtime" / "patent_agent_server.json"
LOG_PATH = PROJECT_ROOT / "runtime" / "patent_agent_server.log"


def _running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def main() -> int:
    host = "127.0.0.1"
    port = int(os.environ.get("PATENT_AGENT_PORT", "8765"))
    if STATE_PATH.exists():
        old = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        if old.get("status") == "RUNNING" and _running(int(old.get("pid", 0))):
            url = f"http://{host}:{old.get('port', port)}/"
            if not os.environ.get("PATENT_AGENT_NO_BROWSER"):
                webbrowser.open(url)
            print(f"Patent Agent 已在运行：{url}")
            return 0
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    with LOG_PATH.open("a", encoding="utf-8") as log:
        process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.web.main:app", "--host", host, "--port", str(port)],
            cwd=PROJECT_ROOT,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=creation_flags,
        )
    record = {"schema_version": "2.0", "pid": process.pid, "host": host, "port": port, "status": "STARTING", "started_at": utc_now(), "stopped_at": None}
    atomic_write_json(STATE_PATH, record)
    url = f"http://{host}:{port}/"
    for _ in range(40):
        if process.poll() is not None:
            record.update(status="FAILED", stopped_at=utc_now())
            atomic_write_json(STATE_PATH, record)
            print(f"启动失败，请查看：{LOG_PATH}")
            return 1
        try:
            with urllib.request.urlopen(f"{url}api/system/status", timeout=0.5) as response:
                if response.status == 200:
                    record["status"] = "RUNNING"
                    atomic_write_json(STATE_PATH, record)
                    if not os.environ.get("PATENT_AGENT_NO_BROWSER"):
                        webbrowser.open(url)
                    print(f"Patent Agent 已启动：{url}")
                    return 0
        except Exception:
            time.sleep(0.25)
    record.update(status="FAILED", stopped_at=utc_now())
    atomic_write_json(STATE_PATH, record)
    print(f"启动超时，请查看：{LOG_PATH}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
