# -*- coding: utf-8 -*-
"""
统一 API 响应格式和错误处理
确保所有 API 返回一致的响应格式
"""
from typing import Any, Optional, Dict
from datetime import datetime
from functools import wraps
from fastapi import Request, Response
from fastapi.responses import JSONResponse
import logging

logger = logging.getLogger(__name__)

# ============== 统一响应格式 ==============

class ApiResponse:
    """统一 API 响应格式"""
    
    @staticmethod
    def success(data: Any = None, message: str = "操作成功", **extra) -> Dict:
        """
        成功响应格式
        前端期望: { success: true, data: {...}, ...extra }
        """
        response = {
            "success": True,
            "data": data,
            "message": message,
            "timestamp": datetime.now().isoformat(),
            **extra
        }
        return response
    
    @staticmethod
    def error(message: str = "操作失败", code: str = "ERROR", details: Any = None, **extra) -> Dict:
        """
        错误响应格式
        前端期望: { success: false, error: { message, code, ... }, ... }
        """
        return {
            "success": False,
            "error": {
                "message": message,
                "code": code,
                "details": details,
                **extra
            },
            "timestamp": datetime.now().isoformat(),
        }
    
    @staticmethod
    def paginated(
        items: list,
        total: int,
        page: int = 1,
        page_size: int = 50,
        **extra
    ) -> Dict:
        """
        分页响应格式
        """
        return {
            "success": True,
            "data": {
                "items": items,
                "pagination": {
                    "total": total,
                    "page": page,
                    "page_size": page_size,
                    "total_pages": (total + page_size - 1) // page_size,
                }
            },
            "timestamp": datetime.now().isoformat(),
            **extra
        }


# ============== 兼容包装器 ==============

def wrap_response(data: Any, success_key: str = "success", data_key: str = "data") -> Dict:
    """
    将现有响应数据包装为统一格式
    
    兼容两种格式:
    1. {"success": True, "stats": {...}} -> {"success": True, "data": {"stats": {...}}}
    2. {"ok": True, "reviews": [...]} -> {"success": True, "data": {"reviews": [...]}}
    """
    if isinstance(data, dict):
        # 已经是统一格式
        if "success" in data and "data" in data:
            return data
        
        # 转换旧格式
        result = {
            "success": data.pop("success", data.pop("ok", True)),
            "data": {},
            "timestamp": datetime.now().isoformat(),
        }
        
        # 保留其他字段到 data 下
        for key, value in data.items():
            if key not in ["success", "ok", "message", "error"]:
                result["data"][key] = value
        
        # 保留 message 或 error
        if "message" in data:
            result["message"] = data["message"]
        if "error" in data:
            result["error"] = data["error"]
        
        return result
    
    # 非字典数据直接包装
    return {
        "success": True,
        "data": data,
        "timestamp": datetime.now().isoformat(),
    }


# ============== 错误处理 ==============

class APIError(Exception):
    """API 异常基类"""
    
    def __init__(self, message: str, code: str = "API_ERROR", status_code: int = 400, details: Any = None):
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details
        super().__init__(message)


class NotFoundError(APIError):
    """资源不存在"""
    def __init__(self, resource: str = "资源"):
        super().__init__(f"{resource}不存在", "NOT_FOUND", 404)


class UnauthorizedError(APIError):
    """未授权"""
    def __init__(self, message: str = "请先登录"):
        super().__init__(message, "UNAUTHORIZED", 401)


class ForbiddenError(APIError):
    """禁止访问"""
    def __init__(self, message: str = "权限不足"):
        super().__init__(message, "FORBIDDEN", 403)


class ValidationError(APIError):
    """验证失败"""
    def __init__(self, message: str, details: Any = None):
        super().__init__(message, "VALIDATION_ERROR", 422, details)


# ============== 全局异常处理 ==============

async def api_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """捕获所有 API 异常并返回统一格式"""
    
    if isinstance(exc, APIError):
        return JSONResponse(
            status_code=exc.status_code,
            content=ApiResponse.error(
                message=exc.message,
                code=exc.code,
                details=exc.details
            )
        )
    
    # 未知异常
    logger.error(f"Unhandled API exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content=ApiResponse.error(
            message="服务器内部错误，请稍后重试",
            code="INTERNAL_ERROR"
        )
    )


# ============== 辅助函数 ==============

def require_auth(func):
    """验证认证的装饰器"""
    @wraps(func)
    async def wrapper(*args, **kwargs):
        # 实际的认证逻辑在 jwt_auth.py 中
        # 这里只是标记需要认证
        return await func(*args, **kwargs)
    return wrapper


def safe_api_call(default: Any = None, log_errors: bool = True):
    """
    安全执行 API 函数的装饰器
    自动捕获异常并返回错误响应
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                result = await func(*args, **kwargs)
                return wrap_response(result) if isinstance(result, dict) else result
            except APIError:
                raise  # 让 APIError 直接抛出
            except Exception as e:
                if log_errors:
                    logger.error(f"API call failed: {func.__name__}: {e}")
                return ApiResponse.error(
                    message=f"执行失败: {str(e)[:100]}",
                    code="EXECUTION_ERROR"
                )
        return wrapper
    return decorator
