# -*- coding: utf-8 -*-
"""
统一 MySQL 数据库连接池
替代所有 SQLite 调用

特性:
- pymysql 连接池（DBUtils.PooledDB）
- 自动重连
- SQLite 回退（开发模式 / 连接失败时）
- 所有数据库操作通过此模块
- 配置从统一环境变量读取
"""
import os
import sys
import sqlite3
import threading
import logging
from typing import Optional, Any, Dict, List, Tuple
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger(__name__)

# ============== 配置 ==============

def _get_mysql_config() -> dict:
    """从环境变量获取 MySQL 配置（兼容所有命名约定）"""
    from config import (
        MYSQL_POOL_SIZE, MYSQL_MAX_OVERFLOW,
        MYSQL_CONNECT_TIMEOUT, MYSQL_READ_TIMEOUT, MYSQL_WRITE_TIMEOUT
    )
    return {
        "host": os.getenv("MYSQL_HOST", os.getenv("SHOP_MYSQL_HOST", "localhost")),
        "port": int(os.getenv("MYSQL_PORT", os.getenv("SHOP_MYSQL_PORT", "3306"))),
        "user": os.getenv("MYSQL_USER", os.getenv("SHOP_MYSQL_USER", "root")),
        "password": os.getenv("MYSQL_PASSWORD", os.getenv("SHOP_MYSQL_PASSWORD", "")),
        "database": os.getenv("MYSQL_DATABASE", os.getenv("SHOP_MYSQL_DATABASE", "ruitalk")),
        "charset": "utf8mb4",
        "autocommit": False,
        "connect_timeout": MYSQL_CONNECT_TIMEOUT,
        "read_timeout": MYSQL_READ_TIMEOUT,
        "write_timeout": MYSQL_WRITE_TIMEOUT,
        # 连接池参数
        "max_connections": MYSQL_POOL_SIZE,
        "min_cached": 5,
        "max_cached": MYSQL_MAX_OVERFLOW,
    }


def _get_sqlite_path() -> Path:
    """获取 SQLite 回退路径"""
    raw = os.getenv("SQLITE_FALLBACK_PATH", "")
    if raw:
        return Path(raw)
    # 用 .absolute() 而非 .resolve() 避免路径穿越 junction/符号链接
    backend_dir = Path(__file__).absolute().parent
    return backend_dir / "data" / "seller.db"


# ============== MySQL 连接池 ==============

_mysql_pool = None
_pool_lock = threading.Lock()
_use_mysql = False


def _init_mysql_pool(force: bool = False) -> bool:
    """
    初始化 MySQL 连接池。
    返回 True 表示使用 MySQL，False 表示使用 SQLite 回退。
    """
    global _mysql_pool, _use_mysql

    if _mysql_pool is not None:
        return _use_mysql

    config = _get_mysql_config()
    password = config.get("password", "")
    skip_mysql = os.getenv("USE_SQLITE_FALLBACK", "false").lower() in ("true", "1", "yes")

    if skip_mysql or not password:
        logger.info("[MySQL] 密码为空或 USE_SQLITE_FALLBACK=true，跳过 MySQL，使用 SQLite 回退")
        _use_mysql = False
        _mysql_pool = None
        return False

    try:
        import pymysql
        pymysql.install_as_MySQLdb()
        from dbutils.pooled_db import PooledDB

        # 性能优化：使用优化的连接池参数
        _mysql_pool = PooledDB(
            creator=pymysql,
            maxconnections=config.get("max_connections", 50),
            mincached=5,
            maxcached=config.get("max_cached", 20),
            blocking=True,
            maxusage=None,
            setsession=["SET sql_mode='STRICT_TRANS_TABLES'"],
            ping=1,
            host=config["host"],
            port=config["port"],
            user=config["user"],
            password=config["password"],
            database=config["database"],
            charset=config["charset"],
            connect_timeout=config.get("connect_timeout", 10),
            read_timeout=config.get("read_timeout", 30),
            write_timeout=config.get("write_timeout", 30),
            autocommit=False,
        )
        logger.info(
            f"[MySQL] 连接池初始化成功: {config['host']}:{config['port']}/{config['database']} "
            f"(max_connections={config.get('max_connections', 50)}, "
            f"max_cached={config.get('max_cached', 20)}, "
            f"pool_timeout={config.get('pool_timeout', 30)})"
        )
        return True
    except ImportError:
        logger.warning("[MySQL] pymysql / dbutils 未安装，使用 SQLite 回退")
        _use_mysql = False
        _mysql_pool = None
        return False
    except Exception as e:
        logger.warning(f"[MySQL] 连接池初始化失败，使用 SQLite 回退: {e}")
        _use_mysql = False
        _mysql_pool = None
        return False


def is_mysql() -> bool:
    """是否使用 MySQL"""
    return _use_mysql and _mysql_pool is not None


def is_ready() -> bool:
    """数据库是否就绪（MySQL 或 SQLite 任一可用）"""
    if _use_mysql and _mysql_pool:
        return True
    # SQLite 回退始终就绪
    return True


# ============== SQLite 回退 ==============

_sqlite_conn: Optional[sqlite3.Connection] = None
_sqlite_lock = threading.Lock()


def _get_sqlite_conn() -> sqlite3.Connection:
    """获取 SQLite 连接（单例）"""
    global _sqlite_conn
    if _sqlite_conn is None:
        with _sqlite_lock:
            if _sqlite_conn is None:
                path = _get_sqlite_path()
                path.parent.mkdir(parents=True, exist_ok=True)
                _sqlite_conn = sqlite3.connect(str(path), check_same_thread=False, timeout=30)
                _sqlite_conn.row_factory = sqlite3.Row
                # 启用 WAL 模式，提升并发读写性能
                _sqlite_conn.execute("PRAGMA journal_mode=WAL")
                _sqlite_conn.execute("PRAGMA foreign_keys = ON")
                logger.info(f"[SQLite] 连接已建立: {path}")
    return _sqlite_conn


def _sqlite_execute(conn: sqlite3.Connection, sql: str, params: tuple = ()):
    """SQLite 执行（自动处理参数）"""
    cursor = conn.cursor()
    try:
        cursor.execute(sql, params)
        conn.commit()
        return cursor
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()


def _sqlite_executemany(conn: sqlite3.Connection, sql: str, params_list: List[tuple]):
    """SQLite 批量执行"""
    cursor = conn.cursor()
    try:
        cursor.executemany(sql, params_list)
        conn.commit()
        return cursor
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()


# ============== 统一连接上下文管理器 ==============

@contextmanager
def get_db():
    """
    统一数据库连接上下文管理器。
    自动在 MySQL 连接池和 SQLite 回退之间选择。
    自动处理 commit / rollback。

    用法:
        with get_db() as (conn, cursor):
            cursor.execute("SELECT * FROM customers")
            rows = cursor.fetchall()
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


def get_raw_cursor():
    """
    获取裸游标（用于需要直接访问 cursor 的场景）。
    返回 (conn, cursor) 元组。
    """
    if _use_mysql and _mysql_pool:
        conn = _mysql_pool.connection()
        cursor = conn.cursor()
        return conn, cursor
    else:
        conn = _get_sqlite_conn()
        cursor = conn.cursor()
        return conn, cursor


# ============== MySQL 兼容工具函数 ==============

def mysql_now() -> str:
    """返回当前时间的 MySQL / SQLite 兼容格式"""
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def mysql_param_placeholders(n: int, placeholder: str = "%s") -> str:
    """生成 MySQL / SQLite 兼容的参数占位符"""
    return ", ".join([placeholder] * n)


def mysql_safe_value(val: Any) -> Any:
    """安全处理值（MySQL None 和 SQLite None 兼容）"""
    if val is None:
        return None
    if isinstance(val, bool):
        return 1 if val else 0
    return val


def dict_to_row(row, columns: List[str]) -> Optional[Dict]:
    """将数据库行转换为字典（兼容 MySQL tuple 和 SQLite Row）"""
    if row is None:
        return None
    if hasattr(row, '_fields'):
        # MySQL named tuple
        return dict(zip(row._fields, row))
    if hasattr(row, 'keys'):
        return dict(row)
    if columns:
        return dict(zip(columns, row))
    return dict(enumerate(row)) if hasattr(row, '__iter__') else None


def get_columns(cursor) -> List[str]:
    """获取查询结果的列名"""
    if hasattr(cursor, 'description') and cursor.description:
        return [desc[0] for desc in cursor.description]
    return []


# ============== 初始化 ==============

def init_pool():
    """初始化连接池（由 main.py 启动时调用）"""
    _init_mysql_pool()


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
    logger.info("[DB] 连接池已关闭")


# ============== 异步非阻塞数据库支持 ==============

_aiomysql_pool = None


async def _init_async_mysql_pool() -> bool:
    """
    初始化异步 MySQL 连接池（aiomysql）。
    返回 True 表示成功，False 表示失败。
    """
    global _aiomysql_pool

    if _aiomysql_pool is not None:
        return True

    config = _get_mysql_config()
    password = config.get("password", "")

    if not password:
        logger.info("[AsyncMySQL] 密码为空，跳过异步连接池")
        return False

    try:
        import aiomysql
        pool = await aiomysql.create_pool(
            minsize=config.get("min_cached", 5),
            maxsize=config.get("max_connections", 50),
            host=config["host"],
            port=config["port"],
            user=config["user"],
            password=config["password"],
            db=config["database"],
            charset=config["charset"],
            connect_timeout=config["connect_timeout"],
            read_timeout=config["read_timeout"],
            write_timeout=config["write_timeout"],
            autocommit=False,
            pool_recycle=3600,  # 1小时回收连接，防止MySQL 8小时超时
        )
        _aiomysql_pool = pool
        logger.info(f"[AsyncMySQL] 连接池初始化成功: {config['host']}:{config['port']}/{config['database']}")
        return True
    except ImportError:
        logger.warning("[AsyncMySQL] aiomysql 未安装，跳过异步数据库支持")
        return False
    except Exception as e:
        logger.warning(f"[AsyncMySQL] 连接池初始化失败: {e}")
        return False


async def get_async_db():
    """
    获取异步数据库连接。
    用法:
        async with get_async_db() as cursor:
            await cursor.execute("SELECT * FROM customers")
    """
    global _aiomysql_pool

    if _aiomysql_pool is None:
        await _init_async_mysql_pool()

    if _aiomysql_pool is None:
        raise RuntimeError("异步MySQL连接池不可用")

    async with _aiomysql_pool.acquire() as conn:
        async with conn.cursor() as cursor:
            try:
                yield cursor
                await conn.commit()
            except Exception:
                await conn.rollback()
                raise


async def async_execute(sql: str, params: Tuple = ()) -> int:
    """异步执行单条 SQL"""
    async with get_async_db() as cursor:
        await cursor.execute(sql, params)
        return cursor.lastrowid if hasattr(cursor, 'lastrowid') else cursor.rowcount


async def async_fetchall(sql: str, params: Tuple = ()) -> List[Dict]:
    """异步查询所有行"""
    async with get_async_db() as cursor:
        await cursor.execute(sql, params)
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        rows = await cursor.fetchall()
        return [dict(zip(columns, row)) for row in rows]


async def async_fetchone(sql: str, params: Tuple = ()) -> Optional[Dict]:
    """异步查询一行"""
    async with get_async_db() as cursor:
        await cursor.execute(sql, params)
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        row = await cursor.fetchone()
        return dict(zip(columns, row)) if row else None


async def async_close_pool():
    """关闭异步连接池"""
    global _aiomysql_pool
    if _aiomysql_pool:
        _aiomysql_pool.close()
        await _aiomysql_pool.wait_closed()
        _aiomysql_pool = None
        logger.info("[AsyncMySQL] 连接池已关闭")


# ============== 便捷执行函数 ==============

def execute(sql: str, params: Tuple = ()) -> Any:
    """执行单条 SQL"""
    with get_db() as (conn, cursor):
        cursor.execute(sql, params)
        return cursor.lastrowid if hasattr(cursor, 'lastrowid') else cursor.rowcount


def executemany(sql: str, params_list: List[Tuple]) -> int:
    """批量执行 SQL"""
    with get_db() as (conn, cursor):
        cursor.executemany(sql, params_list)
        return cursor.rowcount


def fetchall(sql: str, params: Tuple = ()) -> List[Dict]:
    """查询所有行"""
    with get_db() as (conn, cursor):
        cursor.execute(sql, params)
        columns = get_columns(cursor)
        rows = cursor.fetchall()
        return [dict_to_row(row, columns) for row in rows]


def fetchone(sql: str, params: Tuple = ()) -> Optional[Dict]:
    """查询一行"""
    with get_db() as (conn, cursor):
        cursor.execute(sql, params)
        columns = get_columns(cursor)
        row = cursor.fetchone()
        return dict_to_row(row, columns) if row else None


# ============== 调试 ==============

def get_status() -> dict:
    """获取数据库状态"""
    status = {
        "driver": "mysql" if _use_mysql else "sqlite",
        "pool_ready": _mysql_pool is not None,
    }
    if _use_mysql and _mysql_pool:
        cfg = _get_mysql_config()
        status["mysql_host"] = cfg["host"]
        status["mysql_port"] = cfg["port"]
        status["mysql_database"] = cfg["database"]
    else:
        status["sqlite_path"] = str(_get_sqlite_path())
    return status
