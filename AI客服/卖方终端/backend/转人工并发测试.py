# -*- coding: utf-8 -*-
"""
转人工并发压力测试脚本
Transfer-to-Human Concurrency Stress Test

测试场景：
- 50+ 虚拟用户同时请求"转人工"
- 验证坐席分配算法的均衡性
- 检查是否存在"撞线"或数据泄露
- 验证响应时间 <5秒

使用方法：
python 卖方终端\backend\转人工并发测试.py
"""

import sys
import os
import time
import json
import uuid
import threading
import statistics
import concurrent.futures
from datetime import datetime
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from collections import defaultdict

# 添加路径
backend_dir = os.path.dirname(__file__)
seller_root = os.path.dirname(backend_dir)
parent_dir = os.path.dirname(seller_root)
sys.path.insert(0, backend_dir)

import requests

# ============== 配置 ==============
SELLER_BASE = "http://127.0.0.1:8000"
BUYER_BASE = "http://127.0.0.1:8001"
TEST_PHONE_PREFIX = "139"
TEST_COUNT = 50  # 并发用户数

# ============== 颜色输出 ==============
class Colors:
    OK = '\033[92m'
    FAIL = '\033[91m'
    WARN = '\033[93m'
    INFO = '\033[94m'
    END = '\033[0m'
    BOLD = '\033[1m'

def log(typ, label, msg=""):
    icons = {"OK": "[OK]", "FAIL": "[FAIL]", "WARN": "[WARN]", "INFO": "[INFO]", "PROGRESS": "[>>>]"}
    color = getattr(Colors, typ, Colors.END)
    icon = icons.get(typ, "[--]")
    print(f"{color}{icon}{Colors.END} {Colors.BOLD}{label}{Colors.END} {msg}")


# ============== 数据结构 ==============
@dataclass
class TransferResult:
    """单次转人工测试结果"""
    user_id: int
    session_id: str
    customer_id: str
    success: bool
    response_time_ms: float
    status_code: int
    error: str = ""
    assigned_agent: str = ""


@dataclass
class TestSummary:
    """测试汇总"""
    total_users: int
    successful_transfers: int
    failed_transfers: int
    total_response_time_ms: float
    min_response_ms: float
    max_response_ms: float
    avg_response_ms: float
    median_response_ms: float
    success_rate: float
    data_leakage: List[str] = field(default_factory=list)
    agent_distribution: Dict[str, int] = field(default_factory=dict)


# ============== 模拟买家客户端 ==============
class SimulatedBuyer:
    """模拟买家客户端"""

    def __init__(self, user_id: int, phone: str):
        self.user_id = user_id
        self.phone = phone
        self.session_id = None
        self.customer_id = None

    def start_session(self, timeout: float = 10.0) -> bool:
        """开始会话"""
        try:
            start_time = time.perf_counter()
            resp = requests.post(
                f"{BUYER_BASE}/api/customer/start",
                json={"phone": self.phone},
                timeout=timeout
            )
            response_time = (time.perf_counter() - start_time) * 1000

            if resp.status_code == 200:
                data = resp.json()
                self.session_id = data.get("session_id", "")
                customer_info = data.get("customer_info", {})
                if isinstance(customer_info, dict):
                    self.customer_id = customer_info.get("customer", {}).get("customer_id", "")
                else:
                    self.customer_id = str(self.phone)
                log("INFO", f"User-{self.user_id}", f"会话已建立: {self.session_id}")
                return True
            else:
                log("FAIL", f"User-{self.user_id}", f"会话建立失败: {resp.status_code}")
                return False
        except Exception as e:
            log("FAIL", f"User-{self.user_id}", f"会话建立异常: {e}")
            return False

    def transfer_to_human(self, timeout: float = 10.0) -> TransferResult:
        """请求转人工"""
        if not self.session_id:
            return TransferResult(
                user_id=self.user_id,
                session_id="",
                customer_id=self.customer_id or "",
                success=False,
                response_time_ms=0,
                status_code=0,
                error="No session"
            )

        try:
            start_time = time.perf_counter()
            resp = requests.post(
                f"{BUYER_BASE}/api/customer/transfer-to-human",
                params={"session_id": self.session_id},
                timeout=timeout
            )
            response_time_ms = (time.perf_counter() - start_time) * 1000

            success = resp.status_code == 200
            assigned_agent = ""
            error = ""

            if success:
                data = resp.json()
                assigned_agent = data.get("assigned_agent", "") or data.get("agent_id", "")
            else:
                error = resp.text[:100] if resp.text else f"HTTP {resp.status_code}"

            return TransferResult(
                user_id=self.user_id,
                session_id=self.session_id,
                customer_id=self.customer_id or "",
                success=success,
                response_time_ms=response_time_ms,
                status_code=resp.status_code,
                error=error,
                assigned_agent=assigned_agent
            )
        except requests.exceptions.Timeout:
            return TransferResult(
                user_id=self.user_id,
                session_id=self.session_id or "",
                customer_id=self.customer_id or "",
                success=False,
                response_time_ms=timeout * 1000,
                status_code=0,
                error="Timeout"
            )
        except Exception as e:
            return TransferResult(
                user_id=self.user_id,
                session_id=self.session_id or "",
                customer_id=self.customer_id or "",
                success=False,
                response_time_ms=0,
                status_code=0,
                error=str(e)
            )

    def get_my_info(self, timeout: float = 10.0) -> Optional[Dict]:
        """获取我的信息（测试数据隔离）"""
        if not self.session_id:
            return None

        try:
            resp = requests.post(
                f"{BUYER_BASE}/api/customer/myinfo",
                json={"session_id": self.session_id},
                timeout=timeout
            )
            if resp.status_code == 200:
                return resp.json()
            return None
        except Exception:
            return None


# ============== 并发测试执行器 ==============
class ConcurrencyTester:
    """并发测试执行器"""

    def __init__(self, user_count: int = 50):
        self.user_count = user_count
        self.results: List[TransferResult] = []
        self.lock = threading.Lock()

    def run_single_user(self, user_id: int) -> TransferResult:
        """执行单个用户测试"""
        phone = f"{TEST_PHONE_PREFIX}{10000000 + user_id}"
        buyer = SimulatedBuyer(user_id, phone)

        # 1. 建立会话
        if not buyer.start_session():
            return TransferResult(
                user_id=user_id,
                session_id="",
                customer_id=phone,
                success=False,
                response_time_ms=0,
                status_code=0,
                error="Session creation failed"
            )

        # 2. 请求转人工
        result = buyer.transfer_to_human()
        return result

    def run_concurrent_test(self) -> TestSummary:
        """运行并发测试"""
        log("INFO", "并发测试", f"启动 {self.user_count} 个虚拟用户...")
        start_time = time.perf_counter()

        # 使用线程池执行并发测试
        results: List[TransferResult] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.user_count) as executor:
            futures = [executor.submit(self.run_single_user, i) for i in range(self.user_count)]
            completed = 0

            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                results.append(result)
                completed += 1

                # 进度显示
                if completed % 10 == 0:
                    success_count = sum(1 for r in results if r.success)
                    log("PROGRESS", "进度", f"{completed}/{self.user_count} 完成，成功: {success_count}")

        total_time = (time.perf_counter() - start_time) * 1000

        # 计算统计
        successful = [r for r in results if r.success]
        failed = [r for r in results if not r.success]
        response_times = [r.response_time_ms for r in successful]

        summary = TestSummary(
            total_users=self.user_count,
            successful_transfers=len(successful),
            failed_transfers=len(failed),
            total_response_time_ms=total_time,
            min_response_ms=min(response_times) if response_times else 0,
            max_response_ms=max(response_times) if response_times else 0,
            avg_response_ms=statistics.mean(response_times) if response_times else 0,
            median_response_ms=statistics.median(response_times) if response_times else 0,
            success_rate=len(successful) / self.user_count * 100,
        )

        # 检查数据泄露
        summary.data_leakage = self._check_data_leakage(successful)

        # 统计坐席分配
        summary.agent_distribution = self._count_agent_distribution(successful)

        return summary

    def _check_data_leakage(self, successful_results: List[TransferResult]) -> List[str]:
        """检查数据泄露"""
        leakage = []

        # 收集所有会话ID
        all_sessions = set(r.session_id for r in successful_results)
        all_customers = set(r.customer_id for r in successful_results)

        # 检查是否有重复的会话ID
        if len(all_sessions) != len(successful_results):
            leakage.append(f"会话ID重复: {len(successful_results)} 用户但只有 {len(all_sessions)} 个唯一会话")

        # 检查是否有空的客户ID
        empty_customers = [r for r in successful_results if not r.customer_id]
        if empty_customers:
            leakage.append(f"{len(empty_customers)} 个结果缺少客户ID")

        return leakage

    def _count_agent_distribution(self, successful_results: List[TransferResult]) -> Dict[str, int]:
        """统计坐席分配"""
        distribution = defaultdict(int)
        for r in successful_results:
            agent = r.assigned_agent or "unassigned"
            distribution[agent] += 1
        return dict(distribution)


# ============== SLA 检查 ==============
def check_sla(summary: TestSummary, max_response_ms: float = 5000) -> Dict:
    """检查SLA合规性"""

    checks = {
        "success_rate": {
            "name": "成功率 >= 95%",
            "expected": ">= 95%",
            "actual": f"{summary.success_rate:.1f}%",
            "passed": summary.success_rate >= 95
        },
        "avg_response": {
            "name": f"平均响应 < {max_response_ms}ms",
            "expected": f"< {max_response_ms}ms",
            "actual": f"{summary.avg_response_ms:.1f}ms",
            "passed": summary.avg_response_ms < max_response_ms
        },
        "max_response": {
            "name": f"最大响应 < {max_response_ms}ms",
            "expected": f"< {max_response_ms}ms",
            "actual": f"{summary.max_response_ms:.1f}ms",
            "passed": summary.max_response_ms < max_response_ms
        },
        "no_data_leakage": {
            "name": "无数据泄露",
            "expected": "0 泄露项",
            "actual": f"{len(summary.data_leakage)} 泄露项",
            "passed": len(summary.data_leakage) == 0
        },
        "balanced_allocation": {
            "name": "坐席分配均衡",
            "expected": "无单一坐席承担 >50%",
            "actual": _get_allocation_status(summary.agent_distribution),
            "passed": _is_allocation_balanced(summary.agent_distribution, summary.successful_transfers)
        }
    }

    passed = sum(1 for c in checks.values() if c["passed"])
    return {
        "checks": checks,
        "passed_count": passed,
        "total_checks": len(checks),
        "pass_rate": f"{passed / len(checks) * 100:.0f}%",
        "overall_passed": passed == len(checks)
    }


def _get_allocation_status(distribution: Dict[str, int]) -> str:
    """获取分配状态描述"""
    if not distribution:
        return "无分配数据"
    max_agent = max(distribution.items(), key=lambda x: x[1])
    return f"最多分配给 {max_agent[0]}: {max_agent[1]} 次"


def _is_allocation_balanced(distribution: Dict[str, int], total: int) -> bool:
    """检查分配是否均衡"""
    if not distribution or total == 0:
        return True

    max_ratio = max(count / total for count in distribution.values())
    return max_ratio <= 0.6  # 单个坐席不超过60%


# ============== 主测试函数 ==============
def run_stress_test(user_count: int = 50) -> Dict:
    """运行压力测试"""

    print("\n" + "=" * 60)
    print(f"转人工并发压力测试")
    print(f"测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"并发用户: {user_count}")
    print("=" * 60)

    # 1. 检查服务可用性
    print("\n[1/3] 检查服务可用性...")
    try:
        seller_resp = requests.get(f"{SELLER_BASE}/health", timeout=5)
        seller_ok = seller_resp.status_code == 200
    except Exception:
        seller_ok = False

    try:
        buyer_resp = requests.get(f"{BUYER_BASE}/health", timeout=5)
        buyer_ok = buyer_resp.status_code == 200
    except Exception:
        buyer_ok = False

    if not buyer_ok:
        log("FAIL", "服务检查", f"买方系统 ({BUYER_BASE}) 不可用，请先启动服务")
        return {
            "error": "买方系统不可用",
            "seller_available": seller_ok,
            "buyer_available": buyer_ok
        }

    log("OK", "服务检查", f"卖方: {'OK' if seller_ok else '离线'}, 买方: {'OK' if buyer_ok else '离线'}")

    # 2. 运行并发测试
    print(f"\n[2/3] 运行并发测试 ({user_count} 用户)...")
    tester = ConcurrencyTester(user_count=user_count)
    summary = tester.run_concurrent_test()

    # 3. SLA检查
    print(f"\n[3/3] SLA合规性检查...")
    sla_result = check_sla(summary)

    # 输出结果
    print("\n" + "=" * 60)
    print("测试结果汇总")
    print("=" * 60)
    print(f"总用户数:       {summary.total_users}")
    print(f"成功转人工:     {summary.successful_transfers}")
    print(f"失败转人工:     {summary.failed_transfers}")
    print(f"成功率:         {summary.success_rate:.1f}%")
    print(f"平均响应时间:   {summary.avg_response_ms:.1f}ms")
    print(f"最大响应时间:   {summary.max_response_ms:.1f}ms")
    print(f"最小响应时间:   {summary.min_response_ms:.1f}ms")
    print(f"中位数响应:     {summary.median_response_ms:.1f}ms")

    if summary.agent_distribution:
        print(f"\n坐席分配分布:")
        for agent, count in sorted(summary.agent_distribution.items(), key=lambda x: -x[1]):
            ratio = count / summary.successful_transfers * 100
            print(f"  {agent}: {count} ({ratio:.1f}%)")

    if summary.data_leakage:
        print(f"\n⚠️  数据泄露警告:")
        for leak in summary.data_leakage:
            print(f"  - {leak}")

    print(f"\nSLA检查 ({sla_result['passed_count']}/{sla_result['total_checks']} 通过):")
    for name, check in sla_result["checks"].items():
        status = "✅" if check["passed"] else "❌"
        print(f"  {status} {check['name']}")
        print(f"     预期: {check['expected']}, 实际: {check['actual']}")

    # 总体结论
    print("\n" + "=" * 60)
    if sla_result["overall_passed"]:
        log("OK", "最终结论", "✅ 所有SLA检查通过，系统可以部署到生产环境")
    else:
        log("WARN", "最终结论", f"⚠️  {sla_result['total_checks'] - sla_result['passed_count']} 项SLA检查未通过，建议修复后再部署")
    print("=" * 60)

    return {
        "summary": {
            "total_users": summary.total_users,
            "successful_transfers": summary.successful_transfers,
            "failed_transfers": summary.failed_transfers,
            "success_rate": f"{summary.success_rate:.1f}%",
            "avg_response_ms": f"{summary.avg_response_ms:.1f}",
            "max_response_ms": f"{summary.max_response_ms:.1f}",
            "min_response_ms": f"{summary.min_response_ms:.1f}",
        },
        "sla": sla_result,
        "agent_distribution": summary.agent_distribution,
        "data_leakage": summary.data_leakage,
        "timestamp": datetime.now().isoformat()
    }


# ============== 入口 ==============
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="转人工并发压力测试")
    parser.add_argument("-n", "--users", type=int, default=TEST_COUNT, help=f"并发用户数 (默认: {TEST_COUNT})")
    args = parser.parse_args()

    result = run_stress_test(user_count=args.users)

    # 保存结果
    result_file = os.path.join(backend_dir, "转人工并发测试结果.json")
    with open(result_file, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n结果已保存: {result_file}")
