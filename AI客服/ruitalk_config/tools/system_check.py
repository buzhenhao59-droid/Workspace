# -*- coding: utf-8 -*-
"""
Ruitalk 综合自检系统 - 一键检查所有服务和配置
功能：
1. 卖方系统完整自检（端口、数据库、AI服务、安全配置等）
2. 买方系统完整自检
3. 跨系统通信验证
4. 数据库文件检查
5. 服务进程检查
6. 生成详细报告和建议

用法:
    python system_check.py                 # 检查所有
    python system_check.py --seller       # 仅卖方
    python system_check.py --buyer        # 仅买方
    python system_check.py --quick       # 快速检查
    python system_check.py --json         # JSON 输出
    python system_check.py --watch 5     # 每 5 秒自动检查（持续监控）
    python system_check.py --report       # 生成 HTML 报告
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional

# 确保可以导入自检模块
sys.path.insert(0, str(Path(__file__).parent / "卖方终端" / "backend"))
sys.path.insert(0, str(Path(__file__).parent / "AI客服买方系统" / "backend"))
# 统一配置目录（从 tools/ 的父目录加载）
_TOOLS_DIR = Path(__file__).parent.parent  # ruitalk_config
_PROJECT_ROOT = _TOOLS_DIR.parent          # 项目根目录
sys.path.insert(0, str(_PROJECT_ROOT))
sys.path.insert(0, str(_PROJECT_ROOT / "卖方终端" / "backend"))
sys.path.insert(0, str(_PROJECT_ROOT / "AI客服买方系统" / "backend"))

# ============== 配置加载（优先统一配置）==============
_UNIFIED_ENV = _TOOLS_DIR / ".env.master"  # ruitalk_config/.env.master


def load_env(path: Path) -> dict:
    """加载 .env 文件"""
    env = {}
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, val = line.partition("=")
            env[key.strip()] = val.strip().strip('"').strip("'")
    return env


def _auto_shared_db() -> str:
    """自动推导共享数据库路径"""
    env = load_env(_UNIFIED_ENV)
    _shared = env.get("SHARED_DB_PATH", "")
    if _shared:
        return _shared
    return str(_PROJECT_ROOT / "卖方终端" / "data" / "gold_customer.db")


def _load_env_all() -> dict:
    """加载所有配置（统一配置 + 环境变量）"""
    env = load_env(_UNIFIED_ENV)
    env.update(os.environ)
    return env


class CheckStatus(str, Enum):
    OK = "ok"
    WARN = "warn"
    FAIL = "fail"
    SKIP = "skip"
    INFO = "info"


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
class ServiceReport:
    """单个服务/系统的完整报告"""
    name: str
    system: str  # "seller" or "buyer" or "shared"
    timestamp: str
    duration_ms: float
    overall_status: CheckStatus
    critical_count: int
    warn_count: int
    fail_count: int
    pass_count: int
    skip_count: int
    total_count: int
    checks: list[dict]
    recommendations: list[str]
    system_info: dict

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "system": self.system,
            "timestamp": self.timestamp,
            "duration_ms": self.duration_ms,
            "overall_status": self.overall_status.value,
            "summary": {
                "critical": self.critical_count,
                "warn": self.warn_count,
                "fail": self.fail_count,
                "pass": self.pass_count,
                "skip": self.skip_count,
                "total": self.total_count,
            },
            "checks": self.checks,
            "recommendations": self.recommendations,
            "system_info": self.system_info,
        }


@dataclass
class GlobalReport:
    """全局检查报告"""
    timestamp: str
    duration_ms: float
    overall_status: CheckStatus
    total_checks: int
    passed_checks: int
    failed_checks: int
    warned_checks: int
    critical_issues: list[str]
    services: list[dict]
    quick_summary: dict
    recommendations: list[str]

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "duration_ms": self.duration_ms,
            "overall_status": self.overall_status.value,
            "summary": {
                "total_checks": self.total_checks,
                "passed": self.passed_checks,
                "failed": self.failed_checks,
                "warned": self.warned_checks,
            },
            "critical_issues": self.critical_issues,
            "services": self.services,
            "quick_summary": self.quick_summary,
            "recommendations": self.recommendations,
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
        return False, str(e)[:50]


def check_http(url: str, timeout: float = 5.0) -> tuple[bool, str, dict]:
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
        return False, str(e)[:50], {}


def check_neo4j(uri: str, user: str, password: str, timeout: float = 10.0) -> CheckResult:
    """检查 Neo4j 连接"""
    start = time.time()
    name = "Neo4j 数据库"

    if not uri or not user:
        return CheckResult(
            name=name, status=CheckStatus.FAIL, severity=Severity.CRITICAL,
            message="NEO4J_URI 或 NEO4J_USER 未配置",
            suggestions=["配置 NEO4J_URI 和 NEO4J_USER"]
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
            detail={"uri": uri},
            duration_ms=duration
        )
    except ImportError:
        return CheckResult(
            name=name, status=CheckStatus.FAIL, severity=Severity.CRITICAL,
            message="neo4j 模块未安装",
            suggestions=["pip install neo4j"]
        )
    except Exception as e:
        err_msg = str(e)
        suggestions = []

        if "authentication" in err_msg.lower():
            suggestions = ["检查 NEO4J_PASSWORD 是否正确"]
        elif "refused" in err_msg.lower():
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
        elif "resolve" in err_msg.lower() or "DNS" in err_msg:
            suggestions = [
                "Neo4j Aura 数据库实例无法访问",
                "请登录 Neo4j Aura 控制台检查实例状态: https://console.neo4j.io",
                "如果实例已暂停，请重新启动",
                "如果实例已删除，需要重新创建"
            ]
        else:
            suggestions = ["查看完整错误信息"]

        return CheckResult(
            name=name, status=CheckStatus.FAIL, severity=Severity.CRITICAL,
            message=f"连接失败: {err_msg[:80]}",
            detail={"uri": uri},
            duration_ms=(time.time() - start) * 1000,
            suggestions=suggestions
        )


def check_deepseek(api_key: str, api_url: str, timeout: float = 15.0) -> CheckResult:
    """检查 DeepSeek API"""
    start = time.time()
    name = "DeepSeek AI"

    if not api_key:
        return CheckResult(
            name=name, status=CheckStatus.FAIL, severity=Severity.CRITICAL,
            message="DEEPSEEK_API_KEY 未配置",
            suggestions=["配置 DEEPSEEK_API_KEY"]
        )

    if not api_key.startswith("sk-"):
        return CheckResult(
            name=name, status=CheckStatus.FAIL, severity=Severity.CRITICAL,
            message=f"API Key 格式错误: {api_key[:10]}...",
            suggestions=["检查 DEEPSEEK_API_KEY"]
        )

    try:
        import urllib.request
        import urllib.error

        payload = json.dumps({
            "model": "deepseek-chat",
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 2
        }).encode("utf-8")

        req = urllib.request.Request(
            api_url, data=payload,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
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
                message=f"API 响应异常",
                duration_ms=duration
            )
    except urllib.error.HTTPError as e:
        err_body = ""
        try:
            err_body = e.read().decode("utf-8")[:100]
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
                message="请求频率超限 (429)",
                suggestions=["稍后重试"]
            )
        return CheckResult(
            name=name, status=CheckStatus.FAIL, severity=Severity.HIGH,
            message=f"HTTP {e.code}: {err_body[:50]}",
            duration_ms=(time.time() - start) * 1000
        )
    except Exception as e:
        return CheckResult(
            name=name, status=CheckStatus.FAIL, severity=Severity.HIGH,
            message=f"API 调用失败: {str(e)[:50]}",
            duration_ms=(time.time() - start) * 1000
        )


def check_graphrag(api_url: str, timeout: float = 5.0) -> CheckResult:
    """检查 GraphRAG"""
    start = time.time()
    name = "GraphRAG 检索"

    if not api_url:
        return CheckResult(
            name=name, status=CheckStatus.SKIP, severity=Severity.INFO,
            message="GraphRAG 未配置",
            suggestions=["配置 GRAPHRAG_API_URL"]
        )

    try:
        import urllib.request
        import urllib.error

        payload = json.dumps({"customer_id": "ping"}).encode("utf-8")
        req = urllib.request.Request(
            api_url, data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            duration = (time.time() - start) * 1000
            if resp.status == 200:
                return CheckResult(
                    name=name, status=CheckStatus.OK, severity=Severity.INFO,
                    message=f"GraphRAG 正常 ({(time.time() - start)*1000:.0f}ms)",
                    duration_ms=duration
                )
            return CheckResult(
                name=name, status=CheckStatus.FAIL, severity=Severity.MEDIUM,
                message=f"GraphRAG 返回 HTTP {resp.status}",
                duration_ms=duration
            )
    except urllib.error.URLError:
        return CheckResult(
            name=name, status=CheckStatus.WARN, severity=Severity.MEDIUM,
            message="GraphRAG 未运行",
            suggestions=["启动 graphrag_proxy.py"]
        )
    except Exception as e:
        return CheckResult(
            name=name, status=CheckStatus.FAIL, severity=Severity.MEDIUM,
            message=f"GraphRAG 检查失败: {str(e)[:50]}",
            duration_ms=(time.time() - start) * 1000
        )


def check_redis(host: str, port: int, use_fake: bool = False, timeout: float = 5.0) -> CheckResult:
    """检查 Redis（支持真实 Redis 和 fakeredis 模拟模式）"""
    start = time.time()
    name = "Redis 缓存"

    if not host:
        return CheckResult(
            name=name, status=CheckStatus.SKIP, severity=Severity.INFO,
            message="Redis 未配置（使用内存会话存储）"
        )

    # fakeredis 模拟模式
    if use_fake:
        try:
            import fakeredis.aioredis
            return CheckResult(
                name=name, status=CheckStatus.OK, severity=Severity.INFO,
                message="Redis 模拟模式（fakeredis）- 用于开发/测试",
                detail={"mode": "fakeredis", "note": "生产环境请安装真实 Redis"},
                duration_ms=(time.time() - start) * 1000
            )
        except ImportError:
            return CheckResult(
                name=name, status=CheckStatus.WARN, severity=Severity.LOW,
                message="fakeredis 不可用，请安装真实 Redis",
                suggestions=["Docker: docker run -d -p 6379:6379 redis:alpine"],
                duration_ms=(time.time() - start) * 1000
            )

    try:
        import redis
        r = redis.Redis(host=host, port=port, socket_connect_timeout=timeout)
        r.ping()
        info = r.info("server")
        return CheckResult(
            name=name, status=CheckStatus.OK, severity=Severity.INFO,
            message=f"Redis {info.get('redis_version', '?')} 运行正常",
            detail={"host": host, "port": port},
            duration_ms=(time.time() - start) * 1000
        )
    except ImportError:
        return CheckResult(
            name=name, status=CheckStatus.SKIP, severity=Severity.LOW,
            message="redis-py 未安装"
        )
    except Exception as e:
        err_msg = str(e)
        if "REFUSED" in err_msg:
            return CheckResult(
                name=name, status=CheckStatus.WARN, severity=Severity.MEDIUM,
                message="Redis 未运行（使用内存会话存储，服务重启后会话丢失）",
                suggestions=[
                    "Docker: docker run -d -p 6379:6379 redis:alpine",
                    "或设置 REDIS_USE_FAKE=1 使用 fakeredis 模拟"
                ],
                duration_ms=(time.time() - start) * 1000
            )
        return CheckResult(
            name=name, status=CheckStatus.FAIL, severity=Severity.MEDIUM,
            message=f"Redis 连接失败: {err_msg[:50]}",
            duration_ms=(time.time() - start) * 1000
        )


def check_sqlite(db_path: str, name: str = "SQLite 数据库") -> CheckResult:
    """检查 SQLite"""
    start = time.time()

    if not db_path:
        return CheckResult(
            name=name, status=CheckStatus.SKIP, severity=Severity.INFO,
            message="数据库路径未配置"
        )

    db_file = Path(db_path)
    if not db_file.exists():
        return CheckResult(
            name=name, status=CheckStatus.WARN, severity=Severity.LOW,
            message=f"数据库不存在: {db_path}",
            suggestions=["将自动创建"],
            duration_ms=(time.time() - start) * 1000
        )

    try:
        conn = sqlite3.connect(db_path, timeout=5)
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        size_kb = db_file.stat().st_size / 1024
        conn.close()
        return CheckResult(
            name=name, status=CheckStatus.OK, severity=Severity.INFO,
            message=f"数据库正常 ({len(tables)} 表, {size_kb:.1f} KB)",
            detail={"tables": tables, "size_kb": round(size_kb, 1)},
            duration_ms=(time.time() - start) * 1000
        )
    except Exception as e:
        return CheckResult(
            name=name, status=CheckStatus.FAIL, severity=Severity.HIGH,
            message=f"数据库访问失败: {str(e)[:50]}",
            duration_ms=(time.time() - start) * 1000
        )


def check_security(jwt_secret: str, admin_password: str, cors: str) -> list[CheckResult]:
    """检查安全配置"""
    results = []

    # JWT
    name = "JWT 密钥"
    if not jwt_secret or jwt_secret.startswith("dev-") or len(jwt_secret or "") < 32:
        results.append(CheckResult(
            name=name, status=CheckStatus.FAIL, severity=Severity.CRITICAL,
            message="JWT_SECRET_KEY 使用默认值或过短",
            suggestions=["生成强密钥: python -c \"import secrets; print(secrets.token_hex(32))\""]
        ))
    else:
        results.append(CheckResult(
            name=name, status=CheckStatus.OK, severity=Severity.INFO,
            message=f"JWT 密钥正常 ({len(jwt_secret)} 字符)"
        ))

    # 密码
    name = "管理员密码"
    if admin_password == "123456" or len(admin_password or "") < 6:
        results.append(CheckResult(
            name=name, status=CheckStatus.FAIL, severity=Severity.HIGH,
            message="ADMIN_PASSWORD 使用默认密码或强度不足",
            suggestions=["修改为强密码"]
        ))
    else:
        results.append(CheckResult(
            name=name, status=CheckStatus.OK, severity=Severity.INFO,
            message="密码强度正常"
        ))

    # CORS
    name = "CORS 配置"
    if "*" in (cors or ""):
        results.append(CheckResult(
            name=name, status=CheckStatus.FAIL, severity=Severity.HIGH,
            message="CORS 允许所有来源（*）",
            suggestions=["设置明确的域名"]
        ))
    elif not cors:
        results.append(CheckResult(
            name=name, status=CheckStatus.WARN, severity=Severity.MEDIUM,
            message="CORS 未配置"
        ))
    else:
        count = len([o for o in cors.split(",") if o.strip()])
        results.append(CheckResult(
            name=name, status=CheckStatus.OK, severity=Severity.INFO,
            message=f"CORS 已配置 {count} 个来源"
        ))

    return results


def check_service_status(name: str, port: int, health_path: str = "/health") -> CheckResult:
    """检查服务状态"""
    start = time.time()
    full_name = f"{name} (端口 {port})"

    ok, msg = check_port("127.0.0.1", port)
    if not ok:
        return CheckResult(
            name=full_name, status=CheckStatus.FAIL, severity=Severity.MEDIUM,
            message=f"端口 {port} 未监听",
            suggestions=["确认服务已启动"],
            duration_ms=(time.time() - start) * 1000
        )

    # 尝试健康检查
    url = f"http://127.0.0.1:{port}{health_path}"
    ok2, msg2, data = check_http(url, timeout=5)

    if ok2:
        return CheckResult(
            name=full_name, status=CheckStatus.OK, severity=Severity.INFO,
            message=f"服务运行正常 - {msg2}",
            detail=data if data else {},
            duration_ms=(time.time() - start) * 1000
        )
    else:
        return CheckResult(
            name=full_name, status=CheckStatus.OK, severity=Severity.INFO,
            message=f"端口已监听（{health_path} 不可访问）",
            duration_ms=(time.time() - start) * 1000
        )


def get_system_resources() -> dict:
    """获取系统资源"""
    try:
        import psutil
        cpu = psutil.cpu_percent(interval=0.3)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        proc = psutil.Process()
        return {
            "cpu_percent": round(cpu, 1),
            "memory_percent": round(mem.percent, 1),
            "memory_used_gb": round(mem.used / (1024**3), 2),
            "memory_total_gb": round(mem.total / (1024**3), 2),
            "disk_percent": round(disk.percent, 1),
            "disk_used_gb": round(disk.used / (1024**3), 2),
            "disk_total_gb": round(disk.total / (1024**3), 2),
            "process_memory_mb": round(proc.memory_info().rss / (1024**2), 1),
            "process_uptime_s": int(time.time() - proc.create_time()),
        }
    except ImportError:
        return {"error": "psutil 未安装"}
    except Exception as e:
        return {"error": str(e)}


# ============== 报告生成 ==============

def generate_recommendations(results: list[CheckResult]) -> list[str]:
    """生成建议"""
    recs = []
    critical = [r for r in results if r.severity == Severity.CRITICAL and r.status == CheckStatus.FAIL]
    if critical:
        recs.append("【阻断】必须修复以下问题:")
        for r in critical[:3]:
            if r.suggestions:
                recs.append(f"  - {r.name}: {r.suggestions[0]}")
    high = [r for r in results if r.severity in (Severity.HIGH, Severity.MEDIUM) and r.status == CheckStatus.FAIL]
    if high:
        recs.append("【重要】以下功能受限:")
        for r in high[:3]:
            if r.suggestions:
                recs.append(f"  - {r.name}: {r.suggestions[0]}")
    return recs


def make_service_report(name: str, system: str, results: list[CheckResult], duration: float) -> ServiceReport:
    """生成服务报告"""
    critical = sum(1 for r in results if r.severity == Severity.CRITICAL and r.status == CheckStatus.FAIL)
    warns = sum(1 for r in results if r.status == CheckStatus.WARN)
    fails = sum(1 for r in results if r.status == CheckStatus.FAIL and r.severity != Severity.CRITICAL)
    passes = sum(1 for r in results if r.status == CheckStatus.OK)
    skips = sum(1 for r in results if r.status == CheckStatus.SKIP)

    if critical > 0 or fails > 0:
        overall = CheckStatus.FAIL
    elif warns > 0:
        overall = CheckStatus.WARN
    else:
        overall = CheckStatus.OK

    return ServiceReport(
        name=name, system=system,
        timestamp=datetime.now().isoformat(),
        duration_ms=duration,
        overall_status=overall,
        critical_count=critical, warn_count=warns,
        fail_count=fails, pass_count=passes, skip_count=skips,
        total_count=len(results),
        checks=[r.to_dict() for r in results],
        recommendations=generate_recommendations(results),
        system_info=get_system_resources()
    )


# ============== 卖方检查 ==============

def check_seller() -> ServiceReport:
    """检查卖方系统"""
    start = time.time()
    # 优先统一配置，再合并本地覆盖
    env = load_env(_UNIFIED_ENV)
    local = load_env(_PROJECT_ROOT / "卖方终端" / ".env")
    env.update(local)

    results: list[CheckResult] = []

    # 1. 服务端口
    services = [
        ("FastAPI", 8000, "/health"),
        ("Flask", 5000, "/ping"),
        ("GraphRAG", 5050, "/health"),
    ]
    for svc_name, port, path in services:
        results.append(check_service_status(svc_name, port, path))

    # 2. Redis
    results.append(check_redis(
        env.get("REDIS_HOST", ""),
        int(env.get("REDIS_PORT", "6379")),
        env.get("REDIS_USE_FAKE", "0") == "1"
    ))

    # 3. Neo4j
    results.append(check_neo4j(
        env.get("NEO4J_URI", ""),
        env.get("NEO4J_USER", ""),
        env.get("NEO4J_PASSWORD", "")
    ))

    # 4. SQLite（自动推导共享数据库路径）
    _auto_db = _auto_shared_db()
    results.append(check_sqlite(_auto_db, "会话数据库"))

    # 5. DeepSeek
    results.append(check_deepseek(
        env.get("DEEPSEEK_API_KEY", ""),
        env.get("DEEPSEEK_API_URL", "https://api.deepseek.com/v1/chat/completions")
    ))

    # 6. GraphRAG
    results.append(check_graphrag(env.get("GRAPHRAG_API_URL", "")))

    # 7. 安全配置
    results.extend(check_security(
        env.get("JWT_SECRET_KEY", ""),
        env.get("ADMIN_PASSWORD", ""),
        env.get("ALLOWED_ORIGINS", "")
    ))

    # 8. 买方连接检查
    buyer_ok, _, _ = check_http("http://127.0.0.1:8001/health", timeout=3)
    results.append(CheckResult(
        name="买方系统连接",
        status=CheckStatus.OK if buyer_ok else CheckStatus.WARN,
        severity=Severity.INFO if buyer_ok else Severity.LOW,
        message="买方系统可达" if buyer_ok else "买方系统未运行（转人工功能不可用）",
        suggestions=["启动买方系统: python run_buyer.py"] if not buyer_ok else []
    ))

    return make_service_report("卖方坐席系统", "seller", results, (time.time() - start) * 1000)


# ============== 买方检查 ==============

def check_buyer() -> ServiceReport:
    """检查买方系统"""
    start = time.time()
    # 优先统一配置，再合并本地覆盖
    env = load_env(_UNIFIED_ENV)
    local = load_env(_PROJECT_ROOT / "AI客服买方系统" / ".env")
    env.update(local)

    results: list[CheckResult] = []

    # 1. 服务端口
    services = [
        ("买方 FastAPI", 8001, "/health"),
    ]
    for svc_name, port, path in services:
        results.append(check_service_status(svc_name, port, path))

    # 2. 卖方连接
    seller_ok, _, _ = check_http("http://127.0.0.1:8000/health", timeout=3)
    results.append(CheckResult(
        name="卖方系统连接",
        status=CheckStatus.OK if seller_ok else CheckStatus.WARN,
        severity=Severity.INFO if seller_ok else Severity.HIGH,
        message="卖方系统可达" if seller_ok else "卖方系统未运行（转人工功能不可用）",
        suggestions=["启动卖方系统"] if not seller_ok else []
    ))

    # 3. Neo4j
    results.append(check_neo4j(
        env.get("NEO4J_URI", ""),
        env.get("NEO4J_USER", ""),
        env.get("NEO4J_PASSWORD", "")
    ))

    # 4. 共享数据库（自动推导路径）
    db_path = _auto_shared_db()
    results.append(check_sqlite(db_path, "共享会话数据库"))

    # 5. DeepSeek
    results.append(check_deepseek(
        env.get("DEEPSEEK_API_KEY", ""),
        env.get("DEEPSEEK_API_URL", "https://api.deepseek.com/v1/chat/completions")
    ))

    # 6. GraphRAG
    results.append(check_graphrag(env.get("GRAPHRAG_API_URL", "")))

    # 7. 安全配置
    results.extend(check_security(
        env.get("SECRET_KEY", ""),
        "",
        env.get("ALLOWED_ORIGINS", "")
    ))

    return make_service_report("买方 AI 客服", "buyer", results, (time.time() - start) * 1000)


# ============== 共享检查 ==============

def check_shared() -> ServiceReport:
    """检查共享资源"""
    start = time.time()
    results: list[CheckResult] = []

    # 检查数据库文件（自动推导）
    _db = _auto_shared_db()
    if Path(_db).exists():
        results.append(check_sqlite(_db, f"会话数据库 ({Path(_db).name})"))
    else:
        results.append(CheckResult(
            name="会话数据库", status=CheckStatus.WARN, severity=Severity.LOW,
            message="未找到数据库文件",
            suggestions=["系统将自动创建"]
        ))

    # 网络检查
    results.append(CheckResult(
        name="本地网络",
        status=CheckStatus.OK, severity=Severity.INFO,
        message="本地网络正常"
    ))

    return make_service_report("共享资源", "shared", results, (time.time() - start) * 1000)


# ============== 全局检查 ==============

def run_global_check(seller: bool = True, buyer: bool = True, shared: bool = True) -> GlobalReport:
    """运行全局检查"""
    start = time.time()
    reports = []

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {}
        if seller:
            futures["seller"] = executor.submit(check_seller)
        if buyer:
            futures["buyer"] = executor.submit(check_buyer)
        if shared:
            futures["shared"] = executor.submit(check_shared)

        for name, future in futures.items():
            try:
                reports.append(future.result())
            except Exception as e:
                print(f"检查 {name} 失败: {e}")

    # 汇总
    total = sum(r.total_count for r in reports)
    passed = sum(r.pass_count for r in reports)
    failed = sum(r.fail_count for r in reports)
    warned = sum(r.warn_count for r in reports)
    critical_issues = []
    all_recs = []

    for r in reports:
        critical_issues.extend([c["message"] for c in r.checks
                              if c["severity"] == "critical" and c["status"] == "fail"])
        all_recs.extend(r.recommendations)

    if critical_issues:
        overall = CheckStatus.FAIL
    elif failed > 0:
        overall = CheckStatus.FAIL
    elif warned > 0:
        overall = CheckStatus.WARN
    else:
        overall = CheckStatus.OK

    # 快速摘要
    quick = {}
    for r in reports:
        quick[r.name] = r.overall_status.value

    return GlobalReport(
        timestamp=datetime.now().isoformat(),
        duration_ms=(time.time() - start) * 1000,
        overall_status=overall,
        total_checks=total,
        passed_checks=passed,
        failed_checks=failed,
        warned_checks=warned,
        critical_issues=critical_issues[:5],
        services=[r.to_dict() for r in reports],
        quick_summary=quick,
        recommendations=all_recs[:10]
    )


# ============== 输出格式化 ==============

STATUS_ICONS = {
    "ok": "✓",
    "warn": "⚠",
    "fail": "✗",
    "skip": "○",
    "info": "ℹ",
}

STATUS_COLORS = {
    "ok": "\033[92m",      # 绿色
    "warn": "\033[93m",    # 黄色
    "fail": "\033[91m",    # 红色
    "skip": "\033[90m",    # 灰色
    "info": "\033[94m",    # 蓝色
}
RESET = "\033[0m"


def print_report(report: GlobalReport, use_color: bool = True, verbose: bool = False):
    """打印报告到控制台"""
    overall = report.overall_status.value
    overall_icon = STATUS_ICONS.get(overall, "?")
    overall_label = overall.upper()

    print("\n" + "=" * 70)
    print(f"  Ruitalk 综合自检  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    # 整体状态
    if use_color and overall == "ok":
        status_str = f"{STATUS_COLORS['ok']}{overall_icon} {overall_label}{RESET}"
    elif use_color and overall == "warn":
        status_str = f"{STATUS_COLORS['warn']}{overall_icon} {overall_label}{RESET}"
    elif use_color and overall == "fail":
        status_str = f"{STATUS_COLORS['fail']}{overall_icon} {overall_label}{RESET}"
    else:
        status_str = f"{overall_icon} {overall_label}"

    print(f"\n整体状态: {status_str}")
    print(f"检查耗时: {report.duration_ms:.0f}ms")

    # 统计
    print(f"\n检查统计:")
    print(f"  通过: {report.passed_checks}/{report.total_checks}")
    print(f"  警告: {report.warned_checks}")
    print(f"  失败: {report.failed_checks}")

    # 按服务显示
    for svc in report.services:
        svc_status = svc["overall_status"]
        icon = STATUS_ICONS.get(svc_status, "?")
        print(f"\n{'─' * 70}")
        print(f"  {icon} 【{svc['name']}】 {svc_status.upper()}")

        # 检查项
        if verbose:
            for check in svc["checks"]:
                icon = STATUS_ICONS.get(check["status"], "?")
                status_str = check["status"].upper()
                severity = check.get("severity", "")
                # 高亮失败项
                if use_color and check["status"] == "fail":
                    line = f"    {icon} [{status_str:6}] {check['name']}"
                    print(f"{STATUS_COLORS['fail']}{line}{RESET}")
                elif use_color and check["status"] == "warn":
                    line = f"    {icon} [{status_str:6}] {check['name']}"
                    print(f"{STATUS_COLORS['warn']}{line}{RESET}")
                else:
                    print(f"    {icon} [{status_str:6}] {check['name']}")

                if check.get("message"):
                    print(f"           {check['message']}")
                if verbose and check.get("suggestions") and check["status"] in ("fail", "warn"):
                    for s in check["suggestions"][:1]:
                        print(f"           → {s}")

    # 阻断问题
    if report.critical_issues:
        print(f"\n{'=' * 70}")
        print("阻断问题:")
        for issue in report.critical_issues[:3]:
            print(f"  ✗ {issue}")

    # 建议
    if report.recommendations:
        print(f"\n{'─' * 70}")
        print("优化建议:")
        shown = set()
        for rec in report.recommendations[:8]:
            if rec not in shown:
                print(f"  {rec}")
                shown.add(rec)

    # 系统资源
    si = {}
    for svc in report.services:
        if svc.get("system_info") and "error" not in svc["system_info"]:
            si = svc["system_info"]
            break

    if si and "error" not in si:
        print(f"\n{'─' * 70}")
        print("系统资源:")
        print(f"  CPU: {si.get('cpu_percent', 'N/A')}%")
        print(f"  内存: {si.get('memory_used_gb', 'N/A')}GB / {si.get('memory_total_gb', 'N/A')}GB ({si.get('memory_percent', 'N/A')}%)")
        print(f"  磁盘: {si.get('disk_percent', 'N/A')}%")
        print(f"  进程内存: {si.get('process_memory_mb', 'N/A')}MB")

    print("\n" + "=" * 70)


def generate_html_report(report: GlobalReport) -> str:
    """生成 HTML 报告"""
    status_colors = {
        "ok": "#4CAF50",
        "warn": "#FF9800",
        "fail": "#F44336",
        "skip": "#9E9E9E",
        "info": "#2196F3",
    }

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Ruitalk 系统自检报告</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: 'Segoe UI', system-ui, sans-serif; background: #f5f5f5; color: #333; line-height: 1.6; }}
  .container {{ max-width: 1200px; margin: 0 auto; padding: 20px; }}
  h1 {{ text-align: center; color: #1a1a2e; margin-bottom: 10px; font-size: 1.8rem; }}
  .timestamp {{ text-align: center; color: #666; font-size: 0.9rem; margin-bottom: 20px; }}
  .overview {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 24px; }}
  .stat-card {{ background: white; border-radius: 12px; padding: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }}
  .stat-label {{ color: #666; font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.5px; }}
  .stat-value {{ font-size: 2rem; font-weight: 700; margin-top: 4px; }}
  .stat-value.ok {{ color: #4CAF50; }}
  .stat-value.warn {{ color: #FF9800; }}
  .stat-value.fail {{ color: #F44336; }}
  .overall-status {{ background: white; border-radius: 16px; padding: 24px; text-align: center; margin-bottom: 24px; box-shadow: 0 4px 16px rgba(0,0,0,0.1); }}
  .overall-status h2 {{ font-size: 1.2rem; margin-bottom: 8px; }}
  .status-badge {{ display: inline-block; padding: 8px 24px; border-radius: 50px; font-weight: 700; font-size: 1.1rem; color: white; }}
  .status-badge.ok {{ background: #4CAF50; }}
  .status-badge.warn {{ background: #FF9800; }}
  .status-badge.fail {{ background: #F44336; }}
  .services {{ display: grid; gap: 20px; }}
  .service-card {{ background: white; border-radius: 16px; padding: 24px; box-shadow: 0 2px 12px rgba(0,0,0,0.08); }}
  .service-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; padding-bottom: 12px; border-bottom: 1px solid #eee; }}
  .service-name {{ font-size: 1.2rem; font-weight: 600; }}
  .service-status {{ padding: 4px 16px; border-radius: 20px; font-size: 0.85rem; font-weight: 600; color: white; }}
  .checks {{ display: grid; gap: 8px; }}
  .check-item {{ display: flex; align-items: center; padding: 10px 14px; border-radius: 8px; background: #fafafa; }}
  .check-icon {{ width: 24px; height: 24px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 12px; color: white; margin-right: 12px; flex-shrink: 0; }}
  .check-icon.ok {{ background: #4CAF50; }}
  .check-icon.warn {{ background: #FF9800; }}
  .check-icon.fail {{ background: #F44336; }}
  .check-icon.skip {{ background: #9E9E9E; }}
  .check-icon.info {{ background: #2196F3; }}
  .check-name {{ flex: 1; font-weight: 500; }}
  .check-status {{ font-size: 0.8rem; padding: 2px 10px; border-radius: 12px; font-weight: 600; }}
  .check-status.ok {{ background: #E8F5E9; color: #2E7D32; }}
  .check-status.warn {{ background: #FFF3E0; color: #E65100; }}
  .check-status.fail {{ background: #FFEBEE; color: #C62828; }}
  .check-status.skip {{ background: #F5F5F5; color: #616161; }}
  .check-status.info {{ background: #E3F2FD; color: #1565C0; }}
  .check-message {{ font-size: 0.8rem; color: #666; margin-top: 4px; padding-left: 36px; }}
  .recommendations {{ background: white; border-radius: 16px; padding: 24px; margin-top: 24px; box-shadow: 0 2px 12px rgba(0,0,0,0.08); }}
  .recommendations h3 {{ margin-bottom: 12px; color: #1a1a2e; }}
  .recommendation {{ padding: 10px 14px; background: #fff3cd; border-radius: 8px; margin-bottom: 8px; border-left: 4px solid #FF9800; }}
  .recommendation.critical {{ background: #ffebee; border-left-color: #F44336; }}
  .system-info {{ background: white; border-radius: 16px; padding: 24px; margin-top: 24px; box-shadow: 0 2px 12px rgba(0,0,0,0.08); }}
  .system-info h3 {{ margin-bottom: 16px; }}
  .resource-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; }}
  .resource-item {{ background: #f5f5f5; padding: 12px; border-radius: 8px; text-align: center; }}
  .resource-value {{ font-size: 1.4rem; font-weight: 700; color: #1a1a2e; }}
  .resource-label {{ font-size: 0.8rem; color: #666; margin-top: 4px; }}
  @media (max-width: 600px) {{ .overview {{ grid-template-columns: 1fr 1fr; }} }}
</style>
</head>
<body>
<div class="container">
  <h1>🔍 Ruitalk 系统自检报告</h1>
  <p class="timestamp">生成时间: {report.timestamp}</p>

  <div class="overview">
    <div class="stat-card">
      <div class="stat-label">整体状态</div>
      <div class="stat-value {report.overall_status.value}">{report.overall_status.value.upper()}</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">通过</div>
      <div class="stat-value ok">{report.passed_checks}</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">警告</div>
      <div class="stat-value warn">{report.warned_checks}</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">失败</div>
      <div class="stat-value fail">{report.failed_checks}</div>
    </div>
  </div>

  <div class="services">
"""

    for svc in report.services:
        svc_status = svc["overall_status"]
        html += f"""
    <div class="service-card">
      <div class="service-header">
        <span class="service-name">{svc['name']}</span>
        <span class="service-status" style="background: {status_colors.get(svc_status, '#666')}">{svc_status.upper()}</span>
      </div>
      <div class="checks">
"""

        for check in svc["checks"]:
            icon_class = check["status"].replace("fail", "fail").replace("warn", "warn")
            html += f"""
        <div class="check-item">
          <div class="check-icon {icon_class}">{STATUS_ICONS.get(check['status'], '?')}</div>
          <div>
            <div class="check-name">{check['name']}</div>
            <div class="check-message">{check.get('message', '')}</div>
          </div>
          <span class="check-status {check['status']}">{check['status'].upper()}</span>
        </div>
"""

        html += """
      </div>
    </div>
"""

    # 建议
    if report.recommendations:
        html += """
  <div class="recommendations">
    <h3>📋 优化建议</h3>
"""
        for rec in report.recommendations[:8]:
            is_critical = "【阻断】" in rec or "【紧急】" in rec
            html += f'<div class="recommendation{" critical" if is_critical else ""}">{rec}</div>\n'

        html += """
  </div>
"""

    # 系统资源
    si = {}
    for svc in report.services:
        if svc.get("system_info") and "error" not in svc["system_info"]:
            si = svc["system_info"]
            break

    if si and "error" not in si:
        html += f"""
  <div class="system-info">
    <h3>💻 系统资源</h3>
    <div class="resource-grid">
      <div class="resource-item">
        <div class="resource-value">{si.get('cpu_percent', 'N/A')}%</div>
        <div class="resource-label">CPU</div>
      </div>
      <div class="resource-item">
        <div class="resource-value">{si.get('memory_percent', 'N/A')}%</div>
        <div class="resource-label">内存</div>
      </div>
      <div class="resource-item">
        <div class="resource-value">{si.get('disk_percent', 'N/A')}%</div>
        <div class="resource-label">磁盘</div>
      </div>
      <div class="resource-item">
        <div class="resource-value">{si.get('process_memory_mb', 'N/A')} MB</div>
        <div class="resource-label">进程内存</div>
      </div>
    </div>
  </div>
"""

    html += """
</div>
</body>
</html>
"""
    return html


# ============== CLI ==============

def main():
    parser = argparse.ArgumentParser(description="Ruitalk 综合自检系统")
    parser.add_argument("--seller", action="store_true", help="仅检查卖方")
    parser.add_argument("--buyer", action="store_true", help="仅检查买方")
    parser.add_argument("--shared", action="store_true", help="仅检查共享资源")
    parser.add_argument("--quick", "-q", action="store_true", help="快速检查（省略详细输出）")
    parser.add_argument("--json", "-j", action="store_true", help="JSON 输出")
    parser.add_argument("--report", "-r", metavar="FILE", help="生成 HTML 报告")
    parser.add_argument("--watch", "-w", metavar="SECONDS", type=int, help="持续监控（每隔 N 秒）")
    parser.add_argument("--no-color", action="store_true", help="禁用彩色输出")
    args = parser.parse_args()

    # 默认检查全部
    check_all = not any([args.seller, args.buyer, args.shared])
    check_seller_flag = args.seller or check_all
    check_buyer_flag = args.buyer or check_all
    check_shared_flag = args.shared or check_all

    use_color = not args.no_color and sys.platform != "win32"

    def run_once():
        report = run_global_check(
            seller=check_seller_flag,
            buyer=check_buyer_flag,
            shared=check_shared_flag
        )

        if args.json:
            print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
        else:
            print_report(report, use_color=use_color, verbose=not args.quick)

        if args.report:
            html = generate_html_report(report)
            Path(args.report).write_text(html, encoding="utf-8")
            print(f"\nHTML 报告已保存: {args.report}")

        return 0 if report.overall_status == CheckStatus.OK else 1

    if args.watch:
        print(f"持续监控模式：每隔 {args.watch} 秒检查一次（Ctrl+C 退出）")
        try:
            while True:
                print("\n" + "▓" * 70)
                exit_code = run_once()
                print(f"\n下次检查: {args.watch} 秒后...")
                time.sleep(args.watch)
        except KeyboardInterrupt:
            print("\n\n监控已停止")
            return 0
    else:
        return run_once()


if __name__ == "__main__":
    sys.exit(main())
