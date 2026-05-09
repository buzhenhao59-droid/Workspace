# -*- coding: utf-8 -*-
"""
API 限流中间件 - 防止恶意请求和滥用
支持按 IP、用户 ID、API Key 限流，支持突发流量和持续速率限制
支持 Redis 分布式存储（回退到内存）
"""
import time
import logging
import hashlib
from typing import Dict, Optional, Tuple
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
import redis.asyncio as redis

logger = logging.getLogger(__name__)


class RateLimitStrategy(str, Enum):
    """限流策略"""
    FIXED_WINDOW = "fixed"       # 固定窗口
    SLIDING_WINDOW = "sliding"   # 滑动窗口
    TOKEN_BUCKET = "token"       # 令牌桶


@dataclass
class RateLimitRule:
    """限流规则"""
    max_requests: int      # 最大请求数
    window_seconds: int   # 时间窗口（秒）
    strategy: str = "fixed"  # 策略
    burst: int = 0        # 突发容量（令牌桶）

    def __post_init__(self):
        if self.strategy not in ["fixed", "sliding", "token"]:
            self.strategy = "fixed"


@dataclass
class RateLimitResult:
    """限流结果"""
    allowed: bool
    current: int
    limit: int
    remaining: int
    reset_at: float
    retry_after: Optional[int] = None


class InMemoryRateLimiter:
    """内存版限流器（单实例使用）"""

    def __init__(self):
        self._requests: Dict[str, list] = defaultdict(list)
        self._tokens: Dict[str, float] = defaultdict(lambda: 0.0)
        self._lock = __import__("threading").Lock()

    def _cleanup(self, key: str, now: float, window: int):
        """清理过期请求记录"""
        self._requests[key] = [
            t for t in self._requests[key] if now - t < window
        ]

    def check_fixed(self, key: str, rule: RateLimitRule) -> RateLimitResult:
        """固定窗口限流"""
        now = time.time()
        with self._lock:
            self._cleanup(key, now, rule.window_seconds)
            current = len(self._requests[key])
            allowed = current < rule.max_requests
            if allowed:
                self._requests[key].append(now)
            reset_at = now + rule.window_seconds
            return RateLimitResult(
                allowed=allowed,
                current=current + (1 if allowed else 0),
                limit=rule.max_requests,
                remaining=max(0, rule.max_requests - current - (1 if allowed else 0)),
                reset_at=reset_at,
                retry_after=None if allowed else rule.window_seconds
            )

    def check_sliding(self, key: str, rule: RateLimitRule) -> RateLimitResult:
        """滑动窗口限流"""
        now = time.time()
        window_start = now - rule.window_seconds
        with self._lock:
            self._requests[key] = [t for t in self._requests[key] if t > window_start]
            current = len(self._requests[key])
            allowed = current < rule.max_requests
            if allowed:
                self._requests[key].append(now)
            reset_at = now + rule.window_seconds
            return RateLimitResult(
                allowed=allowed,
                current=current + (1 if allowed else 0),
                limit=rule.max_requests,
                remaining=max(0, rule.max_requests - current - (1 if allowed else 0)),
                reset_at=reset_at,
                retry_after=None if allowed else rule.window_seconds
            )

    def check_token(self, key: str, rule: RateLimitRule) -> RateLimitResult:
        """令牌桶限流"""
        now = time.time()
        rate = rule.max_requests / rule.window_seconds
        with self._lock:
            tokens = self._tokens.get(key, 0.0)
            tokens = min(rule.burst + rule.max_requests, tokens + (now - self._tokens.get(key + "_last", now)) * rate)
            self._tokens[key + "_last"] = now
            allowed = tokens >= 1
            if allowed:
                tokens -= 1
            self._tokens[key] = tokens
            return RateLimitResult(
                allowed=allowed,
                current=int(rule.burst + rule.max_requests - tokens),
                limit=rule.burst + rule.max_requests,
                remaining=max(0, int(tokens)),
                reset_at=now + (1 / rate) if tokens < 1 else now,
                retry_after=None if allowed else int((1 - tokens) / rate) + 1
            )


class RedisRateLimiter:
    """Redis 版限流器（分布式使用）"""

    def __init__(self, redis_client: redis.Redis):
        self._r = redis_client

    async def check(self, key: str, rule: RateLimitRule) -> RateLimitResult:
        """Redis 滑动窗口限流"""
        now = time.time()
        window_key = f"ratelimit:{rule.strategy}:{key}"
        pipeline = self._r.pipeline()
        pipeline.zremrangebyscore(window_key, 0, now - rule.window_seconds * 1000)
        pipeline.zcard(window_key)
        pipeline.zadd(window_key, {f"{now}": now * 1000})
        pipeline.expire(window_key, rule.window_seconds + 1)
        results = await pipeline.execute()
        current = results[1]
        allowed = current < rule.max_requests
        if not allowed:
            await self._r.zrem(window_key, f"{now}")
        reset_at = now + rule.window_seconds
        return RateLimitResult(
            allowed=allowed,
            current=current + (1 if allowed else 0),
            limit=rule.max_requests,
            remaining=max(0, rule.max_requests - current - (1 if allowed else 0)),
            reset_at=reset_at,
            retry_after=None if allowed else rule.window_seconds
        )


class RateLimiter:
    """
    API 限流器
    - 自动检测 Redis 是否可用
    - 可用时使用 Redis（支持分布式）
    - 不可用时回退到内存存储
    """

    def __init__(self):
        self._memory = InMemoryRateLimiter()
        self._redis: Optional[RedisRateLimiter] = None
        self._redis_client: Optional[redis.Redis] = None
        self._connected = False

    async def set_redis(self, redis_client: redis.Redis):
        """设置 Redis 客户端"""
        self._redis_client = redis_client
        self._redis = RedisRateLimiter(redis_client)
        try:
            await redis_client.ping()
            self._connected = True
            logger.info("RateLimiter: Redis 已连接，将使用 Redis 进行限流")
        except Exception:
            self._connected = False
            logger.warning("RateLimiter: Redis 不可用，将使用内存限流")

    def _make_key(self, identifier: str, scope: str) -> str:
        """生成限流 key"""
        return f"{scope}:{hashlib.md5(identifier.encode()).hexdigest()[:12]}"

    async def check(self, identifier: str, scope: str, rule: RateLimitRule) -> RateLimitResult:
        """检查限流"""
        key = self._make_key(identifier, scope)
        if self._connected and self._redis:
            return await self._redis.check(key, rule)
        if rule.strategy == "sliding":
            return self._memory.check_sliding(key, rule)
        elif rule.strategy == "token":
            return self._memory.check_token(key, rule)
        else:
            return self._memory.check_fixed(key, rule)

    def check_sync(self, identifier: str, scope: str, rule: RateLimitRule) -> RateLimitResult:
        """同步检查限流（用于中间件）"""
        key = self._make_key(identifier, scope)
        if rule.strategy == "sliding":
            return self._memory.check_sliding(key, rule)
        elif rule.strategy == "token":
            return self._memory.check_token(key, rule)
        else:
            return self._memory.check_fixed(key, rule)


# 全局单例
rate_limiter = RateLimiter()


# ============== 默认限流规则 ==============
DEFAULT_LIMITS = {
    "default": RateLimitRule(max_requests=100, window_seconds=60, strategy="sliding"),
    "chat": RateLimitRule(max_requests=30, window_seconds=60, strategy="sliding"),
    "chat_stream": RateLimitRule(max_requests=20, window_seconds=60, strategy="sliding"),
    "translate": RateLimitRule(max_requests=60, window_seconds=60, strategy="sliding"),
    "auth": RateLimitRule(max_requests=10, window_seconds=60, strategy="sliding"),
    "upload": RateLimitRule(max_requests=10, window_seconds=60, strategy="sliding"),
    "websocket": RateLimitRule(max_requests=100, window_seconds=60, strategy="token", burst=20),
    "admin": RateLimitRule(max_requests=200, window_seconds=60, strategy="sliding"),
}

# 高风险操作更严格的限制
STRICT_LIMITS = {
    "login": RateLimitRule(max_requests=5, window_seconds=300, strategy="sliding"),
    "transfer": RateLimitRule(max_requests=10, window_seconds=60, strategy="sliding"),
}


def get_client_ip(request: Request) -> str:
    """获取客户端真实 IP（支持代理）"""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip
    if request.client:
        return request.client.host
    return "unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    FastAPI 限流中间件
    自动对所有请求进行限流，支持路径级别的自定义规则
    """

    def __init__(self, app, limiter: RateLimiter):
        super().__init__(app)
        self._limiter = limiter
        # 路径 -> 限流规则（支持 /api/v1/ 前缀）
        self._path_limits = {
            # v1 API 路由
            "/api/v1/customer/chat": DEFAULT_LIMITS["chat"],
            "/api/v1/customer/send": DEFAULT_LIMITS["chat"],
            "/api/v1/chat": DEFAULT_LIMITS["chat"],
            "/api/v1/translate": DEFAULT_LIMITS["translate"],
            "/api/v1/admin/login": STRICT_LIMITS["login"],
            "/api/v1/seller/login": STRICT_LIMITS["login"],
            "/ws/": DEFAULT_LIMITS["websocket"],
            # v1 严格限制
            "/api/v1/internal/": RateLimitRule(max_requests=20, window_seconds=60, strategy="sliding"),
        }

    def _get_rule(self, path: str) -> RateLimitRule:
        """根据路径获取限流规则"""
        for prefix, rule in self._path_limits.items():
            if path.startswith(prefix):
                return rule
        return DEFAULT_LIMITS["default"]

    def _get_identifier(self, request: Request) -> str:
        """
        获取限流标识符（按优先级）：
        1. API Key（最优先）
        2. JWT user_id（已认证用户）
        3. session_id（会话级别）
        4. client IP（兜底）
        """
        # 1. API Key
        api_key = request.headers.get("X-Api-Key") or request.headers.get("Authorization", "")[7:] if request.headers.get("Authorization", "").startswith("Bearer ") else ""
        if api_key and len(api_key) > 10:
            return f"apikey:{hashlib.md5(api_key.encode()).hexdigest()[:12]}"

        # 2. JWT user_id
        if hasattr(request.state, "user_id") and request.state.user_id:
            return f"user:{request.state.user_id}"
        if hasattr(request.state, "username") and request.state.username:
            return f"user:{request.state.username}"

        # 3. session_id
        session_id = (
            request.headers.get("X-Session-Id")
            or request.cookies.get("session_id")
            or getattr(request.state, "session_id", None)
        )
        if session_id:
            return f"session:{session_id[:16]}"

        # 4. client IP (兜底)
        return f"ip:{get_client_ip(request)}"

    async def dispatch(self, request: Request, call_next):
        """中间件处理"""
        path = request.url.path
        # 跳过健康检查、指标、文档等路径
        if path in (
            "/health", "/ready", "/live", "/metrics",
            "/docs", "/redoc", "/openapi.json", "/favicon.ico",
            # Swagger UI v1 路径
            "/api/v1/docs", "/api/v1/redoc", "/api/v1/openapi.json",
        ):
            return await call_next(request)
        # 开发模式绕过：本地请求不受限
        client_ip = get_client_ip(request)
        if client_ip in ("127.0.0.1", "::1", "localhost") or client_ip.startswith("192.168.") or client_ip.startswith("10."):
            return await call_next(request)
        # Operator 权限拦截（检查路径白名单/黑名单）
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            try:
                from jwt_auth import decode_token
                payload = decode_token(auth_header[7:])
                if payload.get("role") == "operator":
                    from jwt_auth import check_operator_access
                    if not check_operator_access(path, "operator"):
                        return JSONResponse(
                            status_code=403,
                            content={
                                "success": False,
                                "error": {
                                    "code": "RTK_AUTH00403",
                                    "message": "运营专员无权访问此功能",
                                    "detail": f"路径 {path} 需要管理员权限",
                                }
                            }
                        )
            except Exception:
                pass  # 认证错误由后续路由处理
        rule = self._get_rule(path)
        identifier = self._get_identifier(request)
        scope = path.split("/")[2] if len(path.split("/")) > 2 else "default"
        result = self._limiter.check_sync(identifier, scope, rule)
        headers = {
            "X-RateLimit-Limit": str(result.limit),
            "X-RateLimit-Remaining": str(result.remaining),
            "X-RateLimit-Reset": str(int(result.reset_at)),
        }
        if not result.allowed:
            headers["Retry-After"] = str(result.retry_after)
            logger.warning(f"限流触发: {identifier} {path} ({result.current}/{result.limit})")
            return JSONResponse(
                status_code=429,
                content={
                    "success": False,
                    "error": "请求过于频繁，请稍后再试",
                    "retry_after": result.retry_after,
                    "limit": result.limit,
                    "remaining": 0,
                },
                headers=headers
            )
        response = await call_next(request)
        for k, v in headers.items():
            response.headers[k] = v
        return response
