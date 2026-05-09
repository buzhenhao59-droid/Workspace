# -*- coding: utf-8 -*-
"""
Webhook 客户端单元测试
"""
import pytest
import time
import hmac
import hashlib


class TestHMACSignature:
    """HMAC 签名测试"""

    def test_generate_signature(self):
        from webhook_client import generate_signature

        sig = generate_signature(
            secret="test-secret",
            timestamp="1743168000",
            method="POST",
            path="/api/v1/internal/buyer-transfer",
            body='{"session_id":"S001"}',
        )
        assert isinstance(sig, str)
        assert len(sig) > 0

    def test_signature_is_deterministic(self):
        from webhook_client import generate_signature

        sig1 = generate_signature("secret", "1234567890", "POST", "/path", "body")
        sig2 = generate_signature("secret", "1234567890", "POST", "/path", "body")
        assert sig1 == sig2

    def test_signature_changes_with_body(self):
        from webhook_client import generate_signature

        sig1 = generate_signature("secret", "1234567890", "POST", "/path", "body1")
        sig2 = generate_signature("secret", "1234567890", "POST", "/path", "body2")
        assert sig1 != sig2

    def test_signature_changes_with_timestamp(self):
        from webhook_client import generate_signature

        sig1 = generate_signature("secret", "1234567890", "POST", "/path", "body")
        sig2 = generate_signature("secret", "9999999999", "POST", "/path", "body")
        assert sig1 != sig2

    def test_signature_changes_with_method(self):
        from webhook_client import generate_signature

        sig1 = generate_signature("secret", "1234567890", "POST", "/path", "body")
        sig2 = generate_signature("secret", "1234567890", "GET", "/path", "body")
        assert sig1 != sig2

    def test_verify_signature_valid(self):
        from webhook_client import generate_signature, verify_signature

        secret = "test-secret"
        timestamp = "1743168000"
        method = "POST"
        path = "/api/v1/internal/buyer-transfer"
        body = '{"session_id":"S001"}'

        sig = generate_signature(secret, timestamp, method, path, body)
        assert verify_signature(secret, timestamp, method, path, body, sig) is True

    def test_verify_signature_invalid(self):
        from webhook_client import verify_signature

        assert verify_signature(
            "secret", "1234567890", "POST", "/path", "body", "invalid-sig"
        ) is False

    def test_verify_signature_wrong_secret(self):
        from webhook_client import generate_signature, verify_signature

        sig = generate_signature("correct-secret", "1234567890", "POST", "/path", "body")
        assert verify_signature("wrong-secret", "1234567890", "POST", "/path", "body", sig) is False


class TestTimestampValidation:
    """时间戳验证测试"""

    def test_timestamp_valid_within_window(self):
        from webhook_client import is_timestamp_valid

        now = str(int(time.time()))
        assert is_timestamp_valid(now, ttl=300) is True

    def test_timestamp_expired(self):
        from webhook_client import is_timestamp_valid

        old = str(int(time.time()) - 400)
        assert is_timestamp_valid(old, ttl=300) is False

    def test_timestamp_future_within_tolerance(self):
        from webhook_client import is_timestamp_valid

        # 允许 30 秒的时钟偏移
        future = str(int(time.time()) + 25)
        assert is_timestamp_valid(future, ttl=300, tolerance=30) is True

    def test_timestamp_future_outside_tolerance(self):
        from webhook_client import is_timestamp_valid

        # 未来太远
        future = str(int(time.time()) + 600)
        assert is_timestamp_valid(future, ttl=300, tolerance=30) is False

    def test_timestamp_invalid_format(self):
        from webhook_client import is_timestamp_valid

        assert is_timestamp_valid("not-a-number", ttl=300) is False
        assert is_timestamp_valid("", ttl=300) is False
        assert is_timestamp_valid(None, ttl=300) is False


class TestWebhookClient:
    """Webhook 客户端测试"""

    @pytest.fixture
    def client(self, mock_requests):
        from webhook_client import WebhookClient

        return WebhookClient(base_url="http://buyer:8001", timeout=5)

    def test_client_initialization(self, client):
        assert client.base_url == "http://buyer:8001"
        assert client.timeout == 5
        assert client.max_retries == 3

    def test_post_succeeds(self, client, mock_requests):
        result = client.post("/api/v1/internal/buyer-transfer", json={"session_id": "S001"})
        assert result is True

    def test_post_retries_on_500(self, client, mocker):
        mock_resp = mocker.MagicMock()
        mock_resp.status_code = 503
        mock_resp.text = "Service Unavailable"
        mocker.patch("requests.post", return_value=mock_resp)

        from webhook_client import WebhookClient

        client = WebhookClient(base_url="http://buyer:8001", max_retries=3)
        result = client.post("/api/v1/internal/buyer-transfer", json={"session_id": "S001"})
        assert result is False

    def test_post_no_retry_on_400(self, client, mocker):
        mock_resp = mocker.MagicMock()
        mock_resp.status_code = 400
        mock_resp.text = "Bad Request"
        mocker.patch("requests.post", return_value=mock_resp)

        from webhook_client import WebhookClient

        client = WebhookClient(base_url="http://buyer:8001", max_retries=3)
        result = client.post("/api/v1/internal/buyer-transfer", json={})
        assert result is False
        # 应只调用一次（不重试 4xx）
        import requests as req
        assert req.post.call_count == 1

    def test_generate_headers_includes_signature(self, client):
        headers = client._generate_headers(
            method="POST",
            path="/api/v1/internal/buyer-transfer",
            body='{"session_id":"S001"}',
        )
        assert "X-Internal-Timestamp" in headers
        assert "X-Internal-Signature" in headers
        assert "Content-Type" in headers


class TestCrossSystemNotifier:
    """跨系统通知器测试"""

    @pytest.fixture
    def notifier(self, mock_requests):
        from webhook_client import CrossSystemNotifier

        return CrossSystemNotifier(
            buyer_base_url="http://buyer:8001",
            internal_token="test-internal-secret",
        )

    def test_notify_buyer_back_to_ai(self, notifier, mock_requests):
        ok, data, err = notifier.notify_buyer_back_to_ai(
            session_id="S001", customer_id="C001"
        )
        assert ok is True
        assert data is not None
        assert err is None

    def test_notify_buyer_message(self, notifier, mock_requests):
        ok, data, err = notifier.notify_buyer_message(
            session_id="S001",
            customer_id="C001",
            message="Hello from seller",
        )
        assert ok is True

    def test_notify_buyer_transfer(self, notifier, mock_requests):
        ok, data, err = notifier.notify_buyer_transfer(
            session_id="S001",
            customer_id="C001",
            reason="CUSTOMER_REQUEST",
        )
        assert ok is True
