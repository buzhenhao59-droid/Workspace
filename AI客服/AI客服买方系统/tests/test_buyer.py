# -*- coding: utf-8 -*-
"""
买方系统测试套件（单元测试）
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

os.environ["NEO4J_URI"] = "bolt://localhost:7687"
os.environ["NEO4J_PASSWORD"] = "test"
os.environ["DEEPSEEK_API_KEY"] = "test-key"
os.environ["SELLER_API_HOST"] = "http://localhost:8000"
os.environ["BUYER_PORT"] = "8001"
os.environ["REDIS_USE_FAKE"] = "1"

import types
_mock_cfg = types.ModuleType("config")
for k, v in {
    "NEO4J_URI": "bolt://localhost:7687",
    "NEO4J_USER": "neo4j",
    "NEO4J_PASSWORD": "test",
    "DEEPSEEK_API_KEY": "test",
    "DEEPSEEK_API_URL": "https://api.deepseek.com/v1/chat/completions",
    "GRAPHRAG_API_URL": "",
    "SELLER_API_HOST": "http://localhost:8000",
    "SELLER_INTERNAL_TOKEN": "test-token",
    "BUYER_PORT": 8001,
    "SHARED_DB_PATH": "",
    "SECRET_KEY": "test",
    "ALLOWED_ORIGINS": "http://localhost:3000",
}.items():
    setattr(_mock_cfg, k, v)
sys.modules.setdefault("dotenv", types.ModuleType("dotenv"))
sys.modules["config"] = _mock_cfg

import unittest.mock as mock

with mock.patch("neo4j.GraphDatabase", mock.MagicMock()):
    from main_buyer import BuyerSessionManager, BuyerNeo4jConnection


class TestBuyerSessionManager:
    """买方会话管理器单元测试"""

    def setup_method(self):
        self.mgr = BuyerSessionManager()

    def test_create_session_returns_session_id(self):
        sid = self.mgr.create_session({"customer": {"id": "c1"}}, "zh")
        assert isinstance(sid, str)
        assert len(sid) > 0

    def test_get_existing_session(self):
        sid = self.mgr.create_session({"customer": {"id": "c2"}}, "en")
        session = self.mgr.get_session(sid)
        assert session is not None
        assert session["language"] == "en"

    def test_get_nonexistent_session_returns_none(self):
        assert self.mgr.get_session("does_not_exist") is None

    def test_update_session_language(self):
        sid = self.mgr.create_session({}, "zh")
        self.mgr.update_session_language(sid, "en")
        session = self.mgr.get_session(sid)
        assert session["language"] == "en"

    def test_add_message_to_session(self):
        sid = self.mgr.create_session({"customer": {"id": "c3"}}, "zh")
        self.mgr.add_message(sid, "user", "你好")
        self.mgr.add_message(sid, "assistant", "您好")
        messages = self.mgr.get_messages(sid)
        assert len(messages) >= 2
        assert messages[0]["role"] == "user"
        assert messages[1]["role"] == "assistant"

    def test_duplicate_session_detection(self):
        sid = self.mgr.create_session({"customer": {"id": "c_dup"}}, "zh")
        assert self.mgr.has_active_session({"customer": {"id": "c_dup"}}) is True
        assert self.mgr.has_active_session({"customer": {"id": "c_new"}}) is False

    def test_close_session(self):
        sid = self.mgr.create_session({"customer": {"id": "c_close"}}, "zh")
        self.mgr.close_session(sid)
        assert self.mgr.get_session(sid) is None


class TestBuyerNeo4jConnection:
    """买方 Neo4j 连接测试（Mock）"""

    def setup_method(self):
        self.neo4j_conn = BuyerNeo4jConnection()

    def test_query_returns_empty_when_no_connection(self):
        results = self.neo4j_conn.query("MATCH (n) RETURN n LIMIT 1")
        assert isinstance(results, list)

    def test_get_customer_returns_none_when_not_found(self):
        result = self.neo4j_conn.get_customer_info("cust_123")
        assert result is None

    def test_get_customer_returns_data_when_mocked(self):
        with mock.patch.object(self.neo4j_conn, "query",
                               return_value=[{"name": "测试客户", "level": "VIP"}]):
            result = self.neo4j_conn.get_customer_info("cust_abc")
            assert result is not None
            assert result["name"] == "测试客户"
