"""在后台启动 Flask 金牌客服（日志 flask_startup.log）。路径相对本脚本所在目录。"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SELLER = ROOT.parent.parent  # 卖方终端目录
PY = SELLER / ".venv" / "Scripts" / "python.exe"
MAIN = SELLER / "backend" / "gold_customer_service.py"
CWD = MAIN.parent
LOG = ROOT / "flask_startup.log"

if not PY.is_file():
    PY = Path(sys.executable)

env = os.environ.copy()
env["PYTHONIOENCODING"] = "utf-8"

if not MAIN.is_file():
    print(f"[ERROR] 未找到: {MAIN}")
    raise SystemExit(1)

print("Starting Flask Gold Customer Service...")
proc = subprocess.Popen(
    [str(PY), "-u", str(MAIN)],
    env=env,
    stdout=open(LOG, "w", encoding="utf-8"),
    stderr=subprocess.STDOUT,
    cwd=str(CWD),
    start_new_session=True,
)
print(f"PID: {proc.pid}")

port = int(os.environ.get("GOLD_CS_PORT", "5001"))
for i in range(30):
    time.sleep(1)
    r = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            f"(Get-NetTCPConnection -LocalPort {port} -ErrorAction SilentlyContinue).Count",
        ],
        capture_output=True,
        text=True,
    )
    if r.stdout.strip() not in ("", "0"):
        print(f"Port {port} is listening!")
        break
    print(f"  waiting... ({i + 1}/30)")
else:
    print(f"WARNING: Port {port} not listening after 30s")

print("Done.")
