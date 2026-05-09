#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""启动卖方终端所有服务"""
import os
import sys
import subprocess
import time
import signal
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

def find_buyer_dir():
    """找到买方系统目录"""
    for d in SCRIPT_DIR.iterdir():
        if d.is_dir():
            dirname = d.name.lower()
            if 'buyer' in dirname or 'ai' in dirname:
                return str(d)
    return None

def start_seller_services():
    """启动卖方终端服务"""
    seller_dir = find_seller_dir()
    if not seller_dir:
        print("错误：找不到卖方终端目录")
        return False
    
    print(f"找到卖方终端目录: {seller_dir}")
    
    # 启动 FastAPI 主服务 (端口 8000)
    print("\n1. 启动 FastAPI 主服务 (端口 8000)...")
    main_py = os.path.join(seller_dir, 'backend', 'main.py')
    if os.path.exists(main_py):
        subprocess.Popen(
            [sys.executable, main_py],
            cwd=seller_dir,
            creationflags=subprocess.CREATE_NEW_CONSOLE,
            env={**os.environ, 'PYTHONPATH': seller_dir}
        )
        print(f"   已启动: {main_py}")
    else:
        print(f"   警告：找不到 main.py")
    
    # 等待一下
    time.sleep(2)
    
    # 启动 GoldCS (Flask, 端口 5001)
    print("\n2. 启动 GoldCS (端口 5001)...")
    gold_py = os.path.join(seller_dir, 'backend', 'gold_customer_service.py')
    if os.path.exists(gold_py):
        subprocess.Popen(
            [sys.executable, gold_py],
            cwd=seller_dir,
            creationflags=subprocess.CREATE_NEW_CONSOLE,
            env={**os.environ, 'PYTHONPATH': seller_dir}
        )
        print(f"   已启动: {gold_py}")
    else:
        print(f"   警告：找不到 gold_customer_service.py")
    
    # 等待一下
    time.sleep(2)
    
    # 启动 GraphRAG Proxy (端口 5050)
    print("\n3. 启动 GraphRAG Proxy (端口 5050)...")
    graphrag_py = os.path.join(seller_dir, 'backend', 'graphrag_proxy.py')
    if os.path.exists(graphrag_py):
        subprocess.Popen(
            [sys.executable, graphrag_py],
            cwd=seller_dir,
            creationflags=subprocess.CREATE_NEW_CONSOLE,
            env={**os.environ, 'PYTHONPATH': seller_dir}
        )
        print(f"   已启动: {graphrag_py}")
    else:
        print(f"   警告：找不到 graphrag_proxy.py")
    
    print("\n所有服务已启动！")
    print("请等待 5 秒后访问:")
    print("  卖方后台: http://127.0.0.1:8000")
    print("  GoldCS: http://127.0.0.1:5001")
    
    return True

if __name__ == '__main__':
    start_seller_services()
