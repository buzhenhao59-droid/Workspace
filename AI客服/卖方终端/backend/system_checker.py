# -*- coding: utf-8 -*-
"""
卖方系统自检模块 - 全面检查所有依赖服务和组件状态
用于启动前验证和运行时健康监控

检查项目：
1. 端口可用性（FastAPI 8000, Flask 5000, GraphRAG 5050）
2. Neo4j 数据库连接
3. Redis 连接和状态
4. DeepSeek API 连通性
5. GraphRAG 代理状态
6. SQLite 数据库文件
7. MySQL 连接（可选）
8. 各电商平台 API 配置
9. 物流 API 配置
10. JWT 配置安全性
11. CORS 配置
12. 熔断器状态
13. 坐席在线状态
14. 会话统计
15. 系统资源（CPU/内存/磁盘）
16. 跨系统通信（买方-卖方）
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional

# 加载环境变量（优先统一配置）
try:
    from dotenv import load_dotenv
    _script_dir = Path(__file__).parent
    _project_root = _script_dir.parent  # 卖方终端根目录
    # 统一配置（唯一入口）
    _unified_env = _project_root.parent / ".env"  # 项目根目录 .env
    if _unified_env.exists():
        load_dotenv(_unified_env, override=False)
    # 本地 .env（向后兼容）
    _local_env = _project_root / ".env"
    if _local_env.exists():
        load_dotenv(_local_env, override=True)
except Exception:
    pass


def _auto_db_path() -> str:
    """自动推导卖方 SQLite 数据库路径"""
    _shared = os.getenv("SHARED_DB_PATH", "")
    if _shared:
        return _shared
    _self = Path(__file__).resolve().parent  # backend/
    _project_root = _self.parent              # 卖方终端/
    return str((_project_root / "data" / "gold_customer.db").resolve())


logger = logging.getLogger(__name__)


# ============== 数据模型 ==============

class CheckStatus(str, Enum):
    """检查状态"""
    OK = "ok"                    # 正常
    WARN = "warn"                # 警告（可接受但需关注）
    FAIL = "fail"                # 失败（阻塞性）
    SKIP = "skip"                # 跳过（未配置）
    UNKNOWN = "unknown"           # 未知


class Severity(str, Enum):
    """严重等级"""
    CRITICAL = "critical"         # 致命：服务无法启动
    HIGH = "high"                # 高：功能受限
    MEDIUM = "medium"            # 中：性能或安全风险
    LOW = "low"                  # 低：建议改进
    INFO = "info"                # 信息：提示


@dataclass
class CheckResult:
    """单项检查结果"""
    name: str                    # 检查项名称
    status: CheckStatus          # 状态
    severity: Severity           # 严重等级
    message: str                  # 详细信息
    detail: dict = field(default_factory=dict)  # 额外数据
    duration_ms: float = 0.0      # 检查耗时（毫秒）
    suggestions: list[str] = field(default_factory=list)  # 修复建议

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        d["severity"] = self.severity.value
        return d


@dataclass
class SystemCheckReport:
    """完整系统检查报告"""
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
        if result == 0:
            return True, f"端口 {port} 已监听"
        return False, f"端口 {port} 未监听"
    except Exception as e:
        return False, f"端口检查失败: {e}"


def check_http_endpoint(url: str, timeout: float = 5.0, method: str = "GET") -> tuple[bool, str, dict]:
    """
    检查 HTTP 端点是否可达
    返回: (是否成功, 消息, 响应数据)
    """
    try:
        import urllib.request
        import urllib.error

        req = urllib.request.Request(url, method=method)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.status
            content = resp.read().decode("utf-8", errors="ignore")
            try:
                data = json.loads(content)
            except (json.JSONDecodeError, ValueError):
                data = {"raw": content[:500]}
            success = status < 500
            return success, f"HTTP {status}", data
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
            suggestions=["在 .env 中配置 NEO4J_URI 和 NEO4J_USER"]
        )

    try:
        from neo4j import GraphDatabase
        drv = GraphDatabase.driver(uri, auth=(user, password), connection_timeout=timeout)
        with drv.session() as session:
            result = session.run("RETURN 1 AS n")
            result.single()
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

        # 诊断具体错误
        suggestions = []
        if "authentication" in err_msg.lower():
            suggestions = ["检查 NEO4J_PASSWORD 是否正确"]
        elif "refused" in err_msg.lower() or "connect" in err_msg.lower():
            suggestions = [
                "确认 Neo4j 服务已启动",
                "检查 NEO4J_URI 地址是否正确（本地: bolt://localhost:7687）",
                "检查防火墙设置"
            ]
        elif "SSL" in err_msg or "TLS" in err_msg:
            suggestions = [
                "Neo4j Aura 需要使用 bolt+s:// 或 neo4j+s:// 协议",
                "确认 NEO4J_URI 以 bolt+s:// 开头"
            ]
        else:
            suggestions = ["查看完整错误信息"]

        return CheckResult(
            name=name, status=CheckStatus.FAIL, severity=Severity.CRITICAL,
            message=f"连接失败: {err_msg[:100]}",
            detail={"uri": uri},
            duration_ms=duration,
            suggestions=suggestions
        )


def check_redis(host: str, port: int, password: str = "", db: int = 0, timeout: float = 5.0) -> CheckResult:
    """检查 Redis 连接"""
    start = time.time()
    name = "Redis 连接"

    if not host:
        return CheckResult(
            name=name, status=CheckStatus.SKIP, severity=Severity.INFO,
            message="Redis 未配置（将使用内存会话存储，单实例模式）",
            suggestions=["如需分布式部署，安装 Redis: docker run -d -p 6379:6379 redis:alpine"]
        )

    try:
        import redis
        params = {"host": host, "port": port, "db": db, "socket_connect_timeout": timeout}
        if password:
            params["password"] = password
        r = redis.Redis(**params)
        r.ping()
        info = r.info("server")
        latency = (time.time() - start) * 1000
        return CheckResult(
            name=name, status=CheckStatus.OK, severity=Severity.INFO,
            message=f"连接成功，延迟 {latency:.0f}ms",
            detail={
                "host": host, "port": port, "db": db,
                "version": info.get("redis_version", "unknown"),
                "mode": info.get("redis_mode", "unknown"),
            },
            duration_ms=latency
        )
    except ImportError:
        return CheckResult(
            name=name, status=CheckStatus.SKIP, severity=Severity.LOW,
            message="redis-py 未安装（使用内存会话存储）",
            suggestions=["运行: pip install redis（生产环境推荐）"]
        )
    except Exception as e:
        err_msg = str(e)
        if "REFUSED" in err_msg:
            return CheckResult(
                name=name, status=CheckStatus.WARN, severity=Severity.MEDIUM,
                message="Redis 未运行",
                suggestions=[
                    "安装并启动 Redis: docker run -d -p 6379:6379 redis:alpine",
                    "或安装 Memurai (Windows): https://dist.memurai.com/",
                    "当前使用内存会话存储（服务重启后会话丢失）"
                ]
            )
        return CheckResult(
            name=name, status=CheckStatus.FAIL, severity=Severity.MEDIUM,
            message=f"Redis 连接失败: {err_msg[:80]}",
            suggestions=["检查 Redis 配置和网络连接"]
        )


def check_deepseek(api_key: str, api_url: str, timeout: float = 15.0) -> CheckResult:
    """检查 DeepSeek API 连通性"""
    start = time.time()
    name = "DeepSeek AI API"

    if not api_key:
        return CheckResult(
            name=name, status=CheckStatus.FAIL, severity=Severity.CRITICAL,
            message="DEEPSEEK_API_KEY 未配置",
            suggestions=["在 .env 中配置 DEEPSEEK_API_KEY"]
        )

    if not api_key.startswith("sk-"):
        return CheckResult(
            name=name, status=CheckStatus.FAIL, severity=Severity.CRITICAL,
            message=f"DEEPSEEK_API_KEY 格式可能错误（应使用 sk- 开头）: {api_key[:10]}...",
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

    except ImportError:
        return CheckResult(
            name=name, status=CheckStatus.FAIL, severity=Severity.HIGH,
            message="urllib 不可用",
            suggestions=["检查 Python 环境"]
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
                suggestions=[
                    "检查 DEEPSEEK_API_KEY 是否正确",
                    "确认 API Key 未过期，可在 DeepSeek 平台续费"
                ]
            )
        elif e.code == 429:
            return CheckResult(
                name=name, status=CheckStatus.WARN, severity=Severity.HIGH,
                message="API 请求过于频繁 (429)",
                suggestions=["降低请求频率，稍后重试"]
            )
        return CheckResult(
            name=name, status=CheckStatus.FAIL, severity=Severity.HIGH,
            message=f"HTTP {e.code}: {err_body[:80] if err_body else '无响应体'}",
            duration_ms=(time.time() - start) * 1000
        )
    except Exception as e:
        err_msg = str(e)
        if "timed out" in err_msg.lower():
            return CheckResult(
                name=name, status=CheckStatus.FAIL, severity=Severity.HIGH,
                message="API 请求超时",
                suggestions=["检查网络连接，或 DeepSeek 服务是否正常"]
            )
        return CheckResult(
            name=name, status=CheckStatus.FAIL, severity=Severity.HIGH,
            message=f"API 调用失败: {err_msg[:80]}",
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
            suggestions=["配置 GRAPHRAG_API_URL=http://127.0.0.1:5050/query"]
        )

    try:
        import urllib.request
        import urllib.error

        # 优先用专用健康检查端点（GET /health），否则回退到 POST /query
        health_url = api_url.rstrip("/") + "/health"
        req = urllib.request.Request(health_url, method="GET")

        with urllib.request.urlopen(req, timeout=timeout) as resp:
            duration = (time.time() - start) * 1000
            if resp.status == 200:
                return CheckResult(
                    name=name, status=CheckStatus.OK, severity=Severity.INFO,
                    message=f"GraphRAG 运行正常 ({(time.time() - start)*1000:.0f}ms)",
                    detail={"endpoint": health_url},
                    duration_ms=duration
                )
            return CheckResult(
                name=name, status=CheckStatus.FAIL, severity=Severity.MEDIUM,
                message=f"GraphRAG /health 返回 HTTP {resp.status}",
                detail={"endpoint": health_url},
                duration_ms=duration
            )
    except urllib.error.HTTPError as e:
        # /health 不存在时尝试 /query（需要 customer_id=ping）
        if e.code in (404, 405):
            try:
                payload = json.dumps({"customer_id": "ping"}).encode("utf-8")
                req2 = urllib.request.Request(
                    api_url, data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST"
                )
                with urllib.request.urlopen(req2, timeout=timeout) as resp2:
                    duration = (time.time() - start) * 1000
                    if resp2.status == 200:
                        return CheckResult(
                            name=name, status=CheckStatus.OK, severity=Severity.INFO,
                            message=f"GraphRAG /query 正常 ({(time.time() - start)*1000:.0f}ms)",
                            duration_ms=duration
                        )
                    return CheckResult(
                        name=name, status=CheckStatus.FAIL, severity=Severity.MEDIUM,
                        message=f"GraphRAG /query 返回 HTTP {resp2.status}",
                        duration_ms=duration
                    )
            except Exception:
                pass
        duration = (time.time() - start) * 1000
        return CheckResult(
            name=name, status=CheckStatus.FAIL, severity=Severity.MEDIUM,
            message=f"GraphRAG 连接失败: HTTP {e.code}",
            suggestions=["确认 graphrag_proxy.py 已在 5050 端口启动"],
            duration_ms=duration
        )
    except urllib.error.URLError as e:
        duration = (time.time() - start) * 1000
        if "refused" in str(e.reason).lower():
            return CheckResult(
                name=name, status=CheckStatus.WARN, severity=Severity.MEDIUM,
                message="GraphRAG 代理未运行（端口 5050 未监听）",
                suggestions=[
                    "启动 GraphRAG 代理: python graphrag_proxy.py",
                    "路径: 卖方终端\\backend\\graphrag_proxy.py"
                ],
                duration_ms=duration
            )
        return CheckResult(
            name=name, status=CheckStatus.FAIL, severity=Severity.MEDIUM,
            message=f"GraphRAG 连接失败: {e.reason}",
            suggestions=["检查 GRAPHRAG_API_URL 是否正确"],
            duration_ms=duration
        )
    except Exception as e:
        return CheckResult(
            name=name, status=CheckStatus.FAIL, severity=Severity.MEDIUM,
            message=f"GraphRAG 检查失败: {str(e)[:80]}",
            suggestions=["确认 graphrag_proxy.py 正在运行"],
            duration_ms=(time.time() - start) * 1000
        )


def check_sqlite_db(db_path: str) -> CheckResult:
    """检查 SQLite 数据库"""
    start = time.time()
    name = "SQLite 数据库"

    if not db_path:
        return CheckResult(
            name=name, status=CheckStatus.SKIP, severity=Severity.INFO,
            message="未配置 SQLite 数据库路径",
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

        # 检查关键表
        required_tables = ["customers", "sessions", "messages", "sellers"]
        missing_tables = [t for t in required_tables if t not in tables]

        # 获取数据库大小
        size_kb = db_file.stat().st_size / 1024

        conn.close()
        duration = (time.time() - start) * 1000

        if missing_tables:
            return CheckResult(
                name=name, status=CheckStatus.WARN, severity=Severity.MEDIUM,
                message=f"数据库缺少表: {', '.join(missing_tables)}",
                detail={"tables": tables, "size_kb": round(size_kb, 1), "path": str(db_path)},
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
            suggestions=["检查数据库文件权限和路径"],
            duration_ms=(time.time() - start) * 1000
        )


def check_mysql(host: str, port: int, user: str, password: str, database: str) -> CheckResult:
    """检查 MySQL 连接"""
    start = time.time()
    name = "MySQL 数据库"

    if not host:
        return CheckResult(
            name=name, status=CheckStatus.SKIP, severity=Severity.INFO,
            message="MySQL 未配置（使用 SQLite 回退）",
            suggestions=["如需使用 MySQL，安装并配置 MYSQL_* 环境变量"]
        )

    try:
        import pymysql
        conn = pymysql.connect(
            host=host, port=port, user=user, password=password,
            database=database, connect_timeout=5
        )
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        conn.close()
        duration = (time.time() - start) * 1000
        return CheckResult(
            name=name, status=CheckStatus.OK, severity=Severity.INFO,
            message=f"MySQL 连接成功 ({(time.time() - start)*1000:.0f}ms)",
            detail={"host": host, "port": port, "database": database},
            duration_ms=duration
        )
    except ImportError:
        return CheckResult(
            name=name, status=CheckStatus.SKIP, severity=Severity.INFO,
            message="pymysql 未安装（使用 SQLite）",
            suggestions=["如需 MySQL 支持: pip install pymysql"]
        )
    except Exception as e:
        err_msg = str(e)
        suggestions = ["检查 MySQL 配置和网络连接"]
        if "connect" in err_msg.lower():
            suggestions = [
                "确认 MySQL 服务已启动",
                "检查 MYSQL_HOST/MYSQL_PORT 是否正确"
            ]
        elif "Access denied" in err_msg:
            suggestions = ["检查 MYSQL_USER 和 MYSQL_PASSWORD"]
        return CheckResult(
            name=name, status=CheckStatus.WARN, severity=Severity.MEDIUM,
            message=f"MySQL 连接失败: {err_msg[:80]}",
            suggestions=suggestions,
            duration_ms=(time.time() - start) * 1000
        )


def check_security_config(jwt_secret: str, admin_password: str, cors_origins: str) -> list[CheckResult]:
    """检查安全配置"""
    results = []

    # JWT 密钥检查
    name = "JWT 密钥强度"
    if not jwt_secret or jwt_secret.startswith("dev-") or len(jwt_secret) < 32:
        results.append(CheckResult(
            name=name, status=CheckStatus.FAIL, severity=Severity.CRITICAL,
            message=f"JWT_SECRET_KEY 使用默认值或长度不足（当前 {len(jwt_secret or '')} 字符）",
            suggestions=[
                "生成强随机密钥（建议 64 字符）: python -c \"import secrets; print(secrets.token_hex(32))\"",
                "将新密钥添加到 .env: JWT_SECRET_KEY=your_new_strong_key"
            ]
        ))
    else:
        results.append(CheckResult(
            name=name, status=CheckStatus.OK, severity=Severity.INFO,
            message=f"JWT 密钥长度正常 ({len(jwt_secret)} 字符)"
        ))

    # 管理员密码检查
    name = "管理员密码强度"
    if admin_password == "123456" or len(admin_password) < 6:
        results.append(CheckResult(
            name=name, status=CheckStatus.FAIL, severity=Severity.HIGH,
            message="ADMIN_PASSWORD 使用默认密码或强度不足",
            suggestions=["修改 .env 中的 ADMIN_PASSWORD 为强密码"]
        ))
    else:
        results.append(CheckResult(
            name=name, status=CheckStatus.OK, severity=Severity.INFO,
            message="管理员密码强度正常"
        ))

    # CORS 配置检查
    name = "CORS 配置"
    if "*" in (cors_origins or ""):
        results.append(CheckResult(
            name=name, status=CheckStatus.FAIL, severity=Severity.HIGH,
            message="CORS 允许所有来源（*），存在安全风险",
            suggestions=[
                "在生产环境设置明确的域名",
                "示例: ALLOWED_ORIGINS=https://your-domain.com"
            ]
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

    return results


def check_api_configs(platform_configs: dict) -> list[CheckResult]:
    """检查各电商平台 API 配置"""
    results = []
    platforms = {
        "tiktok": "TikTok Shop",
        "shopee": "Shopee",
        "lazada": "Lazada",
        "amazon": "Amazon",
        "aliexpress": "AliExpress",
        "ebay": "eBay",
        "shopify": "Shopify",
    }

    for key, name in platforms.items():
        url_key = f"{key.upper()}_API_URL"
        url = platform_configs.get(url_key, "")
        name_check = f"{name} API"

        if not url:
            results.append(CheckResult(
                name=name_check, status=CheckStatus.SKIP, severity=Severity.INFO,
                message=f"{name} API 未配置（功能不可用）",
                suggestions=[f"配置 {url_key} 以启用 {name} 集成"]
            ))
        else:
            # 简单检查 URL 格式
            if url.startswith("http"):
                results.append(CheckResult(
                    name=name_check, status=CheckStatus.OK, severity=Severity.INFO,
                    message=f"{name} API 已配置"
                ))
            else:
                results.append(CheckResult(
                    name=name_check, status=CheckStatus.FAIL, severity=Severity.MEDIUM,
                    message=f"{name} API URL 格式不正确: {url[:50]}",
                    suggestions=[f"检查 {url_key} 配置"]
                ))

    return results


def check_logistics_configs(logistics_configs: dict) -> list[CheckResult]:
    """检查物流 API 配置"""
    results = []
    carriers = {
        "dhl": "DHL",
        "fedex": "FedEx",
        "ups": "UPS",
        "yanwen": "燕文物流",
        "fpx": "4PX"
    }

    for key, name in carriers.items():
        url_key = f"{key.upper()}_API_URL"
        url = logistics_configs.get(url_key, "")
        name_check = f"{name} API"

        if not url:
            results.append(CheckResult(
                name=name_check, status=CheckStatus.SKIP, severity=Severity.INFO,
                message=f"{name} API 未配置（物流查询不可用）"
            ))
        else:
            results.append(CheckResult(
                name=name_check, status=CheckStatus.OK, severity=Severity.INFO,
                message=f"{name} API 已配置"
            ))

    return results


def check_service_ports() -> list[CheckResult]:
    """检查服务端口状态"""
    results = []
    ports = [
        (8000, "FastAPI 服务 (端口 8000)", Severity.INFO),
        (5000, "Flask 服务 (端口 5000)", Severity.INFO),
        (5050, "GraphRAG 代理 (端口 5050)", Severity.LOW),
        (6379, "Redis (端口 6379)", Severity.LOW),
    ]

    for port, name, default_severity in ports:
        ok, msg = check_port("127.0.0.1", port)
        if ok:
            results.append(CheckResult(
                name=name, status=CheckStatus.OK, severity=Severity.INFO,
                message="端口已被监听"
            ))
        else:
            if port in (8000,):
                severity = Severity.MEDIUM
                suggestions = ["确认服务已启动"]
            else:
                severity = default_severity
                suggestions = []

            results.append(CheckResult(
                name=name, status=CheckStatus.WARN, severity=severity,
                message="端口未监听",
                suggestions=suggestions if suggestions else None
            ))

    return results


def check_cross_system_communication(seller_api_host: str, internal_token: str) -> CheckResult:
    """检查买方-卖方跨系统通信"""
    start = time.time()
    name = "跨系统通信（买方-卖方）"

    if not seller_api_host:
        return CheckResult(
            name=name, status=CheckStatus.SKIP, severity=Severity.INFO,
            message="卖方 API 地址未配置"
        )

    # 尝试访问卖方健康检查端点
    url = f"{seller_api_host}/health"
    ok, msg, data = check_http_endpoint(url, timeout=5)

    if ok:
        return CheckResult(
            name=name, status=CheckStatus.OK, severity=Severity.INFO,
            message=f"卖方系统可达 ({seller_api_host})",
            detail={"seller_api": seller_api_host},
            duration_ms=(time.time() - start) * 1000
        )
    else:
        return CheckResult(
            name=name, status=CheckStatus.WARN, severity=Severity.MEDIUM,
            message=f"无法连接卖方系统: {msg}",
            suggestions=[
                "确认卖方系统（端口 8000）已启动",
                "检查 SELLER_API_HOST 配置是否正确"
            ],
            duration_ms=(time.time() - start) * 1000
        )


def get_system_resources() -> dict:
    """获取系统资源使用情况"""
    try:
        import psutil

        cpu_percent = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage('/')

        # 获取进程信息
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

    # 按类别收集警告
    high_warns = [r for r in results if r.severity == Severity.HIGH and r.status != CheckStatus.OK]
    if high_warns:
        recommendations.append("【重要】以下功能受限，建议尽快配置:")
        for r in high_warns[:3]:
            if r.suggestions:
                recommendations.append(f"  - {r.name}: {r.suggestions[0]}")

    # 安全建议
    security_warns = [r for r in results if "密码" in r.name or "密钥" in r.name or "CORS" in r.name]
    if security_warns:
        recommendations.append("【安全】存在安全配置问题:")
        for r in security_warns[:2]:
            if r.suggestions:
                recommendations.append(f"  - {r.name}: {r.suggestions[0]}")

    return recommendations


# ============== 主检查器类 ==============

class SellerSystemChecker:
    """
    卖方系统完整自检器
    全面检查所有依赖项和配置
    """

    def __init__(self, config: dict[str, str] = None):
        """
        初始化检查器

        Args:
            config: 配置字典，如果为 None 则从环境变量加载
        """
        if config:
            self.config = config
        else:
            self.config = dict(os.environ)

    def _get(self, key: str, default: str = "") -> str:
        return self.config.get(key, default)

    def run_all_checks(self, parallel: bool = True) -> SystemCheckReport:
        """
        运行所有检查

        Args:
            parallel: 是否并行执行检查（默认 True）

        Returns:
            SystemCheckReport: 完整的检查报告
        """
        start_time = time.time()

        # 定义所有检查
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
        """定义所有检查项"""
        checks = []

        # 1. 服务端口检查
        checks.append(("端口", lambda: check_service_ports()))

        # 2. 数据库检查
        checks.append(("数据库", lambda: [check_neo4j(
            self._get("NEO4J_URI"),
            self._get("NEO4J_USER"),
            self._get("NEO4J_PASSWORD")
        )]))

        checks.append(("数据库", lambda: [check_sqlite_db(
            self._get("SHOP_SQLITE_PATH", _auto_db_path())
        )]))

        checks.append(("数据库", lambda: [check_mysql(
            self._get("MYSQL_HOST"),
            int(self._get("MYSQL_PORT", "3306")),
            self._get("MYSQL_USER"),
            self._get("MYSQL_PASSWORD"),
            self._get("MYSQL_DATABASE")
        )]))

        # 3. Redis 检查
        checks.append(("缓存", lambda: [check_redis(
            self._get("REDIS_HOST", "127.0.0.1"),
            int(self._get("REDIS_PORT", "6379")),
            self._get("REDIS_PASSWORD", ""),
            int(self._get("REDIS_DB", "0"))
        )]))

        # 4. AI 服务检查
        checks.append(("AI服务", lambda: [check_deepseek(
            self._get("DEEPSEEK_API_KEY"),
            self._get("DEEPSEEK_API_URL", "https://api.deepseek.com/v1/chat/completions")
        )]))

        checks.append(("AI服务", lambda: [check_graphrag(
            self._get("GRAPHRAG_API_URL", "http://127.0.0.1:5050/query")
        )]))

        # 5. 安全配置检查
        checks.append(("安全", lambda: check_security_config(
            self._get("JWT_SECRET_KEY"),
            self._get("ADMIN_PASSWORD"),
            self._get("ALLOWED_ORIGINS")
        )))

        # 6. 电商平台检查
        platform_configs = {k: self._get(k) for k in self.config if k.endswith("_API_URL")}
        checks.append(("平台", lambda: check_api_configs(platform_configs)))

        # 7. 物流配置检查
        logistics_configs = {k: self._get(k) for k in self.config if k.endswith("_API_URL")}
        checks.append(("物流", lambda: check_logistics_configs(logistics_configs)))

        # 8. 跨系统通信检查
        checks.append(("通信", lambda: [check_cross_system_communication(
            self._get("SELLER_API_HOST", "http://127.0.0.1:8000"),
            self._get("INTERNAL_API_SECRET")
        )]))

        return checks

    def _run_sequential(self, checks: list[tuple[str, callable]]) -> list[CheckResult]:
        """顺序执行所有检查"""
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
        """并行执行所有检查（使用线程池）"""
        results = [None] * len(checks)

        def run_check(index: int, category: str, check_func: callable):
            try:
                result = check_func()
                if isinstance(result, list):
                    results[index] = result  # list of CheckResult
                else:
                    results[index] = [result]
            except Exception as e:
                results[index] = [CheckResult(
                    name=category, status=CheckStatus.UNKNOWN, severity=Severity.INFO,
                    message=f"检查执行失败: {str(e)[:80]}"
                )]

        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = [
                executor.submit(run_check, i, cat, func)
                for i, (cat, func) in enumerate(checks)
            ]
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    logger.error(f"并行检查执行失败: {e}")

        # 展平结果
        flat_results = []
        for r in results:
            if r:
                if isinstance(r, list):
                    flat_results.extend(r)
                else:
                    flat_results.append(r)

        return flat_results


# ============== 便捷函数 ==============

def quick_health_check() -> dict:
    """
    快速健康检查（用于 /health 端点）
    仅检查核心服务是否可用，返回简化结果
    所有网络调用均加 2 秒硬超时，防止阻塞
    """
    checks = {
        "neo4j": False,
        "redis": False,
        "deepseek": False,
        "graphrag": False,
    }

    import socket, urllib.request, json as _json

    def _can_connect(host: str, port: int, timeout: float = 2.0) -> bool:
        """快速 socket 连通性测试（不触发 DNS 解析超时）"""
        try:
            socket.setdefaulttimeout(timeout)
            socket.create_connection((host, port), timeout=timeout)
            return True
        except Exception:
            return False
        finally:
            socket.setdefaulttimeout(None)

    # ── Neo4j ──────────────────────────────────────────────────
    # neo4j+s://b5af9f59.databases.neo4j.io:7687 → 检查 7687
    try:
        uri = os.getenv("NEO4J_URI", "")
        if uri.startswith("neo4j"):
            from urllib.parse import urlparse
            parsed = urlparse(uri.replace("neo4j+s://", "neo4j://").replace("bolt://", "bolt://"))
            host = parsed.hostname or ""
            port = parsed.port or 7687
            # 快速预检：先 DNS 解析（2秒超时）
            try:
                socket.setdefaulttimeout(2.0)
                socket.gethostbyname(host)
                checks["neo4j"] = True  # DNS 通，认为可达
            except Exception:
                # DNS 失败则跳过，不等 Neo4j 驱动重试
                pass
            finally:
                socket.setdefaulttimeout(None)
    except Exception:
        pass

    # ── Redis ─────────────────────────────────────────────────
    try:
        import redis
        r_host = os.getenv("REDIS_HOST", "127.0.0.1")
        r_port = int(os.getenv("REDIS_PORT", "6379"))
        try:
            if _can_connect(r_host, r_port, 2.0):
                r = redis.Redis(host=r_host, port=r_port,
                                socket_connect_timeout=2, socket_timeout=2)
                r.ping()
                checks["redis"] = True
        except Exception:
            pass
    except ImportError:
        pass

    # ── DeepSeek ──────────────────────────────────────────────
    try:
        api_key = os.getenv("DEEPSEEK_API_KEY", "")
        api_url = os.getenv("DEEPSEEK_API_URL", "https://api.deepseek.com/v1/chat/completions")
        if api_key:
            payload = _json.dumps({
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 2
            }).encode()
            req = urllib.request.Request(
                api_url, data=payload,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=4) as resp:
                checks["deepseek"] = resp.status == 200
    except Exception:
        pass

    # ── GraphRAG ──────────────────────────────────────────────
    try:
        graphrag_url = os.getenv("GRAPHRAG_API_URL", "")
        if graphrag_url:
            # 优先 GET /health，失败则 POST /query
            try:
                req = urllib.request.Request(
                    graphrag_url.rstrip("/") + "/health",
                    method="GET"
                )
                with urllib.request.urlopen(req, timeout=3) as resp:
                    checks["graphrag"] = resp.status == 200
            except Exception:
                # 回退：POST /query 方式
                try:
                    payload = _json.dumps({"customer_id": "ping"}).encode()
                    req2 = urllib.request.Request(
                        graphrag_url, data=payload,
                        headers={"Content-Type": "application/json"},
                        method="POST"
                    )
                    with urllib.request.urlopen(req2, timeout=3) as resp2:
                        checks["graphrag"] = resp2.status == 200
                except Exception:
                    pass
    except Exception:
        pass

    all_ok = all(checks.values())

    return {
        "status": "ok" if all_ok else "degraded",
        "checks": checks,
        "timestamp": __import__("datetime").datetime.now().isoformat(),
    }


# ============== CLI 入口 ==============

def main():
    """命令行入口"""
    import argparse
    import pprint

    parser = argparse.ArgumentParser(description="卖方系统自检工具")
    parser.add_argument("--quick", "-q", action="store_true", help="快速检查（仅核心项）")
    parser.add_argument("--json", "-j", action="store_true", help="JSON 格式输出")
    parser.add_argument("--parallel", "-p", action="store_true", default=True, help="并行执行（默认）")
    parser.add_argument("--sequential", "-s", action="store_true", help="顺序执行")
    args = parser.parse_args()

    print("=" * 70)
    print("  卖方系统自检  " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 70)

    checker = SellerSystemChecker()

    if args.quick:
        # 快速检查
        result = quick_health_check()
        print(f"\n整体状态: {result['status'].upper()}")
        print("\n检查项:")
        for name, status in result["checks"].items():
            icon = "[OK]" if status else "[FAIL]"
            print(f"  {icon} {name}")
        print(f"\n时间: {result['timestamp']}")
        return 0 if result["status"] == "ok" else 1

    # 完整检查
    report = checker.run_all_checks(parallel=not args.sequential)

    print(f"\n检查完成，耗时: {report.duration_ms:.0f}ms")
    print(f"\n整体状态: {report.overall_status.value.upper()}")
    print(f"  通过: {report.pass_count}")
    print(f"  警告: {report.warn_count}")
    print(f"  失败: {report.fail_count}")
    print(f"  阻塞: {report.critical_count}")

    # 按分类显示结果
    print("\n" + "-" * 70)
    print("详细结果:")
    for category, items in report.categories.items():
        print(f"\n【{category}】")
        for item in items:
            status = item["status"]
            icon = {
                "ok": "✓",
                "warn": "⚠",
                "fail": "✗",
                "skip": "○",
                "unknown": "?"
            }.get(status, "?")
            print(f"  {icon} [{status.upper():6}] {item['name']}")
            if item.get("message"):
                print(f"       {item['message']}")
            if item.get("suggestions") and status in ("fail", "warn"):
                for suggestion in item["suggestions"][:2]:
                    print(f"       → {suggestion}")

    # 显示建议
    if report.recommendations:
        print("\n" + "=" * 70)
        print("优化建议:")
        for rec in report.recommendations[:5]:
            print(f"  {rec}")

    # 显示系统资源
    if report.system_info and "error" not in report.system_info:
        print("\n" + "-" * 70)
        print("系统资源:")
        si = report.system_info
        print(f"  CPU: {si.get('cpu_percent', 'N/A')}%")
        print(f"  内存: {si.get('memory_used_gb', 'N/A')}GB / {si.get('memory_total_gb', 'N/A')}GB ({si.get('memory_percent', 'N/A')}%)")
        print(f"  磁盘: {si.get('disk_used_gb', 'N/A')}GB / {si.get('disk_total_gb', 'N/A')}GB ({si.get('disk_percent', 'N/A')}%)")
        print(f"  进程内存: {si.get('process_memory_mb', 'N/A')}MB")
        print(f"  进程运行: {si.get('process_uptime_seconds', 'N/A')}s")

    if args.json:
        print("\n" + "=" * 70)
        print("JSON 输出:")
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))

    return 0 if report.overall_status == CheckStatus.OK else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
