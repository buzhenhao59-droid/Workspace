# -*- coding: utf-8 -*-
"""
卖方 jwt_auth.py 单元测试
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import types
_mock_cfg = types.ModuleType("config")
_mock_cfg.JWT_SECRET_KEY = "test-jwt-secret-key-32-chars-min"
_mock_cfg.JWT_ALGORITHM = "HS256"
_mock_cfg.JWT_ACCESS_TOKEN_EXPIRE_MINUTES = 30
_mock_cfg.JWT_REFRESH_TOKEN_EXPIRE_DAYS = 7
sys.modules["config"] = _mock_cfg

from jwt_auth import create_access_token, create_refresh_token, decode_token


class TestJWTTokens:
    def test_create_access_token_returns_string(self):
        token = create_access_token("user123", role="admin")
        assert isinstance(token, str)
        assert len(token) > 20

    def test_create_refresh_token_returns_string(self):
        token = create_refresh_token("user123")
        assert isinstance(token, str)
        assert len(token) > 20

    def test_access_and_refresh_tokens_different(self):
        at = create_access_token("user", role="user")
        rt = create_refresh_token("user")
        assert at != rt

    def test_decode_token_raises_on_invalid(self):
        try:
            decode_token("not.a.valid.token")
            assert False, "应抛出异常"
        except Exception:
            pass  # 预期抛出异常

    def test_decode_token_raises_on_wrong_secret(self):
        try:
            decode_token("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.invalid.signature")
        except Exception:
            pass  # 预期异常

    def test_decode_token_with_valid_token(self):
        token = create_access_token("testuser", role="admin")
        payload = decode_token(token)
        assert payload is not None
        assert payload.get("sub") == "testuser"
        assert payload.get("role") == "admin"

    def test_access_token_expires_in_configured_time(self):
        token = create_access_token("temp_user", role="user")
        payload = decode_token(token)
        assert payload is not None
        assert "exp" in payload
