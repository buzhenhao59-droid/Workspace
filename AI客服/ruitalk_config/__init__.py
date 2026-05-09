# -*- coding: utf-8 -*-
"""
Ruitalk 统一配置加载模块
所有系统共享此配置加载器，确保 .env.master 一处修改全局生效

使用方式：
    from ruitalk_config import UNIFIED_CONFIG, get_config
    config = get_config()  # 获取完整配置字典
    api_key = UNIFIED_CONFIG.get("DEEPSEEK_API_KEY")
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Optional

# ============== 路径常量 ==============
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
CONFIG_DIR = Path(__file__).parent.resolve()
UNIFIED_ENV_PATH = CONFIG_DIR / ".env.master"


def _load_env_file(path: Path) -> dict[str, str]:
    """解析 .env 文件，返回 key-value 字典（忽略注释行）"""
    env = {}
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        # 跳过空行和注释行
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip().strip('"').strip("'")
    return env


# ============== 配置加载（自动搜索 .env.master）=============

def _find_master_env() -> Path:
    """自动查找 .env.master 的位置"""
    # 1. ruitalk_config/.env.master（标准位置）
    if UNIFIED_ENV_PATH.exists():
        return UNIFIED_ENV_PATH

    # 2. 检查环境变量覆盖
    if os.getenv("RUITALK_ENV_PATH"):
        p = Path(os.getenv("RUITALK_ENV_PATH", ""))
        if p.exists():
            return p

    # 3. 向上搜索（兼容旧结构）
    current = CONFIG_DIR
    for _ in range(5):
        p = current / ".env.master"
        if p.exists():
            return p
        current = current.parent

    # 4. 返回标准路径（即使不存在，后续加载会处理）
    return UNIFIED_ENV_PATH


def load_unified_config() -> dict[str, str]:
    """
    加载统一配置
    优先级：
    1. .env.master（统一配置，shared）
    2. 系统环境变量（最高优先级，允许外部覆盖）
    """
    master = _find_master_env()
    config = _load_env_file(master)

    # 环境变量覆盖（用于容器化或 CI/CD 场景）
    for key, val in os.environ.items():
        if key.startswith("RUITALK_") or key in config:
            config[key] = val

    return config


# ============== 全局配置 ==============

UNIFIED_CONFIG: dict[str, str] = {}
_config_loaded = False


def ensure_config_loaded():
    """确保配置已加载（惰性加载）"""
    global UNIFIED_CONFIG, _config_loaded
    if not _config_loaded:
        UNIFIED_CONFIG = load_unified_config()
        _config_loaded = True


def get_config() -> dict[str, str]:
    """获取完整配置字典"""
    ensure_config_loaded()
    return UNIFIED_CONFIG


def get(key: str, default: str = "") -> str:
    """获取配置值"""
    ensure_config_loaded()
    return UNIFIED_CONFIG.get(key, default)


def get_int(key: str, default: int = 0) -> int:
    """获取整数配置"""
    ensure_config_loaded()
    val = UNIFIED_CONFIG.get(key, str(default))
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def get_bool(key: str, default: bool = False) -> bool:
    """获取布尔配置"""
    ensure_config_loaded()
    val = UNIFIED_CONFIG.get(key, str(default)).lower()
    return val in ("1", "true", "yes", "on")


# ============== 便捷访问器 ==============

class ConfigAccessor:
    """
    配置访问器，惰性加载，仅在使用时加载配置
    用于需要多次访问配置的场景
    """

    def __getitem__(self, key: str) -> str:
        ensure_config_loaded()
        return UNIFIED_CONFIG.get(key, "")

    def __getattr__(self, name: str) -> Any:
        ensure_config_loaded()
        return UNIFIED_CONFIG.get(name, "")

    def get(self, key: str, default: str = "") -> str:
        ensure_config_loaded()
        return UNIFIED_CONFIG.get(key, default)

    def items(self):
        ensure_config_loaded()
        return UNIFIED_CONFIG.items()

    def __contains__(self, key: str) -> bool:
        ensure_config_loaded()
        return key in UNIFIED_CONFIG

    def __len__(self) -> int:
        ensure_config_loaded()
        return len(UNIFIED_CONFIG)

    def keys(self):
        ensure_config_loaded()
        return UNIFIED_CONFIG.keys()

    def values(self):
        ensure_config_loaded()
        return UNIFIED_CONFIG.values()


# 全局访问器
CFG = ConfigAccessor()


# ============== 自动加载钩子（用于导入时自动加载）=============

def _reload():
    """重新加载配置（当 .env.master 被修改后调用）"""
    global UNIFIED_CONFIG, _config_loaded
    UNIFIED_CONFIG = load_unified_config()
    _config_loaded = True
