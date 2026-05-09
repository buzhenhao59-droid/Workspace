# -*- coding: utf-8 -*-
"""
买方系统 MySQL 数据库连接池
替代 buyer.db (SQLite)

特性:
- pymysql 连接池（DBUtils.PooledDB）
- 自动重连
- SQLite 回退（开发模式 / 连接失败时）
- 配置从 BUYER_MYSQL_* 环境变量读取

表结构（与卖方 buyer_* 表一致）:
  buyer_customers, buyer_sessions, buyer_messages
"""
import os
import sys
import sqlite3
import threading
import logging
from typing import Optional, List, Dict, Tuple
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger(__name__)

# ============== 配置 ==============

def _get_mysql_config() -> dict:
    """从环境变量获取买方 MySQL 配置"""
    return {
        "host": os.getenv("BUYER_MYSQL_HOST", os.getenv("MYSQL_HOST", "localhost")),
        "port": int(os.getenv("BUYER_MYSQL_PORT", os.getenv("MYSQL_PORT", "3306"))),
        "user": os.getenv("BUYER_MYSQL_USER", os.getenv("MYSQL_USER", "root")),
        "password": os.getenv("BUYER_MYSQL_PASSWORD", os.getenv("MYSQL_PASSWORD", "")),
        "database": os.getenv("BUYER_MYSQL_DATABASE", os.getenv("MYSQL_DATABASE", "ruitalk_buyer")),
        "charset": "utf8mb4",
        "autocommit": False,
        "connect_timeout": 10,
        "read_timeout": 30,
        "write_timeout": 30,
    }


def _get_sqlite_path() -> Path:
    """获取 SQLite 回退路径"""
    raw = os.getenv("BUYER_SQLITE_FALLBACK_PATH", "")
    if raw:
        return Path(raw)
    buyer_root = Path(__file__).resolve().parent.parent
    return buyer_root / "backend" / "data" / "buyer.db"


# ============== MySQL 连接池 ==============

_mysql_pool: Optional["PooledDB"] = None
_pool_lock = threading.Lock()
_use_mysql = False


def _init_mysql_pool(force: bool = False) -> bool:
    """初始化买方 MySQL 连接池。返回 True=MySQL, False=SQLite回退"""
    global _mysql_pool, _use_mysql

    if _mysql_pool is not None and not force:
        return _use_mysql

    config = _get_mysql_config()
    password = config.get("password", "")
    skip_mysql = os.getenv("USE_SQLITE_FALLBACK", "false").lower() in ("true", "1", "yes")

    if skip_mysql or not password:
        logger.info("[BuyerMySQL] 密码为空或 USE_SQLITE_FALLBACK=true，跳过 MySQL，使用 SQLite 回退")
        _use_mysql = False
        _mysql_pool = None
        return False

    try:
        import pymysql
        pymysql.install_as_MySQLdb()
        from dbutils.pooled_db import PooledDB

        _mysql_pool = PooledDB(
            creator=pymysql,
            maxconnections=20,
            mincached=3,
            maxcached=10,
            blocking=True,
            ping=1,
            host=config["host"],
            port=config["port"],
            user=config["user"],
            password=config["password"],
            database=config["database"],
            charset=config["charset"],
            connect_timeout=config["connect_timeout"],
            read_timeout=config["read_timeout"],
            write_timeout=config["write_timeout"],
            autocommit=False,
        )
        _use_mysql = True
        logger.info(f"[BuyerMySQL] 连接池初始化成功: {config['host']}:{config['port']}/{config['database']}")
        return True
    except ImportError:
        logger.warning("[BuyerMySQL] pymysql / dbutils 未安装，使用 SQLite 回退")
        _use_mysql = False
        _mysql_pool = None
        return False
    except Exception as e:
        logger.warning(f"[BuyerMySQL] 连接池初始化失败，使用 SQLite 回退: {e}")
        _use_mysql = False
        _mysql_pool = None
        return False


def is_mysql() -> bool:
    """是否使用 MySQL"""
    return _use_mysql and _mysql_pool is not None


# ============== SQLite 回退 ==============

_sqlite_conn: Optional[sqlite3.Connection] = None
_sqlite_lock = threading.Lock()


def _get_sqlite_conn() -> sqlite3.Connection:
    """获取 SQLite 连接（单例，自动重建已关闭的连接）"""
    global _sqlite_conn
    if _sqlite_conn is None:
        with _sqlite_lock:
            if _sqlite_conn is None:
                path = _get_sqlite_path()
                path.parent.mkdir(parents=True, exist_ok=True)
                _sqlite_conn = sqlite3.connect(str(path), check_same_thread=False)
                _sqlite_conn.row_factory = sqlite3.Row
                _sqlite_conn.execute("PRAGMA foreign_keys = ON")
                logger.info(f"[BuyerSQLite] 连接已建立: {path}")
    # 检测已关闭的连接并重建
    try:
        _sqlite_conn.execute("SELECT 1")
    except Exception:
        logger.warning("[BuyerSQLite] 连接已关闭，正在重建...")
        with _sqlite_lock:
            try:
                _sqlite_conn.close()
            except Exception:
                pass
            path = _get_sqlite_path()
            _sqlite_conn = sqlite3.connect(str(path), check_same_thread=False)
            _sqlite_conn.row_factory = sqlite3.Row
            _sqlite_conn.execute("PRAGMA foreign_keys = ON")
            logger.info(f"[BuyerSQLite] 连接已重建: {path}")
    return _sqlite_conn


# ============== 统一连接上下文管理器 ==============

@contextmanager
def get_db():
    """
    统一买方数据库连接上下文管理器。
    用法:
        with get_db() as (conn, cursor):
            cursor.execute("SELECT * FROM buyer_customers")
    """
    if _use_mysql and _mysql_pool:
        conn = _mysql_pool.connection()
        cursor = conn.cursor()
        try:
            yield conn, cursor
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()
            conn.close()
    else:
        conn = _get_sqlite_conn()
        cursor = conn.cursor()
        try:
            yield conn, cursor
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()


def get_status() -> dict:
    """获取买方数据库状态"""
    return {
        "driver": "mysql" if _use_mysql else "sqlite",
        "pool_ready": _mysql_pool is not None,
    }


def close_pool():
    """关闭所有连接"""
    global _mysql_pool, _sqlite_conn
    if _mysql_pool:
        try:
            _mysql_pool.close()
        except Exception:
            pass
        _mysql_pool = None
    if _sqlite_conn:
        try:
            _sqlite_conn.close()
        except Exception:
            pass
        _sqlite_conn = None
    logger.info("[BuyerDB] 连接池已关闭")


def _row_to_dict(row, columns: List[str]) -> Optional[Dict]:
    """将行转换为字典"""
    if row is None:
        return None
    if hasattr(row, 'keys'):
        return dict(row)
    if columns:
        return dict(zip(columns, row))
    return dict(enumerate(row)) if hasattr(row, '__iter__') else None


def _cols(cursor) -> List[str]:
    return [d[0] for d in cursor.description] if cursor.description else []
