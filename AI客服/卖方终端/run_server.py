# -*- coding: utf-8 -*-
"""
金牌客服系统启动脚本
使用本脚本自身的相对路径，兼容任意电脑和任意目录
"""
import sys
import os
from pathlib import Path

# 获取脚本自身所在目录（项目根目录）
SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR / "backend"

# 将 backend 目录加入 Python 模块搜索路径
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# 切换工作目录到 backend（确保相对路径正常工作）
os.chdir(BACKEND_DIR)

import uvicorn
import main
from config import FASTAPI_PORT

if __name__ == "__main__":
    print("=" * 50)
    print("  金牌客服系统")
    print("=" * 50)
    print(f"  根目录: {SCRIPT_DIR}")
    print(f"  后端目录: {BACKEND_DIR}")
    print(f"  端口: {FASTAPI_PORT}")
    print("=" * 50)
    uvicorn.run(
        main.app,
        host="127.0.0.1",
        port=FASTAPI_PORT,
        log_level="info",
        reload=False,
    )
