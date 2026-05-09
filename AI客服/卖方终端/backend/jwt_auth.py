# -*- coding: utf-8 -*-
"""
JWT 认证工具模块
提供 token 生成、验证、刷新功能
"""
import jwt
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
from fastapi import HTTPException, Security, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from config import JWT_SECRET_KEY, JWT_ALGORITHM, JWT_ACCESS_TOKEN_EXPIRE_MINUTES, JWT_REFRESH_TOKEN_EXPIRE_DAYS

logger = logging.getLogger(__name__)

# FastAPI 依赖项：Bearer token 提取器
bearer_scheme = HTTPBearer(auto_error=False)


def create_access_token(
    subject: str,
    role: str,
    extra_claims: Optional[Dict[str, Any]] = None
) -> str:
    """
    生成 JWT access token

    Args:
        subject: token 的主体标识（如 username, user_id）
        role: 用户角色（如 'admin', 'seller', 'agent'）
        extra_claims: 额外Claims

    Returns:
        JWT token 字符串
    """
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=JWT_ACCESS_TOKEN_EXPIRE_MINUTES)

    payload = {
        "sub": str(subject),
        "role": role,
        "type": "access",
        "iat": now,
        "exp": expire,
    }
    if extra_claims:
        payload.update(extra_claims)

    token = jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    return token


def create_refresh_token(subject: str, role: Optional[str] = None) -> str:
    """
    生成 JWT refresh token（有效期更长，无敏感信息）

    Args:
        subject: token 的主体标识
        role: 可选，写入 payload 以便刷新 access token 时恢复角色
    """
    now = datetime.now(timezone.utc)
    expire = now + timedelta(days=JWT_REFRESH_TOKEN_EXPIRE_DAYS)

    payload = {
        "sub": str(subject),
        "type": "refresh",
        "iat": now,
        "exp": expire,
    }
    if role:
        payload["role"] = role
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> Dict[str, Any]:
    """
    解码并验证 JWT token

    Args:
        token: JWT token 字符串

    Returns:
        解码后的 payload

    Raises:
        HTTPException: token 无效或已过期
    """
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token已过期，请重新登录")
    except jwt.InvalidTokenError as e:
        logger.warning(f"无效的JWT token: {e}")
        raise HTTPException(status_code=401, detail="无效的认证凭证")


def verify_access_token(token: str) -> Dict[str, Any]:
    """
    验证 access token，区分 refresh token

    Args:
        token: JWT token 字符串

    Returns:
        解码后的 payload

    Raises:
        HTTPException: token 无效、已过期或不是 access token
    """
    payload = decode_token(token)
    if payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="无效的token类型")
    return payload


def verify_refresh_token(token: str) -> Dict[str, Any]:
    """
    验证 refresh token，用于刷新 access token

    Args:
        token: JWT refresh token 字符串

    Returns:
        解码后的 payload

    Raises:
        HTTPException: token 无效、已过期或不是 refresh token
    """
    payload = decode_token(token)
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="无效的refresh token")
    return payload


def refresh_access_token(refresh_token: str) -> Dict[str, Any]:
    """
    用 refresh token 签发新的 access token

    Args:
        refresh_token: 有效的 refresh token

    Returns:
        包含新 access_token 的字典
    """
    payload = verify_refresh_token(refresh_token)
    new_access_token = create_access_token(
        subject=payload["sub"],
        role=payload.get("role") or "admin",
    )
    return {"access_token": new_access_token, "token_type": "bearer"}


# ============================================================
# FastAPI 依赖项（用于保护 API 端点）
# ============================================================

async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
) -> Dict[str, Any]:
    """
    FastAPI 依赖项：从 Authorization: Bearer <token> 提取并验证用户

    用法：
        @app.get("/protected")
        async def protected(user: dict = Depends(get_current_user)):
            return {"user": user}
    """
    if credentials is None:
        raise HTTPException(status_code=401, detail="未提供认证凭证", headers={"WWW-Authenticate": "Bearer"})

    payload = verify_access_token(credentials.credentials)
    return payload


# ============================================================
# 权限配置 - 基础模块 vs 高级模块
# ============================================================

# 基础模块 - admin 和 super_admin 都可以访问
BASIC_API_PATHS = {
    "/health",
    "/ready",
    "/live",
    "/api/v1/dashboard",
    "/api/v1/customer",
    "/api/v1/orders",
    "/api/v1/reviews",
    "/api/v1/translate",
    "/api/v1/admin/stats",
    "/api/v1/shop/stats",
    "/api/v1/shop/platforms",
    "/api/v1/platforms",
    "/api/v1/internal/buyer",
    "/api/v1/message-center",
    "/api/v1/audit-logs",
}

# 高级模块 - 仅 super_admin 可访问
ADVANCED_API_PATHS = {
    "/api/v1/admin/users",
    "/api/v1/admin/create",
    "/api/v1/admin/after-sales",
    "/api/v1/settings",
    "/api/v1/system",
    "/api/v1/agents",
    "/api/v1/agent-console",
    "/api/v1/system-check",
}


def check_module_access(role: str, path: str) -> bool:
    """
    检查用户角色是否有权访问指定 API 路径。
    - super_admin: 可访问所有路径
    - admin: 仅可访问基础模块
    - operator: 原有白名单逻辑（仅基础模块）
    """
    if role == "super_admin":
        return True
    if role == "admin":
        return path in BASIC_API_PATHS or any(path.startswith(p) for p in BASIC_API_PATHS)
    if role == "operator":
        # operator 只能访问白名单中的路径
        if path in ADVANCED_API_PATHS or any(path.startswith(p) for p in ADVANCED_API_PATHS):
            return False
        return path in OPERATOR_ALLOWED_PATHS or any(path.startswith(p) for p in OPERATOR_ALLOWED_PATHS)
    return False


async def get_current_super_admin(
    user: Dict[str, Any] = Security(get_current_user),
) -> Dict[str, Any]:
    """
    管理后台：超管或管理员（super_admin / admin）可访问，用于系统核心管理功能。
    在Ruitalk卖家系统中，admin拥有完整管理权限。
    """
    r = user.get("role")
    if r not in ("super_admin", "admin"):
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


async def get_current_admin_or_super_admin(
    user: Dict[str, Any] = Security(get_current_user),
) -> Dict[str, Any]:
    """
    管理后台门户：超管或管理员（super_admin / admin）。
    敏感接口请使用 get_current_super_admin。
    """
    r = user.get("role")
    if r not in ("super_admin", "admin"):
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


async def get_current_admin_only(
    user: Dict[str, Any] = Security(get_current_user),
) -> Dict[str, Any]:
    """
    仅 admin 可访问（排除 super_admin）。
    用于特定管理功能。
    """
    if user.get("role") != "admin":
        raise HTTPException(
            status_code=403,
            detail="此操作仅管理员可用",
        )
    return user


async def get_current_admin(
    user: Dict[str, Any] = Security(get_current_user),
) -> Dict[str, Any]:
    """
    管理后台门户：超管或管理员（super_admin / admin）。
    敏感接口请使用 get_current_super_admin。
    """
    r = user.get("role")
    if r not in ("super_admin", "admin"):
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


async def get_current_staff(
    user: Dict[str, Any] = Security(get_current_user),
) -> Dict[str, Any]:
    """
    管理员或坐席（客服后台订单/售后等业务共用）。
    包括 super_admin、admin、agent、operator。
    """
    r = user.get("role")
    if r not in ("super_admin", "admin", "agent", "operator"):
        raise HTTPException(status_code=403, detail="需要管理员或坐席权限")
    return user


async def get_current_seller(
    user: Dict[str, Any] = Security(get_current_user),
) -> Dict[str, Any]:
    """
    FastAPI 依赖项：验证当前用户角色为 seller 或 agent
    """
    if user.get("role") not in ("seller", "agent"):
        raise HTTPException(status_code=403, detail="需要商家权限")
    return user


# ============================================================
# Operator 权限限制
# ============================================================

# Operator 可访问的 API 路径前缀（精确匹配 / 前缀匹配）
OPERATOR_ALLOWED_PATHS = {
    "/health",
    "/ready",
    "/live",
    "/api/v1/dashboard",
    "/api/v1/customer",
    "/api/v1/orders",
    "/api/v1/reviews",
    "/api/v1/translate",
    "/api/v1/admin/stats",
    "/api/v1/shop/stats",
    "/api/v1/shop/platforms",
    "/api/v1/platforms",
    "/api/v1/internal/buyer",
    "/api/v1/message-center",
    "/api/v1/audit-logs",
}

# Operator 禁止访问的 API 路径（admin 专用）
OPERATOR_FORBIDDEN_PATHS = {
    "/api/v1/admin/users",
    "/api/v1/admin/create",
    "/api/v1/after-sales",
    "/api/v1/settings",
    "/api/v1/system",
    "/api/v1/agents",
}


async def get_current_admin_only(
    user: Dict[str, Any] = Security(get_current_user),
) -> Dict[str, Any]:
    """
    仅 admin 可访问（排除 operator）。
    用于系统设置、用户管理、系统监控等敏感操作。
    """
    if user.get("role") != "admin":
        raise HTTPException(
            status_code=403,
            detail="此操作需要超级管理员权限，运营专员无法访问",
        )
    return user


def check_operator_access(path: str, role: str) -> bool:
    """
    检查 operator 角色是否有权访问指定路径。
    operator 只能访问白名单中的路径，黑名单优先级更高。
    """
    if role != "operator":
        return True
    if path in OPERATOR_FORBIDDEN_PATHS:
        return False
    for allowed in OPERATOR_ALLOWED_PATHS:
        if path.startswith(allowed):
            return True
    return False


def extract_token_from_request(request: Request) -> Optional[str]:
    """
    从请求头提取 Bearer token（不抛异常）
    """
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return None


async def optional_current_user(
    request: Request,
) -> Optional[Dict[str, Any]]:
    """
    可选的当前用户（不强制要求登录）
    """
    token = extract_token_from_request(request)
    if not token:
        return None
    try:
        return verify_access_token(token)
    except HTTPException:
        return None
