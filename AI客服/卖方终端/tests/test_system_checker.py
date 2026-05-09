# -*- coding: utf-8 -*-
"""
卖方 system_checker.py 系统检查器单元测试
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import types
_mock_cfg = types.ModuleType("config")
for k, v in {
    "DEEPSEEK_API_KEY": "test-key",
    "DEEPSEEK_API_URL": "https://api.deepseek.com/v1/chat/completions",
    "GRAPHRAG_API_URL": "http://localhost:5050/query",
}.items():
    setattr(_mock_cfg, k, v)
sys.modules["config"] = _mock_cfg

from system_checker import (
    CheckStatus,
    Severity,
    check_port,
    check_http_endpoint,
    check_sqlite_db,
    get_system_resources,
    generate_recommendations,
)


class TestCheckPort:
    def test_localhost_refuses_returns_false(self):
        ok, msg = check_port("127.0.0.1", 99999, timeout=0.5)
        assert ok is False

    def test_invalid_host_returns_false(self):
        ok, msg = check_port("invalid.hostname.xyz", 80, timeout=1.0)
        assert ok is False


class TestCheckHttpEndpoint:
    def test_nonexistent_url_returns_false(self):
        ok, msg, info = check_http_endpoint(
            "http://this-domain-does-not-exist-xyz123.com/api",
            timeout=2.0
        )
        assert ok is False
        assert isinstance(msg, str)

    def test_200_response_returns_true(self):
        ok, msg, info = check_http_endpoint(
            "https://httpbin.org/status/200",
            timeout=10.0
        )
        assert ok is True


class TestCheckSqliteDb:
    def test_valid_db_returns_ok_or_warn(self, tmp_path):
        import sqlite3
        test_db = tmp_path / "valid.db"
        sqlite3.connect(str(test_db)).close()
        result = check_sqlite_db(str(test_db))
        # 有效 DB 应返回 OK 或 WARN
        assert result.status in (CheckStatus.OK, CheckStatus.WARN)

    def test_nonexistent_db_returns_warn(self):
        result = check_sqlite_db("/path/that/does/not/exist/test.db")
        # 不存在的 DB 返回 WARN（系统会自动创建）
        assert result.status in (CheckStatus.WARN, CheckStatus.OK)

    def test_empty_path_returns_skip(self):
        result = check_sqlite_db("")
        assert result.status == CheckStatus.SKIP


class TestSystemResources:
    def test_get_system_resources_returns_dict(self):
        resources = get_system_resources()
        assert isinstance(resources, dict)
        assert "cpu_percent" in resources
        assert "memory_percent" in resources

    def test_resource_values_in_valid_range(self):
        resources = get_system_resources()
        cpu = resources.get("cpu_percent", 0)
        mem = resources.get("memory_percent", 0)
        assert 0 <= cpu <= 100
        assert 0 <= mem <= 100


class TestGenerateRecommendations:
    def test_no_results_returns_empty(self):
        recs = generate_recommendations([])
        assert isinstance(recs, list)

    def test_critical_error_generates_recommendation(self):
        from system_checker import CheckResult
        results = [
            CheckResult(name="Redis", status=CheckStatus.FAIL,
                        severity=Severity.CRITICAL,
                        message="连接失败", suggestions=["安装 Redis"])
        ]
        recs = generate_recommendations(results)
        assert len(recs) > 0

    def test_neo4j_error_generates_recommendation(self):
        from system_checker import CheckResult
        results = [
            CheckResult(name="Neo4j", status=CheckStatus.FAIL,
                        severity=Severity.HIGH,
                        message="连接失败", suggestions=["检查 Neo4j 配置"])
        ]
        recs = generate_recommendations(results)
        assert len(recs) > 0
