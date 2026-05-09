# -*- coding: utf-8 -*-
"""
JWT 认证模块单元测试
"""
import pytest
import time
from datetime import datetime, timezone

# 延迟导入以应用 conftest 中的环境变量
import importlib
import sys

# 确保 config 模块使用测试环境变量
if "config" in sys.modules:
    del sys.modules["config"]
if "jwt_auth" in sys.modules:
    del sys.modules["jwt_auth"]

from jwt_auth import (
    create_access_token,
    create_refresh_token,
    verify_token,
    decode_token_without_verification,
    TokenType,
)


class TestJWTTokens:
    """Token 生成测试"""

    def test_create_access_token_returns_string(self):
        token = create_access_token(subject="test_user", role="admin")
        assert isinstance(token, str)
        assert len(token) > 20
        assert token.count(".") == 2  # JWT 格式: header.payload.signature

    def test_create_access_token_with_extra_claims(self):
        token = create_access_token(
            subject="test_user",
            role="seller",
            extra_claims={"tenant_id": "tenant_001", "permissions": ["read", "write"]},
        )
        payload = decode_token_without_verification(token)
        assert payload["sub"] == "test_user"
        assert payload["role"] == "seller"
        assert payload["tenant_id"] == "tenant_001"
        assert payload["permissions"] == ["read", "write"]

    def test_create_refresh_token_type_is_refresh(self):
        token = create_refresh_token(subject="test_user", role="admin")
        payload = decode_token_without_verification(token)
        assert payload["type"] == "refresh"
        assert payload["sub"] == "test_user"

    def test_access_token_does_not_have_refresh_type(self):
        token = create_access_token(subject="test_user", role="admin")
        payload = decode_token_without_verification(token)
        assert payload["type"] == "access"

    def test_token_contains_required_claims(self):
        token = create_access_token(subject="admin01", role="admin")
        payload = decode_token_without_verification(token)
        assert "sub" in payload
        assert "role" in payload
        assert "type" in payload
        assert "iat" in payload
        assert "exp" in payload

    def test_different_users_get_different_tokens(self):
        token1 = create_access_token(subject="user_a", role="admin")
        token2 = create_access_token(subject="user_b", role="admin")
        assert token1 != token2


class TestVerifyToken:
    """Token 验证测试"""

    def test_verify_valid_access_token(self):
        token = create_access_token(subject="test_user", role="admin")
        payload = verify_token(token, TokenType.ACCESS)
        assert payload["sub"] == "test_user"
        assert payload["role"] == "admin"

    def test_verify_valid_refresh_token(self):
        token = create_refresh_token(subject="test_user", role="admin")
        payload = verify_token(token, TokenType.REFRESH)
        assert payload["sub"] == "test_user"

    def test_verify_expired_token_raises(self):
        import jwt_auth as _ja
        importlib.reload(_ja)
        from datetime import timedelta
        import jwt

        # 创建一个已过期的 token
        expired_payload = {
            "sub": "test_user",
            "role": "admin",
            "type": "access",
            "iat": datetime.now(timezone.utc),
            "exp": datetime.now(timezone.utc) - timedelta(minutes=1),
        }
        expired_token = jwt.encode(
            expired_payload, "test-jwt-secret-key-for-unit-tests-only", algorithm="HS256"
        )
        with pytest.raises(Exception) as exc_info:
            _ja.verify_token(expired_token, TokenType.ACCESS)
        assert "expired" in str(exc_info.value).lower() or "exp" in str(exc_info.value).lower()

    def test_verify_wrong_type_token_raises(self):
        # 用 access token 去验证 refresh token
        access_token = create_access_token(subject="test_user", role="admin")
        with pytest.raises(Exception) as exc_info:
            verify_token(access_token, TokenType.REFRESH)
        assert "type" in str(exc_info.value).lower()

    def test_verify_tampered_token_raises(self):
        token = create_access_token(subject="test_user", role="admin")
        # 篡改 payload（翻转第一个字符）
        parts = token.rsplit(".", 1)
        tampered = parts[0][:-1] + ("A" if parts[0][-1] != "A" else "B") + "." + parts[1]
        with pytest.raises(Exception):
            verify_token(tampered, TokenType.ACCESS)
