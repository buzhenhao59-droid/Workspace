# -*- coding: utf-8 -*-
"""
无弹窗后台启动脚本
- 在后台用 CREATE_NO_WINDOW 启动 uvicorn 进程（无黑窗口）
- 等待服务就绪后打开浏览器
- 所有启动信息写入同目录 buyer_start.log
"""
import os, socket, subprocess, sys, time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
LOG_FILE = SCRIPT_DIR / "buyer_start.log"

# 加载根目录 .env 配置
_ROOT_ENV = (SCRIPT_DIR.parent / ".env").resolve()
if _ROOT_ENV.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(_ROOT_ENV, override=True)
    except Exception:
        pass


def _log(msg):
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _port_free(port):
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


# ── 端口检测 ──────────────────────────────────────────────
preferred = int(os.environ.get("BUYER_PORT", "8001"))
port = None
for p in [preferred] + [x for x in range(8001, 8011) if x != preferred]:
    if _port_free(p):
        port = p
        if p != preferred:
            _log(f"端口 {preferred} 被占用，自动换用 {p}")
        break

if port is None:
    _log("[ERROR] 端口 8001~8010 全部被占用。请关闭多余进程后重试。")
    raise SystemExit(1)

buyer_url = f"http://127.0.0.1:{port}/"
_log(f"买方AI客服 启动中...  URL: {buyer_url}")

# ── 找 Python 解释器 ──────────────────────────────────────
python_exec = sys.executable
for candidate in [
    SCRIPT_DIR / ".venv" / "Scripts" / "python.exe",
    SCRIPT_DIR.parent / "卖方终端" / ".venv" / "Scripts" / "python.exe",
]:
    if candidate.is_file():
        python_exec = str(candidate)
        _log(f"发现 venv: {candidate}")
        break

_log(f"Python: {python_exec}")

# ── 启动 uvicorn（隐藏窗口）───────────────────────────────
CREATE_NO_WINDOW = 0x08000000

env = {**os.environ}
env["BUYER_PORT"] = str(port)

cmd = [
    python_exec, "-m", "uvicorn",
    "backend.main_buyer:app",
    "--host", "127.0.0.1",
    "--port", str(port),
    "--log-level", "info",
]

_log(f"uvicorn 启动命令: {' '.join(cmd)}")

try:
    proc = subprocess.Popen(
        cmd,
        cwd=str(SCRIPT_DIR),
        env=env,
        creationflags=CREATE_NO_WINDOW,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
        text=True,
    )
except Exception as e:
    _log(f"[ERROR] 启动 uvicorn 失败: {e}")
    raise SystemExit(1)

_log(f"uvicorn 进程已启动（PID={proc.pid}），等待服务就绪...")

# ── 等待服务真正开始监听 ──────────────────────────────────
_ready = False
_start_time = time.time()

while time.time() - _start_time < 15:
    if proc.poll() is not None:
        # 进程提前退出，读取错误输出
        _out, _ = proc.communicate()
        if _out:
            for _line in _out.strip().split("\n"):
                if _line.strip():
                    _log("[ERR] " + _line)
        _log(f"[ERROR] uvicorn 进程提前退出（退出码: {proc.returncode}）。请检查 buyer_start.log。")
        raise SystemExit(1)

    # Windows 上 select 不可用，改用端口轮询
    time.sleep(0.5)
    if not _port_free(port):
        _ready = True
        _log("服务就绪！")
        break

if not _ready:
    # 再次确认
    time.sleep(1)
    if not _port_free(port):
        _ready = True
        _log("服务就绪！")
    else:
        _log("[WARN] 端口仍未监听，但继续尝试打开浏览器...")

time.sleep(0.3)

# ── 打开浏览器 ────────────────────────────────────────────
try:
    if sys.platform == "win32":
        os.startfile(buyer_url)
    else:
        subprocess.call(["xdg-open", buyer_url])
    _log(f"已打开浏览器: {buyer_url}")
except Exception as e:
    _log(f"[WARN] 打开浏览器失败，请手动访问: {buyer_url}  （{e}）")

_log(f"[OK] 买方AI客服已在后台运行: {buyer_url}")
_log(f"    查看日志: {LOG_FILE}")
