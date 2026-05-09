# -*- coding: utf-8 -*-
"""
Ruitalk 统一系统自检模块
卖方终端、买方系统、根目录工具共用此模块

使用方式：
    from system_checker import SellerSystemChecker, BuyerSystemChecker
    checker = SellerSystemChecker()
    report = checker.run_all_checks()
"""
from __future__ import annotations

import json
import platform
import socket
import sqlite3
import time
import traceback
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional

import psutil

# ============== 配置加载（兼容两种项目结构）=============
try:
    import sys as _sys

    # 方案1: ruitalk_config 模块
    try:
        from ruitalk_config import get_config
        _cfg = get_config()
    except Exception:
        # 方案2: 直接 dotenv 加载
        from pathlib import Path as _Path
        try:
            from dotenv import load_dotenv
            _env_path = _Path(__file__).parent / ".env.master"
            if _env_path.exists():
                load_dotenv(_env_path)
        except Exception:
            pass
    import os as _os
    _cfg = {k: v for k, v in _os.environ.items()}
except Exception:
    import os as _os
    _cfg = {k: v for k, v in _os.environ.items()}


def _get_cfg(key: str, default: str = "") -> str:
    """获取配置值（兼容各种导入方式）"""
    try:
        if callable(get_config):
            return get_config().get(key, default)
    except Exception:
        pass
    try:
        return _cfg.get(key, default)
    except Exception:
        import os
        return os.getenv(key, default)


def _get_cfg_int(key: str, default: int = 0) -> int:
    try:
        return int(_get_cfg(key, str(default)))
    except Exception:
        return default


def _get_cfg_bool(key: str, default: bool = False) -> bool:
    val = _get_cfg(key, str(default)).lower()
    return val in ("1", "true", "yes", "on")


# ============== 枚举和结果类 ==============

class CheckStatus(str, Enum):
    OK = "ok"
    FAIL = "fail"
    WARN = "warn"
    SKIP = "skip"


class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class CheckResult:
    name: str
    status: CheckStatus
    message: str
    severity: Severity = Severity.MEDIUM
    duration_ms: float = 0.0
    details: Optional[dict] = None
    suggestion: Optional[str] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        d["severity"] = self.severity.value
        return d


@dataclass
class SystemCheckReport:
    system: str
    timestamp: str
    duration_ms: float
    passed: int
    failed: int
    warnings: int
    skipped: int
    results: list[CheckResult] = field(default_factory=list)
    system_info: Optional[dict] = None
    overall_status: str = "ok"

    def to_dict(self) -> dict:
        return {
            "system": self.system,
            "timestamp": self.timestamp,
            "duration_ms": self.duration_ms,
            "passed": self.passed,
            "failed": self.failed,
            "warnings": self.warnings,
            "skipped": self.skipped,
            "overall_status": self.overall_status,
            "results": [r.to_dict() for r in self.results],
            "system_info": self.system_info or {},
        }


# ============== 基础检查函数 ==============

def check_port(host: str, port: int, timeout: float = 2.0) -> tuple[bool, str]:
    """检查端口是否可连接"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        sock.close()
        if result == 0:
            return True, f"{host}:{port} is open"
        return False, f"{host}:{port} is closed"
    except socket.gaierror:
        return False, f"{host}:{port} DNS resolution failed"
    except Exception as e:
        return False, f"{host}:{port} error: {e}"


def check_http_endpoint(url: str, timeout: float = 5.0, method: str = "GET") -> tuple[bool, str, dict]:
    """检查 HTTP 端点是否可达"""
    try:
        import urllib.request
        import urllib.error
        req = urllib.request.Request(url, method=method)
        req.add_header("User-Agent", "Ruitalk-SystemChecker/1.0")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return True, f"HTTP {resp.status} {resp.reason}", {
                "status_code": resp.status,
                "content_length": len(body),
            }
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code} {e.reason}", {"status_code": e.code}
    except urllib.error.URLError as e:
        return False, f"Connection failed: {e.reason}", {}
    except Exception as e:
        return False, f"Error: {e}", {}


# ============== Neo4j 检查 ==============

def check_neo4j(uri: str, user: str, password: str, timeout: float = 10.0) -> CheckResult:
    """检查 Neo4j 连接"""
    name = "Neo4j 数据库连接"
    start = time.time()
    if not uri or not user:
        return CheckResult(name, CheckStatus.SKIP, "Neo4j 配置不完整，跳过", Severity.LOW, (time.time() - start) * 1000)

    try:
        from neo4j import GraphDatabase
        driver = GraphDatabase.driver(uri, auth=(user, password), max_connection_lifetime=5)
        with driver.session() as session:
            result = session.run("RETURN 1 AS n")
            result.single()
        driver.close()
        return CheckResult(name, CheckStatus.OK, f"连接成功: {uri}", Severity.LOW, (time.time() - start) * 1000)
    except ImportError:
        return CheckResult(name, CheckStatus.SKIP, "neo4j 库未安装，跳过", Severity.LOW, (time.time() - start) * 1000)
    except Exception as e:
        msg = str(e)
        if "authorization" in msg.lower() or "auth" in msg.lower():
            return CheckResult(name, CheckStatus.FAIL, f"认证失败: {msg}", Severity.HIGH, (time.time() - start) * 1000,
                             suggestion="检查 NEO4J_USER 和 NEO4J_PASSWORD 是否正确")
        if "Unable to resolve" in msg or "Connection refused" in msg:
            return CheckResult(name, CheckStatus.FAIL, f"无法连接到 Neo4j: {msg}", Severity.CRITICAL,
                             suggestion="检查 Neo4j Aura 实例是否运行，或确认网络连接。提示：Neo4j Aura 免费实例在长时间空闲后会自动暂停，需要在控制台恢复。")
        return CheckResult(name, CheckStatus.FAIL, f"连接失败: {msg}", Severity.HIGH, (time.time() - start) * 1000)


# ============== Redis 检查 ==============

def check_redis(host: str, port: int, password: str = "", db: int = 0, timeout: float = 5.0, use_fake: bool = False) -> CheckResult:
    """检查 Redis 连接（支持 fakeredis 模式）"""
    name = "Redis 连接"
    start = time.time()
    if use_fake:
        try:
            import fakeredis
            fakeredis.FakeRedis()
            return CheckResult(name, CheckStatus.OK, "fakeredis 模拟模式 (开发环境)", Severity.LOW, (time.time() - start) * 1000)
        except Exception as e:
            return CheckResult(name, CheckStatus.FAIL, f"fakeredis 初始化失败: {e}", Severity.MEDIUM, (time.time() - start) * 1000)

    if not host:
        return CheckResult(name, CheckStatus.SKIP, "Redis 未配置，跳过", Severity.LOW, (time.time() - start) * 1000)

    try:
        import redis
        client = redis.Redis(host=host, port=port, password=password or None, db=db,
                             socket_timeout=timeout, socket_connect_timeout=timeout)
        client.ping()
        client.close()
        return CheckResult(name, CheckStatus.OK, f"连接成功: {host}:{port}", Severity.LOW, (time.time() - start) * 1000)
    except ImportError:
        return CheckResult(name, CheckStatus.SKIP, "redis 库未安装，跳过", Severity.LOW, (time.time() - start) * 1000)
    except Exception as e:
        return CheckResult(name, CheckStatus.FAIL, f"连接失败: {e}", Severity.MEDIUM, (time.time() - start) * 1000,
                          suggestion="安装 Memurai (Windows Redis) 或运行: docker run -d -p 6379:6379 redis:alpine")


# ============== DeepSeek 检查 ==============

def check_deepseek(api_key: str, api_url: str, timeout: float = 15.0) -> CheckResult:
    """检查 DeepSeek API 可用性"""
    name = "DeepSeek AI API"
    start = time.time()
    if not api_key:
        return CheckResult(name, CheckStatus.SKIP, "DeepSeek API Key 未配置，跳过", Severity.LOW, (time.time() - start) * 1000)

    try:
        import urllib.request
        import urllib.error
        payload = {
            "model": "deepseek-chat",
            "messages": [{"role": "user", "content": "Hi"}],
            "max_tokens": 5,
            "temperature": 0.1
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(api_url, data=data, headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            if "choices" in result:
                return CheckResult(name, CheckStatus.OK, "API 调用成功", Severity.LOW, (time.time() - start) * 1000)
            return CheckResult(name, CheckStatus.WARN, f"响应异常: {result}", Severity.MEDIUM, (time.time() - start) * 1000)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:200]
        if e.code == 401:
            return CheckResult(name, CheckStatus.FAIL, "API Key 无效或已过期", Severity.HIGH, (time.time() - start) * 1000,
                             suggestion="在 ruitalk_config/.env.master 中更新 DEEPSEEK_API_KEY")
        return CheckResult(name, CheckStatus.FAIL, f"HTTP {e.code}: {body}", Severity.MEDIUM, (time.time() - start) * 1000)
    except ImportError:
        return CheckResult(name, CheckStatus.SKIP, "urllib 不可用，跳过", Severity.LOW, (time.time() - start) * 1000)
    except Exception as e:
        return CheckResult(name, CheckStatus.FAIL, f"API 调用失败: {e}", Severity.HIGH, (time.time() - start) * 1000,
                          suggestion="检查 DEEPSEEK_API_URL 和 DEEPSEEK_API_KEY 是否正确，网络是否可达")


# ============== GraphRAG 检查 ==============

def check_graphrag(api_url: str, timeout: float = 5.0) -> CheckResult:
    """检查 GraphRAG 服务"""
    name = "GraphRAG 服务"
    start = time.time()
    if not api_url:
        return CheckResult(name, CheckStatus.SKIP, "GraphRAG 未配置，跳过", Severity.LOW, (time.time() - start) * 1000)

    ok, msg, _ = check_http_endpoint(api_url, timeout=timeout)
    if ok:
        return CheckResult(name, CheckStatus.OK, f"GraphRAG 可用: {api_url}", Severity.LOW, (time.time() - start) * 1000)
    return CheckResult(name, CheckStatus.WARN, f"GraphRAG 不可用: {msg}", Severity.MEDIUM, (time.time() - start) * 1000,
                      suggestion="启动 GraphRAG 服务: python -m graphrag.index")


# ============== SQLite 检查 ==============

def check_sqlite_db(db_path: str) -> CheckResult:
    """检查 SQLite 数据库"""
    name = f"SQLite 数据库 ({Path(db_path).name})"
    start = time.time()
    if not db_path:
        return CheckResult(name, CheckStatus.SKIP, "数据库路径未配置，跳过", Severity.LOW, (time.time() - start) * 1000)

    path = Path(db_path)
    if not path.exists():
        return CheckResult(name, CheckStatus.WARN, f"数据库文件不存在，将自动创建: {db_path}", Severity.MEDIUM, (time.time() - start) * 1000)

    try:
        conn = sqlite3.connect(db_path, timeout=5.0)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'")
        tables = cursor.fetchone()[0]
        conn.close()
        return CheckResult(name, CheckStatus.OK, f"数据库正常，共 {tables} 个表", Severity.LOW, (time.time() - start) * 1000)
    except sqlite3.OperationalError as e:
        return CheckResult(name, CheckStatus.FAIL, f"数据库错误: {e}", Severity.HIGH, (time.time() - start) * 1000)
    except Exception as e:
        return CheckResult(name, CheckStatus.FAIL, f"检查失败: {e}", Severity.HIGH, (time.time() - start) * 1000)


# ============== MySQL 检查 ==============

def check_mysql(host: str, port: int, user: str, password: str, database: str) -> CheckResult:
    """检查 MySQL 连接"""
    name = "MySQL 数据库"
    start = time.time()
    if not host:
        return CheckResult(name, CheckStatus.SKIP, "MySQL 未配置，跳过", Severity.LOW, (time.time() - start) * 1000)
    try:
        import pymysql
        conn = pymysql.connect(host=host, port=port, user=user, password=password,
                               database=database, connect_timeout=5)
        cursor = conn.cursor()
        cursor.execute("SELECT VERSION()")
        version = cursor.fetchone()[0]
        conn.close()
        return CheckResult(name, CheckStatus.OK, f"MySQL {version}", Severity.LOW, (time.time() - start) * 1000)
    except ImportError:
        return CheckResult(name, CheckStatus.SKIP, "pymysql 未安装，跳过", Severity.LOW, (time.time() - start) * 1000)
    except Exception as e:
        return CheckResult(name, CheckStatus.WARN, f"MySQL 不可用: {e} (不影响核心功能)", Severity.MEDIUM, (time.time() - start) * 1000)


# ============== 安全配置检查 ==============

def check_security_config(jwt_secret: str = "", admin_password: str = "", cors_origins: str = "") -> list[CheckResult]:
    """检查安全配置"""
    results = []

    # JWT Secret
    if not jwt_secret or "change-in-production" in jwt_secret.lower() or len(jwt_secret) < 32:
        results.append(CheckResult(
            "JWT Secret Key", CheckStatus.FAIL,
            "JWT_SECRET_KEY 未设置或使用了默认值",
            Severity.HIGH, 0.0,
            suggestion="在 ruitalk_config/.env.master 中设置 64 字符以上的随机字符串作为 JWT_SECRET_KEY"
        ))
    else:
        results.append(CheckResult("JWT Secret Key", CheckStatus.OK, "JWT_SECRET_KEY 已正确配置", Severity.LOW))

    # Admin Password
    if not admin_password or len(admin_password) < 8:
        results.append(CheckResult(
            "管理员密码", CheckStatus.FAIL,
            "ADMIN_PASSWORD 密码强度不足（需至少8字符）",
            Severity.HIGH, 0.0,
            suggestion="在 ruitalk_config/.env.master 中设置强密码"
        ))
    elif admin_password in ("123456", "password", "admin", "Admin123", "TUOYUE"):
        results.append(CheckResult(
            "管理员密码", CheckStatus.WARN,
            "管理员密码使用了常见弱密码",
            Severity.MEDIUM, 0.0,
            suggestion="在 ruitalk_config/.env.master 中更换为更强的密码"
        ))
    else:
        results.append(CheckResult("管理员密码", CheckStatus.OK, "密码强度符合要求", Severity.LOW))

    # CORS
    if "*" in cors_origins:
        results.append(CheckResult(
            "CORS 配置", CheckStatus.WARN,
            "CORS 允许所有来源 (*)，存在安全风险",
            Severity.MEDIUM, 0.0,
            suggestion="在 ruitalk_config/.env.master 中明确指定允许的域名"
        ))
    else:
        results.append(CheckResult("CORS 配置", CheckStatus.OK, f"CORS 已正确配置: {cors_origins}", Severity.LOW))

    return results


# ============== 跨系统通信检查 ==============

def check_cross_system_communication(seller_api_host: str, internal_token: str = "") -> CheckResult:
    """检查买方到卖方的通信"""
    name = "跨系统通信（买方→卖方）"
    start = time.time()
    if not seller_api_host:
        return CheckResult(name, CheckStatus.SKIP, "卖方 API 地址未配置，跳过", Severity.LOW, (time.time() - start) * 1000)

    health_url = seller_api_host.rstrip("/") + "/health"
    ok, msg, details = check_http_endpoint(health_url, timeout=5.0)
    if ok:
        return CheckResult(name, CheckStatus.OK, f"卖方 API 可达: {msg}", Severity.LOW, (time.time() - start) * 1000,
                          details=details)
    return CheckResult(name, CheckStatus.WARN, f"卖方 API 不可达: {msg}", Severity.MEDIUM, (time.time() - start) * 1000,
                      suggestion="确保卖方终端服务正在运行（uvicorn main:app --port 8000）")


# ============== 端口检查 ==============

def check_service_ports() -> list[CheckResult]:
    """检查关键服务端口状态"""
    results = []
    port_map = [
        ("FastAPI 端口 (8000)", "127.0.0.1", 8000),
        ("Flask 金牌客服端口 (5000)", "127.0.0.1", 5000),
        ("GraphRAG 端口 (5050)", "127.0.0.1", 5050),
        ("买方 API 端口 (8001)", "127.0.0.1", 8001),
    ]
    for name, host, port in port_map:
        start = time.time()
        ok, msg = check_port(host, port, timeout=2.0)
        results.append(CheckResult(name, CheckStatus.OK if ok else CheckStatus.WARN,
                                   msg, Severity.LOW, (time.time() - start) * 1000))
    return results


# ============== 平台 API 配置检查 ==============

def check_api_configs(platform_configs: dict) -> list[CheckResult]:
    """检查各平台 API 配置"""
    results = []
    for platform, config in platform_configs.items():
        if isinstance(config, dict) and config.get("configured"):
            results.append(CheckResult(f"{platform} API", CheckStatus.OK,
                                       f"已配置: {config.get('name', platform)}", Severity.LOW))
        else:
            results.append(CheckResult(f"{platform} API", CheckStatus.SKIP,
                                       f"未配置，跳过", Severity.LOW))
    return results


# ============== 物流配置检查 ==============

def check_logistics_configs(logistics_configs: dict) -> list[CheckResult]:
    """检查物流 API 配置"""
    results = []
    for name, config in logistics_configs.items():
        if isinstance(config, dict) and config.get("configured"):
            results.append(CheckResult(f"物流 {name}", CheckStatus.OK,
                                       f"已配置", Severity.LOW))
        else:
            results.append(CheckResult(f"物流 {name}", CheckStatus.SKIP,
                                       f"未配置，跳过", Severity.LOW))
    return results


# ============== 系统资源检查 ==============

def check_system_resources() -> list[CheckResult]:
    """检查系统资源"""
    results = []
    try:
        cpu = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")

        if cpu > 90:
            results.append(CheckResult("CPU 使用率", CheckStatus.WARN,
                                       f"CPU 使用率 {cpu:.1f}%（过高）", Severity.HIGH))
        else:
            results.append(CheckResult("CPU 使用率", CheckStatus.OK,
                                       f"CPU 使用率 {cpu:.1f}%", Severity.LOW))

        if mem.percent > 90:
            results.append(CheckResult("内存使用率", CheckStatus.WARN,
                                       f"内存使用率 {mem.percent:.1f}%（过高）", Severity.HIGH))
        else:
            results.append(CheckResult("内存使用率", CheckStatus.OK,
                                       f"内存使用率 {mem.percent:.1f}%", Severity.LOW))

        if disk.percent > 90:
            results.append(CheckResult("磁盘使用率", CheckStatus.WARN,
                                       f"磁盘使用率 {disk.percent:.1f}%（过高）", Severity.MEDIUM))
        else:
            results.append(CheckResult("磁盘使用率", CheckStatus.OK,
                                       f"磁盘使用率 {disk.percent:.1f}%", Severity.LOW))
    except Exception as e:
        results.append(CheckResult("系统资源", CheckStatus.SKIP,
                                   f"无法获取系统资源: {e}", Severity.LOW))
    return results


# ============== 卖方系统检查器 ==============

class SellerSystemChecker:
    """卖方终端系统自检"""

    def __init__(self):
        self.system_name = "卖方终端"
        # 从配置加载
        self.cfg = _cfg if _cfg else {}

    def _load_env(self) -> dict:
        """加载环境变量（兼容独立运行）"""
        try:
            from config import get_config
            return get_config()
        except Exception:
            import os
            return dict(os.environ)

    def run_all_checks(self) -> SystemCheckReport:
        """执行所有检查"""
        cfg = self._load_env()
        start = time.time()
        results: list[CheckResult] = []

        # --- 端口检查 ---
        for r in check_service_ports():
            results.append(r)

        # --- Neo4j ---
        results.append(check_neo4j(
            cfg.get("NEO4J_URI", ""),
            cfg.get("NEO4J_USER", ""),
            cfg.get("NEO4J_PASSWORD", ""),
        ))

        # --- Redis ---
        redis_use_fake = _get_cfg_bool("REDIS_USE_FAKE", True)
        results.append(check_redis(
            cfg.get("REDIS_HOST", "127.0.0.1"),
            _get_cfg_int("REDIS_PORT", 6379),
            cfg.get("REDIS_PASSWORD", ""),
            _get_cfg_int("REDIS_DB", 0),
            use_fake=redis_use_fake,
        ))

        # --- DeepSeek ---
        results.append(check_deepseek(
            cfg.get("DEEPSEEK_API_KEY", ""),
            cfg.get("DEEPSEEK_API_URL", "https://api.deepseek.com/v1/chat/completions"),
        ))

        # --- GraphRAG ---
        results.append(check_graphrag(cfg.get("GRAPHRAG_API_URL", "")))

        # --- SQLite（自动推导路径）---
        _shared = cfg.get("SHARED_DB_PATH", "")
        if not _shared:
            _root = Path(cfg.get("PROJECT_ROOT", str(Path(__file__).parent.parent.parent)))
            _shared = str(_root / "卖方终端" / "data" / "gold_customer.db")
        results.append(check_sqlite_db(_shared))

        # --- MySQL ---
        results.append(check_mysql(
            cfg.get("SHOP_MYSQL_HOST", ""),
            _get_cfg_int("SHOP_MYSQL_PORT", 3306),
            cfg.get("SHOP_MYSQL_USER", ""),
            cfg.get("SHOP_MYSQL_PASSWORD", ""),
            cfg.get("SHOP_MYSQL_DATABASE", ""),
        ))

        # --- 安全配置 ---
        results.extend(check_security_config(
            cfg.get("JWT_SECRET_KEY", ""),
            cfg.get("ADMIN_PASSWORD", ""),
            cfg.get("ALLOWED_ORIGINS", ""),
        ))

        # --- 系统资源 ---
        results.extend(check_system_resources())

        # --- 汇总 ---
        passed = sum(1 for r in results if r.status == CheckStatus.OK)
        failed = sum(1 for r in results if r.status == CheckStatus.FAIL)
        warnings = sum(1 for r in results if r.status == CheckStatus.WARN)
        skipped = sum(1 for r in results if r.status == CheckStatus.SKIP)

        return SystemCheckReport(
            system=self.system_name,
            timestamp=datetime.now().isoformat(),
            duration_ms=(time.time() - start) * 1000,
            passed=passed, failed=failed, warnings=warnings, skipped=skipped,
            results=results,
            overall_status="ok" if failed == 0 else ("warn" if failed < 3 else "critical"),
        )


# ============== 买方系统检查器 ==============

class BuyerSystemChecker:
    """买方系统自检"""

    def __init__(self):
        self.system_name = "AI客服买方系统"

    def _load_env(self) -> dict:
        try:
            from config import get_config
            return get_config()
        except Exception:
            import os
            return dict(os.environ)

    def run_all_checks(self) -> SystemCheckReport:
        """执行所有检查"""
        cfg = self._load_env()
        start = time.time()
        results: list[CheckResult] = []

        # --- 端口检查 ---
        port_checks = [
            ("FastAPI 端口 (8000)", "127.0.0.1", 8000),
            ("买方 API 端口 (8001)", "127.0.0.1", 8001),
            ("GraphRAG 端口 (5050)", "127.0.0.1", 5050),
        ]
        for name, host, port in port_checks:
            ok, msg = check_port(host, port, timeout=2.0)
            results.append(CheckResult(name, CheckStatus.OK if ok else CheckStatus.WARN, msg, Severity.LOW,
                                       (time.time() - start) * 1000))

        # --- Neo4j ---
        results.append(check_neo4j(
            cfg.get("NEO4J_URI", ""),
            cfg.get("NEO4J_USER", ""),
            cfg.get("NEO4J_PASSWORD", ""),
        ))

        # --- DeepSeek ---
        results.append(check_deepseek(
            cfg.get("DEEPSEEK_API_KEY", ""),
            cfg.get("DEEPSEEK_API_URL", "https://api.deepseek.com/v1/chat/completions"),
        ))

        # --- GraphRAG ---
        results.append(check_graphrag(cfg.get("GRAPHRAG_API_URL", "")))

        # --- 共享数据库 ---
        shared_db = cfg.get("SHARED_DB_PATH", "")
        if shared_db:
            results.append(check_sqlite_db(shared_db))

        # --- 卖方连通性 ---
        results.append(check_cross_system_communication(
            cfg.get("SELLER_API_HOST", ""),
            cfg.get("SELLER_INTERNAL_TOKEN", ""),
        ))

        # --- 安全配置 ---
        results.extend(check_security_config(
            cfg.get("JWT_SECRET_KEY", ""),
            cfg.get("ADMIN_PASSWORD", ""),
            cfg.get("ALLOWED_ORIGINS", ""),
        ))

        # --- 系统资源 ---
        results.extend(check_system_resources())

        passed = sum(1 for r in results if r.status == CheckStatus.OK)
        failed = sum(1 for r in results if r.status == CheckStatus.FAIL)
        warnings = sum(1 for r in results if r.status == CheckStatus.WARN)
        skipped = sum(1 for r in results if r.status == CheckStatus.SKIP)

        return SystemCheckReport(
            system=self.system_name,
            timestamp=datetime.now().isoformat(),
            duration_ms=(time.time() - start) * 1000,
            passed=passed, failed=failed, warnings=warnings, skipped=skipped,
            results=results,
            overall_status="ok" if failed == 0 else ("warn" if failed < 3 else "critical"),
        )


# ============== 快速健康检查 ==============

def quick_health_check(system: str = "seller") -> dict:
    """轻量级健康检查（用于 /health 端点）"""
    cfg = {}
    try:
        from config import get_config
        cfg = get_config()
    except Exception:
        import os
        cfg = dict(os.environ)

    status = "ok"
    checks = {}

    # 端口
    for name, host, port in [("fastapi", "127.0.0.1", 8000), ("buyer", "127.0.0.1", 8001)]:
        ok, _ = check_port(host, port, timeout=1.0)
        checks[name] = "ok" if ok else "unavailable"
        if not ok and system == "seller" and name == "fastapi":
            status = "degraded"

    # Redis
    redis_use_fake = _get_cfg_bool("REDIS_USE_FAKE", True)
    if redis_use_fake:
        checks["redis"] = "ok (fakeredis)"
    else:
        ok, _ = check_port(cfg.get("REDIS_HOST", "127.0.0.1"), _get_cfg_int("REDIS_PORT", 6379), timeout=1.0)
        checks["redis"] = "ok" if ok else "unavailable"

    return {"status": status, "system": system, "checks": checks}
