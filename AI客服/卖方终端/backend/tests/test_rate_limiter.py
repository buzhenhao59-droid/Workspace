# -*- coding: utf-8 -*-
"""
API 限流模块单元测试
"""
import pytest
import time
from unittest.mock import MagicMock


class TestRateLimitRule:
    """限流规则测试"""

    def test_rule_has_correct_attributes(self):
        from rate_limiter import RateLimitRule

        rule = RateLimitRule(max_requests=100, window_seconds=60, strategy="sliding")
        assert rule.max_requests == 100
        assert rule.window_seconds == 60
        assert rule.strategy == "sliding"

    def test_rule_default_strategy_is_sliding(self):
        from rate_limiter import RateLimitRule

        rule = RateLimitRule(max_requests=50, window_seconds=120)
        assert rule.strategy == "sliding"

    def test_rule_with_token_bucket_strategy(self):
        from rate_limiter import RateLimitRule

        rule = RateLimitRule(
            max_requests=10, window_seconds=60, strategy="token_bucket", burst=20
        )
        assert rule.strategy == "token_bucket"
        assert rule.burst == 20


class TestRateLimitResponse:
    """限流响应模型测试"""

    def test_response_model_fields(self):
        from rate_limiter import RateLimitResponse

        resp = RateLimitResponse(
            limited=False,
            limit=100,
            remaining=95,
            reset=int(time.time()) + 60,
            retry_after=None,
        )
        assert resp.limited is False
        assert resp.limit == 100
        assert resp.remaining == 95

    def test_response_model_retry_after(self):
        from rate_limiter import RateLimitResponse

        resp = RateLimitResponse(
            limited=True,
            limit=100,
            remaining=0,
            reset=int(time.time()) + 60,
            retry_after=30,
        )
        assert resp.limited is True
        assert resp.retry_after == 30

    def test_response_model_serialization(self):
        from rate_limiter import RateLimitResponse

        reset_ts = int(time.time()) + 60
        resp = RateLimitResponse(
            limited=False, limit=100, remaining=50, reset=reset_ts, retry_after=None
        )
        d = resp.model_dump()
        assert d["limited"] is False
        assert d["limit"] == 100
        assert d["remaining"] == 50
        assert d["reset"] == reset_ts


class TestRateLimiterHelpers:
    """限流辅助函数测试"""

    def test_get_client_ip_ipv4(self):
        from rate_limiter import get_client_ip

        request = MagicMock()
        request.client.host = "192.168.1.100"
        request.headers.get = lambda k, d=None: {
            "X-Forwarded-For": None,
            "X-Real-IP": None,
        }.get(k, d)
        assert get_client_ip(request) == "192.168.1.100"

    def test_get_client_ip_from_x_forwarded_for(self):
        from rate_limiter import get_client_ip

        request = MagicMock()
        request.headers.get = lambda k, d=None: {
            "X-Forwarded-For": "10.0.0.1, 192.168.1.1",
            "X-Real-IP": None,
        }.get(k, d)
        assert get_client_ip(request) == "10.0.0.1"

    def test_get_client_ip_from_x_real_ip(self):
        from rate_limiter import get_client_ip

        request = MagicMock()
        request.headers.get = lambda k, d=None: {
            "X-Forwarded-For": None,
            "X-Real-IP": "172.16.0.5",
        }.get(k, d)
        assert get_client_ip(request) == "172.16.0.5"

    def test_is_skip_path(self):
        from rate_limiter import is_skip_path

        assert is_skip_path("/api/v1/docs") is True
        assert is_skip_path("/api/v1/redoc") is True
        assert is_skip_path("/api/v1/openapi.json") is True
        assert is_skip_path("/health") is True
        assert is_skip_path("/metrics") is True
        assert is_skip_path("/api/v1/customer/chat") is False
        assert is_skip_path("/api/v1/admin/login") is False

    def test_match_limit_by_path(self):
        from rate_limiter import match_limit_by_path, DEFAULT_LIMITS, STRICT_LIMITS

        rule = match_limit_by_path("/api/v1/customer/chat")
        assert rule is not None
        assert rule.max_requests == DEFAULT_LIMITS["chat"].max_requests

        rule = match_limit_by_path("/api/v1/admin/login")
        assert rule.max_requests == STRICT_LIMITS["login"].max_requests

        rule = match_limit_by_path("/api/v1/internal/buyer-transfer")
        assert rule.max_requests == 20  # 内部回调限流规则

    def test_match_limit_defaults(self):
        from rate_limiter import match_limit_by_path

        rule = match_limit_by_path("/api/v1/unknown/path")
        assert rule is not None


class TestRedisRateLimiter:
    """Redis 限流器测试（使用 mock）"""

    def test_sliding_window_check(self, mock_redis):
        from rate_limiter import RedisRateLimiter, RateLimitRule

        limiter = RedisRateLimiter(redis_client=mock_redis)
        rule = RateLimitRule(max_requests=100, window_seconds=60)

        result = limiter.check("test_user_1", rule)
        assert result.limited is False
        assert result.limit == 100
        mock_redis.eval.assert_called()

    def test_rate_limited_response(self, mock_redis):
        from rate_limiter import RedisRateLimiter, RateLimitRule

        mock_redis.eval.return_value = [False, 0, 15, 101]  # limited, remaining, retry, current

        limiter = RedisRateLimiter(redis_client=mock_redis)
        rule = RateLimitRule(max_requests=100, window_seconds=60)

        result = limiter.check("rate_limited_user", rule)
        assert result.limited is True
        assert result.remaining == 0
        assert result.retry_after == 15
