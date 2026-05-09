# -*- coding: utf-8 -*-
"""
RuiTalk 启动器
同时启动：卖方系统(8000) + 买方系统(8001)

启动方式：
  - 双击此文件
  - 或 py -3 start_all.py
  - 或 python start_all.py
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
# 统一配置文件路径
_UNIFIED_ENV = SCRIPT_DIR / ".env"


def _load_env():
    """从统一配置文件加载环境变量"""
    if not _UNIFIED_ENV.exists():
        print(f"[WARN] 配置文件未找到: {_UNIFIED_ENV}")
        return False
    from dotenv import load_dotenv
    load_dotenv(_UNIFIED_ENV, override=True)
    print(f"[INFO] 已加载配置: {_UNIFIED_ENV}")
    return True


def _resolve_venv():
    """查找 Python venv（优先卖方终端的 venv）"""
    candidates = [
        SCRIPT_DIR / "卖方终端" / ".venv" / "Scripts" / "python.exe",
        SCRIPT_DIR / ".venv" / "Scripts" / "python.exe",
    ]
    for cand in candidates:
        if cand.is_file():
            return cand
    return None


def _port_free(port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _open_browser(url: str) -> None:
    if sys.platform == "win32":
        try:
            os.startfile(url)
            print(f"[INFO] 已打开浏览器: {url}")
            return
        except OSError:
            pass
    import webbrowser
    try:
        webbrowser.open(url)
        print(f"[INFO] 已打开浏览器: {url}")
    except Exception as e:
        print(f"[WARN] 无法打开浏览器: {e}")
        print(f"       请手动打开: {url}")


def _wait_ready(url: str, timeout: int = 30) -> bool:
    """等待服务就绪"""
    import urllib.request
    start = time.time()
    while time.time() - start < timeout:
        try:
            urllib.request.urlopen(url, timeout=3)
            return True
        except Exception:
            time.sleep(1)
    return False


def main():
    print("=" * 55)
    print("  RuiTalk 智能客服系统")
    print("=" * 55)
    print(f"  根目录: {SCRIPT_DIR}")
    print(f"  配置:   {_UNIFIED_ENV}")
    print("=" * 55)

    _load_env()

    seller_port = int(os.getenv("FASTAPI_PORT", os.getenv("SELLER_PORT", "8000")))
    buyer_port = int(os.getenv("BUYER_PORT", "8001"))

    venv = _resolve_venv()
    if venv:
        python_exec = str(venv)
        print(f"[INFO] 使用 venv: {venv}")
    else:
        python_exec = sys.executable
        print(f"[WARN] 未找到 venv，使用系统 Python: {python_exec}")

    # 端口检查（可通过 .env 中 FASTAPI_PORT / BUYER_PORT 覆盖）
    ports = {}
    for name, port in [("卖方系统", seller_port), ("买方系统", buyer_port)]:
        if not _port_free(port):
            print(
                f"[WARN] 端口 {port} ({name}) 已被占用，跳过该服务启动。\n"
                f"       请关闭占用进程：PowerShell 执行 Get-NetTCPConnection -LocalPort {port}\n"
                f"       或在 .env 中修改 FASTAPI_PORT / BUYER_PORT 后重试。"
            )
            ports[name] = None
        else:
            ports[name] = port

    env = os.environ.copy()

    # 启动买方系统
    if ports["买方系统"]:
        buyer_dir = SCRIPT_DIR / "AI客服买方系统"
        buyer_main = buyer_dir / "backend" / "main_buyer.py"
        cmd = [
            python_exec, "-m", "uvicorn",
            "main_buyer:app",
            "--host", "127.0.0.1",
            "--port", str(buyer_port),
            "--log-level", "info",
        ]
        print(f"\n[INFO] 启动买方系统 ({buyer_port})...")
        subprocess.Popen(cmd, cwd=str(buyer_dir / "backend"), env=env)
        if _wait_ready(f"http://127.0.0.1:{buyer_port}/"):
            print(f"  [OK] 买方系统已就绪 http://127.0.0.1:{buyer_port}/")
        else:
            print(f"  [WARN] 买方系统可能未正常启动")

    # 启动卖方系统
    if ports["卖方系统"]:
        seller_dir = SCRIPT_DIR / "卖方终端"
        seller_main = seller_dir / "backend" / "main.py"
        cmd = [
            python_exec, "-m", "uvicorn",
            "main:app",
            "--host", "127.0.0.1",
            "--port", str(seller_port),
            "--log-level", "info",
        ]
        print(f"\n[INFO] 启动卖方系统 ({seller_port})...")
        subprocess.Popen(cmd, cwd=str(seller_dir / "backend"), env=env)
        if _wait_ready(f"http://127.0.0.1:{seller_port}/"):
            print(f"  [OK] 卖方系统已就绪 http://127.0.0.1:{seller_port}/")
        else:
            print(f"  [WARN] 卖方系统可能未正常启动")

    print("\n" + "=" * 55)
    if ports.get("卖方系统"):
        print(f"  卖方后台: http://127.0.0.1:{seller_port}/")
    if ports.get("买方系统"):
        print(f"  买方前台: http://127.0.0.1:{buyer_port}/")
    print("=" * 55)

    # 自动打开浏览器
    def _delayed_open():
        time.sleep(2)
        if ports.get("卖方系统"):
            _open_browser(f"http://127.0.0.1:{seller_port}/")

    threading.Thread(target=_delayed_open, daemon=True).start()
    print("\n按 Ctrl+C 停止服务。")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n已停止。")


if __name__ == "__main__":
    main()
