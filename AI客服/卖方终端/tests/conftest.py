# -*- coding: utf-8 -*-
"""
Pytest 配置与共享 fixtures
"""
import sys, os
from pathlib import Path

# 确保 backend 目录在 Python 路径中
backend_dir = Path(__file__).parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

# 测试环境变量
os.environ.setdefault("REDIS_USE_FAKE", "1")
os.environ.setdefault("ENVIRONMENT", "testing")

import pytest


@pytest.fixture
def sample_customer_info():
    return {
        "customer": {
            "customer_id": "test_cust_001",
            "name": "测试客户",
            "phone": "13800138000",
            "region": "中国",
            "level": "VIP",
        },
        "orders": [
            {"order_id": "ORD-2024-001", "status": "已完成", "total": 299.00, "created_at": "2024-01-15"}
        ],
        "skus": [{"name": "测试商品A", "category": "电子产品", "price": 199.00, "quantity": 1}],
        "communications": [],
    }


@pytest.fixture
def sample_conversation_history():
    return [
        {"role": "user", "content": "你好，我想问一下订单情况"},
        {"role": "assistant", "content": "您好，请问您的订单号是多少？"},
        {"role": "user", "content": "ORD-2024-001"},
    ]
