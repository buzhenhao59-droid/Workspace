# -*- coding: utf-8 -*-
"""
API 版本控制模块
为所有 API 路由提供统一的版本管理
"""
from typing import Dict, Optional
from dataclasses import dataclass
from datetime import datetime

# ============== API 版本信息 ==============

@dataclass
class APIVersion:
    """API 版本信息"""
    version: str
    release_date: datetime
    status: str  # 'current', 'deprecated', 'eol'
    docs_url: Optional[str] = None
    changelog: Optional[str] = None

API_VERSIONS: Dict[str, APIVersion] = {
    "v1": APIVersion(
        version="v1",
        release_date=datetime(2024, 1, 1),
        status="current",
        docs_url="/docs",
        changelog="""
        ## v1.0.0 (2024-01-01)
        - 初始版本
        - 支持管理员登录认证
        - 支持坐席管理
        - 支持客户会话管理
        - 支持消息中心
        - 支持评价管理
        - 支持售后单管理
        - 支持多语言切换
        - 支持 AI 回复生成
        - 支持转人工服务
        - 支持熔断器保护
        - 支持 Redis 会话存储
        - 支持限流保护
        """,
    ),
}

CURRENT_API_VERSION = "v1"
SUPPORTED_API_VERSIONS = list(API_VERSIONS.keys())

# ============== 版本检查中间件 ==============

def check_api_version(version: Optional[str]) -> tuple[bool, str]:
    """
    检查 API 版本是否支持
    
    Returns:
        (is_valid, error_message)
    """
    if version is None:
        return True, ""
    
    if version not in SUPPORTED_API_VERSIONS:
        return False, f"API 版本 '{version}' 不支持。支持的版本: {', '.join(SUPPORTED_API_VERSIONS)}"
    
    api_info = API_VERSIONS.get(version)
    if api_info and api_info.status == "eol":
        return False, f"API 版本 '{version}' 已停止维护，请升级到最新版本"
    
    return True, ""


def get_deprecated_headers(version: Optional[str]) -> Dict[str, str]:
    """
    为已弃用的 API 版本生成警告头
    
    Returns:
        Dict[str, str]: 警告头信息
    """
    headers = {}
    
    if version is None:
        return headers
    
    api_info = API_VERSIONS.get(version)
    if api_info:
        if api_info.status == "deprecated":
            headers["X-API-Warning"] = f"API 版本 {version} 已弃用，将在未来的更新中移除"
        elif api_info.status == "eol":
            headers["X-API-Warning"] = f"API 版本 {version} 已停止维护，请立即升级"
    
    return headers


# ============== OpenAPI 扩展 ==============

def get_openapi_extensions() -> Dict:
    """
    获取 OpenAPI 扩展配置
    
    Returns:
        Dict: OpenAPI 扩展配置
    """
    return {
        "x-api-version": CURRENT_API_VERSION,
        "x-supported-versions": SUPPORTED_API_VERSIONS,
        "x-api-info": {
            "name": "Ruitalk 客服系统 API",
            "description": "跨境电商金牌客服系统 API",
            "contact": {
                "name": "API Support",
                "email": "support@ruitalk.com",
            },
            "license": {
                "name": "Proprietary",
            },
        },
        "x-rate-limiting": {
            "enabled": True,
            "requests_per_minute": 60,
            "burst": 10,
        },
        "x-circuit-breaker": {
            "enabled": True,
            "failure_threshold": 5,
            "timeout_seconds": 30,
        },
    }


def get_security_schemes() -> Dict:
    """
    获取 OpenAPI 安全方案
    
    Returns:
        Dict: 安全方案配置
    """
    return {
        "BearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "JWT 访问令牌",
        },
        "InternalAuth": {
            "type": "apiKey",
            "in": "header",
            "name": "X-Internal-Token",
            "description": "内部服务调用令牌",
        },
    }
