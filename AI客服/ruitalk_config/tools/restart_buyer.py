"""重启买方服务（相对本脚本目录解析路径）。"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

try:
    import requests
except ImportError:
    requests = None  # type: ignore

ROOT = Path(__file__).resolve().parent.parent.parent  # 项目根目录
BUYER_ROOT = ROOT / "AI客服买方系统"
BUYER_SCRIPT = BUYER_ROOT / "backend" / "main_buyer.py"
BUYER_CWD = BUYER_SCRIPT.parent

buyer_venv = BUYER_ROOT / ".venv" / "Scripts" / "python.exe"
seller_venv = ROOT / "卖方终端" / ".venv" / "Scripts" / "python.exe"
PYTHON = buyer_venv if buyer_venv.is_file() else (seller_venv if seller_venv.is_file() else Path(sys.executable))


def _kill_port_8001() -> None:
    result = subprocess.run(
        ["netstat", "-ano"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    for line in result.stdout.split("\n"):
        if ":8001" in line and "LISTENING" in line:
            parts = line.split()
            if not parts:
                continue
            pid = parts[-1]
            if pid.isdigit():
                print(f"Force killing PID: {pid} (port 8001)")
                subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True)


print("Stopping existing buyer process...")
_kill_port_8001()
subprocess.run(
    ["taskkill", "/F", "/FI", "WINDOWTITLE eq *main_buyer*"],
    capture_output=True,
    text=True,
)
time.sleep(2)
_kill_port_8001()
time.sleep(1)

if not BUYER_SCRIPT.is_file():
    print(f"[ERROR] 未找到: {BUYER_SCRIPT}")
    raise SystemExit(1)

print(f"Starting buyer with Python: {PYTHON}")
print(f"Script: {BUYER_SCRIPT}")

if sys.platform == "win32":
    CREATE_NO_WINDOW = 0x08000000
    proc = subprocess.Popen(
        [str(PYTHON), str(BUYER_SCRIPT)],
        cwd=str(BUYER_CWD),
        creationflags=CREATE_NO_WINDOW,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
else:
    proc = subprocess.Popen(
        [str(PYTHON), str(BUYER_SCRIPT)],
        cwd=str(BUYER_CWD),
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

print(f"Buyer started with PID: {proc.pid}")
print("Waiting for buyer to be ready...")

if requests:
    for i in range(20):
        time.sleep(2)
        try:
            r = requests.get("http://127.0.0.1:8001/health", timeout=3)
            if r.status_code == 200:
                print(f"[OK] Buyer ready after {(i + 1) * 2}s (PID: {proc.pid})")
                print(f"Health: {r.json()}")
                break
        except Exception as e:
            print(f"  Waiting... {(i + 1) * 2}s ({type(e).__name__})")
    else:
        print("[FAIL] Buyer did not become ready after 40s")

    print("\n=== Final Status ===")
    for port, name in [(8000, "Seller"), (8001, "Buyer")]:
        try:
            r = requests.get(f"http://127.0.0.1:{port}/health", timeout=3)
            print(f"[OK] {name} (port {port}): {r.status_code}")
        except Exception as e:
            print(f"[FAIL] {name} (port {port}): {e}")
else:
    print("[INFO] requests 未安装，跳过健康检查。请手动访问 http://127.0.0.1:8001/health")
