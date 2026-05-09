# -*- coding: utf-8 -*-
"""
结构化 JSON 日志模块
用于生产环境 ELK/Grafana Loki/Prometheus 集成
所有日志输出为 JSON Lines 格式（每行一条 JSON）

用法:
    from structured_logging import get_structured_logger, setup_structured_logging
    logger = get_structured_logger(__name__)
    setup_structured_logging("seller")  # 初始化

    logger.info("用户登录", extra={
        "user_id": "admin",
        "ip": "192.168.1.1",
        "action": "login",
        "success": True,
    })
"""
import os
import sys
import json
import logging
import traceback
import threading
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Any
from logging.handlers import RotatingFileHandler
from collections import OrderedDict


# ============== 日志级别映射 ==============
LOG_LEVEL_MAP = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


# ============== 自定义日志字段（保留给 ELK/Loki 使用）==============
class StructuredLogFields:
    """
    预定义的标准日志字段，确保所有服务日志格式统一。
    字段名遵循 ECS (Elastic Common Schema) 规范子集。
    """

    @staticmethod
    def base(service: str, level: str) -> dict:
        return OrderedDict([
            ("@timestamp", datetime.now(timezone.utc).isoformat()),
            ("log.level", level.upper()),
            ("service.name", service),
            ("ecs.version", "1.12.0"),
        ])

    @staticmethod
    def http_request(
        method: str, path: str, status_code: int,
        duration_ms: float, client_ip: str,
        user_agent: str = "", request_id: str = ""
    ) -> dict:
        d = OrderedDict([
            ("http.request.method", method),
            ("http.url.path", path),
            ("http.response.status_code", status_code),
            ("http.request.duration_ms", round(duration_ms, 2)),
            ("source.ip", client_ip),
        ])
        if user_agent:
            d["user_agent.original"] = user_agent
        if request_id:
            d["trace.id"] = request_id
        return d

    @staticmethod
    def security(
        action: str, success: bool,
        user_id: str = "", username: str = "",
        ip: str = "", reason: str = ""
    ) -> dict:
        d = OrderedDict([
            ("event.action", action),
            ("event.outcome", "success" if success else "failure"),
        ])
        if user_id:
            d["user.id"] = user_id
        if username:
            d["user.name"] = username
        if ip:
            d["source.ip"] = ip
        if reason:
            d["eventreason"] = reason
        return d

    @staticmethod
    def db_query(
        operation: str, table: str,
        duration_ms: float, rows: int = -1,
        error: str = ""
    ) -> dict:
        d = OrderedDict([
            ("db.operation", operation),
            ("db.table", table),
            ("db.duration_ms", round(duration_ms, 2)),
        ])
        if rows >= 0:
            d["db.rows_affected"] = rows
        if error:
            d["db.error"] = error
        return d

    @staticmethod
    def ai_request(
        model: str, input_tokens: int, output_tokens: int,
        duration_ms: float, success: bool, error: str = ""
    ) -> dict:
        d = OrderedDict([
            ("ai.model", model),
            ("ai.input_tokens", input_tokens),
            ("ai.output_tokens", output_tokens),
            ("ai.duration_ms", round(duration_ms, 2)),
            ("ai.success", success),
        ])
        if error:
            d["ai.error"] = error
        return d

    @staticmethod
    def session(
        session_id: str, action: str,
        customer_id: str = "", language: str = ""
    ) -> dict:
        d = OrderedDict([
            ("session.id", session_id),
            ("session.action", action),
        ])
        if customer_id:
            d["customer.id"] = customer_id
        if language:
            d["session.language"] = language
        return d

    @staticmethod
    def system_check(
        component: str, status: str,
        duration_ms: float, error: str = ""
    ) -> dict:
        d = OrderedDict([
            ("system.component", component),
            ("system.check_status", status),
            ("system.duration_ms", round(duration_ms, 2)),
        ])
        if error:
            d["system.error"] = error
        return d


# ============== JSON 格式化器 ==============
class StructuredJSONFormatter(logging.Formatter):
    """
    将日志记录转换为 JSON Lines 格式。
    兼容 Python 标准日志系统，自动序列化所有 extra 字段。
    """

    def __init__(
        self,
        service: str = "ruitalk",
        include_stack_trace: bool = True,
        include_locals: bool = False,
        extra_blacklist: tuple = ("taskName", "task_id", "color"),
    ):
        super().__init__()
        self.service = service
        self.include_stack_trace = include_stack_trace
        self.include_locals = include_locals
        self.extra_blacklist = extra_blacklist

    def format(self, record: logging.LogRecord) -> str:
        fields = StructuredLogFields.base(self.service, record.levelname)

        # 日志来源
        fields["log.logger"] = record.name
        fields["code.filepath"] = record.filename
        fields["code.lineno"] = record.lineno
        fields["code.function"] = record.funcName

        # 日志消息
        fields["message"] = record.getMessage()

        # 异常信息
        if record.exc_info:
            fields["error.type"] = record.exc_info[0].__name__ if record.exc_info[0] else "UnknownError"
            fields["error.message"] = str(record.exc_info[1]) if record.exc_info[1] else ""
            if self.include_stack_trace:
                fields["error.stack_trace"] = self._format_traceback(record.exc_info)

        # 序列化所有 extra 字段（排除黑名单）
        extra = {
            k: v for k, v in record.__dict__.items()
            if k not in self.extra_blacklist
            and k not in ("name", "msg", "args", "levelname", "levelno",
                         "pathname", "lineno", "funcName", "filename",
                         "module", "msecs", "relativeCreated", "thread",
                         "threadName", "processName", "process",
                         "exc_info", "exc_text", "stack_info", "message")
            and not k.startswith("_")
        }
        if extra:
            fields["extra"] = self._serialize_extra(extra)

        # 响应时间（Prometheus histogram 兼容）
        if hasattr(record, "duration_ms"):
            fields["http.request.duration_ms"] = round(record.duration_ms, 2)

        # 请求 ID（分布式追踪）
        if hasattr(record, "request_id"):
            fields["trace.id"] = record.request_id

        # 用户 ID
        if hasattr(record, "user_id"):
            fields["user.id"] = record.user_id

        # IP 地址
        if hasattr(record, "client_ip"):
            fields["source.ip"] = record.client_ip

        return json.dumps(fields, ensure_ascii=False, separators=(',', ':'))

    def _serialize_extra(self, extra: dict) -> dict:
        """序列化 extra 字段，处理不可 JSON 序列化的对象"""
        result = {}
        for k, v in extra.items():
            try:
                if isinstance(v, (str, int, float, bool, type(None))):
                    result[k] = v
                elif isinstance(v, dict):
                    result[k] = self._serialize_extra(v)
                elif isinstance(v, (list, tuple)):
                    result[k] = [self._serialize_value(item) for item in v]
                else:
                    result[k] = str(v)
            except Exception:
                result[k] = repr(v)
        return result

    def _serialize_value(self, v: Any) -> Any:
        if isinstance(v, (str, int, float, bool, type(None))):
            return v
        try:
            return json.dumps(v, ensure_ascii=False)
        except Exception:
            return repr(v)

    def _format_traceback(self, exc_info) -> str:
        import traceback as tb
        lines = tb.format_exception(*exc_info)
        return "".join(lines).strip()


# ============== 简化的 JSON 输出（用于 Ctrl+C 控制台可读性）==============
class ConsoleJSONFormatter(StructuredJSONFormatter):
    """简化版 JSON 格式化（控制台友好，生产用 StructuredJSONFormatter）"""

    def format(self, record: logging.LogRecord) -> str:
        fields = {
            "ts": datetime.now(timezone.utc).strftime("%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name.split(".")[-1][:20],
            "msg": record.getMessage(),
        }
        if record.exc_info:
            fields["exc"] = str(record.exc_info[1])
        return json.dumps(fields, ensure_ascii=False)


# ============== 全局日志配置 ==============
_loggers: dict[str, logging.Logger] = {}
_init_lock = threading.Lock()
_initialized = False


def setup_structured_logging(
    system: str = "ruitalk",
    level: str = "INFO",
    log_dir: Optional[Path] = None,
    max_bytes: int = 50 * 1024 * 1024,  # 50 MB
    backup_count: int = 10,
    json_console: bool = False,
    service_name: Optional[str] = None,
) -> None:
    """
    配置全局结构化日志系统。

    Args:
        system: 系统名称（用于日志文件名和服务字段）
        level: 日志级别 DEBUG/INFO/WARNING/ERROR
        log_dir: 日志目录（None 时自动使用 {system}/logs/）
        max_bytes: 单个日志文件最大字节数
        backup_count: 轮转备份数量
        json_console: 控制台也输出 JSON（生产环境推荐 True）
        service_name: ECS service.name 字段值（默认等于 system）
    """
    global _initialized

    with _init_lock:
        if _initialized:
            return

        numeric_level = LOG_LEVEL_MAP.get(level.upper(), logging.INFO)
        service = service_name or system

        # 创建根 logger
        root = logging.getLogger()
        root.setLevel(numeric_level)

        # 避免重复 handler
        if root.handlers:
            root.handlers.clear()

        # 格式化器
        if json_console:
            console_fmt = StructuredJSONFormatter(service=service)
        else:
            console_fmt = ConsoleJSONFormatter(service=service)

        # 控制台 Handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(numeric_level)
        console_handler.setFormatter(console_fmt)
        root.addHandler(console_handler)

        # 文件 Handler（JSON Lines，轮转）
        if log_dir is None:
            log_dir = Path(__file__).resolve().parent.parent / "logs"
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)

        json_file_fmt = StructuredJSONFormatter(
            service=service,
            include_stack_trace=True,
        )
        file_handler = RotatingFileHandler(
            filename=str(log_dir / f"{system}.json.log"),
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(numeric_level)
        file_handler.setFormatter(json_file_fmt)
        root.addHandler(file_handler)

        # 抑制第三方噪音
        logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
        logging.getLogger("uvicorn.error").setLevel(logging.WARNING)
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)
        logging.getLogger("neo4j").setLevel(logging.WARNING)
        logging.getLogger("urllib3").setLevel(logging.WARNING)
        logging.getLogger("PIL").setLevel(logging.WARNING)
        logging.getLogger("watchfiles").setLevel(logging.WARNING)

        _initialized = True


def get_structured_logger(name: str) -> logging.Logger:
    """
    获取结构化日志记录器（从缓存）。
    所有 extra 字段会自动序列化为 JSON。
    """
    if name not in _loggers:
        _loggers[name] = logging.getLogger(name)
    return _loggers[name]


# ============== 便捷方法 ==============
def log_http_request(
    logger: logging.Logger,
    method: str, path: str, status_code: int,
    duration_ms: float, client_ip: str,
    user_id: str = "", request_id: str = "",
    **extra
) -> None:
    """记录 HTTP 请求（结构化）"""
    fields = StructuredLogFields.http_request(
        method, path, status_code, duration_ms, client_ip,
        request_id=request_id
    )
    fields["user.id"] = user_id
    fields.update(extra)
    logger.info(
        f"{method} {path} -> {status_code} ({duration_ms:.0f}ms)",
        extra=fields
    )


def log_security(
    logger: logging.Logger,
    action: str, success: bool,
    user_id: str = "", username: str = "",
    ip: str = "", reason: str = ""
) -> None:
    """记录安全事件（登录/登出/鉴权）"""
    fields = StructuredLogFields.security(
        action, success, user_id, username, ip, reason
    )
    outcome = "成功" if success else "失败"
    logger.info(
        f"[{action}] {outcome} - {username or user_id or 'unknown'} from {ip or 'unknown'}",
        extra=fields
    )


def log_db(
    logger: logging.Logger,
    operation: str, table: str,
    duration_ms: float, rows: int = -1,
    error: str = "", **extra
) -> None:
    """记录数据库操作"""
    fields = StructuredLogFields.db_query(operation, table, duration_ms, rows, error)
    fields.update(extra)
    if error:
        logger.warning(f"DB {operation} {table} failed: {error}", extra=fields)
    else:
        logger.debug(f"DB {operation} {table} ({duration_ms:.0f}ms, rows={rows})", extra=fields)


def log_ai_request(
    logger: logging.Logger,
    model: str, input_tokens: int, output_tokens: int,
    duration_ms: float, success: bool, error: str = ""
) -> None:
    """记录 AI 请求"""
    fields = StructuredLogFields.ai_request(
        model, input_tokens, output_tokens, duration_ms, success, error
    )
    logger.info(
        f"AI {model} req={input_tokens} resp={output_tokens} ({duration_ms:.0f}ms)",
        extra=fields
    )
