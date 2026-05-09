# -*- coding: utf-8 -*-
"""
六大核心模块完整测试脚本
测试卖方终端的所有主要功能模块

测试模块：
1. 售前处理 - 订单创建、查询、统计
2. 售后服务 - 售后创建、查询、处理
3. 个人信息 - 客户查询、会话管理
4. 店铺管理 - 平台管理、店铺配置
5. 信息查询 - 订单查询、退换货、评价
6. 信息管理 - 快捷回复、模板、通知

使用方法：
    # 运行所有测试
    python test_six_modules.py
    
    # 运行指定模块测试
    python test_six_modules.py --module orders
    
    # 详细输出
    python test_six_modules.py --verbose
"""

import os
import sys
import json
import time
import argparse
import logging
from datetime import datetime
from typing import Dict, List, Any, Optional

import requests

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


class TestResult:
    """测试结果"""
    
    def __init__(self):
        self.module = ""
        self.name = ""
        self.passed = False
        self.message = ""
        self.duration = 0.0
        self.data = None
    
    def to_dict(self) -> Dict:
        return {
            "module": self.module,
            "name": self.name,
            "passed": self.passed,
            "message": self.message,
            "duration": f"{self.duration:.3f}s",
            "data": self.data
        }


class SixModulesTester:
    """
    六模块测试器
    """
    
    def __init__(self, base_url: str = "http://127.0.0.1:8000", verbose: bool = False):
        self.base_url = base_url
        self.verbose = verbose
        self.token = None
        self.agent_token = None
        self.results: List[TestResult] = []
        self.stats = {
            "total": 0,
            "passed": 0,
            "failed": 0,
            "skipped": 0
        }
    
    def log(self, msg: str) -> None:
        """日志输出"""
        if self.verbose:
            logger.info(msg)
    
    def get_headers(self) -> Dict[str, str]:
        """获取认证头"""
        if self.token:
            return {"Authorization": f"Bearer {self.token}"}
        return {}
    
    def admin_login(self) -> bool:
        """管理员登录"""
        self.log("\n正在登录管理员账号...")
        
        result = TestResult()
        result.module = "认证"
        result.name = "管理员登录"
        
        try:
            response = requests.post(
                f"{self.base_url}/api/admin/login",
                json={"username": "admin", "password": "123456789"},
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get("success"):
                    self.token = data["data"]["access_token"]
                    result.passed = True
                    result.message = "登录成功"
                    self.log(f"✅ 登录成功，Token: {self.token[:30]}...")
                else:
                    result.message = data.get("message", "登录失败")
            else:
                result.message = f"HTTP {response.status_code}"
        except Exception as e:
            result.message = str(e)
        
        self.results.append(result)
        return result.passed
    
    def agent_login(self) -> bool:
        """坐席登录"""
        self.log("\n正在登录坐席账号...")
        
        result = TestResult()
        result.module = "认证"
        result.name = "坐席登录"
        
        try:
            response = requests.post(
                f"{self.base_url}/api/agent/login",
                json={
                    "agent_id": "12345678910",
                    "agent_name": "测试坐席",
                    "role": "agent"
                },
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get("success"):
                    self.agent_token = data["data"]["access_token"]
                    result.passed = True
                    result.message = "登录成功"
                    self.log(f"✅ 坐席登录成功")
                else:
                    result.message = data.get("message", "登录失败")
            else:
                result.message = f"HTTP {response.status_code}"
        except Exception as e:
            result.message = str(e)
        
        self.results.append(result)
        return result.passed
    
    def test_presale_module(self) -> None:
        """测试售前处理模块"""
        self.log("\n" + "=" * 50)
        self.log("测试模块1: 售前处理")
        self.log("=" * 50)
        
        # 1. 订单列表
        result = TestResult()
        result.module = "售前处理"
        result.name = "订单列表查询"
        
        try:
            start = time.time()
            response = requests.get(
                f"{self.base_url}/api/admin/orders",
                headers=self.get_headers(),
                params={"page": 1, "page_size": 10},
                timeout=10
            )
            result.duration = time.time() - start
            
            if response.status_code == 200:
                data = response.json()
                result.passed = True
                result.message = f"查询成功，共 {len(data.get('orders', []))} 条"
                result.data = {"status_code": 200, "orders_count": len(data.get('orders', []))}
            else:
                result.message = f"HTTP {response.status_code}"
        except Exception as e:
            result.message = str(e)
        
        self.results.append(result)
        self._print_result(result)
        
        # 2. 订单统计
        result = TestResult()
        result.module = "售前处理"
        result.name = "订单统计"
        
        try:
            start = time.time()
            response = requests.get(
                f"{self.base_url}/api/admin/stats",
                headers=self.get_headers(),
                timeout=10
            )
            result.duration = time.time() - start
            
            if response.status_code == 200:
                result.passed = True
                result.message = "统计查询成功"
                result.data = {"status_code": 200}
            else:
                result.message = f"HTTP {response.status_code}"
        except Exception as e:
            result.message = str(e)
        
        self.results.append(result)
        self._print_result(result)
    
    def test_aftersale_module(self) -> None:
        """测试售后服务模块"""
        self.log("\n" + "=" * 50)
        self.log("测试模块2: 售后服务")
        self.log("=" * 50)
        
        # 1. 售后列表
        result = TestResult()
        result.module = "售后服务"
        result.name = "售后列表查询"
        
        try:
            start = time.time()
            response = requests.get(
                f"{self.base_url}/api/admin/after-sales",
                headers=self.get_headers(),
                params={"page": 1, "page_size": 10},
                timeout=10
            )
            result.duration = time.time() - start
            
            if response.status_code == 200:
                data = response.json()
                result.passed = True
                result.message = f"查询成功"
                result.data = {"status_code": 200}
            else:
                result.message = f"HTTP {response.status_code}"
        except Exception as e:
            result.message = str(e)
        
        self.results.append(result)
        self._print_result(result)
        
        # 2. 售后统计
        result = TestResult()
        result.module = "售后服务"
        result.name = "售后统计"
        
        try:
            start = time.time()
            response = requests.get(
                f"{self.base_url}/api/admin/after-sales/stats",
                headers=self.get_headers(),
                timeout=10
            )
            result.duration = time.time() - start
            
            if response.status_code == 200:
                result.passed = True
                result.message = "统计查询成功"
                result.data = {"status_code": 200}
            else:
                result.message = f"HTTP {response.status_code}"
        except Exception as e:
            result.message = str(e)
        
        self.results.append(result)
        self._print_result(result)
    
    def test_profile_module(self) -> None:
        """测试个人信息模块"""
        self.log("\n" + "=" * 50)
        self.log("测试模块3: 个人信息")
        self.log("=" * 50)
        
        # 1. 当前用户信息
        result = TestResult()
        result.module = "个人信息"
        result.name = "获取当前用户"
        
        try:
            start = time.time()
            response = requests.get(
                f"{self.base_url}/api/admin/me",
                headers=self.get_headers(),
                timeout=10
            )
            result.duration = time.time() - start
            
            if response.status_code == 200:
                data = response.json()
                if data.get("success"):
                    result.passed = True
                    result.message = f"获取成功: {data.get('data', {}).get('user', {}).get('username', 'N/A')}"
                    result.data = {"username": data.get('data', {}).get('user', {}).get('username')}
            else:
                result.message = f"HTTP {response.status_code}"
        except Exception as e:
            result.message = str(e)
        
        self.results.append(result)
        self._print_result(result)
        
        # 2. 客户列表（如果有会话）
        result = TestResult()
        result.module = "个人信息"
        result.name = "会话列表"
        
        try:
            start = time.time()
            response = requests.get(
                f"{self.base_url}/api/admin/sessions",
                headers=self.get_headers(),
                timeout=10
            )
            result.duration = time.time() - start
            
            if response.status_code == 200:
                result.passed = True
                result.message = "会话列表获取成功"
                result.data = {"status_code": 200}
            else:
                result.message = f"HTTP {response.status_code}"
        except Exception as e:
            result.message = str(e)
        
        self.results.append(result)
        self._print_result(result)
    
    def test_shop_module(self) -> None:
        """测试店铺管理模块"""
        self.log("\n" + "=" * 50)
        self.log("测试模块4: 店铺管理")
        self.log("=" * 50)
        
        # 1. 平台列表
        result = TestResult()
        result.module = "店铺管理"
        result.name = "平台列表"
        
        try:
            start = time.time()
            response = requests.get(
                f"{self.base_url}/api/v1/platforms",
                headers=self.get_headers(),
                timeout=10
            )
            result.duration = time.time() - start
            
            if response.status_code == 200:
                result.passed = True
                result.message = "平台列表获取成功"
                result.data = {"status_code": 200}
            else:
                result.message = f"HTTP {response.status_code}"
        except Exception as e:
            result.message = str(e)
        
        self.results.append(result)
        self._print_result(result)
        
        # 2. 店铺统计
        result = TestResult()
        result.module = "店铺管理"
        result.name = "店铺统计"
        
        try:
            start = time.time()
            response = requests.get(
                f"{self.base_url}/api/v1/shop/stats",
                headers=self.get_headers(),
                timeout=10
            )
            result.duration = time.time() - start
            
            if response.status_code == 200:
                result.passed = True
                result.message = "店铺统计获取成功"
                result.data = {"status_code": 200}
            else:
                result.message = f"HTTP {response.status_code}"
        except Exception as e:
            result.message = str(e)
        
        self.results.append(result)
        self._print_result(result)
    
    def test_query_module(self) -> None:
        """测试信息查询模块"""
        self.log("\n" + "=" * 50)
        self.log("测试模块5: 信息查询")
        self.log("=" * 50)
        
        # 1. 评价列表
        result = TestResult()
        result.module = "信息查询"
        result.name = "评价列表"
        
        try:
            start = time.time()
            response = requests.get(
                f"{self.base_url}/api/admin/reviews",
                headers=self.get_headers(),
                params={"page": 1, "page_size": 10},
                timeout=10
            )
            result.duration = time.time() - start
            
            if response.status_code == 200:
                result.passed = True
                result.message = "评价列表获取成功"
                result.data = {"status_code": 200}
            else:
                result.message = f"HTTP {response.status_code}"
        except Exception as e:
            result.message = str(e)
        
        self.results.append(result)
        self._print_result(result)
        
        # 2. 评价统计
        result = TestResult()
        result.module = "信息查询"
        result.name = "评价统计"
        
        try:
            start = time.time()
            response = requests.get(
                f"{self.base_url}/api/admin/reviews/stats",
                headers=self.get_headers(),
                timeout=10
            )
            result.duration = time.time() - start
            
            if response.status_code == 200:
                result.passed = True
                result.message = "评价统计获取成功"
                result.data = {"status_code": 200}
            else:
                result.message = f"HTTP {response.status_code}"
        except Exception as e:
            result.message = str(e)
        
        self.results.append(result)
        self._print_result(result)
    
    def test_management_module(self) -> None:
        """测试信息管理模块"""
        self.log("\n" + "=" * 50)
        self.log("测试模块6: 信息管理")
        self.log("=" * 50)
        
        # 1. 快捷回复列表
        result = TestResult()
        result.module = "信息管理"
        result.name = "快捷回复列表"
        
        try:
            start = time.time()
            response = requests.get(
                f"{self.base_url}/api/admin/quick-replies",
                headers=self.get_headers(),
                timeout=10
            )
            result.duration = time.time() - start
            
            if response.status_code == 200:
                result.passed = True
                result.message = "快捷回复列表获取成功"
                result.data = {"status_code": 200}
            else:
                result.message = f"HTTP {response.status_code}"
        except Exception as e:
            result.message = str(e)
        
        self.results.append(result)
        self._print_result(result)
        
        # 2. 审计日志
        result = TestResult()
        result.module = "信息管理"
        result.name = "审计日志"
        
        try:
            start = time.time()
            response = requests.get(
                f"{self.base_url}/api/admin/audit-logs",
                headers=self.get_headers(),
                params={"page": 1, "page_size": 10},
                timeout=10
            )
            result.duration = time.time() - start
            
            if response.status_code == 200:
                result.passed = True
                result.message = "审计日志获取成功"
                result.data = {"status_code": 200}
            else:
                result.message = f"HTTP {response.status_code}"
        except Exception as e:
            result.message = str(e)
        
        self.results.append(result)
        self._print_result(result)
        
        # 3. 通知列表
        result = TestResult()
        result.module = "信息管理"
        result.name = "通知列表"
        
        try:
            start = time.time()
            response = requests.get(
                f"{self.base_url}/api/admin/notifications",
                headers=self.get_headers(),
                params={"page": 1, "page_size": 10},
                timeout=10
            )
            result.duration = time.time() - start
            
            if response.status_code == 200:
                result.passed = True
                result.message = "通知列表获取成功"
                result.data = {"status_code": 200}
            else:
                result.message = f"HTTP {response.status_code}"
        except Exception as e:
            result.message = str(e)
        
        self.results.append(result)
        self._print_result(result)
    
    def _print_result(self, result: TestResult) -> None:
        """打印测试结果"""
        self.stats["total"] += 1
        
        if result.passed:
            self.stats["passed"] += 1
            status = "✅ PASS"
        else:
            self.stats["failed"] += 1
            status = "❌ FAIL"
        
        logger.info(f"  {status} | {result.name}")
        logger.info(f"         {result.message}")
        if self.verbose:
            logger.info(f"         耗时: {result.duration:.3f}s")
    
    def run_all_tests(self) -> Dict[str, Any]:
        """运行所有测试"""
        logger.info("=" * 60)
        logger.info("Ruitalk 六模块测试")
        logger.info("=" * 60)
        logger.info(f"测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"服务器: {self.base_url}")
        logger.info("")
        
        # 1. 管理员登录
        if not self.admin_login():
            logger.error("❌ 管理员登录失败，无法继续测试")
            return self.get_summary()
        
        # 2. 运行所有模块测试
        self.test_presale_module()
        self.test_aftersale_module()
        self.test_profile_module()
        self.test_shop_module()
        self.test_query_module()
        self.test_management_module()
        
        return self.get_summary()
    
    def get_summary(self) -> Dict[str, Any]:
        """获取测试汇总"""
        # 统计各模块通过率
        modules = {}
        for r in self.results:
            if r.module not in modules:
                modules[r.module] = {"total": 0, "passed": 0, "failed": 0}
            modules[r.module]["total"] += 1
            if r.passed:
                modules[r.module]["passed"] += 1
            else:
                modules[r.module]["failed"] += 1
        
        summary = {
            "total_tests": self.stats["total"],
            "passed": self.stats["passed"],
            "failed": self.stats["failed"],
            "pass_rate": f"{self.stats['passed'] / max(1, self.stats['total']) * 100:.1f}%",
            "modules": modules,
            "results": [r.to_dict() for r in self.results]
        }
        
        # 打印汇总
        logger.info("")
        logger.info("=" * 60)
        logger.info("测试汇总")
        logger.info("=" * 60)
        logger.info(f"总计: {summary['total_tests']} | ✅ 通过: {summary['passed']} | ❌ 失败: {summary['failed']}")
        logger.info(f"通过率: {summary['pass_rate']}")
        logger.info("")
        
        logger.info("各模块通过率:")
        for module, stats in summary["modules"].items():
            rate = stats["passed"] / max(1, stats["total"]) * 100
            logger.info(f"  {module}: {rate:.0f}% ({stats['passed']}/{stats['total']})")
        
        logger.info("=" * 60)
        
        return summary


def main():
    parser = argparse.ArgumentParser(description="六模块测试工具")
    parser.add_argument("--module", choices=["presale", "aftersale", "profile", "shop", "query", "management", "all"],
                       default="all", help="测试模块")
    parser.add_argument("--verbose", "-v", action="store_true", help="详细输出")
    parser.add_argument("--url", default="http://127.0.0.1:8000", help="服务器地址")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    args = parser.parse_args()
    
    tester = SixModulesTester(base_url=args.url, verbose=args.verbose)
    
    if args.module == "all":
        summary = tester.run_all_tests()
    else:
        # 单模块测试
        tester.admin_login()
        module_map = {
            "presale": tester.test_presale_module,
            "aftersale": tester.test_aftersale_module,
            "profile": tester.test_profile_module,
            "shop": tester.test_shop_module,
            "query": tester.test_query_module,
            "management": tester.test_management_module,
        }
        module_map.get(args.module, lambda: None)()
        summary = tester.get_summary()
    
    if args.json:
        print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
