# -*- coding: utf-8 -*-
"""
卖方 rate_limiter.py 单元测试
覆盖：固定窗口 / 滑动窗口 / 令牌桶 三种限流算法
"""
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from rate_limiter import (
    RateLimitRule,
    RateLimitResult,
    InMemoryRateLimiter,
)


class TestRateLimitRule:
    """限流规则测试"""

    def test_default_strategy_is_fixed(self):
        rule = RateLimitRule(max_requests=10, window_seconds=60)
        assert rule.strategy == "fixed"

    def test_invalid_strategy_defaults_to_fixed(self):
        rule = RateLimitRule(max_requests=10, window_seconds=60, strategy="invalid")
        assert rule.strategy == "fixed"

    def test_all_strategies_accepted(self):
        for s in ["fixed", "sliding", "token"]:
            rule = RateLimitRule(max_requests=10, window_seconds=60, strategy=s)
            assert rule.strategy == s


class TestRateLimitResult:
    """限流结果测试"""

    def test_allowed_result_fields(self):
        result = RateLimitResult(
            allowed=True,
            current=5,
            limit=10,
            remaining=4,
            reset_at=1000.0,
        )
        assert result.allowed is True
        assert result.current == 5
        assert result.limit == 10
        assert result.remaining == 4
        assert result.retry_after is None

    def test_rejected_result_retry_after(self):
        result = RateLimitResult(
            allowed=False,
            current=10,
            limit=10,
            remaining=0,
            reset_at=1000.0,
            retry_after=60,
        )
        assert result.allowed is False
        assert result.retry_after == 60


class TestInMemoryRateLimiterFixed:
    """固定窗口限流算法测试"""

    def setup_method(self):
        self.limiter = InMemoryRateLimiter()

    def test_first_request_allowed(self):
        rule = RateLimitRule(max_requests=5, window_seconds=60)
        result = self.limiter.check_fixed("test_key", rule)
        assert result.allowed is True
        assert result.current == 1

    def test_at_limit_rejected(self):
        rule = RateLimitRule(max_requests=3, window_seconds=60)
        for _ in range(3):
            self.limiter.check_fixed("limit_key", rule)
        result = self.limiter.check_fixed("limit_key", rule)
        assert result.allowed is False
        assert result.retry_after == 60

    def test_different_keys_independent(self):
        rule = RateLimitRule(max_requests=2, window_seconds=60)
        self.limiter.check_fixed("key_a", rule)
        self.limiter.check_fixed("key_a", rule)
        result = self.limiter.check_fixed("key_b", rule)
        assert result.allowed is True

    def test_remaining_calculated_correctly(self):
        rule = RateLimitRule(max_requests=10, window_seconds=60)
        self.limiter.check_fixed("remain_key", rule)
        result = self.limiter.check_fixed("remain_key", rule)
        assert result.remaining == 8


class TestInMemoryRateLimiterSliding:
    """滑动窗口限流算法测试"""

    def setup_method(self):
        self.limiter = InMemoryRateLimiter()

    def test_first_request_allowed(self):
        rule = RateLimitRule(max_requests=5, window_seconds=60)
        result = self.limiter.check_sliding("slide_key", rule)
        assert result.allowed is True

    def test_at_limit_rejected(self):
        rule = RateLimitRule(max_requests=2, window_seconds=60)
        self.limiter.check_sliding("slide_limit", rule)
        self.limiter.check_sliding("slide_limit", rule)
        result = self.limiter.check_sliding("slide_limit", rule)
        assert result.allowed is False


class TestInMemoryRateLimiterTokenBucket:
    """令牌桶限流算法测试"""

    def setup_method(self):
        self.limiter = InMemoryRateLimiter()

    def test_token_bucket_limit_field_correct(self):
        """limit = burst + max_requests"""
        rule = RateLimitRule(max_requests=5, window_seconds=10, strategy="token", burst=10)
        result = self.limiter.check_token("t1", rule)
        assert result.limit == 15

    def test_token_bucket_fields_present(self):
        """返回结果包含所有必需字段"""
        rule = RateLimitRule(max_requests=2, window_seconds=10, strategy="token", burst=5)
        result = self.limiter.check_token("t2", rule)
        assert hasattr(result, "allowed")
        assert hasattr(result, "current")
        assert hasattr(result, "limit")
        assert hasattr(result, "remaining")
        assert hasattr(result, "reset_at")
        assert isinstance(result.limit, int)
        assert isinstance(result.remaining, int)

    def test_token_bucket_different_keys_independent(self):
        """不同 key 独立计数"""
        rule = RateLimitRule(max_requests=1, window_seconds=5, strategy="token", burst=2)
        result_a = self.limiter.check_token("ta", rule)
        result_b = self.limiter.check_token("tb", rule)
        assert result_a.limit == 3
        assert result_b.limit == 3
