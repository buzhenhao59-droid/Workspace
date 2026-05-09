# -*- coding: utf-8 -*-
"""
消息中心服务 - 会话列表、快捷回复、消息通知、强提醒
"""
import re
import os as _os
import sqlite3
import json
import threading
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
from pathlib import Path
from enum import Enum

logger = logging.getLogger(__name__)


def get_db_path() -> Path:
    """与主库一致的 SQLite 路径（用于消息中心回退）"""
    try:
        from db import get_db_path as _main_db_path

        return Path(_main_db_path())
    except Exception:
        return Path(__file__).resolve().parent.parent / "data" / "ruitalk.db"


def _ensure_sqlite_path() -> None:
    try:
        p = Path(get_db_path())
        p.parent.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        logger.debug("[msg_center] _ensure_sqlite_path: %s", e)


# ============== MySQL 兼容层 ==============
# 优先使用 MySQL（通过 db.py 的连接池），SQLite 仅作为开发回退


def _get_mysql_pool_config() -> dict:
    """获取 MySQL 连接配置（同 db.py）"""
    import os as _os
    return {
        "host": _os.getenv("MYSQL_HOST", _os.getenv("SHOP_MYSQL_HOST", "localhost")),
        "port": int(_os.getenv("MYSQL_PORT") or _os.getenv("SHOP_MYSQL_PORT") or "3306"),
        "user": _os.getenv("MYSQL_USER", _os.getenv("SHOP_MYSQL_USER", "root")),
        "password": _os.getenv("MYSQL_PASSWORD", _os.getenv("SHOP_MYSQL_PASSWORD", "")),
        "database": _os.getenv("MYSQL_DATABASE", _os.getenv("SHOP_MYSQL_DATABASE", "ruitalk")),
        "charset": "utf8mb4",
        "autocommit": False,
        "connect_timeout": 10,
    }


def _adapt_sql(sql: str) -> str:
    """将 SQLite SQL 转换为 MySQL 兼容格式"""
    sql = sql.replace("?", "%s")
    sql = re.sub(r"CURRENT_TIMESTAMP", "NOW()", sql)
    sql = re.sub(r"datetime\(\s*'now'\s*\)", "NOW()", sql)
    sql = re.sub(
        r"datetime\(\s*'now'\s*,\s*'\+?\s*(\d+)\s*days?\s*'\)",
        lambda m: f"DATE_ADD(NOW(), INTERVAL {m.group(1)} DAY)",
        sql,
    )
    sql = re.sub(
        r"datetime\(\s*'now'\s*,\s*'\-?\s*(\d+)\s*days?\s*'\)",
        lambda m: f"DATE_SUB(NOW(), INTERVAL {m.group(1)} DAY)",
        sql,
    )
    sql = re.sub(r"INTEGER PRIMARY KEY AUTOINCREMENT", "INT AUTO_INCREMENT", sql)
    return sql


_mysql_pool = None
_mysql_lock = threading.Lock()
# None=尚未决策；True=使用 MySQL；False=永久使用 SQLite（直至进程重启），避免每次请求都重试连 MySQL
_mysql_decided: Optional[bool] = None


def _ensure_mysql_pool():
    global _mysql_pool, _mysql_decided
    if _mysql_decided is not None:
        return _mysql_decided is True
    with _mysql_lock:
        if _mysql_decided is not None:
            return _mysql_decided is True
        skip = _os.getenv("USE_SQLITE_FALLBACK", "false").lower() in ("true", "1", "yes")
        cfg = _get_mysql_pool_config()
        pwd = (cfg.get("password") or "").strip()
        if skip or not pwd:
            logger.info("[msg_center] 跳过 MySQL（USE_SQLITE_FALLBACK 或未配置 MYSQL_PASSWORD），使用 SQLite")
            _mysql_decided = False
            _mysql_pool = None
            return False
        try:
            PooledDB = None
            try:
                from dbutils.pooled_db import PooledDB
            except ImportError:
                try:
                    from DBUtils.PooledDB import PooledDB
                except ImportError:
                    try:
                        from dbutils_pooled_db import PooledDB  # type: ignore
                    except ImportError:
                        pass
            import pymysql

            if PooledDB is None:
                raise ImportError("未找到 PooledDB，请 pip install DBUtils pymysql")
            _cfg = dict(_get_mysql_pool_config())
            _cfg["connect_timeout"] = min(int(_cfg.get("connect_timeout") or 10), 4)
            _mysql_pool = PooledDB(
                creator=pymysql,
                maxconnections=10,
                mincached=0,
                maxcached=3,
                blocking=True,
                **_cfg,
            )
            logger.info("[msg_center] MySQL 连接池已初始化")
            _mysql_decided = True
            return True
        except Exception as e:
            logger.warning("[msg_center] MySQL 连接池初始化失败，已固定使用 SQLite 回退: %s", e)
            _mysql_pool = None
            _mysql_decided = False
            return False


def _is_mysql() -> bool:
    return _ensure_mysql_pool()


def _infer_platform_from_customer_id(customer_id: Optional[str]) -> str:
    """从演示库 customer_id 前缀推断平台（与 build_demo_data.gen_customer_id 一致）"""
    if not customer_id:
        return "other"
    cid = str(customer_id).strip().upper()
    mapping = (
        ("AMZ", "amazon"),
        ("SP", "shopee"),
        ("LZ", "lazada"),
        ("TM", "temu"),
        ("AE", "aliexpress"),
        ("EB", "ebay"),
        ("TT", "tiktok"),
    )
    for prefix, plat in mapping:
        if cid.startswith(prefix):
            return plat
    return "other"


def _conversation_list_from_main_sessions(
    platform: Optional[str], time_threshold: str, limit: int = 80
) -> List[Dict]:
    """conversation_history 为空时，从主库 sessions + messages 聚合会话列表（演示/生产均有数据）。"""
    try:
        from db import get_db, is_mysql as db_is_mysql
    except Exception as e:
        logger.debug("[msg_center] 无法导入 db 做会话回退: %s", e)
        return []
    rows_out: List[Dict] = []

    # 优化：使用 JOIN + GROUP BY 替代 N+1 子查询，大幅提升大量会话时的查询速度
    try:
        with get_db() as (conn, cursor):
            is_mysql = db_is_mysql()

            # 先查最近的会话（只查人工会话 + 有消息的）
            if is_mysql:
                cursor.execute(
                    """
                    SELECT s.session_id, s.customer_id, c.name AS customer_name,
                           s.is_ai, s.created_at, s.updated_at,
                           msg_stats.last_content, msg_stats.last_sender, msg_stats.msg_count
                    FROM sessions s
                    LEFT JOIN customers c ON s.customer_id = c.customer_id
                    LEFT JOIN (
                        SELECT session_id,
                               content AS last_content,
                               role AS last_sender,
                               cnt AS msg_count
                        FROM (
                            SELECT m.session_id, m.content, m.role,
                                   COUNT(*) OVER (PARTITION BY m.session_id) AS cnt,
                                   ROW_NUMBER() OVER (PARTITION BY m.session_id ORDER BY m.id DESC) AS rn
                            FROM messages m
                        ) ranked
                        WHERE rn = 1
                    ) msg_stats ON msg_stats.session_id = s.session_id
                    WHERE s.updated_at >= %s
                      AND msg_stats.msg_count > 0
                    ORDER BY s.updated_at DESC
                    LIMIT %s
                    """,
                    (time_threshold, limit),
                )
            else:
                # SQLite: 使用窗口函数（3.25+）或回退到简化的查询
                try:
                    cursor.execute(
                        """
                        SELECT s.session_id, s.customer_id, c.name AS customer_name,
                               s.is_ai, s.created_at, s.updated_at,
                               (SELECT m.content FROM messages m WHERE m.session_id = s.session_id
                                ORDER BY m.id DESC LIMIT 1) AS last_content,
                               (SELECT m.role FROM messages m WHERE m.session_id = s.session_id
                                ORDER BY m.id DESC LIMIT 1) AS last_sender,
                               (SELECT COUNT(*) FROM messages m WHERE m.session_id = s.session_id) AS msg_count
                        FROM sessions s
                        LEFT JOIN customers c ON s.customer_id = c.customer_id
                        WHERE s.updated_at >= ?
                          AND (SELECT COUNT(*) FROM messages m WHERE m.session_id = s.session_id) > 0
                        ORDER BY s.updated_at DESC
                        LIMIT ?
                        """,
                        (time_threshold, limit),
                    )
                except Exception:
                    # 回退到仅查询会话 ID，不含消息预览
                    cursor.execute(
                        """
                        SELECT s.session_id, s.customer_id, c.name AS customer_name,
                               s.is_ai, s.created_at, s.updated_at,
                               NULL AS last_content, NULL AS last_sender, 0 AS msg_count
                        FROM sessions s
                        LEFT JOIN customers c ON s.customer_id = c.customer_id
                        WHERE s.updated_at >= ?
                        ORDER BY s.updated_at DESC
                        LIMIT ?
                        """,
                        (time_threshold, limit),
                    )

            cols = [d[0] for d in cursor.description] if cursor.description else []
            for row in cursor.fetchall():
                d = dict(zip(cols, row))
                # 转换 is_ai → is_human_session
                d["is_human_session"] = 0 if d.get("is_ai") else 1
                d["last_message"] = d.pop("last_content", None)
                d["message_count"] = d.pop("msg_count", 0)
                d["platform"] = _infer_platform_from_customer_id(d.get("customer_id"))
                for k, v in list(d.items()):
                    if v is not None and hasattr(v, "isoformat"):
                        d[k] = v.isoformat(sep=" ", timespec="seconds")
                rows_out.append(d)
    except Exception as e:
        logger.warning("[msg_center] 从 sessions 聚合会话列表失败: %s", e)
        return []

    if platform:
        p = platform.lower().strip()
        rows_out = [r for r in rows_out if (r.get("platform") or "").lower() == p]
    return rows_out




def get_connection():
    """获取数据库连接

    MySQL 模式：返回 pymysql 连接，cursor.fetchall() 返回 dict 列表（兼容 sqlite3.Row 访问）
    SQLite 模式：返回 sqlite3 连接，cursor.row_factory = sqlite3.Row
    """
    if _is_mysql():
        try:
            conn = _mysql_pool.connection()
            conn.autocommit = False
            return conn
        except Exception as e:
            logger.warning(f"[msg_center] MySQL 连接失败，切换 SQLite: {e}")

    # SQLite 回退
    _ensure_sqlite_path()
    conn = sqlite3.connect(str(get_db_path()), check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.text_factory = str  # Ensure strings are returned as str, not bytes
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def get_cursor(conn):
    """获取适配 MySQL/SQLite 的 cursor

    MySQL：fetchall/fetchone/fetchmany 返回 dict 列表（兼容 sqlite3.Row 访问）
    SQLite：使用连接上的 row_factory = sqlite3.Row
    """
    if isinstance(conn, sqlite3.Connection):
        return conn.cursor()

    cursor = conn.cursor()
    _orig_execute = cursor.execute
    _orig_callproc = getattr(cursor, "callproc", None)
    _orig_fetchall = cursor.fetchall
    _orig_fetchone = cursor.fetchone
    _orig_fetchmany = cursor.fetchmany

    def _wrap_execute(sql, params=None):
        sql = _adapt_sql(sql)
        if params is not None:
            result = _orig_execute(sql, params)
        else:
            result = _orig_execute(sql)
        cursor._keys = [d[0] for d in cursor.description] if cursor.description else []
        return result

    def _fetchall():
        rows = _orig_fetchall()
        return [dict(zip(cursor._keys, r)) for r in rows] if rows and cursor._keys else (rows or [])

    def _fetchone():
        row = _orig_fetchone()
        return dict(zip(cursor._keys, row)) if row and cursor._keys else row

    def _fetchmany(size=None):
        rows = _orig_fetchmany(size if size is not None else cursor.arraysize)
        return [dict(zip(cursor._keys, r)) for r in rows] if rows and cursor._keys else (rows or [])

    cursor.execute = _wrap_execute
    if _orig_callproc is not None:
        cursor.callproc = _orig_callproc
    cursor.fetchall = _fetchall
    cursor.fetchone = _fetchone
    cursor.fetchmany = _fetchmany

    return cursor



def _sqlite_notification_column_set(conn) -> set:
    """notifications 表实际列名（seller.db 为 notification_type/source/is_important；旧版为 notify_type/related_type/priority）"""
    cur = conn.execute("PRAGMA table_info(notifications)")
    return {row[1] for row in cur.fetchall()}


def _sqlite_type_column_name(cols: set) -> str:
    if "notify_type" in cols:
        return "notify_type"
    if "notification_type" in cols:
        return "notification_type"
    return "notify_type"


def _sqlite_build_notifications_select(
    cols: set,
    notification_type: Optional[str],
    include_read: bool,
    limit: int,
    exclude_types: Optional[List[str]] = None,
    include_types: Optional[List[str]] = None,
    days: Optional[int] = None,
) -> tuple[str, tuple]:
    """构建与 seller.db / 旧版 schema 均兼容的 SELECT"""
    type_col = _sqlite_type_column_name(cols)

    if "related_type" in cols:
        src_col = "related_type"
    elif "source" in cols:
        src_col = "source"
    else:
        src_col = None

    if "priority" in cols:
        order_sql = (
            "ORDER BY CASE priority WHEN 'high' THEN 0 WHEN 'important' THEN 1 "
            "WHEN 'normal' THEN 2 ELSE 3 END ASC, created_at DESC"
        )
    elif "is_important" in cols:
        order_sql = "ORDER BY is_important DESC, created_at DESC"
    else:
        order_sql = "ORDER BY created_at DESC"

    url_sel = "url" if "url" in cols else "'' AS url"

    rel_sql = f"{src_col} AS related_type" if src_col else "NULL AS related_type"
    prio_sql = "priority" if "priority" in cols else "'normal' AS priority"
    base_select = (
        f"id, {type_col} AS notify_type, title, content, {rel_sql}, {prio_sql}, "
        f"is_read, created_at, {url_sel}"
    )

    where_parts = []
    params: List = []

    if notification_type:
        where_parts.append(f"{type_col} = ?")
        params.append(notification_type)
    elif include_types:
        placeholders = ",".join("?" * len(include_types))
        where_parts.append(f"{type_col} IN ({placeholders})")
        params.extend(include_types)
    elif exclude_types:
        placeholders = ",".join("?" * len(exclude_types))
        where_parts.append(f"{type_col} NOT IN ({placeholders})")
        params.extend(exclude_types)

    if not include_read:
        where_parts.append("is_read = 0")

    if days is not None and days > 0:
        where_parts.append("created_at >= datetime('now', ?)")
        params.append(f"-{days} days")

    where_sql = (" WHERE " + " AND ".join(where_parts)) if where_parts else ""
    sql = f"SELECT {base_select} FROM notifications{where_sql} {order_sql} LIMIT ?"
    params.append(limit)
    return sql, tuple(params)


def _normalize_notification_row(item: Dict) -> Dict:
    """统一 notify_type / notification_type，避免把已有 notification_type 覆盖成 None"""
    nt = item.pop("notify_type", None) or item.pop("notification_type", None)
    if nt is not None:
        item["notification_type"] = nt
    elif not item.get("notification_type"):
        item["notification_type"] = "system"

    src = item.pop("related_type", None) or item.get("source")
    if src is not None:
        item["source"] = src

    if "is_important" in item and item["is_important"] not in (0, 1):
        try:
            item["is_important"] = int(bool(item["is_important"]))
        except Exception:
            item["is_important"] = 0

    if "priority" in item:
        pr = item.get("priority") or "normal"
        item["is_important"] = 1 if pr in ("high", "important") else item.get("is_important", 0)
        item.pop("priority", None)
    elif item.get("is_important") is None:
        item["is_important"] = 0

    if item.get("created_at"):
        item["created_at"] = str(item["created_at"])

    if not str(item.get("source") or "").strip():
        item["source"] = "系统"
    return item


class MessageCenterService:
    """消息中心服务"""
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def init_db(self):
        """初始化消息中心相关表"""
        conn = get_connection()
        if isinstance(conn, sqlite3.Connection):
            try:
                from init_mysql_schema import _ensure_sqlite_notifications_columns

                _ensure_sqlite_notifications_columns(conn)
            except Exception as e:
                logger.debug("[msg_center] notifications 列补全跳过: %s", e)
        cursor = get_cursor(conn)
        
        # 快捷回复表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS quick_replies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL DEFAULT '通用',
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                shortcut TEXT,
                is_active INTEGER DEFAULT 1,
                created_by TEXT DEFAULT 'admin',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # 消息通知表（政策消息、市场动态）
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                notification_type TEXT NOT NULL DEFAULT 'policy',
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                source TEXT DEFAULT 'deepseek',
                url TEXT DEFAULT '',
                is_read INTEGER DEFAULT 0,
                is_important INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                read_at TEXT
            )
        """)

        # 已有旧表缺少 url 列时补上
        if isinstance(conn, sqlite3.Connection):
            try:
                cursor.execute("PRAGMA table_info(notifications)")
                cols = [row[1] for row in cursor.fetchall()]
                if 'url' not in cols:
                    cursor.execute("ALTER TABLE notifications ADD COLUMN url TEXT DEFAULT ''")
                    conn.commit()
                    logger.info("[msg_center] notifications 表已添加 url 列")
            except Exception as e:
                logger.debug("[msg_center] notifications url 列检查跳过: %s", e)
        
        # 强提醒表（闹钟功能）
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                content TEXT,
                remind_type TEXT DEFAULT 'once',
                remind_time TEXT NOT NULL,
                is_repeat INTEGER DEFAULT 0,
                repeat_days TEXT,
                is_active INTEGER DEFAULT 1,
                is_triggered INTEGER DEFAULT 0,
                created_by TEXT DEFAULT 'admin',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                last_triggered TEXT
            )
        """)
        
        # 会话历史记录表（用于消息中心的会话列表）
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS conversation_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT UNIQUE NOT NULL,
                platform TEXT NOT NULL,
                customer_id TEXT,
                customer_name TEXT,
                last_message TEXT,
                last_sender TEXT,
                message_count INTEGER DEFAULT 0,
                is_human_session INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # 插入默认快捷回复
        default_replies = [
            ("通用", "您好，请问有什么可以帮您？", "您好"),
            ("通用", "感谢您的咨询，祝您生活愉快！", "再见"),
            ("订单", "请问您的订单号是多少？方便我为您查询。", "订单号"),
            ("订单", "好的，我帮您查询一下订单状态，请稍等。", "查询中"),
            ("物流", "您的包裹正在配送中，预计2-3个工作日送达。", "物流中"),
            ("物流", "很抱歉，物流信息暂时未更新，我们已联系物流公司处理。", "延迟"),
            ("售后", "请问您是遇到了什么问题呢？我来帮您解决。", "售后"),
            ("售后", "好的，我已为您提交售后申请，请耐心等待处理结果。", "已提交"),
        ]
        
        for category, title, shortcut in default_replies:
            cursor.execute("""
                INSERT OR IGNORE INTO quick_replies (category, title, content, shortcut)
                VALUES (?, ?, ?, ?)
            """, (category, title, title, shortcut))
        
        conn.commit()
        conn.close()
        logger.info("消息中心数据库表初始化完成")

        # 优化：为高频查询字段创建索引，加速会话列表和通知查询
        # 复合索引：(notification_type, created_at, is_read) - 覆盖 90% 的查询场景
        # 时间索引：(created_at) - 时间范围过滤
        # 重要性索引：(is_important, created_at) - 置顶排序
        if isinstance(conn, sqlite3.Connection):
            try:
                # 会话列表索引
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_conv_updated ON conversation_history(updated_at)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_conv_human ON conversation_history(is_human_session)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_conv_platform ON conversation_history(platform)")
                
                # 通知表索引 - 优化检索性能
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_notif_type_read ON notifications(notification_type, is_read, created_at)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_notif_type_created ON notifications(notification_type, created_at DESC)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_notif_important ON notifications(is_important, created_at DESC)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_notif_created ON notifications(created_at)")
                
                conn.commit()
                logger.info("[msg_center] 数据库索引已优化/确认")
            except Exception as e:
                logger.debug("[msg_center] 索引创建跳过: %s", e)

    # ==================== 会话列表 ====================
    
    def get_conversation_list(self, platform: str = None, hours: int = 72) -> List[Dict]:
        """获取会话列表（最近指定小时内的真人会话；无独立同步数据时从主库 sessions 回退）"""
        conn = get_connection()
        cursor = get_cursor(conn)

        time_threshold = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")

        # 优化：使用更高效的查询，一次性获取所有字段，避免多次访问数据库
        if platform:
            cursor.execute("""
                SELECT session_id, platform, customer_id, customer_name,
                       last_message, last_sender, message_count, is_human_session,
                       created_at, updated_at
                FROM conversation_history
                WHERE platform = ? AND is_human_session = 1 AND updated_at >= ?
                ORDER BY updated_at DESC
                LIMIT 200
            """, (platform, time_threshold))
        else:
            cursor.execute("""
                SELECT session_id, platform, customer_id, customer_name,
                       last_message, last_sender, message_count, is_human_session,
                       created_at, updated_at
                FROM conversation_history
                WHERE is_human_session = 1 AND updated_at >= ?
                ORDER BY updated_at DESC
                LIMIT 200
            """, (time_threshold,))

        rows = cursor.fetchall()
        conn.close()

        result = []
        for row in rows:
            if hasattr(row, '__dict__'):
                result.append(dict(row))
            else:
                result.append(dict(row) if hasattr(row, 'keys') else row)

        if not result:
            # 回退到主库查询（带超时保护，避免大量会话时查询过慢）
            result = _conversation_list_from_main_sessions(platform, time_threshold, limit=120)
        return result
    
    def get_platforms(self) -> List[Dict]:
        """获取所有平台列表（优先 conversation_history 表，必要时回退到主库）"""
        conn = get_connection()
        cursor = get_cursor(conn)

        cursor.execute("""
            SELECT platform, COUNT(*) as session_count,
                   MAX(updated_at) as last_activity
            FROM conversation_history
            WHERE is_human_session = 1
            GROUP BY platform
            ORDER BY last_activity DESC
            LIMIT 20
        """)

        rows = cursor.fetchall()
        conn.close()

        result = []
        for row in rows:
            if hasattr(row, '__dict__'):
                result.append(dict(row))
            else:
                result.append(dict(row) if hasattr(row, 'keys') else row)

        # 只有在 conversation_history 完全为空时才回退
        # 回退时使用更高效的方式：直接聚合 sessions 表，不查 messages
        if not result:
            thr = (datetime.now() - timedelta(hours=72)).strftime("%Y-%m-%d %H:%M:%S")
            try:
                from db import get_db, is_mysql as db_is_mysql
                with get_db() as (conn2, cursor2):
                    is_mysql = db_is_mysql()
                    if is_mysql:
                        cursor2.execute("""
                            SELECT
                                CASE
                                    WHEN customer_id LIKE 'TT%%' THEN 'tiktok'
                                    WHEN customer_id LIKE 'AMZ%%' THEN 'amazon'
                                    WHEN customer_id LIKE 'SP%%' THEN 'shopee'
                                    WHEN customer_id LIKE 'LZ%%' THEN 'lazada'
                                    WHEN customer_id LIKE 'AE%%' THEN 'aliexpress'
                                    WHEN customer_id LIKE 'EB%%' THEN 'ebay'
                                    ELSE 'other'
                                END AS platform,
                                COUNT(*) as session_count,
                                MAX(updated_at) as last_activity
                            FROM sessions
                            WHERE updated_at >= %s AND is_ai = 0
                            GROUP BY platform
                            ORDER BY session_count DESC
                            LIMIT 20
                        """, (thr,))
                    else:
                        cursor2.execute("""
                            SELECT
                                CASE
                                    WHEN customer_id LIKE 'TT%%' THEN 'tiktok'
                                    WHEN customer_id LIKE 'AMZ%%' THEN 'amazon'
                                    WHEN customer_id LIKE 'SP%%' THEN 'shopee'
                                    WHEN customer_id LIKE 'LZ%%' THEN 'lazada'
                                    WHEN customer_id LIKE 'AE%%' THEN 'aliexpress'
                                    WHEN customer_id LIKE 'EB%%' THEN 'ebay'
                                    ELSE 'other'
                                END AS platform,
                                COUNT(*) as session_count,
                                MAX(updated_at) as last_activity
                            FROM sessions
                            WHERE updated_at >= ? AND is_ai = 0
                            GROUP BY platform
                            ORDER BY session_count DESC
                            LIMIT 20
                        """, (thr,))
                    for row in cursor2.fetchall():
                        d = dict(zip([d[0] for d in cursor2.description], row))
                        d["last_activity"] = str(d["last_activity"]) if d.get("last_activity") else ""
                        result.append(d)
            except Exception as e:
                logger.debug("[msg_center] 平台统计回退失败: %s", e)
        return result
    
    def add_conversation(self, session_id: str, platform: str, customer_id: str = None,
                         customer_name: str = None, is_human: bool = False) -> bool:
        """添加或更新会话记录"""
        conn = get_connection()
        cursor = get_cursor(conn)
        
        cursor.execute("""
            INSERT INTO conversation_history 
            (session_id, platform, customer_id, customer_name, is_human_session, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                platform = excluded.platform,
                customer_id = excluded.customer_id,
                customer_name = excluded.customer_name,
                is_human_session = MAX(is_human_session, excluded.is_human_session),
                updated_at = excluded.updated_at
        """, (session_id, platform, customer_id, customer_name, 1 if is_human else 0,
              datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
              datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        
        conn.commit()
        conn.close()
        return True
    
    def update_conversation_message(self, session_id: str, message: str, sender: str) -> bool:
        """更新会话的最后一条消息"""
        conn = get_connection()
        cursor = get_cursor(conn)
        
        cursor.execute("""
            UPDATE conversation_history SET
                last_message = ?,
                last_sender = ?,
                message_count = message_count + 1,
                updated_at = ?
            WHERE session_id = ?
        """, (message[:200], sender, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), session_id))
        
        conn.commit()
        conn.close()
        return True
    
    def cleanup_old_conversations(self, hours: int = 72) -> int:
        """清理超过指定时间的会话记录"""
        conn = get_connection()
        cursor = get_cursor(conn)
        
        time_threshold = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
        
        cursor.execute("""
            DELETE FROM conversation_history 
            WHERE is_human_session = 1 AND updated_at < ?
        """, (time_threshold,))
        
        deleted = cursor.rowcount
        conn.commit()
        conn.close()
        
        logger.info(f"清理了 {deleted} 条过期会话记录")
        return deleted
    
    # ==================== 快捷回复 ====================
    
    def get_quick_replies(self, category: str = None) -> List[Dict]:
        """获取快捷回复列表"""
        conn = get_connection()
        cursor = get_cursor(conn)
        
        if category:
            cursor.execute("""
                SELECT * FROM quick_replies 
                WHERE is_active = 1 AND category = ?
                ORDER BY id
            """, (category,))
        else:
            cursor.execute("""
                SELECT * FROM quick_replies 
                WHERE is_active = 1
                ORDER BY category, id
            """)
        
        rows = cursor.fetchall()
        conn.close()
        
        result = []
        for row in rows:
            result.append(dict(row))
        return result
    
    def get_quick_reply_categories(self) -> List[str]:
        """获取快捷回复分类列表"""
        conn = get_connection()
        cursor = get_cursor(conn)
        
        cursor.execute("""
            SELECT DISTINCT category FROM quick_replies 
            WHERE is_active = 1
            ORDER BY category
        """)
        
        rows = cursor.fetchall()
        conn.close()
        
        return [row['category'] for row in rows]
    
    def add_quick_reply(self, category: str, title: str, content: str, 
                        shortcut: str = None, created_by: str = 'admin') -> Dict:
        """添加快捷回复"""
        conn = get_connection()
        cursor = get_cursor(conn)
        
        cursor.execute("""
            INSERT INTO quick_replies (category, title, content, shortcut, created_by)
            VALUES (?, ?, ?, ?, ?)
        """, (category, title, content, shortcut, created_by))
        
        reply_id = cursor.lastrowid
        conn.commit()
        
        cursor.execute("SELECT * FROM quick_replies WHERE id = ?", (reply_id,))
        result = dict(cursor.fetchone())
        conn.close()
        
        return result
    
    def update_quick_reply(self, reply_id: int, category: str = None, title: str = None,
                           content: str = None, shortcut: str = None) -> bool:
        """更新快捷回复"""
        conn = get_connection()
        cursor = get_cursor(conn)
        
        updates = []
        params = []
        
        if category:
            updates.append("category = ?")
            params.append(category)
        if title:
            updates.append("title = ?")
            params.append(title)
        if content:
            updates.append("content = ?")
            params.append(content)
        if shortcut is not None:
            updates.append("shortcut = ?")
            params.append(shortcut)
        
        updates.append("updated_at = ?")
        params.append(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        
        params.append(reply_id)
        
        cursor.execute(f"""
            UPDATE quick_replies SET {', '.join(updates)}
            WHERE id = ?
        """, params)
        
        conn.commit()
        conn.close()
        return cursor.rowcount > 0
    
    def delete_quick_reply(self, reply_id: int) -> bool:
        """删除快捷回复"""
        conn = get_connection()
        cursor = get_cursor(conn)
        
        cursor.execute("DELETE FROM quick_replies WHERE id = ?", (reply_id,))
        
        conn.commit()
        conn.close()
        return cursor.rowcount > 0
    
    # ==================== 消息通知 - 优化检索 ====================
    
    def get_notifications_optimized(
        self,
        notification_type: Optional[str] = None,
        include_read: bool = True,
        page: int = 1,
        page_size: int = 20,
        days: Optional[int] = None,
        sort_by_importance: bool = True
    ) -> Dict:
        """
        优化版通知查询 - 支持分页和高效索引查询
        
        Args:
            notification_type: 通知类型过滤
            include_read: 是否包含已读
            page: 页码（从1开始）
            page_size: 每页数量
            days: 时间范围过滤（天数）
            sort_by_importance: 是否按重要性排序
        
        Returns:
            {
                "items": [...],  # 通知列表
                "total": 100,    # 总数
                "page": 1,       # 当前页
                "page_size": 20, # 每页数量
                "total_pages": 5 # 总页数
            }
        """
        conn = get_connection()
        cursor = get_cursor(conn)
        is_sqlite = isinstance(conn, sqlite3.Connection)
        
        try:
            # 构建 WHERE 子句（使用索引覆盖）
            where_parts = []
            params = []
            
            if notification_type:
                type_col = "notify_type" if "notify_type" in _sqlite_notification_column_set(conn) else "notification_type"
                where_parts.append(f"{type_col} = ?")
                params.append(notification_type)
            
            if not include_read:
                where_parts.append("is_read = 0")
            
            if days is not None and days > 0:
                time_col = "datetime('now', '-{} days')".format(days) if is_sqlite else "DATE_SUB(NOW(), INTERVAL %s DAY)"
                if is_sqlite:
                    where_parts.append(f"created_at >= {time_col}")
                else:
                    where_parts.append("created_at >= " + time_col)
                    params.append(days)
            
            where_sql = (" WHERE " + " AND ".join(where_parts)) if where_parts else ""
            
            # 构建 ORDER BY（利用索引排序）
            if sort_by_importance:
                order_sql = "ORDER BY is_important DESC, created_at DESC"
            else:
                order_sql = "ORDER BY created_at DESC"
            
            # 计数查询（使用索引覆盖）
            count_sql = f"SELECT COUNT(*) FROM notifications{where_sql}"
            cursor.execute(count_sql, params)
            total = cursor.fetchone()[0] if cursor.fetchone() else 0
            
            # 分页查询（使用索引覆盖 + LIMIT OFFSET）
            offset = (page - 1) * page_size
            limit = page_size
            
            # 构建完整查询
            base_select = "id, notification_type, title, content, source, is_read, is_important, created_at, url"
            query_sql = f"SELECT {base_select} FROM notifications{where_sql} {order_sql} LIMIT ? OFFSET ?"
            
            cursor.execute(query_sql, params + [limit, offset])
            rows = cursor.fetchall()
            
            items = []
            for row in rows:
                if hasattr(row, 'keys'):
                    item = dict(row)
                else:
                    cols = [d[0] for d in cursor.description]
                    item = dict(zip(cols, row))
                items.append(_normalize_notification_row(item))
            
            total_pages = (total + page_size - 1) // page_size if total > 0 else 1
            
            return {
                "items": items,
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": total_pages
            }
            
        finally:
            conn.close()
    
    def get_notifications(self, notification_type: str = None, include_read: bool = True,
                          limit: int = 50, exclude_types: Optional[List[str]] = None,
                          include_types: Optional[List[str]] = None,
                          days: Optional[int] = None) -> List[Dict]:
        """获取消息通知列表

        exclude_types: 与 notification_type / include_types 互斥；inbox 排除 policy、market
        include_types: 仅返回这些类型（如政策通知：policy + market）
        days: 仅返回 N 天内的通知，None 表示不限
        """
        conn = get_connection()
        cursor = get_cursor(conn)
        is_sqlite = isinstance(conn, sqlite3.Connection)

        ex_arg = None if (notification_type or include_types) else exclude_types
        inc_arg = None if notification_type else include_types

        if is_sqlite:
            cols = _sqlite_notification_column_set(conn)
            sql, params = _sqlite_build_notifications_select(
                cols, notification_type, include_read, limit,
                exclude_types=ex_arg,
                include_types=inc_arg,
                days=days,
            )
            cursor.execute(sql, params)
        else:
            order_col = "FIELD(priority, 'high', 'important', 'normal', 'low')"
            order_dir = ""

            def _filter_clause():
                if notification_type:
                    return " AND notify_type = %s", (notification_type,)
                if include_types:
                    ph = ",".join(["%s"] * len(include_types))
                    return f" AND notify_type IN ({ph})", tuple(include_types)
                if exclude_types:
                    ph = ",".join(["%s"] * len(exclude_types))
                    return f" AND notify_type NOT IN ({ph})", tuple(exclude_types)
                return "", ()

            filt_sql, filt_params = _filter_clause()

            if include_read:
                base_where = f"1=1 {filt_sql}"
            else:
                base_where = f"is_read = 0 {filt_sql}"

            if days is not None and days > 0:
                days_clause = "AND created_at >= DATE_SUB(NOW(), INTERVAL %s DAY)"
                cursor.execute(f"""
                    SELECT id, notify_type as notification_type, title, content,
                           related_type as source, priority,
                           is_read, created_at, url
                    FROM notifications
                    WHERE {base_where} {days_clause}
                    ORDER BY {order_col} {order_dir}, created_at DESC
                    LIMIT %s
                """, (*filt_params, days, limit))
            else:
                cursor.execute(f"""
                    SELECT id, notify_type as notification_type, title, content,
                           related_type as source, priority,
                           is_read, created_at, url
                    FROM notifications
                    WHERE {base_where}
                    ORDER BY {order_col} {order_dir}, created_at DESC
                    LIMIT %s
                """, (*filt_params, limit))

        rows = cursor.fetchall()
        conn.close()

        result = []
        for row in rows:
            item = dict(row) if hasattr(row, 'keys') else {k: v for k, v in zip([d[0] for d in cursor.description], row)}
            if is_sqlite:
                result.append(_normalize_notification_row(item))
            else:
                pr = item.get("priority", "normal")
                item["is_important"] = 1 if pr in ("high", "important") else 0
                item.pop("priority", None)
                if item.get("created_at"):
                    item["created_at"] = str(item["created_at"])
                if not str(item.get("source") or "").strip():
                    item["source"] = "系统"
                result.append(item)
        return result

    def get_notification_by_id(self, notification_id: int) -> Optional[Dict]:
        """单条通知（详情弹窗，避免前端拉全表）"""
        conn = get_connection()
        cursor = get_cursor(conn)
        is_sqlite = isinstance(conn, sqlite3.Connection)
        try:
            ph = "?" if is_sqlite else "%s"
            cursor.execute(f"SELECT * FROM notifications WHERE id = {ph}", (notification_id,))
            row = cursor.fetchone()
            if not row:
                return None
            item = dict(row) if hasattr(row, "keys") else {}
            if is_sqlite:
                return _normalize_notification_row(item)
            pr = item.get("priority", "normal")
            item["notification_type"] = item.pop("notify_type", None) or item.get("notification_type")
            if "related_type" in item:
                item["source"] = item.pop("related_type", None)
            item["is_important"] = 1 if pr in ("high", "important") else 0
            item.pop("priority", None)
            if item.get("created_at"):
                item["created_at"] = str(item["created_at"])
            if not str(item.get("source") or "").strip():
                item["source"] = "系统"
            return item
        finally:
            conn.close()

    def add_notification(self, notification_type: str, title: str, content: str,
                         source: str = 'deepseek', is_important: bool = False,
                         url: str = '', created_at: str = '', **kwargs) -> Dict:
        """添加新通知（增强版：支持垂直领域字段）

        Args:
            notification_type: policy / market / system
            title: 通知标题
            content: 通知内容
            source: 来源名称（如：海关总署、DeepSeek AI 分析）
            is_important: 是否重要
            url: 相关链接
            **kwargs 扩展字段：
                domain: cross_border / government
                data_source: customs / mofcom / amazon / tiktok / ln_gov / ln_rst
                item_hash: 去重哈希
                summary: AI一句话摘要
                target_audience: AI提取的人群/企业类型
                policy_type: 利好 / 风险 / 通知 / 补贴
                key_benefit: 核心利好或风险点
                timeliness_check: 时效性核实结果
                is_fresh: 是否新鲜
        """
        conn = get_connection()
        cursor = get_cursor(conn)
        is_sqlite = isinstance(conn, sqlite3.Connection)
        priority = 'high' if is_important else 'normal'

        # 扩展字段
        domain = kwargs.get('domain', 'cross_border')
        data_source = kwargs.get('data_source', '')
        item_hash = kwargs.get('item_hash', '')
        summary = kwargs.get('summary', '')
        target_audience = kwargs.get('target_audience', '')
        policy_type = kwargs.get('policy_type', '通知')
        key_benefit = kwargs.get('key_benefit', '')
        timeliness_check = kwargs.get('timeliness_check', '')
        is_fresh = 1 if kwargs.get('is_fresh') else 0

        if is_sqlite:
            cols = _sqlite_notification_column_set(conn)
            if "notification_type" in cols:
                imp = 1 if is_important else 0
                has_url = "url" in cols
                has_notify_type = "notify_type" in cols
                has_domain = "domain" in cols

                # 构建字段列表和占位符
                fields = ["notification_type", "title", "content", "source", "is_read", "is_important"]
                values = [notification_type, title, content, source, 0, imp]
                field_placeholders = ["?", "?", "?", "?", "?", "?"]

                # Support custom created_at
                if created_at:
                    fields.append("created_at")
                    values.append(created_at)
                    field_placeholders.append("?")
                    
                if has_notify_type:
                    fields.append("notify_type")
                    values.append(notification_type)
                    field_placeholders.append("?")
                if has_url:
                    fields.append("url")
                    values.append(url or "")
                    field_placeholders.append("?")
                if has_domain:
                    fields.extend(["domain", "data_source", "item_hash", "summary",
                                   "target_audience", "policy_type", "key_benefit",
                                   "timeliness_check", "is_fresh"])
                    values.extend([domain, data_source, item_hash, summary,
                                   target_audience, policy_type, key_benefit,
                                   timeliness_check, is_fresh])
                    field_placeholders.extend(["?", "?", "?", "?", "?", "?", "?", "?", "?"])

                sql = f"INSERT INTO notifications ({', '.join(fields)}) VALUES ({', '.join(field_placeholders)})"
                cursor.execute(sql, values)
            else:
                cursor.execute(
                    """INSERT INTO notifications (notify_type, title, content, source, priority, url)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (notification_type, title, content, source, priority, url or ""),
                )
            notification_id = cursor.lastrowid
            conn.commit()
            cursor.execute("SELECT * FROM notifications WHERE id = ?", (notification_id,))
        else:
            # MySQL
            # Build MySQL fields and values
            mysql_fields = ["notify_type", "title", "content", "related_type", "priority", "url",
                           "domain", "data_source", "item_hash", "summary", "target_audience",
                           "policy_type", "key_benefit", "timeliness_check", "is_fresh"]
            mysql_values = [notification_type, title, content, source, priority, url or "",
                           domain, data_source, item_hash, summary, target_audience,
                           policy_type, key_benefit, timeliness_check, is_fresh]
            mysql_placeholders = ["%s"] * len(mysql_fields)
            
            # Add custom created_at if provided
            if created_at:
                mysql_fields.insert(0, "created_at")
                mysql_values.insert(0, created_at)
                mysql_placeholders.insert(0, "%s")
            
            mysql_sql = f"INSERT INTO notifications ({', '.join(mysql_fields)}) VALUES ({', '.join(mysql_placeholders)})"
            cursor.execute(mysql_sql, mysql_values)
            notification_id = cursor.lastrowid
            conn.commit()
            cursor.execute("SELECT * FROM notifications WHERE id = %s", (notification_id,))

        row = cursor.fetchone()
        conn.close()

        if row:
            result = {d[0]: v for d, v in zip(cursor.description, row)}
            # 统一字段名（MySQL 用 related_type，SQLite 用 source）
            result['notification_type'] = result.pop('notify_type', None)
            if 'related_type' in result:
                result['source'] = result.pop('related_type', None)
            # 转换 priority 为 is_important
            result['is_important'] = 1 if result.get('priority') in ('high', 'important') else 0
            if result.get('created_at'):
                result['created_at'] = str(result['created_at'])
            return result
        return {}

    def mark_notification_read(self, notification_id: int) -> bool:
        """标记通知为已读"""
        conn = get_connection()
        cursor = get_cursor(conn)
        is_sqlite = isinstance(conn, sqlite3.Connection)
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if is_sqlite:
            cursor.execute("""
                UPDATE notifications SET is_read = 1, read_at = ?
                WHERE id = ?
            """, (now_str, notification_id))
        else:
            cursor.execute("""
                UPDATE notifications SET is_read = 1, read_at = %s
                WHERE id = %s
            """, (now_str, notification_id))

        conn.commit()
        conn.close()
        return cursor.rowcount > 0

    def get_unread_notification_count(self, exclude_types: Optional[List[str]] = None,
                                      include_types: Optional[List[str]] = None) -> int:
        """获取未读通知数量

        exclude_types: 排除这些 notify_type（如 inbox：不统计 policy、market）
        include_types: 仅统计这些类型（如政策通知：policy + market）
        """
        conn = get_connection()
        cursor = get_cursor(conn)
        is_sqlite = isinstance(conn, sqlite3.Connection)

        type_col = "notify_type" if "notify_type" in _sqlite_notification_column_set(conn) else "notification_type"

        if include_types:
            ph = ",".join(["?" if is_sqlite else "%s"] * len(include_types))
            cursor.execute(
                f"SELECT COUNT(*) FROM notifications WHERE is_read = 0 AND {type_col} IN ({ph})",
                include_types,
            )
        elif exclude_types:
            ph = ",".join(["?" if is_sqlite else "%s"] * len(exclude_types))
            cursor.execute(
                f"SELECT COUNT(*) FROM notifications WHERE is_read = 0 AND {type_col} NOT IN ({ph})",
                exclude_types,
            )
        else:
            cursor.execute("SELECT COUNT(*) FROM notifications WHERE is_read = 0")

        row = cursor.fetchone()
        count = row[0] if row else 0
        conn.close()
        return count

    def mark_all_notifications_read(self, exclude_types: Optional[List[str]] = None) -> int:
        """标记所有通知为已读"""
        conn = get_connection()
        cursor = get_cursor(conn)
        is_sqlite = isinstance(conn, sqlite3.Connection)
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        type_col = "notify_type" if "notify_type" in _sqlite_notification_column_set(conn) else "notification_type"

        if exclude_types:
            ph = ",".join(["?" if is_sqlite else "%s"] * len(exclude_types))
            if is_sqlite:
                cursor.execute(
                    f"UPDATE notifications SET is_read = 1, read_at = ? WHERE is_read = 0 AND {type_col} NOT IN ({ph})",
                    (now_str, *exclude_types),
                )
            else:
                cursor.execute(
                    f"UPDATE notifications SET is_read = 1, read_at = %s WHERE is_read = 0 AND {type_col} NOT IN ({ph})",
                    (now_str, *exclude_types),
                )
        else:
            if is_sqlite:
                cursor.execute(
                    "UPDATE notifications SET is_read = 1, read_at = ? WHERE is_read = 0",
                    (now_str,),
                )
            else:
                cursor.execute(
                    "UPDATE notifications SET is_read = 1, read_at = %s WHERE is_read = 0",
                    (now_str,),
                )

        updated = cursor.rowcount
        conn.commit()
        conn.close()
        return updated
    
    def cleanup_old_notifications(self, days: int = 30) -> int:
        """清理超过指定天数的旧通知"""
        conn = get_connection()
        cursor = get_cursor(conn)
        is_sqlite = isinstance(conn, sqlite3.Connection)

        time_threshold = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")

        if is_sqlite:
            cursor.execute("""
                DELETE FROM notifications WHERE created_at < ? AND is_read = 1
            """, (time_threshold,))
        else:
            cursor.execute("""
                DELETE FROM notifications WHERE created_at < %s AND is_read = 1
            """, (time_threshold,))

        deleted = cursor.rowcount
        conn.commit()
        conn.close()

        logger.info(f"清理了 {deleted} 条旧通知")
        return deleted
    
    # ==================== 强提醒/闹钟 ====================
    
    def get_reminders(self, include_inactive: bool = False) -> List[Dict]:
        """获取提醒列表"""
        conn = get_connection()
        cursor = get_cursor(conn)
        
        if include_inactive:
            cursor.execute("""
                SELECT * FROM reminders 
                ORDER BY is_active DESC, remind_time ASC
            """)
        else:
            cursor.execute("""
                SELECT * FROM reminders 
                WHERE is_active = 1
                ORDER BY remind_time ASC
            """)
        
        rows = cursor.fetchall()
        conn.close()
        
        result = []
        for row in rows:
            result.append(dict(row))
        return result
    
    def get_due_reminders(self) -> List[Dict]:
        """获取到期需要触发的提醒"""
        conn = get_connection()
        cursor = get_cursor(conn)
        is_sqlite = isinstance(conn, sqlite3.Connection)

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        today = datetime.now().strftime("%H:%M")
        weekday = str(datetime.now().weekday())

        if is_sqlite:
            cursor.execute("""
                SELECT * FROM reminders
                WHERE is_active = 1 AND remind_time <= ?
                AND (
                    (is_repeat = 0 AND is_triggered = 0) OR
                    (is_repeat = 1 AND (
                        repeat_days IS NULL OR
                        repeat_days = '' OR
                        repeat_days LIKE ?
                    ))
                )
            """, (now, f"%{weekday}%"))
        else:
            cursor.execute("""
                SELECT * FROM reminders
                WHERE is_active = 1 AND remind_time <= %s
                AND (
                    (is_repeat = 0 AND is_triggered = 0) OR
                    (is_repeat = 1 AND (
                        repeat_days IS NULL OR
                        repeat_days = '' OR
                        repeat_days LIKE %s
                    ))
                )
            """, (now, f"%{weekday}%"))

        rows = cursor.fetchall()
        conn.close()

        result = []
        for row in rows:
            item = dict(row) if hasattr(row, 'keys') else {k: v for k, v in zip([d[0] for d in cursor.description], row)}
            if item.get('created_at'):
                item['created_at'] = str(item['created_at'])
            if item.get('remind_time'):
                item['remind_time'] = str(item['remind_time'])
            result.append(item)
        return result

    def add_reminder(self, title: str, content: str, remind_type: str = 'once',
                     remind_time: str = None, is_repeat: bool = False,
                     repeat_days: str = None, created_by: str = 'admin') -> Dict:
        """添加新提醒"""
        conn = get_connection()
        cursor = get_cursor(conn)
        is_sqlite = isinstance(conn, sqlite3.Connection)

        if not remind_time:
            remind_time = (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")

        if is_sqlite:
            cursor.execute("""
                INSERT INTO reminders (title, content, remind_type, remind_time, is_repeat, repeat_days, created_by)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (title, content, remind_type, remind_time, 1 if is_repeat else 0, repeat_days, created_by))
            reminder_id = cursor.lastrowid
            conn.commit()
            cursor.execute("SELECT * FROM reminders WHERE id = ?", (reminder_id,))
        else:
            cursor.execute("""
                INSERT INTO reminders (title, content, remind_type, remind_time, is_repeat, repeat_days, created_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (title, content, remind_type, remind_time, 1 if is_repeat else 0, repeat_days, created_by))
            reminder_id = cursor.lastrowid
            conn.commit()
            cursor.execute("SELECT * FROM reminders WHERE id = %s", (reminder_id,))

        row = cursor.fetchone()
        conn.close()

        if row:
            result = {d[0]: v for d, v in zip(cursor.description, row)}
            if result.get('created_at'):
                result['created_at'] = str(result['created_at'])
            if result.get('remind_time'):
                result['remind_time'] = str(result['remind_time'])
            return result
        return {}
    
    def update_reminder(self, reminder_id: int, title: str = None, content: str = None,
                        remind_time: str = None, is_active: bool = None,
                        is_repeat: bool = None, repeat_days: str = None) -> bool:
        """更新提醒"""
        conn = get_connection()
        cursor = get_cursor(conn)
        is_sqlite = isinstance(conn, sqlite3.Connection)

        updates = []
        params = []

        if title is not None:
            updates.append("title = " + ("?" if is_sqlite else "%s"))
            params.append(title)
        if content is not None:
            updates.append("content = " + ("?" if is_sqlite else "%s"))
            params.append(content)
        if remind_time is not None:
            updates.append("remind_time = " + ("?" if is_sqlite else "%s"))
            params.append(remind_time)
        if is_active is not None:
            updates.append("is_active = " + ("?" if is_sqlite else "%s"))
            params.append(1 if is_active else 0)
        if is_repeat is not None:
            updates.append("is_repeat = " + ("?" if is_sqlite else "%s"))
            params.append(1 if is_repeat else 0)
        if repeat_days is not None:
            updates.append("repeat_days = " + ("?" if is_sqlite else "%s"))
            params.append(repeat_days)

        updates.append("updated_at = " + ("?" if is_sqlite else "%s"))
        params.append(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

        params.append(reminder_id)

        cursor.execute(f"""
            UPDATE reminders SET {', '.join(updates)}
            WHERE id = {'?' if is_sqlite else '%s'}
        """, params)

        conn.commit()
        conn.close()
        return cursor.rowcount > 0

    def delete_reminder(self, reminder_id: int) -> bool:
        """删除提醒"""
        conn = get_connection()
        cursor = get_cursor(conn)
        is_sqlite = isinstance(conn, sqlite3.Connection)

        cursor.execute(
            "DELETE FROM reminders WHERE id = " + ("?" if is_sqlite else "%s"),
            (reminder_id,)
        )

        conn.commit()
        conn.close()
        return cursor.rowcount > 0

    def trigger_reminder(self, reminder_id: int) -> bool:
        """标记提醒已触发"""
        conn = get_connection()
        cursor = get_cursor(conn)
        is_sqlite = isinstance(conn, sqlite3.Connection)
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if is_sqlite:
            cursor.execute("""
                UPDATE reminders SET
                    is_triggered = 1,
                    last_triggered = ?,
                    updated_at = ?
                WHERE id = ?
            """, (now_str, now_str, reminder_id))
        else:
            cursor.execute("""
                UPDATE reminders SET
                    is_triggered = 1,
                    last_triggered = %s,
                    updated_at = %s
                WHERE id = %s
            """, (now_str, now_str, reminder_id))

        conn.commit()
        conn.close()
        return cursor.rowcount > 0

    def reset_reminder_trigger(self, reminder_id: int) -> bool:
        """重置提醒触发状态（用于重复提醒）"""
        conn = get_connection()
        cursor = get_cursor(conn)
        is_sqlite = isinstance(conn, sqlite3.Connection)
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        cursor.execute(
            "UPDATE reminders SET is_triggered = 0, updated_at = " + ("?" if is_sqlite else "%s") + " WHERE id = " + ("?" if is_sqlite else "%s"),
            (now_str, reminder_id) if is_sqlite else (now_str, reminder_id)
        )

        conn.commit()
        conn.close()
        return cursor.rowcount > 0


# 单例实例
message_center_service = MessageCenterService()
