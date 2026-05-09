# -*- coding: utf-8 -*-
"""
Ruitalk Seller Terminal Backend
================================
AI-powered multilingual customer service system.

模块结构：
  backend/
  ├── main.py          FastAPI 入口，路由注册，生命周期管理
  ├── config.py         所有配置项（从 .env 加载）
  ├── db.py             数据库 CRUD（MySQL/SQLite 双引擎）
  ├── services.py       业务服务层（GraphRAG、DeepSeek、翻译）
  ├── jwt_auth.py       JWT token 生成/验证
  ├── agent_service.py  坐席状态管理
  ├── session_mode.py   会话分配策略
  ├── rate_limiter.py   速率限制
  ├── realtime_server.py WebSocket 实时推送
  ├── system_checker.py 系统健康检查
  ├── routers/          路由拆分（待实施）
  ├── platforms/        电商平台集成
  ├── logistics/        物流追踪
  ├── shop/             店铺管理
  └── tests/            单元/集成测试

环境要求：
  - Python >= 3.11
  - MySQL >= 8.0 或 SQLite (回退)
  - Redis >= 6.0
  - Neo4j >= 5.0

启动方式：
  方式1（直接）：python -m uvicorn main:app --host 127.0.0.1 --port 8000
  方式2（Docker）：docker-compose up -d seller
  方式3（脚本）：..\\launch\\start_seller.bat
"""

__version__ = "1.0.0"
__author__ = "Ruitalk Team"

from backend import config, db, services
