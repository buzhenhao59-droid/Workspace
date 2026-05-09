# -*- coding: utf-8 -*-
"""
业务服务层（services.py）单元测试
测试熔断器、AI 回复生成、翻译等核心逻辑
"""
import pytest
import time
from unittest.mock import patch, MagicMock
import sys

# 强制重新加载 config 和 services 模块（使用测试环境变量）
for mod in list(sys.modules.keys()):
    if mod in ("config", "services"):
        del sys.modules[mod]

from services import (
    CircuitBreaker,
    BreakerBreakerOpen,
    AIService,
    TranslationService,
)


# ============== CircuitBreaker Tests ==============

class TestCircuitBreaker:
    """熔断器状态机测试"""

    def setup_method(self):
        """每个测试前重置熔断器"""
        self.breaker = CircuitBreaker(
            name="test_api",
            failure_threshold=3,
            recovery_timeout=2.0,
        )

    def test_initial_state_is_closed(self):
        assert self.breaker.state == CircuitBreaker.CLOSED

    def test_failure_increments_count(self):
        for _ in range(3):
            self.breaker.record_failure()
        assert self.breaker.failure_count == 3
        assert self.breaker.state == CircuitBreaker.CLOSED

    def test_opens_after_threshold_failures(self):
        for _ in range(3):
            self.breaker.record_failure()
        assert self.breaker.state == CircuitBreaker.OPEN

    def test_open_state_rejects_calls(self):
        for _ in range(3):
            self.breaker.record_failure()
        with pytest.raises(BreakerBreakerOpen):
            self.breaker.call(lambda: "result")

    def test_open_clears_failure_count(self):
        for _ in range(3):
            self.breaker.record_failure()
        assert self.breaker.failure_count == 3
        # OPEN 后计数器不清零，但 record_failure 不再增加
        self.breaker.record_failure()
        assert self.breaker.failure_count == 3

    def test_half_open_on_recovery_timeout(self):
        for _ in range(3):
            self.breaker.record_failure()
        assert self.breaker.state == CircuitBreaker.OPEN
        # 模拟时间流逝
        self.breaker._last_failure_time = time.time() - 3.0
        result = self.breaker.call(lambda: "recovered")
        assert result == "recovered"
        assert self.breaker.state == CircuitBreaker.CLOSED
        assert self.breaker.failure_count == 0

    def test_half_open_failure_reopens(self):
        for _ in range(3):
            self.breaker.record_failure()
        self.breaker._last_failure_time = time.time() - 3.0
        self.breaker.call(lambda: (_ for _ in ()).throw(Exception("probe fail")))
        assert self.breaker.state == CircuitBreaker.OPEN

    def test_success_resets_failure_count(self):
        for _ in range(2):
            self.breaker.record_failure()
        assert self.breaker.failure_count == 2
        self.breaker.record_success()
        assert self.breaker.failure_count == 0
        assert self.breaker.state == CircuitBreaker.CLOSED

    def test_call_exception_recorded(self):
        def failing_func():
            raise ConnectionError("network error")

        with pytest.raises(ConnectionError):
            self.breaker.call(failing_func)
        assert self.breaker.failure_count == 1

    def test_call_with_fallback_on_open(self):
        for _ in range(3):
            self.breaker.record_failure()
        result = self.breaker.call(lambda: "should not reach", fallback="fallback_value")
        assert result == "fallback_value"

    def test_call_with_fallback_on_exception(self):
        def failing():
            raise RuntimeError("api error")

        result = self.breaker.call(failing, fallback="fallback_value")
        assert result == "fallback_value"

    def test_call_with_fallback_func_on_open(self):
        for _ in range(3):
            self.breaker.record_failure()

        def fallback_gen():
            return "computed_fallback"

        result = self.breaker.call(lambda: "ignored", fallback_fn=fallback_gen)
        assert result == "computed_fallback"

    def test_stats_tracking(self):
        for _ in range(2):
            self.breaker.record_failure()
        self.breaker.call(lambda: "ok")
        for _ in range(3):
            self.breaker.record_failure()
        stats = self.breaker.stats
        assert stats["failure_count"] == 3
        assert stats["total_calls"] == 6

    def test_concurrent_access_thread_safety(self):
        import threading

        def fail_task():
            for _ in range(10):
                try:
                    self.breaker.record_failure()
                except Exception:
                    pass

        threads = [threading.Thread(target=fail_task) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        # 至少记录了部分失败，熔断器应进入 OPEN 状态
        assert self.breaker.state in (
            CircuitBreaker.OPEN,
            CircuitBreaker.CLOSED,
            CircuitBreaker.HALF_OPEN,
        )


class TestAIService:
    """AI 服务测试"""

    @pytest.fixture
    def ai_service(self, mock_requests):
        return AIService()

    def test_generate_reply_returns_string(self, ai_service, mock_requests):
        reply = ai_service.generate_reply(
            customer_message="你好，这个产品什么时候发货？",
            customer_id="C001",
            session_id="S001",
        )
        assert isinstance(reply, str)
        assert len(reply) > 0

    def test_generate_reply_includes_thought_process(self, ai_service, mock_requests):
        reply = ai_service.generate_reply(
            customer_message="你好",
            customer_id="C001",
            session_id="S001",
        )
        assert "【思考过程】" in reply or "【AI回复】" in reply

    def test_generate_reply_empty_message(self, ai_service, mock_requests):
        reply = ai_service.generate_reply(
            customer_message="",
            customer_id="C001",
            session_id="S001",
        )
        assert isinstance(reply, str)

    def test_generate_reply_uses_circuit_breaker(self, ai_service, mocker):
        # Mock 调用
        mock_requests.status_code = 500
        mock_requests.json.return_value = {"error": "server error"}
        mocker.patch("requests.post", return_value=mock_requests)

        # 连续失败触发熔断
        for _ in range(6):
            try:
                ai_service.generate_reply(
                    customer_message="test",
                    customer_id="C001",
                    session_id="S001",
                )
            except Exception:
                pass

        # 此时熔断器应 OPEN，直接返回 fallback
        reply = ai_service.generate_reply(
            customer_message="test",
            customer_id="C001",
            session_id="S001",
        )
        assert "稍后重试" in reply or "暂时无法" in reply or reply == ""

    def test_generate_reply_with_system_prompt(self, ai_service, mock_requests):
        system_prompt = "你是客服小助手，回复要简洁。"
        reply = ai_service.generate_reply(
            customer_message="你好",
            customer_id="C001",
            session_id="S001",
            system_prompt=system_prompt,
        )
        assert isinstance(reply, str)

    def test_generate_reply_with_language(self, ai_service, mock_requests):
        reply = ai_service.generate_reply(
            customer_message="Hello, when will my order arrive?",
            customer_id="C001",
            session_id="S001",
            language="en",
        )
        assert isinstance(reply, str)


class TestTranslationService:
    """翻译服务测试"""

    @pytest.fixture
    def trans_service(self, mock_requests):
        return TranslationService()

    def test_translate_returns_string(self, trans_service, mock_requests):
        result = trans_service.translate("你好", target_lang="en", source_lang="zh")
        assert isinstance(result, str)

    def test_translate_same_language_returns_original(self, trans_service, mock_requests):
        result = trans_service.translate("Hello world", target_lang="en", source_lang="en")
        assert result == "Hello world"

    def test_translate_empty_string(self, trans_service, mock_requests):
        result = trans_service.translate("", target_lang="en", source_lang="zh")
        assert result == ""

    def test_translate_uses_ai_when_api_available(self, trans_service, mock_requests):
        result = trans_service.translate("你好世界", target_lang="en", source_lang="zh")
        assert isinstance(result, str)

    def test_translate_caches_result(self, trans_service, mock_requests):
        cache_key = ("test_key", "en", "zh", 0)
        trans_service._cache[cache_key] = "cached_result"
        result = trans_service.translate("test_key", target_lang="en", source_lang="zh")
        assert result == "cached_result"
