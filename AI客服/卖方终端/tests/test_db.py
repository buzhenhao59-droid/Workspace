# -*- coding: utf-8 -*-
"""
卖方 db.py SQLite 数据访问层单元测试
"""
import sys, os, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

os.environ["SHARED_DB_PATH"] = ""
os.chdir(os.path.join(os.path.dirname(__file__), "..", "backend"))

import types
_mock_cfg = types.ModuleType("config")
for k, v in {
    "SECRET_KEY": "test", "ADMIN_PASSWORD": "test",
    "JWT_SECRET_KEY": "test", "JWT_ALGORITHM": "HS256",
    "JWT_ACCESS_TOKEN_EXPIRE_MINUTES": 30,
    "JWT_REFRESH_TOKEN_EXPIRE_DAYS": 7,
    "ALLOWED_ORIGINS": ["*"],
    "FASTAPI_PORT": 8000,
}.items():
    setattr(_mock_cfg, k, v)
sys.modules["config"] = _mock_cfg

import db


class TestDBInit:
    def setup_method(self):
        self._orig_db = db.DB_PATH
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        db.DB_PATH = db.Path(self._tmp.name)
        db.init_db()

    def teardown_method(self):
        db.DB_PATH = self._orig_db
        try:
            os.unlink(self._tmp.name)
        except Exception:
            pass

    def test_init_db_creates_customers_table(self):
        conn = db.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        names = [row[0] for row in cursor.fetchall()]
        conn.close()
        assert "customers" in names

    def test_init_db_creates_sessions_table(self):
        conn = db.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        names = [row[0] for row in cursor.fetchall()]
        conn.close()
        assert "sessions" in names


class TestCustomerCRUD:
    def setup_method(self):
        self._orig_db = db.DB_PATH
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        db.DB_PATH = db.Path(self._tmp.name)
        db.init_db()

    def teardown_method(self):
        db.DB_PATH = self._orig_db
        try:
            os.unlink(self._tmp.name)
        except Exception:
            pass

    def test_create_customer_returns_int(self):
        cid = db.create_customer("cust_001", "13800138000", "张三", "中国", "VIP")
        assert isinstance(cid, int)
        assert cid > 0

    def test_get_customer_returns_dict(self):
        cid = db.create_customer("cust_get", "13800138001", "李四", "中国", "普通")
        customer = db.get_customer("cust_get")
        assert customer is not None
        assert customer["customer_id"] == "cust_get"
        assert customer["name"] == "李四"

    def test_get_nonexistent_returns_none(self):
        assert db.get_customer("definitely_not_there") is None

    def test_find_customer_by_phone(self):
        db.create_customer("cust_ph", "13812345678", "孙七", "中国", "VIP")
        result = db.find_customer_by_phone("13812345678")
        assert result is not None
        assert result["customer_id"] == "cust_ph"

    def test_update_customer_changes_values(self):
        db.create_customer("cust_upd", "13800138005", "原名", "中国", "普通")
        db.update_customer("cust_upd", name="新名", level="VIP")
        customer = db.get_customer("cust_upd")
        assert customer["name"] == "新名"
        assert customer["level"] == "VIP"


class TestSessionCRUD:
    def setup_method(self):
        self._orig_db = db.DB_PATH
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        db.DB_PATH = db.Path(self._tmp.name)
        db.init_db()
        db.create_customer("stc", "13900139000", "测试用户", "中国", "普通")

    def teardown_method(self):
        db.DB_PATH = self._orig_db
        try:
            os.unlink(self._tmp.name)
        except Exception:
            pass

    def test_create_session_returns_int(self):
        sid = db.create_session("sess_001", "stc", is_ai=True)
        assert isinstance(sid, int)

    def test_get_session(self):
        db.create_session("sess_get", "stc", is_ai=True)
        s = db.get_session("sess_get")
        assert s is not None
        assert s["session_id"] == "sess_get"

    def test_add_and_get_messages(self):
        db.create_session("sess_msg", "stc", is_ai=True)
        db.add_message("sess_msg", "user", "你好")
        db.add_message("sess_msg", "assistant", "您好")
        msgs = db.get_messages("sess_msg")
        assert len(msgs) >= 2


class TestSellerCRUD:
    def setup_method(self):
        self._orig_db = db.DB_PATH
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        db.DB_PATH = db.Path(self._tmp.name)
        db.init_db()

    def teardown_method(self):
        db.DB_PATH = self._orig_db
        try:
            os.unlink(self._tmp.name)
        except Exception:
            pass

    def test_create_and_get_seller(self):
        import hashlib
        pw_hash = hashlib.sha256(("gold_customer_salt_testpass123").encode()).hexdigest()
        db.create_seller("agent_test", pw_hash, "测试坐席", "agent")
        seller = db.get_seller("agent_test")
        assert seller is not None
        assert seller["username"] == "agent_test"

    def test_verify_password_correct_and_wrong(self):
        import hashlib
        pw = "my_secure_password"
        pw_hash = hashlib.sha256(("gold_customer_salt_" + pw).encode()).hexdigest()
        db.create_seller("agent_v", pw_hash, "验证坐席", "agent")
        assert db.verify_seller_password(pw, pw_hash) is True
        assert db.verify_seller_password("wrong_password", pw_hash) is False
