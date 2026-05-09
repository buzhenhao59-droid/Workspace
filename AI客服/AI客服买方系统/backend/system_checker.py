# -*- coding: utf-8 -*-
"""
买方系统自检模块 - 全面检查所有依赖服务和组件状态
用于启动前验证和运行时健康监控

检查项目：
1. Neo4j 数据库连接
2. DeepSeek AI API
3. GraphRAG 代理
4. SQLite 共享数据库
5. 卖方-买方跨系统通信
6. 安全配置
7. 端口可用性
"""
from __future__ import annotations

import json
import logging
import os
import socket
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ============== 配置加载（优先统一配置）==============
try:
    from dotenv import load_dotenv
    _buyer_root = Path(__file__).parent.parent  # AI客服买方系统根目录
    _unified_env = _buyer_root.parent / ".env"  # 项目根目录 .env（唯一入口）
    if _unified_env.exists():
        load_dotenv(_unified_env, override=False)
    _local_env = _buyer_root / ".env"
    if _local_env.exists():
        load_dotenv(_local_env, override=True)
except Exception:
    pass


# ============== 数据模型（复用卖方的定义）==============

class CheckStatus(str, Enum):
    OK = "ok"
    WARN = "warn"
    FAIL = "fail"
    SKIP = "skip"
    UNKNOWN = "unknown"


class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


@dataclass
class CheckResult:
    name: str
    status: CheckStatus
    severity: Severity
    message: str
    detail: dict = field(default_factory=dict)
    duration_ms: float = 0.0
    suggestions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        d["severity"] = self.severity.value
        return d


@dataclass
class SystemCheckReport:
    timestamp: str
    duration_ms: float
    overall_status: CheckStatus
    critical_count: int
    warn_count: int
    fail_count: int
    pass_count: int
    total_count: int
    categories: dict[str, list[dict]]
    recommendations: list[str]
    system_info: dict[str, Any]

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "duration_ms": self.duration_ms,
            "overall_status": self.overall_status.value,
            "summary": {
                "critical": self.critical_count,
                "warn": self.warn_count,
                "fail": self.fail_count,
                "pass": self.pass_count,
                "total": self.total_count,
            },
            "categories": self.categories,
            "recommendations": self.recommendations,
            "system_info": self.system_info,
        }


# ============== 基础检查函数 ==============

def check_port(host: str, port: int, timeout: float = 2.0) -> tuple[bool, str]:
    """检查端口是否被监听"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0, f"端口 {port} 已监听" if result == 0 else f"端口 {port} 未监听"
    except Exception as e:
        return False, f"端口检查失败: {e}"


def check_http_endpoint(url: str, timeout: float = 5.0) -> tuple[bool, str, dict]:
    """检查 HTTP 端点"""
    try:
        import urllib.request
        import urllib.error

        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.status
            content = resp.read().decode("utf-8", errors="ignore")
            try:
                data = json.loads(content)
            except (json.JSONDecodeError, ValueError):
                data = {"raw": content[:500]}
            return status < 500, f"HTTP {status}", data
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}", {}
    except urllib.error.URLError as e:
        return False, f"连接失败: {e.reason}", {}
    except Exception as e:
        return False, str(e)[:80], {}


def check_neo4j(uri: str, user: str, password: str, timeout: float = 10.0) -> CheckResult:
    """检查 Neo4j 连接"""
    start = time.time()
    name = "Neo4j 数据库连接"

    if not uri or not user:
        return CheckResult(
            name=name, status=CheckStatus.FAIL, severity=Severity.CRITICAL,
            message="NEO4J_URI 或 NEO4J_USER 未配置",
            suggestions=["在买方 .env 中配置 NEO4J_URI 和 NEO4J_USER"]
        )

    try:
        from neo4j import GraphDatabase
        drv = GraphDatabase.driver(uri, auth=(user, password), connection_timeout=timeout)
        with drv.session() as session:
            session.run("RETURN 1 AS n")
        drv.close()
        duration = (time.time() - start) * 1000
        return CheckResult(
            name=name, status=CheckStatus.OK, severity=Severity.INFO,
            message=f"连接成功 ({(time.time() - start)*1000:.0f}ms)",
            detail={"uri": uri, "user": user},
            duration_ms=duration
        )
    except ImportError:
        return CheckResult(
            name=name, status=CheckStatus.FAIL, severity=Severity.CRITICAL,
            message="neo4j 模块未安装",
            suggestions=["运行: pip install neo4j"]
        )
    except Exception as e:
        err_msg = str(e)
        duration = (time.time() - start) * 1000
        suggestions = []

        if "authentication" in err_msg.lower():
            suggestions = ["检查 NEO4J_PASSWORD 是否正确"]
        elif "refused" in err_msg.lower() or "connect" in err_msg.lower():
            suggestions = ["确认 Neo4j 服务已启动", "检查 NEO4J_URI 地址是否正确"]
        elif "SSL" in err_msg or "TLS" in err_msg:
            suggestions = ["Neo4j Aura 需要使用 bolt+s:// 或 neo4j+s:// 协议"]

        return CheckResult(
            name=name, status=CheckStatus.FAIL, severity=Severity.CRITICAL,
            message=f"连接失败: {err_msg[:100]}",
            detail={"uri": uri},
            duration_ms=duration,
            suggestions=suggestions
        )


def check_deepseek(api_key: str, api_url: str, timeout: float = 15.0) -> CheckResult:
    """检查 DeepSeek API"""
    start = time.time()
    name = "DeepSeek AI API"

    if not api_key:
        return CheckResult(
            name=name, status=CheckStatus.FAIL, severity=Severity.CRITICAL,
            message="DEEPSEEK_API_KEY 未配置",
            suggestions=["在买方 .env 中配置 DEEPSEEK_API_KEY"]
        )

    if not api_key.startswith("sk-"):
        return CheckResult(
            name=name, status=CheckStatus.FAIL, severity=Severity.CRITICAL,
            message=f"DEEPSEEK_API_KEY 格式可能错误: {api_key[:10]}...",
            suggestions=["检查 DEEPSEEK_API_KEY 是否正确"]
        )

    try:
        import urllib.request
        import urllib.error

        payload = json.dumps({
            "model": "deepseek-chat",
            "messages": [{"role": "user", "content": "Hello"}],
            "max_tokens": 5,
            "temperature": 0.1
        }).encode("utf-8")

        req = urllib.request.Request(
            api_url,
            data=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST"
        )

        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            duration = (time.time() - start) * 1000

            if resp.status == 200 and data.get("choices"):
                return CheckResult(
                    name=name, status=CheckStatus.OK, severity=Severity.INFO,
                    message=f"API 正常响应 ({(time.time() - start)*1000:.0f}ms)",
                    detail={"model": data.get("model", "deepseek-chat")},
                    duration_ms=duration
                )
            return CheckResult(
                name=name, status=CheckStatus.FAIL, severity=Severity.HIGH,
                message=f"API 响应异常: {str(data)[:100]}",
                duration_ms=duration
            )

    except urllib.error.HTTPError as e:
        err_body = ""
        try:
            err_body = e.read().decode("utf-8")[:200]
        except Exception:
            pass

        if e.code == 401:
            return CheckResult(
                name=name, status=CheckStatus.FAIL, severity=Severity.CRITICAL,
                message="API Key 无效或已过期 (401)",
                suggestions=["检查 DEEPSEEK_API_KEY"]
            )
        elif e.code == 429:
            return CheckResult(
                name=name, status=CheckStatus.WARN, severity=Severity.HIGH,
                message="API 请求过于频繁 (429)",
                suggestions=["降低请求频率"]
            )
        return CheckResult(
            name=name, status=CheckStatus.FAIL, severity=Severity.HIGH,
            message=f"HTTP {e.code}: {err_body[:80] if err_body else '无响应体'}",
            duration_ms=(time.time() - start) * 1000
        )
    except Exception as e:
        return CheckResult(
            name=name, status=CheckStatus.FAIL, severity=Severity.HIGH,
            message=f"API 调用失败: {str(e)[:80]}",
            duration_ms=(time.time() - start) * 1000
        )


def check_graphrag(api_url: str, timeout: float = 5.0) -> CheckResult:
    """检查 GraphRAG 代理状态"""
    start = time.time()
    name = "GraphRAG 知识检索"

    if not api_url:
        return CheckResult(
            name=name, status=CheckStatus.SKIP, severity=Severity.INFO,
            message="GraphRAG 未配置（AI 回复将不包含客户档案上下文）",
            suggestions=["配置 GRAPHRAG_API_URL"]
        )

    try:
        import urllib.request
        import urllib.error

        payload = json.dumps({"customer_id": "ping"}).encode("utf-8")
        req = urllib.request.Request(
            api_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )

        with urllib.request.urlopen(req, timeout=timeout) as resp:
            duration = (time.time() - start) * 1000
            if resp.status == 200:
                return CheckResult(
                    name=name, status=CheckStatus.OK, severity=Severity.INFO,
                    message=f"GraphRAG 运行正常 ({(time.time() - start)*1000:.0f}ms)",
                    duration_ms=duration
                )
            return CheckResult(
                name=name, status=CheckStatus.FAIL, severity=Severity.MEDIUM,
                message=f"GraphRAG 返回 HTTP {resp.status}",
                duration_ms=duration
            )
    except urllib.error.URLError as e:
        return CheckResult(
            name=name, status=CheckStatus.WARN, severity=Severity.MEDIUM,
            message="GraphRAG 代理未运行",
            suggestions=["启动 GraphRAG 代理服务"],
            duration_ms=(time.time() - start) * 1000
        )
    except Exception as e:
        return CheckResult(
            name=name, status=CheckStatus.FAIL, severity=Severity.MEDIUM,
            message=f"GraphRAG 检查失败: {str(e)[:80]}",
            duration_ms=(time.time() - start) * 1000
        )


def check_shared_sqlite_db(db_path: str) -> CheckResult:
    """检查共享 SQLite 数据库"""
    start = time.time()
    name = "共享 SQLite 数据库"

    if not db_path:
        return CheckResult(
            name=name, status=CheckStatus.SKIP, severity=Severity.INFO,
            message="共享数据库路径未配置",
            duration_ms=(time.time() - start) * 1000
        )

    db_file = Path(db_path)
    if not db_file.exists():
        return CheckResult(
            name=name, status=CheckStatus.WARN, severity=Severity.LOW,
            message=f"数据库文件不存在: {db_path}",
            suggestions=["系统将自动创建数据库文件"],
            duration_ms=(time.time() - start) * 1000
        )

    try:
        conn = sqlite3.connect(db_path, timeout=5)
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]

        required_tables = ["customers", "sessions", "messages", "sellers"]
        missing_tables = [t for t in required_tables if t not in tables]
        size_kb = db_file.stat().st_size / 1024

        conn.close()
        duration = (time.time() - start) * 1000

        if missing_tables:
            return CheckResult(
                name=name, status=CheckStatus.WARN, severity=Severity.MEDIUM,
                message=f"数据库缺少表: {', '.join(missing_tables)}",
                detail={"tables": tables, "size_kb": round(size_kb, 1)},
                duration_ms=duration
            )

        return CheckResult(
            name=name, status=CheckStatus.OK, severity=Severity.INFO,
            message=f"数据库正常 ({len(tables)} 表, {size_kb:.1f} KB)",
            detail={"tables": tables, "size_kb": round(size_kb, 1), "path": str(db_path)},
            duration_ms=duration
        )
    except Exception as e:
        return CheckResult(
            name=name, status=CheckStatus.FAIL, severity=Severity.HIGH,
            message=f"数据库访问失败: {str(e)[:80]}",
            duration_ms=(time.time() - start) * 1000
        )


def check_seller_connectivity(seller_api_host: str, timeout: float = 5.0) -> CheckResult:
    """检查卖方系统连通性"""
    start = time.time()
    name = "卖方系统连接"

    if not seller_api_host:
        return CheckResult(
            name=name, status=CheckStatus.FAIL, severity=Severity.CRITICAL,
            message="SELLER_API_HOST 未配置",
            suggestions=["在买方 .env 中配置 SELLER_API_HOST"]
        )

    url = f"{seller_api_host}/health"
    ok, msg, data = check_http_endpoint(url, timeout=timeout)

    if ok:
        return CheckResult(
            name=name, status=CheckStatus.OK, severity=Severity.INFO,
            message=f"卖方系统可达 ({seller_api_host})",
            detail={"seller_api": seller_api_host},
            duration_ms=(time.time() - start) * 1000
        )
    else:
        return CheckResult(
            name=name, status=CheckStatus.WARN, severity=Severity.HIGH,
            message=f"无法连接卖方系统: {msg}",
            suggestions=[
                "确认卖方系统（端口 8000）已启动",
                "检查 SELLER_API_HOST 配置"
            ],
            duration_ms=(time.time() - start) * 1000
        )


def check_security_config(cors_origins: str, secret_key: str) -> list[CheckResult]:
    """检查安全配置"""
    results = []

    # CORS 配置检查
    name = "CORS 配置"
    if "*" in (cors_origins or ""):
        results.append(CheckResult(
            name=name, status=CheckStatus.FAIL, severity=Severity.HIGH,
            message="CORS 允许所有来源（*），存在安全风险",
            suggestions=["设置明确的域名: ALLOWED_ORIGINS=https://your-domain.com"]
        ))
    elif not cors_origins:
        results.append(CheckResult(
            name=name, status=CheckStatus.WARN, severity=Severity.MEDIUM,
            message="CORS 未配置",
            suggestions=["设置 ALLOWED_ORIGINS 环境变量"]
        ))
    else:
        origins_list = [o.strip() for o in cors_origins.split(",") if o.strip()]
        results.append(CheckResult(
            name=name, status=CheckStatus.OK, severity=Severity.INFO,
            message=f"CORS 已配置 {len(origins_list)} 个来源",
            detail={"origins": origins_list}
        ))

    # Secret Key 检查
    name = "密钥配置"
    if not secret_key or secret_key.startswith("buyer-"):
        results.append(CheckResult(
            name=name, status=CheckStatus.WARN, severity=Severity.LOW,
            message="SECRET_KEY 使用默认值",
            suggestions=["修改为强随机密钥"]
        ))
    else:
        results.append(CheckResult(
            name=name, status=CheckStatus.OK, severity=Severity.INFO,
            message="密钥配置正常"
        ))

    return results


def check_buyer_service_ports() -> list[CheckResult]:
    """检查买方服务端口状态"""
    results = []
    ports = [
        (8001, "买方 FastAPI (端口 8001)", Severity.INFO),
        (8000, "卖方 FastAPI (端口 8000)", Severity.INFO),
        (5050, "GraphRAG 代理 (端口 5050)", Severity.LOW),
        (5051, "GraphRAG 买方端口 (端口 5051)", Severity.LOW),
    ]

    for port, name, default_severity in ports:
        ok, msg = check_port("127.0.0.1", port)
        if ok:
            results.append(CheckResult(
                name=name, status=CheckStatus.OK, severity=Severity.INFO,
                message="端口已被监听"
            ))
        else:
            if port in (8001,):
                severity = Severity.MEDIUM
                suggestions = ["确认买方服务已启动"]
            else:
                severity = default_severity
                suggestions = []
            results.append(CheckResult(
                name=name, status=CheckStatus.WARN, severity=severity,
                message="端口未监听",
                suggestions=suggestions if suggestions else None
            ))

    return results


def get_system_resources() -> dict:
    """获取系统资源使用情况"""
    try:
        import psutil

        cpu_percent = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        proc = psutil.Process()
        proc_mem_mb = proc.memory_info().rss / (1024 * 1024)
        proc_cpu = proc.cpu_percent(interval=0.1)

        return {
            "cpu_percent": round(cpu_percent, 1),
            "memory_total_gb": round(mem.total / (1024**3), 2),
            "memory_used_gb": round(mem.used / (1024**3), 2),
            "memory_percent": round(mem.percent, 1),
            "disk_total_gb": round(disk.total / (1024**3), 2),
            "disk_used_gb": round(disk.used / (1024**3), 2),
            "disk_percent": round(disk.percent, 1),
            "process_memory_mb": round(proc_mem_mb, 1),
            "process_cpu_percent": round(proc_cpu, 1),
            "process_uptime_seconds": int(time.time() - proc.create_time()),
        }
    except ImportError:
        return {"error": "psutil 未安装，无法获取系统资源"}
    except Exception as e:
        return {"error": str(e)}


def generate_recommendations(results: list[CheckResult]) -> list[str]:
    """根据检查结果生成优化建议"""
    recommendations = []

    critical_issues = [r for r in results if r.severity == Severity.CRITICAL]
    if critical_issues:
        recommendations.append("【紧急】存在阻断性错误，必须修复后才能启动服务")
        for r in critical_issues[:3]:
            if r.suggestions:
                recommendations.append(f"  - {r.name}: {r.suggestions[0]}")

    high_warns = [r for r in results if r.severity == Severity.HIGH and r.status != CheckStatus.OK]
    if high_warns:
        recommendations.append("【重要】以下功能受限:")
        for r in high_warns[:3]:
            if r.suggestions:
                recommendations.append(f"  - {r.name}: {r.suggestions[0]}")

    return recommendations


# ============== 买方检查器类 ==============

class BuyerSystemChecker:
    """
    买方系统完整自检器
    """

    def __init__(self, config: dict[str, str] = None):
        if config:
            self.config = config
        else:
            self.config = dict(os.environ)

    def _get(self, key: str, default: str = "") -> str:
        return self.config.get(key, default)

    def run_all_checks(self, parallel: bool = True) -> SystemCheckReport:
        """运行所有检查"""
        start_time = time.time()

        checks = self._define_checks()

        if parallel:
            results = self._run_parallel(checks)
        else:
            results = self._run_sequential(checks)

        # 分类结果
        categories = {}
        for r in results:
            cat = r.name.split()[0] if r.name else "其他"
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(r.to_dict())

        # 统计
        critical = sum(1 for r in results if r.severity == Severity.CRITICAL and r.status == CheckStatus.FAIL)
        warns = sum(1 for r in results if r.status == CheckStatus.WARN)
        fails = sum(1 for r in results if r.status == CheckStatus.FAIL and r.severity != Severity.CRITICAL)
        passes = sum(1 for r in results if r.status == CheckStatus.OK)

        # 确定整体状态
        if critical > 0:
            overall = CheckStatus.FAIL
        elif fails > 0:
            overall = CheckStatus.FAIL
        elif warns > 0:
            overall = CheckStatus.WARN
        else:
            overall = CheckStatus.OK

        duration = (time.time() - start_time) * 1000

        return SystemCheckReport(
            timestamp=datetime.now().isoformat(),
            duration_ms=duration,
            overall_status=overall,
            critical_count=critical,
            warn_count=warns,
            fail_count=fails,
            pass_count=passes,
            total_count=len(results),
            categories=categories,
            recommendations=generate_recommendations(results),
            system_info=get_system_resources()
        )

    def _define_checks(self) -> list[tuple[str, callable]]:
        checks = []

        # 1. 端口检查
        checks.append(("端口", lambda: check_buyer_service_ports()))

        # 2. 数据库检查
        checks.append(("数据库", lambda: [check_neo4j(
            self._get("NEO4J_URI"),
            self._get("NEO4J_USER"),
            self._get("NEO4J_PASSWORD")
        )]))

        # 自动推导买方共享数据库路径
        _buyer_root = Path(__file__).resolve().parent.parent
        _fallback_db = str((_buyer_root.parent / "卖方终端" / "data" / "gold_customer.db").resolve())
        checks.append(("数据库", lambda: [check_shared_sqlite_db(
            self._get("SHARED_DB_PATH", _fallback_db)
        )]))

        # 3. AI 服务检查
        checks.append(("AI服务", lambda: [check_deepseek(
            self._get("DEEPSEEK_API_KEY"),
            self._get("DEEPSEEK_API_URL", "https://api.deepseek.com/v1/chat/completions")
        )]))

        checks.append(("AI服务", lambda: [check_graphrag(
            self._get("GRAPHRAG_API_URL", "http://127.0.0.1:5050/query")
        )]))

        # 4. 跨系统通信
        checks.append(("通信", lambda: [check_seller_connectivity(
            self._get("SELLER_API_HOST", "http://127.0.0.1:8000")
        )]))

        # 5. 安全配置
        checks.append(("安全", lambda: check_security_config(
            self._get("ALLOWED_ORIGINS"),
            self._get("SECRET_KEY")
        )))

        return checks

    def _run_sequential(self, checks: list[tuple[str, callable]]) -> list[CheckResult]:
        results = []
        for category, check_func in checks:
            try:
                result = check_func()
                if isinstance(result, list):
                    results.extend(result)
                else:
                    results.append(result)
            except Exception as e:
                results.append(CheckResult(
                    name=category, status=CheckStatus.UNKNOWN, severity=Severity.INFO,
                    message=f"检查执行失败: {str(e)[:80]}"
                ))
        return results

    def _run_parallel(self, checks: list[tuple[str, callable]]) -> list[CheckResult]:
        results = [None] * len(checks)

        def run_check(index: int, category: str, check_func: callable):
            try:
                result = check_func()
                results[index] = result if isinstance(result, list) else [result]
            except Exception as e:
                results[index] = [CheckResult(
                    name=category, status=CheckStatus.UNKNOWN, severity=Severity.INFO,
                    message=f"检查执行失败: {str(e)[:80]}"
                )]

        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = [
                executor.submit(run_check, i, cat, func)
                for i, (cat, func) in enumerate(checks)
            ]
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    logger.error(f"并行检查执行失败: {e}")

        flat_results = []
        for r in results:
            if r:
                flat_results.extend(r if isinstance(r, list) else [r])
        return flat_results


# ============== 便捷函数 ==============

def quick_health_check() -> dict:
    """快速健康检查"""
    checks = {
        "neo4j": False,
        "deepseek": False,
        "seller_api": False,
    }

    # Neo4j
    try:
        from neo4j import GraphDatabase
        uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        user = os.getenv("NEO4J_USER", "neo4j")
        password = os.getenv("NEO4J_PASSWORD", "")
        drv = GraphDatabase.driver(uri, auth=(user, password), connection_timeout=3)
        with drv.session() as session:
            session.run("RETURN 1")
        drv.close()
        checks["neo4j"] = True
    except Exception:
        pass

    # DeepSeek
    try:
        import urllib.request
        api_key = os.getenv("DEEPSEEK_API_KEY", "")
        api_url = os.getenv("DEEPSEEK_API_URL", "https://api.deepseek.com/v1/chat/completions")
        if api_key:
            payload = json.dumps({
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 2
            }).encode()
            req = urllib.request.Request(
                api_url, data=payload,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                checks["deepseek"] = resp.status == 200
    except Exception:
        pass

    # Seller API
    try:
        import urllib.request
        seller_host = os.getenv("SELLER_API_HOST", "http://127.0.0.1:8000")
        req = urllib.request.Request(f"{seller_host}/health")
        with urllib.request.urlopen(req, timeout=3) as resp:
            checks["seller_api"] = resp.status == 200
    except Exception:
        pass

    all_ok = all(checks.values())
    return {
        "status": "ok" if all_ok else "degraded",
        "checks": checks,
        "timestamp": datetime.now().isoformat()
    }


# ============== CLI 入口 ==============

def main():
    """命令行入口"""
    import argparse

    parser = argparse.ArgumentParser(description="买方系统自检工具")
    parser.add_argument("--quick", "-q", action="store_true", help="快速检查")
    parser.add_argument("--json", "-j", action="store_true", help="JSON 格式输出")
    args = parser.parse_args()

    print("=" * 70)
    print("  买方系统自检  " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 70)

    checker = BuyerSystemChecker()

    if args.quick:
        result = quick_health_check()
        print(f"\n整体状态: {result['status'].upper()}")
        print("\n检查项:")
        for name, status in result["checks"].items():
            icon = "[OK]" if status else "[FAIL]"
            print(f"  {icon} {name}")
        print(f"\n时间: {result['timestamp']}")
        return 0 if result["status"] == "ok" else 1

    # 完整检查
    report = checker.run_all_checks()

    print(f"\n检查完成，耗时: {report.duration_ms:.0f}ms")
    print(f"\n整体状态: {report.overall_status.value.upper()}")
    print(f"  通过: {report.pass_count}")
    print(f"  警告: {report.warn_count}")
    print(f"  失败: {report.fail_count}")
    print(f"  阻塞: {report.critical_count}")

    print("\n" + "-" * 70)
    print("详细结果:")
    for category, items in report.categories.items():
        print(f"\n【{category}】")
        for item in items:
            status = item["status"]
            icon = {"ok": "✓", "warn": "⚠", "fail": "✗", "skip": "○", "unknown": "?"}.get(status, "?")
            print(f"  {icon} [{status.upper():6}] {item['name']}")
            if item.get("message"):
                print(f"       {item['message']}")
            if item.get("suggestions") and status in ("fail", "warn"):
                for suggestion in item["suggestions"][:2]:
                    print(f"       → {suggestion}")

    if report.recommendations:
        print("\n" + "=" * 70)
        print("优化建议:")
        for rec in report.recommendations[:5]:
            print(f"  {rec}")

    if report.system_info and "error" not in report.system_info:
        print("\n" + "-" * 70)
        print("系统资源:")
        si = report.system_info
        print(f"  CPU: {si.get('cpu_percent', 'N/A')}%")
        print(f"  内存: {si.get('memory_used_gb', 'N/A')}GB / {si.get('memory_total_gb', 'N/A')}GB")
        print(f"  进程内存: {si.get('process_memory_mb', 'N/A')}MB")

    if args.json:
        print("\n" + "=" * 70)
        print("JSON 输出:")
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))

    return 0 if report.overall_status == CheckStatus.OK else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
