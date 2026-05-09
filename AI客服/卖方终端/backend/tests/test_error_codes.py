# -*- coding: utf-8 -*-
"""
API 错误码单元测试
"""
import pytest
from error_codes import (
    ErrorCode,
    make_error,
    make_success,
    RuitalkHTTPException,
    ErrorCategory,
)


class TestErrorCodeEnum:
    """错误码枚举测试"""

    def test_all_error_codes_have_code_string(self):
        for item in ErrorCode:
            assert isinstance(item.value, tuple)
            assert len(item.value) == 3
            code, message, http_status = item.value
            assert code.startswith("RTK_")
            assert len(code) == 13  # RTK + Category(4) + 5 digits
            assert isinstance(message, str)
            assert isinstance(http_status, int)
            assert 100 <= http_status < 600

    def test_error_codes_are_unique(self):
        codes = [item.value[0] for item in ErrorCode]
        assert len(codes) == len(set(codes))

    def test_error_codes_sorted_by_category(self):
        prev_cat = None
        for item in ErrorCode:
            cat = item.name.split("_")[0]
            # Categories should be in order
            if prev_cat:
                assert cat >= prev_cat
            prev_cat = cat

    def test_known_error_codes_exist(self):
        assert ErrorCode.INTERNAL_ERROR is not None
        assert ErrorCode.AUTH_TOKEN_INVALID is not None
        assert ErrorCode.RATE_LIMIT_EXCEEDED is not None
        assert ErrorCode.DB_CONNECTION_FAILED is not None
        assert ErrorCode.SESSION_NOT_FOUND is not None
        assert ErrorCode.AI_SERVICE_UNAVAILABLE is not None


class TestErrorCategory:
    """错误分类测试"""

    def test_all_categories_defined(self):
        expected = {
            "GEN", "AUTH", "RATE", "PARAM", "DB",
            "SESSION", "AI", "KG", "XFER", "BIZ",
            "FILE", "EC",
        }
        assert set(ErrorCategory.__members__.keys()) == expected

    def test_category_http_ranges(self):
        # 各分类的 HTTP 状态码范围
        assert ErrorCategory.GEN.http_min <= ErrorCategory.GEN.http_max
        assert ErrorCategory.AUTH.http_min <= ErrorCategory.AUTH.http_max
        assert ErrorCategory.RATE.http_min == 429  # 限流专用 429


class TestMakeError:
    """make_error 辅助函数测试"""

    def test_make_error_returns_dict(self):
        result = make_error(ErrorCode.INTERNAL_ERROR)
        assert isinstance(result, dict)
        assert result["success"] is False

    def test_make_error_includes_code_and_message(self):
        result = make_error(ErrorCode.AUTH_TOKEN_INVALID)
        assert "error" in result
        assert result["error"]["code"] == "RTK_AUTH00102"
        assert result["error"]["message"] == "认证令牌无效或已过期"

    def test_make_error_with_custom_detail(self):
        result = make_error(ErrorCode.DB_CONNECTION_FAILED, detail="MySQL server went away")
        assert result["error"]["detail"] == "MySQL server went away"

    def test_make_error_with_request_id(self):
        result = make_error(ErrorCode.INTERNAL_ERROR, request_id="req-12345")
        assert result["error"]["request_id"] == "req-12345"

    def test_make_error_http_status_matches(self):
        result = make_error(ErrorCode.RATE_LIMIT_EXCEEDED)
        assert result["error"]["http_status"] == 429


class TestMakeSuccess:
    """make_success 辅助函数测试"""

    def test_make_success_returns_dict(self):
        result = make_success(data={"key": "value"})
        assert result["success"] is True

    def test_make_success_with_data(self):
        result = make_success(data={"token": "abc123"})
        assert result["data"]["token"] == "abc123"

    def test_make_success_with_message(self):
        result = make_success(message="操作成功")
        assert result["message"] == "操作成功"

    def test_make_success_without_data(self):
        result = make_success()
        assert "data" not in result or result.get("data") is None

    def test_make_success_with_request_id(self):
        result = make_success(request_id="req-xyz")
        assert result["request_id"] == "req-xyz"


class TestRuitalkHTTPException:
    """自定义 HTTP 异常测试"""

    def test_exception_has_error_code(self):
        exc = RuitalkHTTPException(ErrorCode.AUTH_TOKEN_INVALID)
        assert exc.error_code == ErrorCode.AUTH_TOKEN_INVALID
        assert exc.code == "RTK_AUTH00102"

    def test_exception_http_status(self):
        exc = RuitalkHTTPException(ErrorCode.AUTH_TOKEN_INVALID)
        assert exc.status_code == 401

    def test_exception_detail_overrides_message(self):
        exc = RuitalkHTTPException(
            ErrorCode.DB_CONNECTION_FAILED,
            detail="Neo4j connection timeout after 30s",
        )
        assert exc.detail == "Neo4j connection timeout after 30s"

    def test_exception_request_id(self):
        exc = RuitalkHTTPException(ErrorCode.INTERNAL_ERROR, request_id="req-test")
        assert exc.request_id == "req-test"

    def test_exception_to_dict(self):
        exc = RuitalkHTTPException(ErrorCode.INTERNAL_ERROR, request_id="req-abc")
        d = exc.to_dict()
        assert d["success"] is False
        assert d["error"]["code"] == "RTK_GEN00001"
        assert d["error"]["request_id"] == "req-abc"

    def test_exception_from_code_string(self):
        exc = RuitalkHTTPException.from_code("RTK_RATE00201")
        assert exc.code == "RTK_RATE00201"
        assert exc.status_code == 429

    def test_exception_from_unknown_code_uses_internal_error(self):
        exc = RuitalkHTTPException.from_code("RTK_UNKNOWN99999")
        assert exc.code == "RTK_GEN00001"  # Fallback to INTERNAL_ERROR

    def test_exception_compares_equal_by_code(self):
        exc1 = RuitalkHTTPException(ErrorCode.AUTH_TOKEN_INVALID)
        exc2 = RuitalkHTTPException(ErrorCode.AUTH_TOKEN_INVALID)
        assert exc1 == exc2
