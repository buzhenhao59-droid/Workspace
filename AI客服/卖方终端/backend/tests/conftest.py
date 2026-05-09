# -*- coding: utf-8 -*-
"""
pytest 配置与全局 fixtures
"""
import os
import sys
import pytest
from pathlib import Path

# 将 backend 目录加入 Python path
_backend_dir = Path(__file__).parent
if str(_backend_dir) not in sys.path:
    sys.path.insert(0, str(_backend_dir))

# 测试环境变量（覆盖 .env）
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-for-unit-tests-only")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "30")
os.environ.setdefault("JWT_REFRESH_TOKEN_EXPIRE_DAYS", "7")
os.environ.setdefault("DEEPSEEK_API_KEY", "test-deepseek-key")
os.environ.setdefault("DEEPSEEK_API_URL", "https://api.deepseek.com/v1")
os.environ.setdefault("GRAPHRAG_API_URL", "http://localhost:8011")
os.environ.setdefault("MYSQL_HOST", "localhost")
os.environ.setdefault("MYSQL_PORT", "3306")
os.environ.setdefault("MYSQL_USER", "root")
os.environ.setdefault("MYSQL_PASSWORD", "test")
os.environ.setdefault("MYSQL_DATABASE", "ruitalk_test")
os.environ.setdefault("REDIS_HOST", "localhost")
os.environ.setdefault("REDIS_PORT", "6379")
os.environ.setdefault("INTERNAL_API_SECRET", "test-internal-secret")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ADMIN_PASSWORD_SALT", "test-salt")


# ============== Session Fixtures ==============

@pytest.fixture(scope="session")
def backend_dir():
    return _backend_dir


@pytest.fixture(scope="session")
def project_root():
    return _backend_dir.parent


@pytest.fixture
def mock_env(monkeypatch):
    """动态覆盖环境变量的 fixture"""
    return monkeypatch


# ============== Mock 外部依赖 ==============

@pytest.fixture
def mock_redis(mocker):
    """Mock Redis 客户端"""
    mock = mocker.MagicMock()
    mock.get.return_value = None
    mock.set.return_value = True
    mock.delete.return_value = 1
    mock.exists.return_value = 0
    mock.incr.return_value = 1
    mock.expire.return_value = True
    mock.ttl.return_value = -2
    mock.eval.return_value = [True, 59, 0, 1]  # allowed, remaining, retry_after, current
    return mock


@pytest.fixture
def mock_pymysql(mocker):
    """Mock pymysql"""
    mock_cursor = mocker.MagicMock()
    mock_cursor.fetchone.return_value = None
    mock_cursor.fetchall.return_value = []
    mock_cursor.lastrowid = 1
    mock_cursor.rowcount = 1

    mock_conn = mocker.MagicMock()
    mock_conn.cursor.return_value.__enter__ = mocker.MagicMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = mocker.MagicMock(return_value=False)
    mock_conn.ping.return_value = True
    mock_conn.commit.return_value = True
    mock_conn.rollback.return_value = True
    mock_conn.close.return_value = True

    mocker.patch("pymysql.connect", return_value=mock_conn)
    return mock_conn


@pytest.fixture
def mock_neo4j(mocker):
    """Mock Neo4j driver"""
    mock_driver = mocker.MagicMock()
    mock_session = mocker.MagicMock()
    mock_session.run.return_value.single.return_value = None
    mock_driver.session.return_value.__enter__ = mocker.MagicMock(return_value=mock_session)
    mock_driver.session.return_value.__exit__ = mocker.MagicMock(return_value=False)
    mock_driver.verify_connectivity.return_value = True
    mock_driver.close.return_value = None
    mocker.patch("neo4j.GraphDatabase.driver", return_value=mock_driver)
    return mock_driver


@pytest.fixture
def mock_requests(mocker):
    """Mock requests（用于外部 API 调用）"""
    mock_resp = mocker.MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"choices": [{"message": {"content": "Test response"}}]}
    mock_resp.text = '{"choices": [{"message": {"content": "Test response"}}]}'
    mock_resp.headers = {}
    mock_resp.raise_for_status = mocker.MagicMock()
    mocker.patch("requests.post", return_value=mock_resp)
    mocker.patch("requests.get", return_value=mock_resp)
    return mock_resp
