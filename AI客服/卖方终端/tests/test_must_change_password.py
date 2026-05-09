# -*- coding: utf-8 -*-
"""
卖家强制改密功能测试
"""
import sys, os, tempfile, hashlib, types
from pathlib import Path

# 注入 mock config 避免导入冲突
_mock_cfg = types.ModuleType("config")
for k, v in {
    "SECRET_KEY": "test", "ADMIN_PASSWORD": "test",
    "JWT_SECRET_KEY": "test", "JWT_ALGORITHM": "HS256",
    "JWT_ACCESS_TOKEN_EXPIRE_MINUTES": 30,
    "JWT_REFRESH_TOKEN_EXPIRE_DAYS": 7,
    "ALLOWED_ORIGINS": ["*"],
    "FASTAPI_PORT": 8000,
    "REDIS_USE_FAKE": "1",
    "DEEPSEEK_API_KEY": "test",
    "SENTRY_DSN": "",
}.items():
    setattr(_mock_cfg, k, v)
sys.modules["config"] = _mock_cfg

_backend = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(_backend))
os.chdir(str(_backend))
import db


def _hash_pw(pw: str) -> str:
    return hashlib.sha256(("gold_customer_salt_" + pw).encode()).hexdigest()


class TestMustChangePassword:
    def setup_method(self):
        """创建临时数据库并手动添加新列"""
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._bak_db_path = db.DB_PATH
        db.DB_PATH = db.Path(self._tmp.name)
        db.init_db()
        # 手动添加新列（init_db 用 CREATE TABLE IF NOT EXISTS，不会覆盖已存在的列）
        conn = db.get_connection()
        for col_sql in [
            "ALTER TABLE sellers ADD COLUMN password_changed INTEGER DEFAULT 0",
            "ALTER TABLE sellers ADD COLUMN must_change_password INTEGER DEFAULT 0",
        ]:
            try:
                conn.execute(col_sql)
            except Exception:
                pass  # 列已存在
        conn.commit()
        conn.close()

    def teardown_method(self):
        db.DB_PATH = self._bak_db_path
        try:
            os.unlink(self._tmp.name)
        except Exception:
            pass

    def test_sellers_table_has_must_change_password_column(self):
        """sellers 表应有 must_change_password 和 password_changed 列"""
        conn = db.get_connection()
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(sellers)")
        cols = {row[1] for row in cur.fetchall()}
        conn.close()
        assert "must_change_password" in cols
        assert "password_changed" in cols

    def test_default_seller_has_must_change_flag(self):
        """init_default_seller 创建的账号 must_change_password=1"""
        db.init_default_seller()
        seller = db.get_seller("admin")
        assert seller is not None
        assert seller["must_change_password"] == 1

    def test_set_password_changed_clears_flag(self):
        """改密后 must_change_password 应被清除"""
        db.init_default_seller()
        seller = db.get_seller("admin")
        assert seller["must_change_password"] == 1
        db.set_password_changed("admin")
        seller2 = db.get_seller("admin")
        assert seller2["must_change_password"] == 0
        assert seller2["password_changed"] == 1

    def test_verify_password_with_sha256(self):
        """密码验证应使用 SHA256(gold_customer_salt_+password)"""
        pw = "mysecret123"
        h = _hash_pw(pw)
        assert db.verify_seller_password(pw, h) == True
        assert db.verify_seller_password("wrong", h) == False
        h2 = _hash_pw("admin123")
        assert db.verify_seller_password("admin123", h2) == True
        assert db.verify_seller_password("admin", h2) == False

    def test_new_seller_not_forced_change(self):
        """新建卖家账号不强制改密（must_change_password=0）"""
        h = _hash_pw("brandnewpwd")
        db.create_seller("brandnew", h, "新账号", "agent")
        seller = db.get_seller("brandnew")
        assert seller is not None
        assert seller["must_change_password"] == 0  # 新账号不强制
