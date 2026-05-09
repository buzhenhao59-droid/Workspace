# -*- coding: utf-8 -*-
"""
熔断降级机制 (Circuit Breaker & Fallback System)

功能：
- 增强现有的熔断器，支持更多状态和策略
- AI 5秒无响应自动切换到关键词库匹配模式
- 多级降级：API → 关键词匹配 → 预设回复
- 弹窗提示用户当前状态

原理：
1. AI调用设置5秒超时
2. 超时后自动降级到"关键词库匹配"
3. 关键词库使用预定义FAQ模板
4. 同时记录问题用于后续分析

配置项（.env）：
- FALLBACK_ENABLED=1
- FALLBACK_TIMEOUT=5 (秒)
- FALLBACK_KEYWORD_MATCH=1 (启用关键词匹配)
- FALLBACK_MAX_RETRIES=2 (最多重试次数)
"""
import json
import logging
import os
import time
import asyncio
import threading
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Callable, List, Tuple
from dataclasses import dataclass, field
from enum import Enum
from functools import wraps

logger = logging.getLogger(__name__)

# ============== 配置 ==============
FALLBACK_ENABLED = os.getenv("FALLBACK_ENABLED", "1") == "1"
FALLBACK_TIMEOUT = int(os.getenv("FALLBACK_TIMEOUT", "5"))  # 5秒超时
FALLBACK_KEYWORD_MATCH = os.getenv("FALLBACK_KEYWORD_MATCH", "1") == "1"
FALLBACK_MAX_RETRIES = int(os.getenv("FALLBACK_MAX_RETRIES", "2"))

# ============== 枚举定义 ==============
class ServiceStatus(Enum):
    """服务状态"""
    HEALTHY = "healthy"         # 健康
    DEGRADED = "degraded"       # 降级
    UNHEALTHY = "unhealthy"     # 不健康
    CIRCUIT_OPEN = "circuit_open"  # 熔断打开
    RECOVERING = "recovering"   # 恢复中


class FallbackLevel(Enum):
    """降级级别"""
    NONE = 0           # 正常
    TIMEOUT = 1       # 超时降级
    CIRCUIT = 2       # 熔断降级
    KEYWORD = 3       # 关键词匹配降级
    STATIC = 4        # 静态回复降级


@dataclass
class FallbackResult:
    """降级结果"""
    success: bool
    response: str
    fallback_level: int  # FallbackLevel
    used_cache: bool = False
    matched_keywords: List[str] = field(default_factory=list)
    error: Optional[str] = None
    latency_ms: float = 0.0
    
    @property
    def fallback_level_name(self) -> str:
        return FallbackLevel(self.fallback_level).name


# ============== 服务健康状态 ==============
class ServiceHealthMonitor:
    """
    服务健康状态监控器
    
    追踪各服务的健康状态，用于智能路由。
    """
    
    def __init__(self):
        self._services: Dict[str, Dict] = {}
        self._lock = threading.RLock()
    
    def record_call(self, service: str, success: bool, latency_ms: float):
        """记录一次调用"""
        with self._lock:
            if service not in self._services:
                self._init_service(service)
            
            svc = self._services[service]
            svc["total_calls"] += 1
            svc["total_latency"] += latency_ms
            
            if success:
                svc["success_count"] += 1
            else:
                svc["failure_count"] += 1
            
            svc["last_call_time"] = time.time()
            svc["last_success"] = success
            
            # 更新状态
            self._update_status(service)
    
    def _init_service(self, service: str):
        """初始化服务状态"""
        self._services[service] = {
            "service": service,
            "total_calls": 0,
            "success_count": 0,
            "failure_count": 0,
            "total_latency": 0.0,
            "last_call_time": None,
            "last_success": None,
            "status": ServiceStatus.HEALTHY,
            "consecutive_failures": 0,
            "last_failure_time": None,
            "circuit_open_time": None,
        }
    
    def _update_status(self, service: str):
        """更新服务状态"""
        svc = self._services[service]
        failure_rate = svc["failure_count"] / max(1, svc["total_calls"])
        avg_latency = svc["total_latency"] / max(1, svc["total_calls"])
        
        # 连续失败判断
        if svc["last_success"] is False:
            svc["consecutive_failures"] += 1
        else:
            svc["consecutive_failures"] = 0
        
        # 状态判断
        if svc["consecutive_failures"] >= 5:
            svc["status"] = ServiceStatus.CIRCUIT_OPEN
            if not svc["circuit_open_time"]:
                svc["circuit_open_time"] = time.time()
        elif failure_rate > 0.3:
            svc["status"] = ServiceStatus.DEGRADED
        elif avg_latency > 3000:  # 3秒
            svc["status"] = ServiceStatus.DEGRADED
        else:
            svc["status"] = ServiceStatus.HEALTHY
            svc["circuit_open_time"] = None
    
    def get_status(self, service: str) -> ServiceStatus:
        """获取服务状态"""
        with self._lock:
            if service not in self._services:
                return ServiceStatus.HEALTHY
            return self._services[service]["status"]
    
    def get_stats(self, service: str) -> Optional[Dict]:
        """获取服务统计"""
        with self._lock:
            if service not in self._services:
                return None
            svc = self._services[service].copy()
            # 计算派生指标
            svc["success_rate"] = svc["success_count"] / max(1, svc["total_calls"])
            svc["avg_latency_ms"] = svc["total_latency"] / max(1, svc["total_calls"])
            svc["failure_rate"] = svc["failure_count"] / max(1, svc["total_calls"])
            return svc
    
    def is_available(self, service: str) -> bool:
        """检查服务是否可用"""
        status = self.get_status(service)
        return status in (ServiceStatus.HEALTHY, ServiceStatus.DEGRADED)
    
    def reset(self, service: str):
        """重置服务状态"""
        with self._lock:
            if service in self._services:
                self._init_service(service)


# 全局健康监控器
_health_monitor = ServiceHealthMonitor()


# ============== 关键词FAQ库 ==============
class KeywordFAQ:
    """
    关键词FAQ匹配器
    
    当AI服务不可用时，使用预定义的FAQ模板回复。
    """
    
    def __init__(self):
        self._faq: Dict[str, List[Dict]] = {
            # 中文FAQ
            "zh": [
                {
                    "keywords": ["你好", "您好", "hi", "hello", "嗨"],
                    "response": "您好！很高兴为您服务~请问有什么可以帮您的吗？",
                    "priority": 1
                },
                {
                    "keywords": ["谢谢", "感谢", "thank"],
                    "response": "不客气！很高兴能帮到您~有问题随时来找我~",
                    "priority": 1
                },
                {
                    "keywords": ["订单", "单号", "order", "ord-", "物流", "快递", "tracking"],
                    "response": "亲爱的，建议您提供一下订单号，我来帮您查询哦~",
                    "priority": 5
                },
                {
                    "keywords": ["退款", "refund", "钱", "钱款"],
                    "response": "关于退款问题，请提供一下订单号和退款原因，我帮您跟进处理~",
                    "priority": 5
                },
                {
                    "keywords": ["退货", "return", "换货"],
                    "response": "退货/换货可以帮您处理，请问是因为什么原因需要退换呢？",
                    "priority": 5
                },
                {
                    "keywords": ["地址", "在哪里", "位置", "location"],
                    "response": "我们支持全国配送哦，具体地址可以在下单时选择~",
                    "priority": 2
                },
                {
                    "keywords": ["时间", "营业", "上班", "hours"],
                    "response": "我们的服务时间是每天9:00-21:00，随时为您服务~",
                    "priority": 2
                },
                {
                    "keywords": ["电话", "联系", "contact", "手机"],
                    "response": "您可以拨打客服热线或在APP内联系我们~",
                    "priority": 2
                },
                {
                    "keywords": ["价格", "多少钱", "price", "cost"],
                    "response": "价格因商品不同而异，您可以查看商品详情页~",
                    "priority": 2
                },
                {
                    "keywords": ["投诉", "差评", "complaint", "不满"],
                    "response": "非常抱歉给您带来不好的体验，我会认真跟进您的问题~",
                    "priority": 5
                },
            ],
            
            # 英文FAQ
            "en": [
                {
                    "keywords": ["hello", "hi", "hey"],
                    "response": "Hello! How can I help you today?",
                    "priority": 1
                },
                {
                    "keywords": ["thank", "thanks"],
                    "response": "You're welcome! Happy to help!",
                    "priority": 1
                },
                {
                    "keywords": ["order", "tracking", "delivery", "shipping"],
                    "response": "Could you please provide your order number? I'll check it for you.",
                    "priority": 5
                },
                {
                    "keywords": ["refund", "money", "cancel"],
                    "response": "For refund inquiries, please provide your order number and reason. I'll help you with that.",
                    "priority": 5
                },
                {
                    "keywords": ["return", "exchange"],
                    "response": "I can help you with returns or exchanges. What seems to be the issue?",
                    "priority": 5
                },
                {
                    "keywords": ["price", "cost", "how much"],
                    "response": "Prices vary by product. Please check the product page for details.",
                    "priority": 2
                },
            ],
            
            # 阿拉伯语FAQ
            "ar": [
                {
                    "keywords": ["مرحبا", "السلام", "hello", "hi"],
                    "response": "مرحباً! كيف يمكنني مساعدتك؟",
                    "priority": 1
                },
                {
                    "keywords": ["شكرا", "thanks"],
                    "response": "على الرحبام! سعيد بمساعدتك!",
                    "priority": 1
                },
                {
                    "keywords": ["طلب", "شحن", "تتبع"],
                    "response": "يرجى تقديم رقم الطلب للتحقق منه.",
                    "priority": 5
                },
                {
                    "keywords": ["استرداد", " 돈", "refund"],
                    "response": "للاستفسار عن الاسترداد، يرجى تقديم رقم الطلب والسبب.",
                    "priority": 5
                },
            ],
            
            # 俄语FAQ
            "ru": [
                {
                    "keywords": ["привет", "здравствуйте", "hello", "hi"],
                    "response": "Привет! Чем могу помочь?",
                    "priority": 1
                },
                {
                    "keywords": ["спасибо", "thanks"],
                    "response": "Пожалуйста! Рад помочь!",
                    "priority": 1
                },
                {
                    "keywords": ["заказ", "отслеживание", "доставка"],
                    "response": "Пожалуйста, предоставьте номер заказа для проверки.",
                    "priority": 5
                },
            ],
        }
    
    def match(self, text: str, language: str = "zh") -> Tuple[Optional[str], List[str]]:
        """
        匹配FAQ
        
        Args:
            text: 用户输入
            language: 语言
            
        Returns:
            (匹配的回复, 匹配的关键词列表)
        """
        if not text:
            return None, []
        
        text_lower = text.lower().strip()
        faq_list = self._faq.get(language, self._faq.get("en", []))
        
        # 按优先级排序
        sorted_faq = sorted(faq_list, key=lambda x: x["priority"], reverse=True)
        
        for faq in sorted_faq:
            for keyword in faq["keywords"]:
                if keyword.lower() in text_lower:
                    return faq["response"], [keyword]
        
        return None, []
    
    def get_generic_fallback(self, language: str = "zh") -> str:
        """获取通用降级回复"""
        fallbacks = {
            "zh": "亲爱的，我现在有点忙，您可以先说说您的问题类型，我帮您看看~比如：订单/退款/商品咨询等。",
            "en": "I'm a bit busy right now. Could you tell me what you need help with? Like: order/refund/product inquiry.",
            "ar": "أنا مشغول قليلاً الآن. هل يمكنك إخباري بما تحتاج مساعدة فيه؟",
            "ru": "Я немного занят сейчас. Вы можете сказать, чем я могу помочь?",
            "th": "ตอนนี้ผม/หนูยุ่งนิดหน่อยค่ะ/ครับ ช่วยบอกว่าต้องการให้ช่วยเรื่องอะไรได้ไหมคะ/ครับ?",
            "vi": "Hiện tôi hơi bận. Bạn có thể cho tôi biết bạn cần giúp gì không?",
            "id": "Saya agak sibuk sekarang. Bisa tolong beritahu saya apa yang kamu butuhkan?",
            "ms": "Saya agak sibuk sekarang. Boleh beritahu saya apa yang anda perlukan?",
            "tl": "Medyo busy ako ngayon. Pwede mo bang sabihin kung ano ang kailangan mo?",
        }
        return fallbacks.get(language, fallbacks["en"])


# 全局FAQ
_keyword_faq = KeywordFAQ()


# ============== 熔断降级装饰器 ==============
def circuit_breaker_fallback(
    service_name: str,
    timeout: float = FALLBACK_TIMEOUT,
    max_retries: int = FALLBACK_MAX_RETRIES,
    keyword_match: bool = FALLBACK_KEYWORD_MATCH
):
    """
    熔断降级装饰器
    
    使用方式:
        @circuit_breaker_fallback("deepseek", timeout=5)
        def call_deepseek(messages):
            ...
    
    功能：
    - 包装函数调用
    - 超时后自动降级到关键词匹配
    - 记录健康状态
    - 支持重试
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            return _sync_circuit_breaker(
                func, service_name, timeout, max_retries, keyword_match,
                args, kwargs
            )
        return wrapper
    
    @wraps(func)
    async def async_wrapper(*args, **kwargs):
        return await _async_circuit_breaker(
            func, service_name, timeout, max_retries, keyword_match,
            args, kwargs
        )
    
    # 根据原函数类型返回
    import asyncio
    if asyncio.iscoroutinefunction(func):
        return async_wrapper
    else:
        return wrapper


def _sync_circuit_breaker(
    func: Callable,
    service_name: str,
    timeout: float,
    max_retries: int,
    keyword_match: bool,
    args: tuple,
    kwargs: dict
) -> FallbackResult:
    """同步熔断降级"""
    if not FALLBACK_ENABLED:
        start = time.time()
        try:
            result = func(*args, **kwargs)
            latency_ms = (time.time() - start) * 1000
            _health_monitor.record_call(service_name, True, latency_ms)
            return FallbackResult(
                success=True,
                response=result or "",
                fallback_level=FallbackLevel.NONE.value,
                latency_ms=latency_ms
            )
        except Exception as e:
            latency_ms = (time.time() - start) * 1000
            _health_monitor.record_call(service_name, False, latency_ms)
            return FallbackResult(
                success=False,
                response=str(e),
                fallback_level=FallbackLevel.STATIC.value,
                error=str(e),
                latency_ms=latency_ms
            )
    
    # 尝试调用
    for attempt in range(max_retries + 1):
        start = time.time()
        
        try:
            # 使用线程超时调用
            result = _call_with_timeout(func, args, kwargs, timeout)
            latency_ms = (time.time() - start) * 1000
            
            if result is not None:
                _health_monitor.record_call(service_name, True, latency_ms)
                return FallbackResult(
                    success=True,
                    response=result,
                    fallback_level=FallbackLevel.NONE.value,
                    latency_ms=latency_ms
                )
            else:
                # 超时或返回None
                _health_monitor.record_call(service_name, False, latency_ms)
                
        except TimeoutError:
            latency_ms = (time.time() - start) * 1000
            _health_monitor.record_call(service_name, False, latency_ms)
            logger.warning(f"[Fallback] {service_name} 超时 (attempt {attempt + 1})")
            
        except Exception as e:
            latency_ms = (time.time() - start) * 1000
            _health_monitor.record_call(service_name, False, latency_ms)
            logger.error(f"[Fallback] {service_name} 调用失败: {e}")
    
    # 所有重试都失败，降级
    return _do_fallback(keyword_match, service_name)


def _sync_call_with_timeout(func: Callable, args: tuple, kwargs: dict, timeout: float):
    """带超时的同步调用"""
    import queue
    import functools
    
    result_queue = queue.Queue()
    exception_queue = queue.Queue()
    
    def target():
        try:
            result = func(*args, **kwargs)
            result_queue.put(("ok", result))
        except Exception as e:
            exception_queue.put(("error", e))
    
    thread = threading.Thread(target=target)
    thread.daemon = True
    thread.start()
    thread.join(timeout)
    
    if thread.is_alive():
        # 超时
        raise TimeoutError(f"Function call timed out after {timeout}s")
    
    if not exception_queue.empty():
        _, exc = exception_queue.get()
        raise exc
    
    if not result_queue.empty():
        _, result = result_queue.get()
        return result
    
    return None


async def _async_circuit_breaker(
    func: Callable,
    service_name: str,
    timeout: float,
    max_retries: int,
    keyword_match: bool,
    args: tuple,
    kwargs: dict
) -> FallbackResult:
    """异步熔断降级"""
    if not FALLBACK_ENABLED:
        start = time.time()
        try:
            result = await func(*args, **kwargs)
            latency_ms = (time.time() - start) * 1000
            _health_monitor.record_call(service_name, True, latency_ms)
            return FallbackResult(
                success=True,
                response=result or "",
                fallback_level=FallbackLevel.NONE.value,
                latency_ms=latency_ms
            )
        except Exception as e:
            latency_ms = (time.time() - start) * 1000
            _health_monitor.record_call(service_name, False, latency_ms)
            return FallbackResult(
                success=False,
                response=str(e),
                fallback_level=FallbackLevel.STATIC.value,
                error=str(e),
                latency_ms=latency_ms
            )
    
    # 尝试调用
    for attempt in range(max_retries + 1):
        start = time.time()
        
        try:
            result = await asyncio.wait_for(
                func(*args, **kwargs),
                timeout=timeout
            )
            latency_ms = (time.time() - start) * 1000
            
            if result is not None:
                _health_monitor.record_call(service_name, True, latency_ms)
                return FallbackResult(
                    success=True,
                    response=result,
                    fallback_level=FallbackLevel.NONE.value,
                    latency_ms=latency_ms
                )
            
        except asyncio.TimeoutError:
            latency_ms = (time.time() - start) * 1000
            _health_monitor.record_call(service_name, False, latency_ms)
            logger.warning(f"[Fallback] {service_name} 超时 (attempt {attempt + 1})")
            
        except Exception as e:
            latency_ms = (time.time() - start) * 1000
            _health_monitor.record_call(service_name, False, latency_ms)
            logger.error(f"[Fallback] {service_name} 调用失败: {e}")
    
    # 降级
    return _do_fallback(keyword_match, service_name)


def _do_fallback(keyword_match: bool, service_name: str) -> FallbackResult:
    """执行降级逻辑"""
    # 尝试关键词匹配
    if keyword_match:
        # 从参数中提取用户消息
        user_message = ""
        language = "zh"
        
        # 这里需要从上下文中获取，实际使用时会有更好的方式
        # 暂时返回通用降级回复
        fallback_response = _keyword_faq.get_generic_fallback(language)
        
        return FallbackResult(
            success=True,
            response=fallback_response,
            fallback_level=FallbackLevel.KEYWORD.value,
            error=f"{service_name} 不可用，已降级"
        )
    
    # 完全降级
    return FallbackResult(
        success=False,
        response="服务繁忙，请稍后重试",
        fallback_level=FallbackLevel.STATIC.value,
        error=f"{service_name} 不可用"
    )


def _call_with_timeout(func: Callable, args: tuple, kwargs: dict, timeout: float):
    """带超时的调用（同步版本）"""
    return _sync_call_with_timeout(func, args, kwargs, timeout)


# ============== 降级API调用器 ==============
class FallbackAPICaller:
    """
    带降级的API调用器
    
    封装AI API调用，提供自动降级能力。
    """
    
    def __init__(self, service_name: str = "deepseek"):
        self.service_name = service_name
    
    def call_sync(
        self,
        api_func: Callable,
        user_message: str,
        language: str = "zh",
        *args, **kwargs
    ) -> FallbackResult:
        """
        同步调用API，自动降级
        
        Args:
            api_func: API调用函数
            user_message: 用户消息（用于关键词匹配）
            language: 语言
            *args, **kwargs: 传递给API函数的其他参数
        """
        start = time.time()
        
        # 尝试调用
        for attempt in range(FALLBACK_MAX_RETRIES + 1):
            try:
                result = api_func(*args, **kwargs)
                latency_ms = (time.time() - start) * 1000
                
                if result:
                    _health_monitor.record_call(self.service_name, True, latency_ms)
                    return FallbackResult(
                        success=True,
                        response=result,
                        fallback_level=FallbackLevel.NONE.value,
                        latency_ms=latency_ms
                    )
            
            except Exception as e:
                latency_ms = (time.time() - start) * 1000
                _health_monitor.record_call(self.service_name, False, latency_ms)
                logger.warning(f"[Fallback] {self.service_name} 调用失败 (attempt {attempt + 1}): {e}")
        
        # 降级
        return self._fallback(user_message, language)
    
    async def call_async(
        self,
        api_func: Callable,
        user_message: str,
        language: str = "zh",
        *args, **kwargs
    ) -> FallbackResult:
        """异步调用API，自动降级"""
        start = time.time()
        
        for attempt in range(FALLBACK_MAX_RETRIES + 1):
            try:
                result = await asyncio.wait_for(
                    api_func(*args, **kwargs),
                    timeout=FALLBACK_TIMEOUT
                )
                latency_ms = (time.time() - start) * 1000
                
                if result:
                    _health_monitor.record_call(self.service_name, True, latency_ms)
                    return FallbackResult(
                        success=True,
                        response=result,
                        fallback_level=FallbackLevel.NONE.value,
                        latency_ms=latency_ms
                    )
            
            except asyncio.TimeoutError:
                latency_ms = (time.time() - start) * 1000
                _health_monitor.record_call(self.service_name, False, latency_ms)
                logger.warning(f"[Fallback] {self.service_name} 超时 (attempt {attempt + 1})")
                
            except Exception as e:
                latency_ms = (time.time() - start) * 1000
                _health_monitor.record_call(self.service_name, False, latency_ms)
                logger.error(f"[Fallback] {self.service_name} 调用失败: {e}")
        
        return self._fallback(user_message, language)
    
    def _fallback(self, user_message: str, language: str) -> FallbackResult:
        """执行降级"""
        # 尝试关键词匹配
        if FALLBACK_KEYWORD_MATCH:
            response, matched_keywords = _keyword_faq.match(user_message, language)
            
            if response:
                return FallbackResult(
                    success=True,
                    response=response,
                    fallback_level=FallbackLevel.KEYWORD.value,
                    matched_keywords=matched_keywords
                )
        
        # 通用降级回复
        return FallbackResult(
            success=True,
            response=_keyword_faq.get_generic_fallback(language),
            fallback_level=FallbackLevel.STATIC.value
        )


# ============== 降级消息模板 ==============
FALLBACK_MESSAGES = {
    "zh": {
        FallbackLevel.TIMEOUT: "亲爱的，我需要一点时间思考您的问题，您可以先说说具体是什么情况吗？",
        FallbackLevel.CIRCUIT: "AI助手正在思考，您可以先尝试搜索关键词或直接转接人工~",
        FallbackLevel.KEYWORD: "好的，我了解了，让我帮您查一下...",
        FallbackLevel.STATIC: "服务繁忙，请稍后重试，或者您可以尝试转接人工客服~",
    },
    "en": {
        FallbackLevel.TIMEOUT: "I'm thinking about your question — could you tell me more details?",
        FallbackLevel.CIRCUIT: "The AI is processing. You can search keywords or transfer to a human agent.",
        FallbackLevel.KEYWORD: "Got it, let me check that for you...",
        FallbackLevel.STATIC: "Service is busy. Please try again or transfer to a human agent.",
    },
    "ar": {
        FallbackLevel.TIMEOUT: "أحتاج إلى وقت للتفكير في سؤالك — هل يمكنك إخباري بالمزيد؟",
        FallbackLevel.CIRCUIT: "المساعد الذكي يفكر. يمكنك البحث أو التحويل إلى موظف.",
        FallbackLevel.KEYWORD: "فهمت، دعني أتحقق من ذلك...",
        FallbackLevel.STATIC: "الخدمة مشغولة. يرجى المحاولة لاحقاً أو التحويل إلى موظف.",
    },
    "ru": {
        FallbackLevel.TIMEOUT: "Мне нужно время подумать — расскажите подробнее?",
        FallbackLevel.CIRCUIT: "AI обрабатывает. Поищите или переключитесь на оператора.",
        FallbackLevel.KEYWORD: "Понял, проверю для вас...",
        FallbackLevel.STATIC: "Сервис занят. Попробуйте позже или переключитесь на оператора.",
    },
}


def get_fallback_message(level: FallbackLevel, language: str = "zh") -> str:
    """获取降级消息"""
    messages = FALLBACK_MESSAGES.get(language, FALLBACK_MESSAGES["zh"])
    return messages.get(level, messages[FallbackLevel.STATIC])


# ============== 快捷函数 ==============
def call_with_fallback(
    api_func: Callable,
    user_message: str,
    language: str = "zh",
    *args, **kwargs
) -> FallbackResult:
    """快捷调用"""
    caller = FallbackAPICaller()
    return caller.call_sync(api_func, user_message, language, *args, **kwargs)


def get_health_status(service: str = None) -> Dict:
    """获取健康状态"""
    if service:
        return _health_monitor.get_stats(service) or {"status": "unknown"}
    
    # 所有服务状态
    return {
        svc: _health_monitor.get_stats(svc)
        for svc in ["deepseek", "translation", "graphrag"]
        if _health_monitor.get_stats(svc)
    }


# ============== 导出 ==============
__all__ = [
    'ServiceStatus',
    'FallbackLevel',
    'FallbackResult',
    'ServiceHealthMonitor',
    'KeywordFAQ',
    'FallbackAPICaller',
    'circuit_breaker_fallback',
    'call_with_fallback',
    'get_fallback_message',
    'get_health_status',
]
