# -*- coding: utf-8 -*-
"""
日志配置 - 文件轮转 + 控制台彩色输出
支持 seller 和 buyer 两端共用

用法:
    from logging_config import setup_logging, get_logger
    logger = get_logger(__name__)
    setup_logging("seller")  # 或 "buyer"
"""
from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from pathlib import Path
from datetime import datetime


# 全局 logger 字典（按 name 缓存）
_loggers: dict[str, logging.Logger] = {}


def _get_log_dir(system: str) -> Path:
    """获取日志目录"""
    if system == "seller":
        base = Path(__file__).resolve().parent.parent
    elif system == "buyer":
        base = Path(__file__).resolve().parent.parent
    else:
        base = Path.cwd()

    log_dir = base / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def setup_logging(
    system: str = "seller",
    level: int = logging.INFO,
    max_bytes: int = 10 * 1024 * 1024,  # 10 MB per file
    backup_count: int = 7,               # 保留 7 个轮转备份
    format_string: str | None = None,
) -> None:
    """
    配置全局日志系统（文件轮转 + 控制台）。

    Args:
        system: "seller" 或 "buyer"
        level: 日志级别
        max_bytes: 单个日志文件最大字节数
        backup_count: 保留的轮转备份数量
        format_string: 自定义格式（None 使用默认格式）
    """
    if format_string is None:
        format_string = (
            "%(asctime)s | %(levelname)-8s | %(name)s | "
            "%(filename)s:%(lineno)d | %(message)s"
        )

    formatter = logging.Formatter(format_string, datefmt="%Y-%m-%d %H:%M:%S")

    # ---------- 根 logger ----------
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # 避免重复添加 handler
    if root_logger.handlers:
        root_logger.handlers.clear()

    # ---------- 控制台 Handler ----------
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # ---------- 文件 Handler（轮转）----------
    log_dir = _get_log_dir(system)
    log_file = log_dir / f"{system}.log"

    file_handler = logging.handlers.RotatingFileHandler(
        filename=str(log_file),
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    # ---------- 抑制第三方噪音 ----------
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("neo4j").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """
    获取带项目前缀的 logger（从缓存）。
    用法: logger = get_logger(__name__)
    """
    if name not in _loggers:
        _loggers[name] = logging.getLogger(name)
    return _loggers[name]


def log_startup_banner(system: str, port: int, info: dict | None = None) -> None:
    """打印启动横幅"""
    logger = get_logger("startup")
    border = "=" * 56
    logger.info(border)
    logger.info(f"  {system.upper()} 系统启动")
    logger.info(f"  端口: {port}")
    if info:
        for k, v in info.items():
            logger.info(f"  {k}: {v}")
    logger.info(border)
