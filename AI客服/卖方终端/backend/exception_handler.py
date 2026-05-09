# -*- coding: utf-8 -*-
"""
全局异常处理与降级处理
提供统一的错误处理和优雅降级

使用方法：
    from exception_handler import graceful_degrade, degrade_on_service_unavailable
    
    @graceful_degrade(fallback="服务繁忙", exception_types=(TimeoutError,))
    async def call_deepseek_api():
        ...
"""

import functools
import logging
import asyncio
from typing import Any, Callable, Optional, Dict, Type, Union, List
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


# 多语言降级消息
DEGRADATION_MESSAGES = {
    "zh": {
        "deepseek": "服务繁忙，请稍后重试",
        "translation": "翻译服务暂时不可用，请稍后重试",
        "graphrag": "知识库暂时不可用，将使用备用回复",
        "neo4j": "知识图谱暂时不可用",
        "database": "数据库暂时不可用，请稍后重试",
        "redis": "缓存服务暂时不可用",
        "timeout": "请求超时，请稍后重试",
        "unknown": "系统繁忙，请稍后重试",
        "rate_limit": "请求过于频繁，请稍后再试",
        "auth_failed": "认证失败，请重新登录",
        "permission": "权限不足，无法执行此操作"
    },
    "en": {
        "deepseek": "Service is busy, please try again later",
        "translation": "Translation service temporarily unavailable",
        "graphrag": "Knowledge base temporarily unavailable",
        "neo4j": "Knowledge graph temporarily unavailable",
        "database": "Database temporarily unavailable",
        "redis": "Cache service temporarily unavailable",
        "timeout": "Request timed out, please try again",
        "unknown": "System busy, please try again later",
        "rate_limit": "Too many requests, please try again later",
        "auth_failed": "Authentication failed, please login again",
        "permission": "Permission denied"
    }
}


class ServiceDegradationError(Exception):
    """服务降级异常"""
    
    def __init__(self, service: str, original_error: Exception, fallback: Any = None):
        self.service = service
        self.original_error = original_error
        self.fallback = fallback
        super().__init__(f"Service {service} degraded: {original_error}")


def get_degradation_message(service: str, language: str = "zh") -> str:
    """获取降级消息"""
    messages = DEGRADATION_MESSAGES.get(language, DEGRADATION_MESSAGES["en"])
    return messages.get(service, messages["unknown"])


def graceful_degrade(
    fallback: Any = None,
    exception_types: tuple = (TimeoutError, asyncio.TimeoutError),
    log_error: bool = True,
    service: str = "unknown"
) -> Callable:
    """
    装饰器：优雅降级
    
    Args:
        fallback: 降级后的返回值
        exception_types: 需要降级的异常类型
        log_error: 是否记录错误日志
        service: 服务名称（用于日志和消息）
    
    Example:
        @graceful_degrade(fallback="抱歉，服务暂时不可用", service="deepseek")
        async def call_ai_api():
            response = await client.chat.completions.create(...)
            return response
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except exception_types as e:
                if log_error:
                    logger.warning(f"[Degradation] {service} timeout/error: {e}")
                return fallback
            except Exception as e:
                logger.exception(f"[Degradation] {service} unexpected error: {e}")
                return fallback
        
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except exception_types as e:
                if log_error:
                    logger.warning(f"[Degradation] {service} timeout/error: {e}")
                return fallback
            except Exception as e:
                logger.exception(f"[Degradation] {service} unexpected error: {e}")
                return fallback
        
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    
    return decorator


def degrade_on_service_unavailable(
    fallback: Any = None,
    service: str = "unknown",
    retry_count: int = 0,
    retry_delay: float = 0.5
) -> Callable:
    """
    装饰器：服务不可用时降级
    
    Args:
        fallback: 降级后的返回值
        service: 服务名称
        retry_count: 重试次数
        retry_delay: 重试间隔（秒）
    
    Example:
        @degrade_on_service_unavailable(fallback=None, service="neo4j", retry_count=2)
        async def query_knowledge_graph(query):
            return await neo4j.query(query)
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            last_error = None
            
            for attempt in range(retry_count + 1):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_error = e
                    if attempt < retry_count:
                        logger.info(f"[Retry] {service} attempt {attempt + 1} failed, retrying...")
                        await asyncio.sleep(retry_delay * (attempt + 1))
                    else:
                        logger.warning(f"[Degradation] {service} failed after {retry_count + 1} attempts: {e}")
            
            return fallback
        
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            last_error = None
            
            for attempt in range(retry_count + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_error = e
                    if attempt < retry_count:
                        logger.info(f"[Retry] {service} attempt {attempt + 1} failed, retrying...")
                        import time
                        time.sleep(retry_delay * (attempt + 1))
                    else:
                        logger.warning(f"[Degradation] {service} failed after {retry_count + 1} attempts: {e}")
            
            return fallback
        
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    
    return decorator


class GlobalExceptionHandler:
    """
    全局异常处理器
    用于 FastAPI 应用
    
    Example:
        from fastapi import FastAPI
        from exception_handler import GlobalExceptionHandler
        
        app = FastAPI()
        GlobalExceptionHandler.register(app)
    """
    
    @staticmethod
    def register(app) -> None:
        """注册到 FastAPI 应用"""
        
        @app.exception_handler(HTTPException)
        async def http_exception_handler(request: Request, exc: HTTPException):
            """HTTP 异常处理"""
            return JSONResponse(
                status_code=exc.status_code,
                content={
                    "success": False,
                    "error": {
                        "code": exc.status_code,
                        "message": exc.detail,
                        "type": "http_exception"
                    }
                }
            )
        
        @app.exception_handler(ServiceDegradationError)
        async def service_degradation_handler(request: Request, exc: ServiceDegradationError):
            """服务降级异常处理"""
            logger.warning(f"Service degradation: {exc.service}")
            return JSONResponse(
                status_code=503,
                content={
                    "success": False,
                    "error": {
                        "code": 503,
                        "message": get_degradation_message(exc.service),
                        "type": "service_degradation",
                        "fallback": exc.fallback
                    }
                }
            )
        
        @app.exception_handler(TimeoutError)
        async def timeout_handler(request: Request, exc: TimeoutError):
            """超时异常处理"""
            return JSONResponse(
                status_code=504,
                content={
                    "success": False,
                    "error": {
                        "code": 504,
                        "message": get_degradation_message("timeout"),
                        "type": "timeout"
                    }
                }
            )
        
        @app.exception_handler(Exception)
        async def general_exception_handler(request: Request, exc: Exception):
            """通用异常处理（放在最后）"""
            logger.exception(f"Unhandled exception: {exc}")
            return JSONResponse(
                status_code=500,
                content={
                    "success": False,
                    "error": {
                        "code": 500,
                        "message": get_degradation_message("unknown"),
                        "type": "internal_error"
                    }
                }
            )


def handle_ai_error(e: Exception, language: str = "zh") -> Dict[str, Any]:
    """
    处理 AI 服务错误
    
    Args:
        e: 异常对象
        language: 语言
    
    Returns:
        错误响应字典
    """
    error_type = type(e).__name__
    
    if "timeout" in str(e).lower() or isinstance(e, asyncio.TimeoutError):
        return {
            "success": False,
            "message": get_degradation_message("deepseek", language),
            "error_type": "timeout"
        }
    elif "rate limit" in str(e).lower():
        return {
            "success": False,
            "message": get_degradation_message("rate_limit", language),
            "error_type": "rate_limit"
        }
    elif "auth" in str(e).lower() or "401" in str(e):
        return {
            "success": False,
            "message": get_degradation_message("auth_failed", language),
            "error_type": "auth_failed"
        }
    else:
        logger.exception(f"AI service error: {e}")
        return {
            "success": False,
            "message": get_degradation_message("deepseek", language),
            "error_type": error_type
        }


def handle_translation_error(e: Exception, language: str = "zh") -> str:
    """
    处理翻译服务错误
    
    Args:
        e: 异常对象
        language: 语言
    
    Returns:
        降级消息
    """
    if isinstance(e, asyncio.TimeoutError) or "timeout" in str(e).lower():
        return get_degradation_message("translation", language)
    else:
        logger.warning(f"Translation error: {e}")
        return get_degradation_message("translation", language)


# 预定义的降级装饰器
deepseek_degrade = graceful_degrade(
    fallback={"success": False, "message": "AI服务暂时不可用，请稍后重试"},
    exception_types=(TimeoutError, asyncio.TimeoutError, ConnectionError),
    service="deepseek"
)

translation_degrade = graceful_degrade(
    fallback=None,
    exception_types=(TimeoutError, asyncio.TimeoutError, ConnectionError),
    service="translation"
)

neo4j_degrade = degrade_on_service_unavailable(
    fallback=None,
    service="neo4j",
    retry_count=2,
    retry_delay=0.5
)
