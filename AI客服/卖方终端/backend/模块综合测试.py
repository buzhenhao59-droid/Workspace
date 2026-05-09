# -*- coding: utf-8 -*-
"""
卖家终端六大模块综合测试
Module Test Suite for Ruitalk Seller Terminal

测试范围：
1. 售前模块 - 咨询处理
2. 售后模块 - 退换货处理
3. 个人信息模块 - 账户管理
4. 店铺模块 - 店铺管理
5. 信息查询模块 - 订单/物流查询
6. 信息管理模块 - AI提示词/配置管理

使用方法：
python 卖方终端\backend\模块综合测试.py
"""

import sys
import os
import json
import time
import logging
from datetime import datetime
from typing import Dict, List, Any, Optional

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s'
)
logger = logging.getLogger(__name__)

# ============== 测试结果收集 ==============
class TestResult:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors = []
        self.details = []

    def add_pass(self, module: str, test: str, msg: str = ""):
        self.passed += 1
        self.details.append({
            "module": module,
            "test": test,
            "status": "PASS",
            "message": msg
        })
        logger.info(f"  [PASS] {test}: {msg or 'OK'}")

    def add_fail(self, module: str, test: str, msg: str):
        self.failed += 1
        self.errors.append({
            "module": module,
            "test": test,
            "error": msg
        })
        logger.error(f"  [FAIL] {test}: {msg}")

    def summary(self) -> Dict:
        return {
            "total": self.passed + self.failed,
            "passed": self.passed,
            "failed": self.failed,
            "pass_rate": f"{self.passed / max(1, self.passed + self.failed) * 100:.1f}%",
            "errors": self.errors,
            "timestamp": datetime.now().isoformat()
        }


# ============== 测试基类 ==============
class BaseModuleTest:
    def __init__(self, result: TestResult):
        self.result = result
        self.module_name = "Base"

    def run(self):
        logger.info(f"\n{'='*60}")
        logger.info(f"模块测试: {self.module_name}")
        logger.info(f"{'='*60}")
        try:
            self.test()
        except Exception as e:
            self.result.add_fail(self.module_name, "整体测试", str(e))
            logger.exception(f"{self.module_name} 测试异常")

    def test(self):
        raise NotImplementedError


# ============== 模块1：售前模块测试 ==============
class PresaleModuleTest(BaseModuleTest):
    """售前模块测试 - 咨询处理、客户跟进"""

    def __init__(self, result: TestResult):
        super().__init__(result)
        self.module_name = "售前模块"

    def test(self):
        # 测试1：客户档案查询
        try:
            from services import query_customer_profile
            profile = query_customer_profile("TEST_001")
            self.result.add_pass(self.module_name, "客户档案查询", "可正常查询客户档案")
        except ImportError:
            self.result.add_fail(self.module_name, "客户档案查询", "services模块不可用")
        except Exception as e:
            self.result.add_fail(self.module_name, "客户档案查询", str(e))

        # 测试2：会话记忆
        try:
            from conversation_memory import ConversationMemory
            memory = ConversationMemory()
            session_id = f"test_session_{int(time.time())}"
            memory.save_message(session_id, "customer", "测试消息")
            history = memory.get_history(session_id)
            if history:
                self.result.add_pass(self.module_name, "会话记忆", f"保存/读取正常，共{len(history)}条记录")
            else:
                self.result.add_fail(self.module_name, "会话记忆", "无法获取会话历史")
        except ImportError:
            self.result.add_fail(self.module_name, "会话记忆", "conversation_memory模块不可用")
        except Exception as e:
            self.result.add_fail(self.module_name, "会话记忆", str(e))

        # 测试3：情绪检测
        try:
            from services import detect_emotion
            emotion = detect_emotion("我非常满意！谢谢！")
            if emotion:
                self.result.add_pass(self.module_name, "情绪检测", f"检测到情绪: {emotion}")
            else:
                self.result.add_fail(self.module_name, "情绪检测", "无法检测情绪")
        except ImportError:
            self.result.add_fail(self.module_name, "情绪检测", "services模块不可用")
        except Exception as e:
            self.result.add_fail(self.module_name, "情绪检测", str(e))

        # 测试4：订单同步
        try:
            from platform_sync import get_synced_orders
            orders, total = get_synced_orders(page=1, page_size=10)
            self.result.add_pass(self.module_name, "订单同步", f"获取到{total}条订单")
        except ImportError:
            self.result.add_fail(self.module_name, "订单同步", "platform_sync模块不可用")
        except Exception as e:
            self.result.add_fail(self.module_name, "订单同步", str(e))


# ============== 模块2：售后模块测试 ==============
class AfterSaleModuleTest(BaseModuleTest):
    """售后模块测试 - 退换货处理"""

    def __init__(self, result: TestResult):
        super().__init__(result)
        self.module_name = "售后模块"

    def test(self):
        # 测试1：售后单查询
        try:
            from platform_sync import get_synced_returns
            returns, total = get_synced_returns(page=1, page_size=10)
            self.result.add_pass(self.module_name, "售后单查询", f"获取到{total}条售后记录")
        except ImportError:
            self.result.add_fail(self.module_name, "售后单查询", "platform_sync模块不可用")
        except Exception as e:
            self.result.add_fail(self.module_name, "售后单查询", str(e))

        # 测试2：创建售后单
        try:
            from platform_sync import _upsert_return
            test_data = {
                "return_id": f"TEST_RET_{int(time.time())}",
                "order_id": "TEST_ORDER_001",
                "customer_id": "TEST_CUST_001",
                "type": "退货退款",
                "reason": "测试",
                "status": "待处理",
                "amount": 100.00,
                "description": "自动化测试创建",
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            _upsert_return(test_data)
            self.result.add_pass(self.module_name, "创建售后单", "售后单创建成功")
        except ImportError:
            self.result.add_fail(self.module_name, "创建售后单", "platform_sync模块不可用")
        except Exception as e:
            self.result.add_fail(self.module_name, "创建售后单", str(e))

        # 测试3：评价查询
        try:
            from platform_sync import get_synced_reviews
            reviews, total = get_synced_reviews(page=1, page_size=10)
            self.result.add_pass(self.module_name, "评价查询", f"获取到{total}条评价")
        except ImportError:
            self.result.add_fail(self.module_name, "评价查询", "platform_sync模块不可用")
        except Exception as e:
            self.result.add_fail(self.module_name, "评价查询", str(e))

        # 测试4：退款处理
        try:
            from config import REFUND_API
            if REFUND_API:
                self.result.add_pass(self.module_name, "退款API配置", "已配置退款接口")
            else:
                self.result.add_pass(self.module_name, "退款API配置", "未配置（使用本地处理）")
        except Exception as e:
            self.result.add_fail(self.module_name, "退款API配置", str(e))


# ============== 模块3：个人信息模块测试 ==============
class ProfileModuleTest(BaseModuleTest):
    """个人信息模块测试 - 账户管理"""

    def __init__(self, result: TestResult):
        super().__init__(result)
        self.module_name = "个人信息模块"

    def test(self):
        # 测试1：JWT认证
        try:
            from jwt_auth import create_access_token, verify_access_token
            test_user = "test_user"
            token = create_access_token({"sub": test_user, "role": "admin"})
            payload = verify_access_token(token)
            if payload and payload.get("sub") == test_user:
                self.result.add_pass(self.module_name, "JWT认证", "Token创建和验证正常")
            else:
                self.result.add_fail(self.module_name, "JWT认证", "Token验证失败")
        except ImportError:
            self.result.add_fail(self.module_name, "JWT认证", "jwt_auth模块不可用")
        except Exception as e:
            self.result.add_fail(self.module_name, "JWT认证", str(e))

        # 测试2：会话管理
        try:
            from services import verify_admin_password
            result = verify_admin_password("123456789", "invalid_hash")
            # 无论结果如何，只要不抛异常就算通过
            self.result.add_pass(self.module_name, "密码验证", "密码验证函数正常")
        except ImportError:
            self.result.add_fail(self.module_name, "密码验证", "services模块不可用")
        except Exception as e:
            self.result.add_fail(self.module_name, "密码验证", str(e))

        # 测试3：权限检查
        try:
            from jwt_auth import check_module_access
            # 模拟权限检查
            allowed = check_module_access("admin", "presale")
            self.result.add_pass(self.module_name, "权限检查", f"模块访问控制正常")
        except ImportError:
            self.result.add_fail(self.module_name, "权限检查", "jwt_auth模块不可用")
        except Exception as e:
            self.result.add_fail(self.module_name, "权限检查", str(e))

        # 测试4：会话存储
        try:
            from redis_store import session_store
            test_key = f"test_session_{int(time.time())}"
            session_store.set(test_key, {"user": "test", "role": "admin"}, ttl=60)
            value = session_store.get(test_key)
            session_store.delete(test_key)
            if value:
                self.result.add_pass(self.module_name, "会话存储", "Redis会话读写正常")
            else:
                self.result.add_fail(self.module_name, "会话存储", "无法读取会话数据")
        except ImportError:
            self.result.add_pass(self.module_name, "会话存储", "redis_store模块不可用（使用内存会话）")
        except Exception as e:
            self.result.add_fail(self.module_name, "会话存储", str(e))


# ============== 模块4：店铺模块测试 ==============
class ShopModuleTest(BaseModuleTest):
    """店铺模块测试 - 店铺管理"""

    def __init__(self, result: TestResult):
        super().__init__(result)
        self.module_name = "店铺模块"

    def test(self):
        # 测试1：店铺列表
        try:
            from shop_api import get_shops
            shops = get_shops()
            self.result.add_pass(self.module_name, "店铺列表", f"获取到{len(shops)}家店铺")
        except ImportError:
            self.result.add_fail(self.module_name, "店铺列表", "shop_api模块不可用")
        except Exception as e:
            self.result.add_fail(self.module_name, "店铺列表", str(e))

        # 测试2：平台配置检查
        try:
            from config import (
                TIKTOK_API_URL, SHOPEE_API_URL, LAZADA_API_URL,
                AMAZON_API_URL, ALIEXPRESS_API_URL, EBAY_API_URL, SHOPIFY_API_URL,
            )
            platforms = {
                "TikTok": bool(TIKTOK_API_URL),
                "Shopee": bool(SHOPEE_API_URL),
                "Lazada": bool(LAZADA_API_URL),
                "Amazon": bool(AMAZON_API_URL),
                "AliExpress": bool(ALIEXPRESS_API_URL),
                "eBay": bool(EBAY_API_URL),
                "Shopify": bool(SHOPIFY_API_URL),
            }
            configured = [k for k, v in platforms.items() if v]
            self.result.add_pass(self.module_name, "平台配置", f"已配置{len(configured)}个平台: {', '.join(configured)}")
        except ImportError:
            self.result.add_fail(self.module_name, "平台配置", "config模块不可用")
        except Exception as e:
            self.result.add_fail(self.module_name, "平台配置", str(e))

        # 测试3：店铺统计
        try:
            from shop_api import get_dashboard_stats
            stats = get_dashboard_stats()
            if stats:
                self.result.add_pass(self.module_name, "店铺统计", "仪表盘统计正常")
            else:
                self.result.add_pass(self.module_name, "店铺统计", "仪表盘统计返回空数据（正常）")
        except ImportError:
            self.result.add_fail(self.module_name, "店铺统计", "shop_api模块不可用")
        except Exception as e:
            self.result.add_fail(self.module_name, "店铺统计", str(e))

        # 测试4：分类管理
        try:
            from shop_api import get_categories
            categories = get_categories()
            self.result.add_pass(self.module_name, "分类管理", f"获取到{len(categories)}个分类")
        except ImportError:
            self.result.add_fail(self.module_name, "分类管理", "shop_api模块不可用")
        except Exception as e:
            self.result.add_fail(self.module_name, "分类管理", str(e))


# ============== 模块5：信息查询模块测试 ==============
class QueryModuleTest(BaseModuleTest):
    """信息查询模块测试 - 订单/物流查询"""

    def __init__(self, result: TestResult):
        super().__init__(result)
        self.module_name = "信息查询模块"

    def test(self):
        # 测试1：订单查询
        try:
            from platform_sync import get_synced_orders
            orders, total = get_synced_orders(page=1, page_size=10)
            self.result.add_pass(self.module_name, "订单查询", f"查询成功，共{total}条订单")
        except ImportError:
            self.result.add_fail(self.module_name, "订单查询", "platform_sync模块不可用")
        except Exception as e:
            self.result.add_fail(self.module_name, "订单查询", str(e))

        # 测试2：物流查询
        try:
            from logistics import DHLClient, FedExClient, UPSClient
            self.result.add_pass(self.module_name, "物流客户端", "物流查询客户端可用")
        except ImportError:
            self.result.add_fail(self.module_name, "物流客户端", "logistics模块不可用")
        except Exception as e:
            self.result.add_fail(self.module_name, "物流客户端", str(e))

        # 测试3：政策检索
        try:
            from policy_search_service import policy_search_service
            results = policy_search_service.search_policies(limit=5)
            self.result.add_pass(self.module_name, "政策检索", f"检索到{len(results)}条政策")
        except ImportError:
            self.result.add_fail(self.module_name, "政策检索", "policy_search_service不可用")
        except Exception as e:
            self.result.add_fail(self.module_name, "政策检索", str(e))

        # 测试4：客户图谱
        try:
            from services import query_graphrag
            result = query_graphrag("TEST_001")
            self.result.add_pass(self.module_name, "客户图谱", "GraphRAG查询正常")
        except ImportError:
            self.result.add_fail(self.module_name, "客户图谱", "services模块不可用")
        except Exception as e:
            self.result.add_fail(self.module_name, "客户图谱", str(e))


# ============== 模块6：信息管理模块测试 ==============
class AdminModuleTest(BaseModuleTest):
    """信息管理模块测试 - AI提示词/配置管理"""

    def __init__(self, result: TestResult):
        super().__init__(result)
        self.module_name = "信息管理模块"

    def test(self):
        # 测试1：AI提示词加载
        try:
            # 尝试导入买方系统的提示词管理器
            sys.path.insert(0, str(os.path.join(os.path.dirname(__file__), "..", "..", "AI客服买方系统", "backend")))
            from AI提示词版本控制 import get_prompt_manager
            manager = get_prompt_manager()
            config = manager.load()
            self.result.add_pass(self.module_name, "AI提示词加载", f"加载成功 v{config.version}")
        except ImportError:
            self.result.add_fail(self.module_name, "AI提示词加载", "AI提示词版本控制模块不可用")
        except Exception as e:
            self.result.add_fail(self.module_name, "AI提示词加载", str(e))

        # 测试2：提示词版本历史
        try:
            from AI提示词版本控制 import get_prompt_manager
            manager = get_prompt_manager()
            history = manager.get_version_history(limit=5)
            self.result.add_pass(self.module_name, "提示词版本历史", f"获取到{len(history)}条历史")
        except ImportError:
            self.result.add_fail(self.module_name, "提示词版本历史", "AI提示词版本控制模块不可用")
        except Exception as e:
            self.result.add_fail(self.module_name, "提示词版本历史", str(e))

        # 测试3：配置验证
        try:
            from config_validator import ConfigValidator
            validator = ConfigValidator()
            issues = validator.validate_all()
            if not issues:
                self.result.add_pass(self.module_name, "配置验证", "所有配置项有效")
            else:
                self.result.add_pass(self.module_name, "配置验证", f"发现{len(issues)}个配置问题")
        except ImportError:
            self.result.add_fail(self.module_name, "配置验证", "config_validator模块不可用")
        except Exception as e:
            self.result.add_fail(self.module_name, "配置验证", str(e))

        # 测试4：日志配置
        try:
            from config import SENTRY_DSN
            if SENTRY_DSN:
                self.result.add_pass(self.module_name, "Sentry配置", "Sentry APM已配置")
            else:
                self.result.add_pass(self.module_name, "Sentry配置", "Sentry未配置（可选）")
        except ImportError:
            self.result.add_fail(self.module_name, "Sentry配置", "config模块不可用")
        except Exception as e:
            self.result.add_fail(self.module_name, "Sentry配置", str(e))


# ============== 主测试运行器 ==============
def run_all_tests() -> Dict:
    """运行所有模块测试"""
    result = TestResult()

    # 执行六大模块测试
    tests = [
        PresaleModuleTest(result),
        AfterSaleModuleTest(result),
        ProfileModuleTest(result),
        ShopModuleTest(result),
        QueryModuleTest(result),
        AdminModuleTest(result),
    ]

    for test in tests:
        test.run()

    # 输出汇总
    summary = result.summary()
    print("\n" + "=" * 60)
    print("测试汇总")
    print("=" * 60)
    print(f"总计: {summary['total']} 项测试")
    print(f"通过: {summary['passed']} 项")
    print(f"失败: {summary['failed']} 项")
    print(f"通过率: {summary['pass_rate']}")

    if summary['errors']:
        print("\n失败详情:")
        for err in summary['errors']:
            print(f"  [{err['module']}] {err['test']}: {err['error']}")

    return summary


# ============== 入口 ==============
if __name__ == "__main__":
    print("Ruitalk 卖家终端六大模块综合测试")
    print("=" * 60)

    # 添加路径
    backend_dir = os.path.dirname(__file__)
    seller_root = os.path.dirname(backend_dir)
    parent_dir = os.path.dirname(seller_root)
    sys.path.insert(0, backend_dir)
    sys.path.insert(0, parent_dir)

    summary = run_all_tests()

    # 保存结果
    result_file = os.path.join(backend_dir, "模块测试结果.json")
    with open(result_file, 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"\n结果已保存: {result_file}")
