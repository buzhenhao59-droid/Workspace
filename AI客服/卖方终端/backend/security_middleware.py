# -*- coding: utf-8 -*-
"""
安全中间件 - 为 FastAPI 应用提供全面的安全保护
"""
import time
import hashlib
import hmac
import secrets
from typing import Optional, Dict, List, Callable
from fastapi import Request, Response, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

# ============== 安全配置 ==============

class SecurityConfig:
    """安全配置类"""
    
    def __init__(
        self,
        secret_key: str = "",
        allowed_hosts: Optional[List[str]] = None,
        allowed_origins: Optional[List[str]] = None,
        max_content_length: int = 10 * 1024 * 1024,  # 10MB
        enable_csrf_protection: bool = True,
        enable_hsts: bool = True,
        enable_csp: bool = True,
        api_key_header: str = "X-API-Key",
    ):
        self.secret_key = secret_key or secrets.token_hex(32)
        self.allowed_hosts = allowed_hosts or ["localhost", "127.0.0.1"]
        self.allowed_origins = allowed_origins or ["http://localhost:5173"]
        self.max_content_length = max_content_length
        self.enable_csrf_protection = enable_csrf_protection
        self.enable_hsts = enable_hsts
        self.enable_csp = enable_csp
        self.api_key_header = api_key_header


# ============== 安全响应头 ==============

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """安全响应头中间件"""
    
    def __init__(self, app: ASGIApp, config: Optional[SecurityConfig] = None):
        super().__init__(app)
        self.config = config or SecurityConfig()
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        
        # HSTS (HTTP Strict Transport Security)
        if self.config.enable_hsts:
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains; preload"
            )
        
        # X-Frame-Options (防止点击劫持)
        response.headers["X-Frame-Options"] = "DENY"
        
        # X-Content-Type-Options (防止 MIME 类型嗅探)
        response.headers["X-Content-Type-Options"] = "nosniff"
        
        # X-XSS-Protection (XSS 过滤器 - 已废弃但仍添加作为后备)
        response.headers["X-XSS-Protection"] = "1; mode=block"
        
        # Content Security Policy
        if self.config.enable_csp:
            csp = (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
                "style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data: https:; "
                "font-src 'self' data:; "
                "connect-src 'self' https://api.deepseek.com; "
                "frame-ancestors 'none';"
            )
            response.headers["Content-Security-Policy"] = csp
        
        # Referrer Policy
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        
        # Permissions Policy
        response.headers["Permissions-Policy"] = (
            "geolocation=(), "
            "microphone=(), "
            "camera=(), "
            "payment=()"
        )
        
        # Cache Control (敏感数据不缓存)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
            response.headers["Pragma"] = "no-cache"
        
        # X-Request-ID (请求追踪)
        request_id = request.headers.get("X-Request-ID") or secrets.token_hex(16)
        response.headers["X-Request-ID"] = request_id
        
        return response


# ============== Host 验证 ==============

class HostValidationMiddleware(BaseHTTPMiddleware):
    """Host 验证中间件"""
    
    def __init__(self, app: ASGIApp, config: Optional[SecurityConfig] = None):
        super().__init__(app)
        self.config = config or SecurityConfig()
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        host = request.headers.get("host", "").split(":")[0]
        
        # 检查 Host 头
        if host not in self.config.allowed_hosts:
            # 在生产环境中，拒绝未知 Host
            if self.config.secret_key:  # 已配置密钥，认为是生产环境
                return JSONResponse(
                    status_code=400,
                    content={"error": "Invalid Host header"},
                )
        
        return await call_next(request)


# ============== 速率限制 ==============

class RateLimitMiddleware(BaseHTTPMiddleware):
    """简单的内存速率限制中间件"""
    
    def __init__(
        self,
        app: ASGIApp,
        requests_per_minute: int = 60,
        burst_size: int = 10,
    ):
        super().__init__(app)
        self.requests_per_minute = requests_per_minute
        self.burst_size = burst_size
        self.requests: Dict[str, List[float]] = {}
    
    def _get_client_ip(self, request: Request) -> str:
        """获取客户端 IP"""
        # 检查代理头
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip
        
        if request.client:
            return request.client.host
        
        return "unknown"
    
    def _is_rate_limited(self, client_ip: str) -> bool:
        """检查是否超过速率限制"""
        now = time.time()
        minute_ago = now - 60
        
        # 清理旧记录
        if client_ip in self.requests:
            self.requests[client_ip] = [
                t for t in self.requests[client_ip] if t > minute_ago
            ]
        else:
            self.requests[client_ip] = []
        
        # 检查限制
        if len(self.requests[client_ip]) >= self.requests_per_minute:
            return True
        
        # 记录请求
        self.requests[client_ip].append(now)
        return False
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # 跳过健康检查
        if request.url.path in ["/health", "/ready", "/live", "/metrics"]:
            return await call_next(request)
        
        client_ip = self._get_client_ip(request)
        
        if self._is_rate_limited(client_ip):
            return JSONResponse(
                status_code=429,
                content={
                    "error": "请求过于频繁，请稍后再试",
                    "retry_after": 60,
                },
                headers={"Retry-After": "60"},
            )
        
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(self.requests_per_minute)
        response.headers["X-RateLimit-Remaining"] = str(
            self.requests_per_minute - len(self.requests.get(client_ip, []))
        )
        
        return response


# ============== CSRF 保护 ==============

class CSRFProtectionMiddleware(BaseHTTPMiddleware):
    """CSRF 保护中间件"""
    
    # Safe methods (不需要 CSRF 验证)
    SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}
    
    def __init__(self, app: ASGIApp, config: Optional[SecurityConfig] = None):
        super().__init__(app)
        self.config = config or SecurityConfig()
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # 只对非安全方法进行 CSRF 检查
        if request.method not in self.SAFE_METHODS:
            # 检查 Origin 或 Referer 头
            origin = request.headers.get("origin")
            referer = request.headers.get("referer")
            
            if not origin and not referer:
                # API 请求可能没有这些头，跳过检查
                if not request.url.path.startswith("/api/"):
                    return JSONResponse(
                        status_code=403,
                        content={"error": "CSRF token missing"},
                    )
            
            # 如果有 Origin/Referer，验证是否来自允许的源
            if origin:
                allowed = any(
                    origin.startswith(allowed)
                    for allowed in self.config.allowed_origins
                )
                if not allowed:
                    return JSONResponse(
                        status_code=403,
                        content={"error": "Invalid origin"},
                    )
        
        return await call_next(request)


# ============== 请求签名验证 ==============

def verify_request_signature(
    secret_key: str,
    timestamp: str,
    signature: str,
    method: str,
    path: str,
    body: bytes = b"",
    max_age: int = 300,
) -> bool:
    """
    验证请求签名 (防止篡改和重放攻击)
    
    Args:
        secret_key: 密钥
        timestamp: 时间戳
        signature: 签名
        method: HTTP 方法
        path: 请求路径
        body: 请求体
        max_age: 签名最大有效期（秒）
    
    Returns:
        bool: 签名是否有效
    """
    # 检查时间戳（防止重放攻击）
    try:
        ts = int(timestamp)
        if abs(time.time() - ts) > max_age:
            return False
    except ValueError:
        return False
    
    # 计算期望的签名
    message = f"{timestamp}{method}{path}".encode()
    if body:
        message += hashlib.sha256(body).digest()
    
    expected = hmac.new(
        secret_key.encode(),
        message,
        hashlib.sha256
    ).hexdigest()
    
    return hmac.compare_digest(signature, expected)


def generate_request_signature(
    secret_key: str,
    method: str,
    path: str,
    body: bytes = b"",
) -> tuple[str, str]:
    """
    生成请求签名
    
    Returns:
        (timestamp, signature)
    """
    timestamp = str(int(time.time()))
    
    message = f"{timestamp}{method}{path}".encode()
    if body:
        message += hashlib.sha256(body).digest()
    
    signature = hmac.new(
        secret_key.encode(),
        message,
        hashlib.sha256
    ).hexdigest()
    
    return timestamp, signature


# ============== 输入验证和清理 ==============

def sanitize_input(text: str, max_length: int = 10000) -> str:
    """
    清理和验证输入
    
    Args:
        text: 输入文本
        max_length: 最大长度
    
    Returns:
        str: 清理后的文本
    """
    if not text:
        return ""
    
    # 限制长度
    text = text[:max_length]
    
    # 移除控制字符（保留换行和制表符）
    text = "".join(
        c for c in text
        if c == "\n" or c == "\t" or (ord(c) >= 32 and ord(c) != 127)
    )
    
    return text.strip()


def validate_api_key(api_key: str, valid_keys: List[str]) -> bool:
    """
    验证 API 密钥
    
    Args:
        api_key: API 密钥
        valid_keys: 有效密钥列表
    
    Returns:
        bool: 是否有效
    """
    if not api_key:
        return False
    
    # 使用恒定时间比较，防止时序攻击
    for valid_key in valid_keys:
        if hmac.compare_digest(api_key, valid_key):
            return True
    
    return False


# ============== 安全工具函数 ==============

def generate_secure_token(length: int = 32) -> str:
    """生成安全的随机令牌"""
    return secrets.token_urlsafe(length)


def hash_sensitive_data(data: str) -> str:
    """哈希敏感数据（如 API 密钥）"""
    return hashlib.sha256(data.encode()).hexdigest()


def constant_time_compare(a: str, b: str) -> bool:
    """恒定时间字符串比较（防止时序攻击）"""
    return hmac.compare_digest(a.encode(), b.encode())
