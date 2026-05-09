# -*- coding: utf-8 -*-
"""
配置和工具模块单元测试
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "ruitalk_config"))

from tools import backup_db


class TestBackupDBHelpers:
    """backup_db.py 辅助函数测试"""

    def test_stamp_format(self):
        stamp = backup_db._stamp()
        assert isinstance(stamp, str)
        assert len(stamp) == 15  # YYYYMMDD_HHMMSS
        assert stamp[8] == "_"

    def test_sha256_returns_12_chars(self):
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False, mode="w") as f:
            f.write("test content")
            f.flush()
            path = backup_db.Path(f.name)
        try:
            result = backup_db._sha256(path)
            assert len(result) == 12
            assert result.isalnum()
        finally:
            os.unlink(f.name)

    def test_sha256_deterministic(self):
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False, mode="w") as f:
            f.write("consistent content")
            f.flush()
            path = backup_db.Path(f.name)
        try:
            h1 = backup_db._sha256(path)
            h2 = backup_db._sha256(path)
            assert h1 == h2
        finally:
            os.unlink(f.name)

    def test_load_env_parses_correctly(self):
        import tempfile
        content = '''
# 这是注释
VAR1=value1
VAR2="quoted value"
VAR3='single quoted'
EMPTY=
SPACED=  with spaces  
'''
        with tempfile.NamedTemporaryFile(delete=False, mode="w", suffix=".env") as f:
            f.write(content)
            f.flush()
            env = backup_db._load_env(backup_db.Path(f.name))
        try:
            assert env.get("VAR1") == "value1"
            assert env.get("VAR2") == "quoted value"
            assert env.get("VAR3") == "single quoted"
            assert env.get("EMPTY") == ""
            assert "with spaces" in env.get("SPACED", "")
        finally:
            os.unlink(f.name)

    def test_load_env_missing_file_returns_empty(self):
        env = backup_db._load_env(backup_db.Path("/nonexistent/path/.env"))
        assert env == {}

    def test_compress_backup_creates_zip(self):
        import tempfile, zipfile
        with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as f:
            f.write(b"test database content")
            f.flush()
            src = backup_db.Path(f.name)

        try:
            result = backup_db._compress_backup(src, "test_db")
            assert result is not None
            assert result.suffix == ".zip"
            assert result.exists()
            # 验证 zip 内容
            with zipfile.ZipFile(result, "r") as zf:
                names = zf.namelist()
                assert len(names) >= 1
        finally:
            if result and result.exists():
                result.unlink()

    def test_restore_sqlite_copies_file(self):
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as src_f:
            src_f.write(b"backup content")
            src_f.flush()
            src_path = backup_db.Path(src_f.name)

        with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as dst_f:
            dst_path = backup_db.Path(dst_f.name)

        try:
            result = backup_db._restore_sqlite(src_path, dst_path)
            assert result is True
            assert dst_path.read_bytes() == b"backup content"
        finally:
            src_path.unlink(missing_ok=True)
            dst_path.unlink(missing_ok=True)

    def test_restore_sqlite_nonexistent_source_returns_false(self):
        result = backup_db._restore_sqlite(
            backup_db.Path("/nonexistent/backup.db"),
            backup_db.Path("/tmp/target.db")
        )
        assert result is False
