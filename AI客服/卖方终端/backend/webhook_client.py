# -*- coding: utf-8 -*-
"""
Webhook 客户端模块
提供：
- 带重试的 HTTP 调用（指数退避）
- HMAC-SHA256 签名生成与验证
- 防重放攻击（时间戳窗口）
- 请求日志记录
"""
import time
import hmac
import hashlib
import base64
import logging
import threading
from typing import Optional, Dict, Any, Callable, TypeVar, List
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import requests

logger = logging.getLogger(__name__)

T = TypeVar('T')


# ============== 告警级别枚举 ==============
class AlertLevel(str, Enum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


# ============== Webhook 配置 ==============
@dataclass
class WebhookConfig:
    """Webhook 调用配置"""
    url: str
    timeout: float = 10.0
    max_retries: int = 3
    retry_base_delay: float = 1.0  # 基础退避延迟（秒）
    retry_max_delay: float = 30.0  # 最大退避延迟
    success_codes: tuple = (200, 201, 202, 204)
    raise_on_failure: bool = False


@dataclass
class SignedRequestConfig:
    """签名请求配置"""
    secret: str
    timestamp_ttl: int = 300  # 5分钟时间戳窗口
    algorithm: str = "sha256"


# ============== 签名工具 ==============
def generate_signature(secret: str, timestamp: str, method: str, path: str,
                       body: str = "") -> str:
    """
    生成 HMAC-SHA256 请求签名
    格式: base64(HMAC-SHA256(secret, timestamp + method + path + body))
    """
    payload = f"{timestamp}{method.upper()}{path}{body}"
    sig = hmac.new(
        secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256
    ).digest()
    return base64.b64encode(sig).decode("utf-8")


def verify_signature(secret: str, timestamp: str, method: str, path: str,
                     body: str, signature: str) -> bool:
    """验证签名"""
    expected = generate_signature(secret, timestamp, method, path, body)
    return hmac.compare_digest(expected, signature)


def is_timestamp_valid(timestamp_str: str, ttl: int = 300) -> bool:
    """检查时间戳是否在有效窗口内（防重放）"""
    try:
        ts = int(timestamp_str)
        now = int(datetime.now(timezone.utc).timestamp())
        return abs(now - ts) <= ttl
    except (ValueError, OSError):
        return False


# ============== 重试策略 ==============
def exponential_backoff(attempt: int, base: float = 1.0, max_delay: float = 30.0,
                       jitter: bool = True) -> float:
    """
    指数退避延迟计算
    attempt: 当前重试次数（0-based）
    base: 基础延迟
    max_delay: 最大延迟
    jitter: 是否添加随机抖动（防止惊群效应）
    """
    delay = min(base * (2 ** attempt), max_delay)
    if jitter:
        import random
        delay = delay * (0.5 + random.random() * 0.5)  # 50%-100%
    return delay


# ============== Webhook 客户端 ==============
class WebhookClient:
    """
    带重试机制的 Webhook 客户端

    使用示例:
        client = WebhookClient(
            default_config=WebhookConfig(
                url="https://example.com/webhook",
                max_retries=3,
                timeout=10.0,
            ),
            secret="your-hmac-secret",
        )
        result = client.post("/webhook", json={"event": "transfer"})
    """

    def __init__(
        self,
        base_url: str = "",
        default_config: Optional[WebhookConfig] = None,
        secret: Optional[str] = None,
        default_headers: Optional[Dict[str, str]] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.default_config = default_config or WebhookConfig(url="")
        self.secret = secret or ""
        self.default_headers = default_headers or {}
        self._session = requests.Session()
        self._log: List[Dict] = []
        self._log_lock = threading.Lock()

    def _get_url(self, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        return f"{self.base_url}{path}"

    def _make_headers(self, path: str, method: str, body: str = "",
                     extra_headers: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Ruitalk-Webhook/1.0",
            **self.default_headers,
        }
        if extra_headers:
            headers.update(extra_headers)

        if self.secret:
            ts = str(int(datetime.now(timezone.utc).timestamp()))
            sig = generate_signature(self.secret, ts, method, path, body)
            headers["X-Internal-Signature"] = sig
            headers["X-Internal-Timestamp"] = ts

        return headers

    def _call(
        self,
        method: str,
        path: str,
        config: Optional[WebhookConfig] = None,
        headers: Optional[Dict[str, str]] = None,
        body: str = "",
        **kwargs,
    ) -> tuple[bool, Optional[requests.Response], str]:
        """执行 HTTP 调用（带重试）"""
        cfg = config or self.default_config
        url = self._get_url(path)

        if isinstance(kwargs.get("json"), (dict, list)):
            import json as _json
            body = _json.dumps(kwargs["json"], ensure_ascii=False)
            kwargs = {k: v for k, v in kwargs.items() if k != "json"}

        req_headers = self._make_headers(path, method, body, headers)
        last_error = "未知错误"

        for attempt in range(cfg.max_retries + 1):
            try:
                delay = exponential_backoff(attempt) if attempt > 0 else 0
                if delay > 0 and attempt > 0:
                    logger.debug(f"重试 {attempt}次，等待 {delay:.1f}s...")
                    time.sleep(delay)

                resp = self._session.request(
                    method.upper(),
                    url,
                    headers=req_headers,
                    data=body.encode("utf-8") if body else None,
                    timeout=cfg.timeout,
                    **kwargs,
                )

                if resp.status_code in cfg.success_codes:
                    self._log_call(method, path, resp.status_code, attempt, None)
                    return True, resp, ""

                last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
                logger.warning(
                    f"Webhook 调用失败 [{resp.status_code}] {method} {url} "
                    f"(尝试 {attempt+1}/{cfg.max_retries+1}): {last_error}"
                )

                # 4xx 错误不重试（客户端错误）
                if 400 <= resp.status_code < 500:
                    self._log_call(method, path, resp.status_code, attempt, last_error)
                    if cfg.raise_on_failure:
                        raise WebhookError(f"Webhook 调用失败: {last_error}")
                    return False, resp, last_error

            except requests.exceptions.Timeout:
                last_error = f"请求超时 ({cfg.timeout}s)"
                logger.warning(
                    f"Webhook 超时 {method} {url} "
                    f"(尝试 {attempt+1}/{cfg.max_retries+1})"
                )
            except requests.exceptions.ConnectionError as e:
                last_error = f"连接失败: {e}"
                logger.warning(
                    f"Webhook 连接失败 {method} {url} "
                    f"(尝试 {attempt+1}/{cfg.max_retries+1}): {last_error}"
                )
            except Exception as e:
                last_error = str(e)
                logger.error(
                    f"Webhook 异常 {method} {url} "
                    f"(尝试 {attempt+1}/{cfg.max_retries+1}): {last_error}"
                )

        # 所有重试耗尽
        self._log_call(method, path, -1, cfg.max_retries, last_error)
        if cfg.raise_on_failure:
            raise WebhookError(f"Webhook 重试耗尽: {last_error}")
        return False, None, last_error

    def _log_call(self, method: str, path: str, status: int, attempt: int, error: Optional[str]):
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "method": method,
            "path": path,
            "status": status,
            "attempt": attempt,
            "error": error,
        }
        with self._log_lock:
            self._log.append(entry)
            # 只保留最近 1000 条
            if len(self._log) > 1000:
                self._log = self._log[-1000:]

    # ---- 公开方法 ----
    def post(self, path: str, json: Any = None, **kwargs) -> tuple[bool, Optional[Any], str]:
        """POST 请求"""
        ok, resp, err = self._call("POST", path, body="", json=json, **kwargs)
        if ok and resp is not None:
            try:
                return True, resp.json(), ""
            except Exception:
                return True, resp.text, ""
        return ok, None, err

    def get(self, path: str, params: Optional[Dict] = None, **kwargs) -> tuple[bool, Optional[Any], str]:
        """GET 请求"""
        ok, resp, err = self._call("GET", path, params=params, **kwargs)
        if ok and resp is not None:
            try:
                return True, resp.json(), ""
            except Exception:
                return True, resp.text, ""
        return ok, None, err

    def put(self, path: str, json: Any = None, **kwargs) -> tuple[bool, Optional[Any], str]:
        """PUT 请求"""
        ok, resp, err = self._call("PUT", path, body="", json=json, **kwargs)
        if ok and resp is not None:
            try:
                return True, resp.json(), ""
            except Exception:
                return True, resp.text, ""
        return ok, None, err

    def delete(self, path: str, **kwargs) -> tuple[bool, Optional[Any], str]:
        """DELETE 请求"""
        ok, resp, err = self._call("DELETE", path, **kwargs)
        if ok and resp is not None:
            try:
                return True, resp.json(), ""
            except Exception:
                return True, resp.text, ""
        return ok, None, err

    def get_log(self, limit: int = 100) -> List[Dict]:
        """获取最近调用日志"""
        with self._log_lock:
            return list(self._log[-limit:])


class WebhookError(Exception):
    """Webhook 调用异常"""
    pass


# ============== 回调签名验证装饰器 ==============
def verify_internal_callback(
    secret: Optional[str] = None,
    ttl: int = 300,
    timestamp_header: str = "X-Internal-Timestamp",
    signature_header: str = "X-Internal-Signature",
):
    """
    FastAPI 依赖项：验证内部回调签名

    使用示例:
        @app.post("/api/internal/buyer-transfer")
        async def buyer_transfer(
            body: TransferRequest,
            _=Depends(verify_internal_callback()),
        ):
            ...
    """
    def dependency(request: requests.Request = None):
        # 延迟导入以避免循环依赖
        try:
            from fastapi import Request
        except ImportError:
            return True  # 非 FastAPI 环境跳过验证

        import os
        _secret = secret or os.getenv("INTERNAL_API_SECRET", "")

        if not _secret:
            logger.warning("[回调验证] 未配置 INTERNAL_API_SECRET，跳过签名验证")
            return True

        ts = request.headers.get(timestamp_header, "")
        sig = request.headers.get(signature_header, "")

        if not ts or not sig:
            logger.warning(f"[回调验证] 缺少签名头（{timestamp_header}/{signature_header}）")
            raise WebhookError("Missing signature headers")

        # 时间戳防重放检查
        if not is_timestamp_valid(ts, ttl):
            logger.warning(f"[回调验证] 时间戳已过期: {ts}")
            raise WebhookError("Timestamp expired or invalid")

        # 获取请求体（需要先读取 body）
        body_bytes = b""
        try:
            body_bytes = request.body()
        except Exception:
            pass

        body_str = body_bytes.decode("utf-8", errors="replace")
        path = request.url.path
        method = request.method

        # 验证签名
        if not verify_signature(_secret, ts, method, path, body_str, sig):
            logger.warning(f"[回调验证] 签名验证失败: {method} {path}")
            raise WebhookError("Invalid signature")

        logger.debug(f"[回调验证] 签名验证通过: {method} {path}")
        return True

    return dependency


# ============== 跨系统通知器（卖方系统用）==============
class CrossSystemNotifier:
    """
    跨系统通知客户端（卖方→买方）

    使用示例:
        from config import BUYER_API_HOST, INTERNAL_API_SECRET
        notifier = CrossSystemNotifier(
            buyer_base_url=BUYER_API_HOST,
            internal_token=INTERNAL_API_SECRET,
        )

        # 通知买方：会话转回AI
        ok, data, err = notifier.notify_buyer_back_to_ai(
            session_id="xxx", customer_id="yyy"
        )
    """

    def __init__(
        self,
        buyer_base_url: str,
        internal_token: str,
        max_retries: int = 3,
        timeout: float = 10.0,
    ):
        self.client = WebhookClient(
            base_url=buyer_base_url,
            default_config=WebhookConfig(
                url="",
                max_retries=max_retries,
                timeout=timeout,
            ),
            secret=internal_token,
        )

    def notify_buyer_back_to_ai(
        self, session_id: str, customer_id: str = ""
    ) -> tuple[bool, Optional[Any], str]:
        """
        卖方通知买方：人工会话已转回AI模式
        """
        return self.client.post(
            "/api/v1/internal/buyer-back-to-ai",
            json={"session_id": session_id, "customer_id": customer_id},
        )

    def notify_buyer_message(
        self, session_id: str, content: str, customer_id: str = ""
    ) -> tuple[bool, Optional[Any], str]:
        """
        卖方通知买方：人工客服发送了新消息
        """
        return self.client.post(
            "/api/v1/internal/buyer-message",
            json={
                "session_id": session_id,
                "content": content,
                "customer_id": customer_id,
            },
        )

    def get_buyer_status(self) -> tuple[bool, Optional[Any], str]:
        """获取买方系统健康状态"""
        return self.client.get("/health")
