#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""启动卖方终端所有服务"""
import os, sys, subprocess, time, socket
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent

def find_seller():
    for d in SCRIPT_DIR.iterdir():
        if d.is_dir():
            main_py = d / 'backend' / 'main.py'
            if main_py.exists():
                return str(d)
    return None

def port_ok(port):
    try:
        s = socket.socket()
        s.settimeout(1)
        r = s.connect_ex(('127.0.0.1', port))
        s.close()
        return r == 0
    except:
        return False

seller = find_seller()
if not seller:
    print("[ERROR] Cannot find seller dir")
    sys.exit(1)

backend = os.path.join(seller, 'backend')
print(f"Seller: {seller}")
print(f"Backend: {backend}")

# 杀掉现有进程
subprocess.run('taskkill /F /IM python.exe', shell=True, capture_output=True)
time.sleep(2)

print("\n[1] Starting FastAPI (8000)...")
subprocess.Popen([sys.executable, 'main.py'], cwd=backend, creationflags=subprocess.CREATE_NEW_CONSOLE)
time.sleep(4)

print("[2] Starting GoldCS (5001)...")
subprocess.Popen([sys.executable, 'gold_customer_service.py'], cwd=backend, creationflags=subprocess.CREATE_NEW_CONSOLE)
time.sleep(3)

print("[3] Starting GraphRAG (5050)...")
subprocess.Popen([sys.executable, 'graphrag_proxy.py'], cwd=backend, creationflags=subprocess.CREATE_NEW_CONSOLE)
time.sleep(3)

print("\n=== Service Status ===")
for port, name in [(8000,"FastAPI"),(5001,"GoldCS"),(5050,"GraphRAG")]:
    if port_ok(port):
        print(f"[OK] {name} port {port}")
    else:
        print(f"[FAIL] {name} port {port}")

print("\nOpen: http://127.0.0.1:8000")
