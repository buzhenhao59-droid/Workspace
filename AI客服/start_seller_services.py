#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""启动卖方终端所有服务"""
import os
import sys
import subprocess
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent

def find_seller_dir():
    """找到卖方终端目录"""
    for d in SCRIPT_DIR.iterdir():
        if d.is_dir():
            gold_path = d / 'backend' / 'gold_customer_service.py'
            if gold_path.exists():
                return str(d)
    return None

def main():
    print("=== 启动卖方终端所有服务 ===")
    
    seller_dir = find_seller_dir()
    if not seller_dir:
        print("错误：找不到卖方终端目录")
        sys.exit(1)
    
    print(f"找到卖方终端: {seller_dir}")
    
    # 启动 FastAPI (8000)
    print("\n1. 启动 FastAPI (端口 8000)...")
    main_py = os.path.join(seller_dir, 'backend', 'main.py')
    p1 = subprocess.Popen(
        [sys.executable, main_py],
        cwd=seller_dir,
        creationflags=subprocess.CREATE_NEW_CONSOLE
    )
    print(f"   PID: {p1.pid}")
    
    time.sleep(3)
    
    # 启动 GoldCS (5001)
    print("\n2. 启动 GoldCS (端口 5001)...")
    gold_py = os.path.join(seller_dir, 'backend', 'gold_customer_service.py')
    p2 = subprocess.Popen(
        [sys.executable, gold_py],
        cwd=seller_dir,
        creationflags=subprocess.CREATE_NEW_CONSOLE
    )
    print(f"   PID: {p2.pid}")
    
    time.sleep(2)
    
    # 启动 GraphRAG (5050)
    print("\n3. 启动 GraphRAG (端口 5050)...")
    graphrag_py = os.path.join(seller_dir, 'backend', 'graphrag_proxy.py')
    p3 = subprocess.Popen(
        [sys.executable, graphrag_py],
        cwd=seller_dir,
        creationflags=subprocess.CREATE_NEW_CONSOLE
    )
    print(f"   PID: {p3.pid}")
    
    print("\n所有服务已启动！")
    print("等待 5 秒后检查状态...")
    time.sleep(5)
    
    # 检查端口
    import socket
    for port, name in [(8000, "FastAPI"), (5001, "GoldCS"), (5050, "GraphRAG")]:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex(('127.0.0.1', port))
            sock.close()
            if result == 0:
                print(f"  [OK] {name} 端口 {port} 已监听")
            else:
                print(f"  [FAIL] {name} 端口 {port} 未监听")
        except:
            print(f"  [FAIL] {name} 检查失败")
    
    print("\n打开浏览器: http://127.0.0.1:8000")

if __name__ == '__main__':
    main()
