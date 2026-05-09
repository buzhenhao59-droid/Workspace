#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
买方AI客服系统 - 启动入口（请双击 启动买方系统.bat）

- 不再依赖 PowerShell 脚本，避免 # 注释被误解析。
- 若 8001 被占用，会自动尝试 8002～8010。
- 启动后约 2 秒自动用系统浏览器打开首页。
- 自动加载统一配置，确保买方和卖方共用同一配置。

环境变量:
  BUYER_PORT        优先使用的端口（默认 8001）；被占用时会自动换端口
  BUYER_NO_BROWSER=1  不自动打开浏览器
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
# 买方系统根目录
BUYER_ROOT = SCRIPT_DIR
# 统一配置文件位置
_UNIFIED_ENV = (BUYER_ROOT.parent / ".env").resolve()


def _load_unified_env() -> bool:
    """在启动前加载统一配置到当前进程环境变量，子进程自动继承"""
    if not _UNIFIED_ENV.exists():
        print(f"[WARN] 统一配置文件未找到: {_UNIFIED_ENV}")
        print(f"       请确认 {_UNIFIED_ENV} 存在。")
        return False
    from dotenv import load_dotenv
    load_dotenv(_UNIFIED_ENV, override=True)
    print(f"[INFO] 已加载统一配置: {_UNIFIED_ENV}")
    return True


def _resolve_venv_python() -> Path | None:
    # 优先从统一项目结构查找
    candidates = [
        SCRIPT_DIR / ".venv" / "Scripts" / "python.exe",
        SCRIPT_DIR.parent / "卖方终端" / ".venv" / "Scripts" / "python.exe",
    ]
    for cand in candidates:
        if cand.is_file():
            return cand
    return None


def _port_free(host: str, port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _pick_port() -> int | None:
    preferred = int(os.environ.get("BUYER_PORT", "8001"))
    order = [preferred] + [p for p in range(8001, 8011) if p != preferred]
    seen: set[int] = set()
    for p in order:
        if p in seen:
            continue
        seen.add(p)
        if _port_free("127.0.0.1", p):
            if p != preferred:
                print(
                    "[INFO] Port %s is busy, using %s instead."
                    % (preferred, p)
                )
            return p
    return None


def _open_browser(url: str) -> None:
    if sys.platform == "win32":
        try:
            os.startfile(url)
            print("[INFO] Opened browser (startfile):", url)
            return
        except OSError:
            pass
    import webbrowser

    try:
        webbrowser.open(url)
        print("[INFO] Opened browser:", url)
    except Exception as e:
        print("[WARN] Could not open browser:", e)
        print("       Open manually:", url)


def main():
    print("=" * 50)
    print("  Buyer AI service")
    print("=" * 50)

    # 加载统一配置（确保买方和卖方共用同一 .env）
    _load_unified_env()

    port = _pick_port()
    if port is None:
        print("\n[错误] 端口 8001～8010 均被占用，无法启动。")
        print("  请关闭多余的买方服务窗口，或结束占用进程。")
        print("  查看: netstat -ano | findstr :8001")
        input("\n按回车键退出...")
        raise SystemExit(1)

    buyer_url = "http://127.0.0.1:%s/" % port
    print("  URL:", buyer_url)
    print("=" * 50)

    venv_py = _resolve_venv_python()
    if venv_py is not None:
        python_exec = str(venv_py)
        print("[INFO] Using seller venv:", python_exec)
    else:
        python_exec = sys.executable
        print("[WARN] Seller venv not found, using:", python_exec)
        print("       If 'No module named uvicorn': install uvicorn or fix seller path.")

    cmd = [
        python_exec,
        "-m",
        "uvicorn",
        "backend.main_buyer:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--log-level",
        "info",
    ]
    print("\nRun:", " ".join(cmd), "\n")

    if os.environ.get("BUYER_NO_BROWSER", "").strip().lower() not in ("1", "true", "yes"):

        def _delayed_open():
            time.sleep(2.0)
            _open_browser(buyer_url)

        threading.Thread(target=_delayed_open, daemon=True).start()

    env = {**os.environ, "BUYER_PORT": str(port)}
    raise SystemExit(subprocess.call(cmd, cwd=str(SCRIPT_DIR), env=env))


if __name__ == "__main__":
    main()
