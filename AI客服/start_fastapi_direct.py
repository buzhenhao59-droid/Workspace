#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""直接运行 main.py 启动服务"""
import os, sys, subprocess
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent

# 找到卖方终端目录
seller_dir = None
for d in SCRIPT_DIR.iterdir():
    if d.is_dir():
        main_py = d / 'backend' / 'main.py'
        if main_py.exists():
            seller_dir = str(d)
            break

if not seller_dir:
    print("[ERROR] Cannot find seller directory")
    sys.exit(1)

backend_dir = os.path.join(seller_dir, 'backend')
main_py = os.path.join(backend_dir, 'main.py')

print(f"Starting FastAPI from: {main_py}")
print(f"Working directory: {backend_dir}")

# 运行 main.py
try:
    proc = subprocess.Popen(
        [sys.executable, main_py],
        cwd=backend_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    print(f"Process started with PID: {proc.pid}")
    
    # 等待几秒
    import time
    time.sleep(5)
    
    # 检查进程状态
    if proc.poll() is None:
        print("[OK] Process is running")
        # 检查端口
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex(('127.0.0.1', 8000))
        sock.close()
        if result == 0:
            print("[OK] Port 8000 is listening")
        else:
            print("[FAIL] Port 8000 is not listening")
    else:
        print(f"[FAIL] Process exited with code: {proc.returncode}")
        stdout, stderr = proc.communicate()
        print("STDOUT:", stdout.decode('utf-8', errors='replace')[:500])
        print("STDERR:", stderr.decode('utf-8', errors='replace')[:500])
except Exception as e:
    print(f"[ERROR] {e}")
