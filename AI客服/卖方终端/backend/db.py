# -*- coding: utf-8 -*-
"""
数据库模型 - MySQL + SQLite 双引擎
优先使用 MySQL 连接池，SQLite 作为回退

配置说明（读取顺序高→低）：
  1. MYSQL_PASSWORD / MYSQL_DATABASE 等环境变量（生产推荐）
  2. SHOP_MYSQL_PASSWORD 等别名（兼容旧命名）
  3. USE_SQLITE_FALLBACK=true 强制回退到 SQLite

所有 CRUD 函数使用统一 mysql_db.py 作为底层连接池。
保持原有函数签名完全不变。
"""
import json
import logging
import uuid as _uuid
from datetime import datetime
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

# 导入统一连接池
from mysql_db import (
    get_db,
    get_raw_cursor,
    is_mysql,
    mysql_now,
)

_use_mysql = is_mysql


def _row_to_dict(row, columns: List[str]) -> Optional[Dict]:
    if row is None:
        return None
    if hasattr(row, 'keys'):
        return dict(row)
    if columns:
        return dict(zip(columns, row))
    return dict(enumerate(row)) if hasattr(row, '__iter__') else None


def _adapt_sql(sql: str) -> str:
    """将 SQLite SQL 转换为 MySQL 兼容 SQL"""
    if not _use_mysql():
        return sql
    import re
    sql = sql.replace('INSERT OR IGNORE', 'INSERT IGNORE')
    # datetime('now', '-7 days') → DATE_SUB(NOW(), INTERVAL 7 DAY)
    m = re.search(r"datetime\(\s*'now'\s*,\s*'-\s*(\d+)\s*days?\s*\)", sql)
    if m:
        days = m.group(1)
        sql = re.sub(r"datetime\(\s*'now'\s*,\s*'-?\s*\d+\s*days?\s*\)",
                     f"DATE_SUB(NOW(), INTERVAL {days} DAY)", sql)
    sql = re.sub(r"datetime\(\s*'now'\s*\)", "NOW()", sql)
    return sql


def _col(cursor) -> List[str]:
    return [d[0] for d in cursor.description] if cursor.description else []


def _q(sql: str, params=()) -> str:
    """自动适配 SQL（MySQL %s / SQLite ?）"""
    if _use_mysql():
        # 简单替换：? → %s
        sql = sql.replace('?', '%s')
    return sql


# ============== 兼容层 ==============

def get_db_path():
    from mysql_db import _get_sqlite_path
    return _get_sqlite_path()


def init_db():
    """初始化数据库表（自动选择 MySQL / SQLite）
    
    启动顺序：
    1. 初始化 MySQL 连接池（失败则自动回退 SQLite）
    2. 如使用 MySQL：执行建表 SQL
    3. 如使用 SQLite：执行 SQLite 建表
    4. 初始化默认卖家账号
    """
    from init_mysql_schema import init_sqlite_schema, init_mysql_schema
    # 1. 确保 MySQL 连接池已初始化
    from mysql_db import _init_mysql_pool, is_mysql as _is_mysql
    _init_mysql_pool()

    # 2. 根据引擎执行建表
    if _is_mysql():
        logger.info("[db] MySQL 模式，正在初始化表结构...")
        init_mysql_schema()
    else:
        logger.info("[db] SQLite 回退模式，正在初始化表结构...")
        init_sqlite_schema()
    # 3. 初始化默认卖家账号（由 main.py 调用 init_default_seller()）


# ============== 客户操作 ==========

def create_customer(customer_id: str, phone: str = None, name: str = None, region: str = None, level: str = '普通') -> int:
    with get_db() as (conn, cursor):
        sql = _q("""
            INSERT OR IGNORE INTO customers (customer_id, phone, name, region, level)
            VALUES (?, ?, ?, ?, ?)
        """, (customer_id, phone, name, region, level))
        cursor.execute(sql, (customer_id, phone, name, region, level))
        conn.commit()
        return cursor.lastrowid


def get_customer(customer_id: str) -> Optional[Dict]:
    with get_db() as (conn, cursor):
        cursor.execute(_q("SELECT * FROM customers WHERE customer_id = ?"), (customer_id,))
        return _row_to_dict(cursor.fetchone(), _col(cursor))


def find_customer_by_phone(phone: str) -> Optional[Dict]:
    with get_db() as (conn, cursor):
        cursor.execute(_q("SELECT * FROM customers WHERE phone = ? LIMIT 1"), (phone,))
        return _row_to_dict(cursor.fetchone(), _col(cursor))


def update_customer(customer_id: str, **kwargs):
    if not kwargs:
        return
    with get_db() as (conn, cursor):
        fields = ", ".join([f"{k} = ?" for k in kwargs.keys()])
        values = list(kwargs.values()) + [customer_id]
        if _use_mysql():
            cursor.execute(f"UPDATE customers SET {fields}, updated_at = NOW() WHERE customer_id = %s", values)
        else:
            cursor.execute(f"UPDATE customers SET {fields}, updated_at = CURRENT_TIMESTAMP WHERE customer_id = ?", values)
        conn.commit()


# ========== 会话操作 ==========

def create_session(session_id: str, customer_id: str = None, is_ai: bool = True) -> int:
    with get_db() as (conn, cursor):
        cursor.execute(_q("""
            INSERT INTO sessions (session_id, customer_id, is_ai, status)
            VALUES (?, ?, ?, 'active')
        """, (session_id, customer_id, 1 if is_ai else 0)), (session_id, customer_id, 1 if is_ai else 0))
        conn.commit()
        return cursor.lastrowid


def get_session(session_id: str) -> Optional[Dict]:
    with get_db() as (conn, cursor):
        cursor.execute(_q("SELECT * FROM sessions WHERE session_id = ?"), (session_id,))
        return _row_to_dict(cursor.fetchone(), _col(cursor))


def get_customer_active_session(customer_id: str) -> Optional[Dict]:
    with get_db() as (conn, cursor):
        if _use_mysql():
            cursor.execute("""
                SELECT * FROM sessions
                WHERE customer_id = %s AND status IN ('active', 'waiting')
                  AND updated_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)
                ORDER BY updated_at DESC
                LIMIT 1
            """, (customer_id,))
        else:
            cursor.execute("""
                SELECT * FROM sessions
                WHERE customer_id = ? AND status IN ('active', 'waiting')
                  AND updated_at >= datetime('now', '-7 days')
                ORDER BY updated_at DESC
                LIMIT 1
            """, (customer_id,))
        return _row_to_dict(cursor.fetchone(), _col(cursor))


def update_session(session_id: str, **kwargs):
    if not kwargs:
        return
    with get_db() as (conn, cursor):
        fields = ", ".join([f"{k} = ?" for k in kwargs.keys()])
        values = list(kwargs.values()) + [session_id]
        if _use_mysql():
            cursor.execute(f"UPDATE sessions SET {fields}, updated_at = NOW() WHERE session_id = %s", values)
        else:
            cursor.execute(f"UPDATE sessions SET {fields}, updated_at = CURRENT_TIMESTAMP WHERE session_id = ?", values)
        conn.commit()


def get_active_sessions() -> List[Dict]:
    with get_db() as (conn, cursor):
        cursor.execute("""
            SELECT s.*, c.name as customer_name, c.level as customer_level, c.phone
            FROM sessions s
            LEFT JOIN customers c ON s.customer_id = c.customer_id
            WHERE s.status = 'active' AND s.is_ai = 1
            ORDER BY s.updated_at DESC
        """)
        cols = _col(cursor)
        return [_row_to_dict(row, cols) for row in cursor.fetchall()]


def get_human_sessions(hours: int = 72) -> List[Dict]:
    """获取最近N小时的人工会话（供消息中心同步使用）"""
    with get_db() as (conn, cursor):
        if _use_mysql():
            cursor.execute("""
                SELECT s.session_id, s.customer_id, s.language, s.created_at, s.updated_at, s.status,
                       c.name as customer_name
                FROM sessions s
                LEFT JOIN customers c ON s.customer_id = c.customer_id
                WHERE s.is_ai = 0 AND s.updated_at >= DATE_SUB(NOW(), INTERVAL %s HOUR)
                ORDER BY s.updated_at DESC
            """, (hours,))
        else:
            cursor.execute("""
                SELECT s.session_id, s.customer_id, s.language, s.created_at, s.updated_at, s.status,
                       c.name as customer_name
                FROM sessions s
                LEFT JOIN customers c ON s.customer_id = c.customer_id
                WHERE s.is_ai = 0 AND s.updated_at >= datetime('now', '-{h} hours')
                ORDER BY s.updated_at DESC
            """.format(h=hours))
        cols = _col(cursor)
        return [_row_to_dict(row, cols) for row in cursor.fetchall()]


def get_customers_for_seller() -> List[Dict]:
    with get_db() as (conn, cursor):
        cursor.execute("""
            SELECT s.session_id, s.customer_id, s.status, s.is_ai, s.language, s.updated_at,
                   c.name as customer_name, c.level as customer_level, c.phone,
                   (SELECT content FROM messages WHERE session_id = s.session_id ORDER BY id DESC LIMIT 1) as last_message
            FROM sessions s
            LEFT JOIN customers c ON s.customer_id = c.customer_id
            WHERE s.status IN ('active', 'waiting') AND s.is_ai = 0
            ORDER BY s.updated_at DESC
        """)
        cols = _col(cursor)
        return [_row_to_dict(row, cols) for row in cursor.fetchall()]


# ========== 消息操作 ==========

def add_message(session_id: str, role: str, content: str) -> int:
    with get_db() as (conn, cursor):
        sql = _q("""
            INSERT INTO messages (session_id, role, content)
            VALUES (?, ?, ?)
        """)
        cursor.execute(sql, (session_id, role, content))
        if _use_mysql():
            cursor.execute("UPDATE sessions SET updated_at = NOW() WHERE session_id = %s", (session_id,))
        else:
            cursor.execute("UPDATE sessions SET updated_at = CURRENT_TIMESTAMP WHERE session_id = ?", (session_id,))
        conn.commit()
        return cursor.lastrowid


def get_messages(session_id: str) -> List[Dict]:
    with get_db() as (conn, cursor):
        cursor.execute(_q("SELECT * FROM messages WHERE session_id = ? ORDER BY created_at ASC"), (session_id,))
        cols = _col(cursor)
        return [_row_to_dict(row, cols) for row in cursor.fetchall()]


def clear_session_messages(session_id: str):
    with get_db() as (conn, cursor):
        cursor.execute(_q("DELETE FROM messages WHERE session_id = ?"), (session_id,))
        conn.commit()


def close_active_sessions(customer_id: str):
    with get_db() as (conn, cursor):
        cursor.execute(_q("""
            UPDATE sessions SET status = 'closed'
            WHERE customer_id = ? AND status IN ('active', 'waiting')
        """, (customer_id,)), (customer_id,))
        conn.commit()


def get_unread_count(session_id: str) -> int:
    with get_db() as (conn, cursor):
        if _use_mysql():
            cursor.execute("""
                SELECT COUNT(*) FROM messages
                WHERE session_id = %s AND role = 'user' AND created_at > (
                    SELECT updated_at FROM sessions WHERE session_id = %s
                )
            """, (session_id, session_id))
        else:
            cursor.execute("""
                SELECT COUNT(*) FROM messages
                WHERE session_id = ? AND role = 'user' AND created_at > (
                    SELECT updated_at FROM sessions WHERE session_id = ?
                )
            """, (session_id, session_id))
        return cursor.fetchone()[0]


# ========== 人工客服设置 ==========

def get_human_settings() -> Dict[str, Any]:
    with get_db() as (conn, cursor):
        cursor.execute(_q("SELECT quick_phrases, timeout_seconds, timeout_presets FROM human_settings WHERE id = 1"))
        row = cursor.fetchone()
        if not row:
            return {"quick_phrases": [], "timeout_seconds": 60, "timeout_presets": []}
        cols = _col(cursor)
        row = _row_to_dict(row, cols)
        qp = row["quick_phrases"] or "[]"
        tp = row["timeout_presets"] or "[]"
        try:
            quick_phrases = json.loads(qp)
            if not isinstance(quick_phrases, list):
                quick_phrases = []
            quick_phrases = quick_phrases[:20]
        except Exception:
            quick_phrases = []
        try:
            timeout_presets = json.loads(tp)
            if not isinstance(timeout_presets, list):
                timeout_presets = []
            timeout_presets = timeout_presets[:10]
        except Exception:
            timeout_presets = []
        return {
            "quick_phrases": quick_phrases,
            "timeout_seconds": int(row["timeout_seconds"]) if row["timeout_seconds"] is not None else 60,
            "timeout_presets": timeout_presets,
        }


def save_human_settings(quick_phrases: List[str] = None, timeout_seconds: int = None, timeout_presets: List[str] = None):
    with get_db() as (conn, cursor):
        current = get_human_settings()
        if quick_phrases is not None:
            current["quick_phrases"] = [str(x).strip() for x in quick_phrases if str(x).strip()][:20]
        if timeout_seconds is not None:
            current["timeout_seconds"] = max(10, min(3600, int(timeout_seconds)))
        if timeout_presets is not None:
            current["timeout_presets"] = [str(x).strip() for x in timeout_presets if str(x).strip()][:10]
        cursor.execute(_q("""
            UPDATE human_settings SET quick_phrases = ?, timeout_seconds = ?, timeout_presets = ? WHERE id = 1
        """, (json.dumps(current["quick_phrases"], ensure_ascii=False),
               current["timeout_seconds"],
               json.dumps(current["timeout_presets"], ensure_ascii=False))),
            (json.dumps(current["quick_phrases"], ensure_ascii=False),
             current["timeout_seconds"],
             json.dumps(current["timeout_presets"], ensure_ascii=False)))
        conn.commit()


# ========== 卖家操作 ==========

def create_seller(username: str, password_hash: str, name: str = None, role: str = 'agent') -> int:
    with get_db() as (conn, cursor):
        cursor.execute(_q("""
            INSERT INTO sellers (username, password_hash, name, role)
            VALUES (?, ?, ?, ?)
        """, (username, password_hash, name, role)), (username, password_hash, name, role))
        conn.commit()
        return cursor.lastrowid


def get_seller(username: str) -> Optional[Dict]:
    with get_db() as (conn, cursor):
        cursor.execute(_q("SELECT * FROM sellers WHERE username = ?"), (username,))
        return _row_to_dict(cursor.fetchone(), _col(cursor))


def update_seller_status(username: str, is_online: bool):
    with get_db() as (conn, cursor):
        if _use_mysql():
            cursor.execute("UPDATE sellers SET is_online = %s, last_login = NOW() WHERE username = %s",
                          (1 if is_online else 0, username))
        else:
            cursor.execute("UPDATE sellers SET is_online = ?, last_login = CURRENT_TIMESTAMP WHERE username = ?",
                          (1 if is_online else 0, username))
        conn.commit()


def get_online_sellers() -> List[Dict]:
    with get_db() as (conn, cursor):
        cursor.execute(_q("SELECT * FROM sellers WHERE is_online = 1"))
        cols = _col(cursor)
        return [_row_to_dict(row, cols) for row in cursor.fetchall()]


def _hash_password(password: str) -> str:
    import hashlib
    return hashlib.sha256(("gold_customer_salt_" + password).encode()).hexdigest()


def verify_seller_password(password: str, password_hash: str) -> bool:
    from config import _hash_password as config_hash
    return config_hash(password) == password_hash


def init_default_seller():
    with get_db() as (conn, cursor):
        cursor.execute(_q("SELECT COUNT(*) FROM sellers"))
        if cursor.fetchone()[0] == 0:
            password_hash = _hash_password("admin123")
            cursor.execute(_q("""
                INSERT INTO sellers (username, password_hash, name, role, must_change_password)
                VALUES (?, ?, ?, ?, 1)
            """, ("admin", password_hash, "管理员", "admin")), ("admin", password_hash, "管理员", "admin"))
            conn.commit()
            logger.info("默认卖家账号已创建: admin / admin123  (必须修改密码)")


def set_password_changed(username: str):
    with get_db() as (conn, cursor):
        cursor.execute(_q(
            "UPDATE sellers SET must_change_password = 0, password_changed = 1 WHERE username = ?"),
            (username,))
        conn.commit()


# ========== 售前备注 CRUD ==========

def create_pre_sale_note(
    order_id: str = None, customer_id: str = None, customer_name: str = None,
    nickname: str = None, platform: str = 'other', platform_id: str = None,
    country: str = None, region: str = None, language: str = 'zh',
    is_old_customer: int = 0, repeat_purchase_count: int = 0,
    has_complaints: int = 0, has_disputes: int = 0,
    has_negative_reviews: int = 0, has_asked_shipping: int = 0, has_asked_logistics: int = 0,
    preference_style: str = None, preference_color: str = None, preference_size: str = None,
    price_sensitivity: str = 'normal', needs_gift: int = 0, needs_card: int = 0,
    needs_privacy_packaging: int = 0,
    product_color: str = None, product_size: str = None, product_model: str = None,
    packaging_type: str = 'normal', no_invoice: int = 0, no_price_list: int = 0,
    logistics_channel: str = None, must_combine: int = 1, urgent_shipping: int = 0,
    needs_gift_item: int = 0, needs_card_item: int = 0,
    customer_message_translation: str = None, fragile_need_extra_protection: int = 0,
    high_risk_area: int = 0, suspected_scammer: int = 0,
    price_modification: str = None, discount: str = None, free_shipping: int = 0,
    out_of_stock: int = 0, pre_order: int = 0, waiting_days: int = 0,
    internal_note: str = None, raw_note: str = None,
    created_by: str = None
) -> str:
    note_id = f"PSN{datetime.now().strftime('%Y%m%d%H%M%S')}{str(_uuid.uuid4())[:6].upper()}"
    p = (note_id, order_id, customer_id, customer_name, nickname, platform, platform_id,
                country, region, language, is_old_customer, repeat_purchase_count,
                has_complaints, has_disputes, has_negative_reviews, has_asked_shipping,
                has_asked_logistics, preference_style, preference_color, preference_size,
                price_sensitivity, needs_gift, needs_card, needs_privacy_packaging,
                product_color, product_size, product_model, packaging_type, no_invoice,
                no_price_list, logistics_channel, must_combine, urgent_shipping,
                needs_gift_item, needs_card_item, customer_message_translation,
                fragile_need_extra_protection, high_risk_area, suspected_scammer,
                price_modification, discount, free_shipping, out_of_stock,
         pre_order, waiting_days, internal_note, raw_note, created_by)
    with get_db() as (conn, cursor):
        cols = ('note_id', 'order_id', 'customer_id', 'customer_name', 'nickname', 'platform', 'platform_id',
                'country', 'region', 'language', 'is_old_customer', 'repeat_purchase_count',
                'has_complaints', 'has_disputes', 'has_negative_reviews', 'has_asked_shipping',
                'has_asked_logistics', 'preference_style', 'preference_color', 'preference_size',
                'price_sensitivity', 'needs_gift', 'needs_card', 'needs_privacy_packaging',
                'product_color', 'product_size', 'product_model', 'packaging_type', 'no_invoice',
                'no_price_list', 'logistics_channel', 'must_combine', 'urgent_shipping',
                'needs_gift_item', 'needs_card_item', 'customer_message_translation',
                'fragile_need_extra_protection', 'high_risk_area', 'suspected_scammer',
                'price_modification', 'discount', 'free_shipping', 'out_of_stock',
                'pre_order', 'waiting_days', 'internal_note', 'raw_note', 'created_by')
        placeholders = ', '.join(['%s' if _use_mysql() else '?' for _ in cols])
        names = ', '.join(cols)
        sql = f"INSERT INTO pre_sale_notes ({names}) VALUES ({placeholders})"
        cursor.execute(sql, p)
        conn.commit()
        return note_id


def get_pre_sale_notes(
    keyword: str = None, platform: str = None, country: str = None,
    language: str = None, risk_only: bool = False, normal_only: bool = False,
    page: int = 1, page_size: int = 20
) -> tuple:
    with get_db() as (conn, cursor):
        q = "SELECT * FROM pre_sale_notes WHERE 1=1"
        c = "SELECT COUNT(*) FROM pre_sale_notes WHERE 1=1"
        params = []
        ph = '%s' if _use_mysql() else '?'
        if keyword:
            kw = f"%{keyword}%"
            q += f" AND (order_id LIKE {ph} OR customer_name LIKE {ph} OR customer_id LIKE {ph} OR nickname LIKE {ph})"
            c += f" AND (order_id LIKE {ph} OR customer_name LIKE {ph} OR customer_id LIKE {ph} OR nickname LIKE {ph})"
            params.extend([kw, kw, kw, kw])
        if platform:
            q += f" AND platform = {ph}"; c += f" AND platform = {ph}"; params.append(platform)
        if country:
            q += f" AND country = {ph}"; c += f" AND country = {ph}"; params.append(country)
        if language:
            q += f" AND language = {ph}"; c += f" AND language = {ph}"; params.append(language)
        if risk_only:
            q += " AND (high_risk_area = 1 OR suspected_scammer = 1 OR has_disputes = 1)"
            c += " AND (high_risk_area = 1 OR suspected_scammer = 1 OR has_disputes = 1)"
        elif normal_only:
            q += " AND COALESCE(high_risk_area,0)=0 AND COALESCE(suspected_scammer,0)=0 AND COALESCE(has_disputes,0)=0"
            c += " AND COALESCE(high_risk_area,0)=0 AND COALESCE(suspected_scammer,0)=0 AND COALESCE(has_disputes,0)=0"
        cursor.execute(c, params)
        total = cursor.fetchone()[0]
        q += f" ORDER BY created_at DESC LIMIT {ph} OFFSET {ph}"
        params.extend([page_size, (page - 1) * page_size])
        cursor.execute(q, params)
        cols = _col(cursor)
        return [_row_to_dict(row, cols) for row in cursor.fetchall()], total


def get_pre_sale_note(note_id: str) -> Optional[Dict]:
    with get_db() as (conn, cursor):
        cursor.execute(_q("SELECT * FROM pre_sale_notes WHERE note_id = ?"), (note_id,))
        return _row_to_dict(cursor.fetchone(), _col(cursor))


def update_pre_sale_note(note_id: str, **kwargs) -> bool:
    if not kwargs:
        return False
    with get_db() as (conn, cursor):
        fields = ", ".join([f"{k} = ?" for k in kwargs.keys()])
        values = list(kwargs.values()) + [note_id]
        if _use_mysql():
            cursor.execute(f"UPDATE pre_sale_notes SET {fields}, updated_at = NOW() WHERE note_id = %s", values)
        else:
            cursor.execute(f"UPDATE pre_sale_notes SET {fields}, updated_at = CURRENT_TIMESTAMP WHERE note_id = ?", values)
        conn.commit()
        return cursor.rowcount > 0


def delete_pre_sale_note(note_id: str) -> bool:
    with get_db() as (conn, cursor):
        cursor.execute(_q("DELETE FROM pre_sale_notes WHERE note_id = ?"), (note_id,))
        conn.commit()
        return cursor.rowcount > 0


def get_pre_sale_note_stats() -> Dict:
    with get_db() as (conn, cursor):
        cursor.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN is_old_customer = 1 THEN 1 ELSE 0 END) as old_customers,
                SUM(CASE WHEN high_risk_area = 1 THEN 1 ELSE 0 END) as high_risk,
                SUM(CASE WHEN suspected_scammer = 1 THEN 1 ELSE 0 END) as suspected_scammers,
                SUM(CASE WHEN has_complaints = 1 THEN 1 ELSE 0 END) as complaints,
                SUM(CASE WHEN has_disputes = 1 THEN 1 ELSE 0 END) as disputes,
                SUM(CASE WHEN urgent_shipping = 1 THEN 1 ELSE 0 END) as urgent,
                SUM(CASE WHEN out_of_stock = 1 THEN 1 ELSE 0 END) as out_of_stock,
                SUM(CASE WHEN pre_order = 1 THEN 1 ELSE 0 END) as pre_orders
            FROM pre_sale_notes
        """)
        return _row_to_dict(cursor.fetchone(), _col(cursor)) or {}


# ========== 评价操作 ==========

def create_review(review_id: str, order_id: str = None, customer_id: str = None,
                  customer_name: str = None, star_rating: int = 5, content: str = None,
                  platform: str = 'other', product_name: str = None, product_image: str = None,
                  review_date: str = None) -> int:
    is_negative = 1 if star_rating <= 2 else 0
    with get_db() as (conn, cursor):
        params = (review_id, order_id, customer_id, customer_name, star_rating, content,
                  platform, product_name, product_image, review_date, is_negative)
        if _use_mysql():
            cursor.execute("""
                INSERT IGNORE INTO reviews
                (review_id, order_id, customer_id, customer_name, star_rating, content, status, platform, product_name, product_image, review_date, is_negative)
                VALUES (%s, %s, %s, %s, %s, %s, 'pending', %s, %s, %s, %s, %s)
            """, params)
        else:
            cursor.execute("""
                INSERT INTO reviews
                (review_id, order_id, customer_id, customer_name, star_rating, content, status, platform, product_name, product_image, review_date, is_negative)
                VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?)
            """, params)
        conn.commit()
        return cursor.lastrowid


def get_reviews(status: str = None, star_rating: int = None, limit: int = 100,
               start_date: str = None, end_date: str = None, platform: str = None,
               page: int = 1, page_size: int = 50) -> tuple:
    with get_db() as (conn, cursor):
        q = "SELECT * FROM reviews WHERE 1=1"
        c = "SELECT COUNT(*) FROM reviews WHERE 1=1"
        params = []
        ph = '%s' if _use_mysql() else '?'
        if status:
            q += f" AND status = {ph}"; c += f" AND status = {ph}"; params.append(status)
        if star_rating:
            q += f" AND star_rating = {ph}"; c += f" AND star_rating = {ph}"; params.append(star_rating)
        if start_date:
            q += f" AND (review_date >= {ph} OR created_at >= {ph})"; c += f" AND (review_date >= {ph} OR created_at >= {ph})"
            params.extend([start_date, start_date])
        if end_date:
            q += f" AND (review_date <= {ph} OR created_at <= {ph})"; c += f" AND (review_date <= {ph} OR created_at <= {ph})"
            params.extend([end_date, end_date])
        if platform:
            q += f" AND platform = {ph}"; c += f" AND platform = {ph}"; params.append(platform)
        cursor.execute(c, params)
        total = cursor.fetchone()[0]
        effective_limit = limit if limit < page_size else page_size
        q += f" ORDER BY created_at DESC LIMIT {ph} OFFSET {ph}"
        params.extend([effective_limit, (page - 1) * effective_limit])
        cursor.execute(q, params)
        cols = _col(cursor)
        return [_row_to_dict(row, cols) for row in cursor.fetchall()], total


def get_review(review_id: str) -> Optional[Dict]:
    with get_db() as (conn, cursor):
        cursor.execute(_q("SELECT * FROM reviews WHERE review_id = ?"), (review_id,))
        return _row_to_dict(cursor.fetchone(), _col(cursor))


def reply_review(review_id: str, reply_content: str, replied_by: str = None) -> bool:
    with get_db() as (conn, cursor):
        if _use_mysql():
            cursor.execute("""
                UPDATE reviews
                SET reply_content = %s, replied_at = NOW(), replied_by = %s, status = 'replied', updated_at = NOW()
                WHERE review_id = %s
            """, (reply_content, replied_by, review_id))
        else:
            cursor.execute("""
                UPDATE reviews
                SET reply_content = ?, replied_at = CURRENT_TIMESTAMP, replied_by = ?, status = 'replied', updated_at = CURRENT_TIMESTAMP
                WHERE review_id = ?
            """, (reply_content, replied_by, review_id))
        conn.commit()
        return cursor.rowcount > 0


def batch_reply_reviews(review_ids: List[str], reply_content: str, replied_by: str = None) -> int:
    if not review_ids:
        return 0
    count = 0
    with get_db() as (conn, cursor):
        for rid in review_ids:
            if _use_mysql():
                cursor.execute("""
                    UPDATE reviews
                    SET reply_content = %s, replied_at = NOW(), replied_by = %s, status = 'replied', updated_at = NOW()
                    WHERE review_id = %s
                """, (reply_content, replied_by, rid))
            else:
                cursor.execute("""
                    UPDATE reviews
                    SET reply_content = ?, replied_at = CURRENT_TIMESTAMP, replied_by = ?, status = 'replied', updated_at = CURRENT_TIMESTAMP
                    WHERE review_id = ?
                """, (reply_content, replied_by, rid))
            if cursor.rowcount > 0:
                count += 1
        conn.commit()
    return count


def get_review_stats() -> Dict:
    with get_db() as (conn, cursor):
        cursor.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) as pending,
                SUM(CASE WHEN status = 'replied' THEN 1 ELSE 0 END) as replied,
                AVG(star_rating) as avg_rating,
                SUM(CASE WHEN star_rating >= 4 THEN 1 ELSE 0 END) as positive,
                SUM(CASE WHEN star_rating = 3 THEN 1 ELSE 0 END) as neutral,
                SUM(CASE WHEN star_rating <= 2 THEN 1 ELSE 0 END) as negative
            FROM reviews
        """)
        return _row_to_dict(cursor.fetchone(), _col(cursor)) or {}


# ========== 自动回复规则 ==========

def create_auto_reply_rule(rule_type: str, reply_content: str, star_min: int = None,
                           star_max: int = None, created_by: str = None) -> int:
    with get_db() as (conn, cursor):
        cursor.execute(_q("""
            INSERT INTO auto_reply_rules (rule_type, star_min, star_max, reply_content, created_by)
            VALUES (?, ?, ?, ?, ?)
        """, (rule_type, star_min, star_max, reply_content, created_by)),
            (rule_type, star_min, star_max, reply_content, created_by))
        conn.commit()
        return cursor.lastrowid


def get_auto_reply_rules(rule_type: str = None, enabled_only: bool = False) -> List[Dict]:
    with get_db() as (conn, cursor):
        q = "SELECT * FROM auto_reply_rules WHERE 1=1"
        params = []
        if rule_type:
            q += " AND rule_type = ?"; params.append(rule_type)
        if enabled_only:
            q += " AND is_enabled = 1"
        q += " ORDER BY created_at DESC"
        cursor.execute(q, params)
        cols = _col(cursor)
        return [_row_to_dict(row, cols) for row in cursor.fetchall()]


def update_auto_reply_rule(rule_id: int, **kwargs) -> bool:
    if not kwargs:
        return False
    with get_db() as (conn, cursor):
        fields = ", ".join([f"{k} = ?" for k in kwargs.keys()])
        values = list(kwargs.values()) + [rule_id]
        if _use_mysql():
            cursor.execute(f"UPDATE auto_reply_rules SET {fields}, updated_at = NOW() WHERE id = %s", values)
        else:
            cursor.execute(f"UPDATE auto_reply_rules SET {fields}, updated_at = CURRENT_TIMESTAMP WHERE id = ?", values)
        conn.commit()
        return cursor.rowcount > 0


def delete_auto_reply_rule(rule_id: int) -> bool:
    with get_db() as (conn, cursor):
        cursor.execute(_q("DELETE FROM auto_reply_rules WHERE id = ?"), (rule_id,))
        conn.commit()
        return cursor.rowcount > 0


def get_matching_auto_reply(star_rating: int) -> Optional[Dict]:
    with get_db() as (conn, cursor):
        cursor.execute(_q("""
            SELECT * FROM auto_reply_rules
            WHERE is_enabled = 1
              AND rule_type = 'star'
              AND star_min <= ? AND star_max >= ?
            ORDER BY star_min DESC
            LIMIT 1
        """, (star_rating, star_rating)), (star_rating, star_rating))
        return _row_to_dict(cursor.fetchone(), _col(cursor))


def auto_reply_pending_reviews() -> int:
    with get_db() as (conn, cursor):
        cursor.execute(_q("SELECT * FROM reviews WHERE status = 'pending'"))
        cols = _col(cursor)
        pending_reviews = [_row_to_dict(row, cols) for row in cursor.fetchall()]
        count = 0
        for review in pending_reviews:
            rule = get_matching_auto_reply(review.get("star_rating", 5))
            if rule:
                if _use_mysql():
                    cursor.execute("""
                        UPDATE reviews
                        SET reply_content = %s, replied_at = NOW(), replied_by = '系统自动', status = 'replied', updated_at = NOW()
                        WHERE review_id = %s
                    """, (rule["reply_content"], review["review_id"]))
                else:
                    cursor.execute("""
                        UPDATE reviews
                        SET reply_content = ?, replied_at = CURRENT_TIMESTAMP, replied_by = '系统自动', status = 'replied', updated_at = CURRENT_TIMESTAMP
                        WHERE review_id = ?
                    """, (rule["reply_content"], review["review_id"]))
                count += cursor.rowcount
        conn.commit()
        return count


# ========== 回复模板 ==========

def create_reply_template(name: str, content: str, category: str = 'general',
                         is_default: int = 0, created_by: str = None) -> int:
    with get_db() as (conn, cursor):
        if is_default:
            cursor.execute(_q("UPDATE reply_templates SET is_default = 0"))
        cursor.execute(_q("""
            INSERT INTO reply_templates (name, content, category, is_default, created_by)
            VALUES (?, ?, ?, ?, ?)
        """, (name, content, category, is_default, created_by)), (name, content, category, is_default, created_by))
        conn.commit()
        return cursor.lastrowid


def get_reply_templates(category: str = None, include_disabled: bool = False) -> List[Dict]:
    with get_db() as (conn, cursor):
        q = "SELECT * FROM reply_templates WHERE 1=1"
        params = []
        if category:
            q += " AND category = ?"; params.append(category)
        if not include_disabled:
            q += " AND is_default >= 0"
        q += " ORDER BY is_default DESC, id DESC"
        cursor.execute(q, params)
        cols = _col(cursor)
        return [_row_to_dict(row, cols) for row in cursor.fetchall()]


def get_default_reply_template() -> Optional[Dict]:
    with get_db() as (conn, cursor):
        cursor.execute(_q("SELECT * FROM reply_templates WHERE is_default = 1 LIMIT 1"))
        return _row_to_dict(cursor.fetchone(), _col(cursor))


def get_reply_template(template_id: int) -> Optional[Dict]:
    with get_db() as (conn, cursor):
        cursor.execute(_q("SELECT * FROM reply_templates WHERE id = ?"), (template_id,))
        return _row_to_dict(cursor.fetchone(), _col(cursor))


def update_reply_template(template_id: int, name: str = None, content: str = None,
                          category: str = None, is_default: int = None) -> bool:
    with get_db() as (conn, cursor):
        updates = []
        params = []
        if name is not None:
            updates.append("name = ?"); params.append(name)
        if content is not None:
            updates.append("content = ?"); params.append(content)
        if category is not None:
            updates.append("category = ?"); params.append(category)
        if is_default is not None:
            if is_default:
                cursor.execute(_q("UPDATE reply_templates SET is_default = 0"))
            updates.append("is_default = ?"); params.append(is_default)
        if not updates:
            return False
        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(template_id)
        if _use_mysql():
            sql = f"UPDATE reply_templates SET {', '.join(updates)}, updated_at = NOW() WHERE id = %s"
        else:
            sql = f"UPDATE reply_templates SET {', '.join(updates)} WHERE id = ?"
        cursor.execute(sql, params)
        conn.commit()
        return cursor.rowcount > 0


def delete_reply_template(template_id: int) -> bool:
    with get_db() as (conn, cursor):
        cursor.execute(_q("DELETE FROM reply_templates WHERE id = ?"), (template_id,))
        conn.commit()
        return cursor.rowcount > 0


# ========== 售后单 CRUD ==========

def create_after_sale(
    order_id: str = None, platform: str = 'other',
    customer_id: str = None, customer_name: str = None,
    type: str = '退货退款', reason_category: str = None, reason_detail: str = None,
    refund_product: float = 0, refund_shipping: float = 0, refund_subsidy: float = 0,
    refund_customs: float = 0, refund_commission: float = 0, refund_other: float = 0,
    refund_total: float = 0, refund_method: str = '原路退回',
    warehouse: str = None, return_address_type: str = '国内',
    exchange_product: str = None, exchange_qty: int = 1,
    internal_note: str = None, buyer_note: str = None,
    created_by: str = None
) -> str:
    as_id = f"AS{datetime.now().strftime('%Y%m%d%H%M%S')}{str(_uuid.uuid4())[:6].upper()}"
    with get_db() as (conn, cursor):
        cols = ('as_id', 'order_id', 'platform', 'customer_id', 'customer_name',
                'type', 'reason_category', 'reason_detail',
                'refund_product', 'refund_shipping', 'refund_subsidy',
                'refund_customs', 'refund_commission', 'refund_other', 'refund_total', 'refund_method',
                'warehouse', 'return_address_type',
                'exchange_product', 'exchange_qty',
                'return_shipping_cost',
                'internal_note', 'buyer_note', 'created_by')
        p = (as_id, order_id, platform, customer_id, customer_name,
            type, reason_category, reason_detail,
            refund_product, refund_shipping, refund_subsidy,
            refund_customs, refund_commission, refund_other, refund_total, refund_method,
            warehouse, return_address_type,
            exchange_product, exchange_qty,
            0.0,
             internal_note, buyer_note, created_by)
        placeholders = ', '.join(['%s' if _use_mysql() else '?' for _ in cols])
        names = ', '.join(cols)
        cursor.execute(f"INSERT INTO after_sales ({names}) VALUES ({placeholders})", p)
        conn.commit()
        return as_id


def get_after_sales(
    status: str = None, type: str = None, platform: str = None,
    keyword: str = None, page: int = 1, page_size: int = 20
) -> tuple:
    with get_db() as (conn, cursor):
        q = "SELECT * FROM after_sales WHERE 1=1"
        c = "SELECT COUNT(*) FROM after_sales WHERE 1=1"
        params = []
        ph = '%s' if _use_mysql() else '?'
        if status:
            q += f" AND status = {ph}"; c += f" AND status = {ph}"; params.append(status)
        if type:
            q += f" AND type = {ph}"; c += f" AND type = {ph}"; params.append(type)
        if platform:
            q += f" AND platform = {ph}"; c += f" AND platform = {ph}"; params.append(platform)
        if keyword:
            kw = f"%{keyword}%"
            q += f" AND (as_id LIKE {ph} OR order_id LIKE {ph} OR customer_name LIKE {ph})"
            c += f" AND (as_id LIKE {ph} OR order_id LIKE {ph} OR customer_name LIKE {ph})"
            params.extend([kw, kw, kw])
        cursor.execute(c, params)
        total = cursor.fetchone()[0]
        q += f" ORDER BY created_at DESC LIMIT {ph} OFFSET {ph}"
        params.extend([page_size, (page - 1) * page_size])
        cursor.execute(q, params)
        cols = _col(cursor)
        return [_row_to_dict(row, cols) for row in cursor.fetchall()], total


def get_after_sale(as_id: str) -> Optional[Dict]:
    with get_db() as (conn, cursor):
        cursor.execute(_q("SELECT * FROM after_sales WHERE as_id = ?"), (as_id,))
        return _row_to_dict(cursor.fetchone(), _col(cursor))


def update_after_sale(as_id: str, **kwargs) -> bool:
    if not kwargs:
        return False
    with get_db() as (conn, cursor):
        fields = ", ".join([f"{k} = ?" for k in kwargs.keys()])
        values = list(kwargs.values()) + [as_id]
        if _use_mysql():
            cursor.execute(f"UPDATE after_sales SET {fields}, updated_at = NOW() WHERE as_id = %s", values)
        else:
            cursor.execute(f"UPDATE after_sales SET {fields}, updated_at = CURRENT_TIMESTAMP WHERE as_id = ?", values)
        conn.commit()
        return cursor.rowcount > 0


def advance_after_sale_status(as_id: str, new_status: str, extra: dict = None) -> bool:
    updates = {"status": new_status}
    if extra:
        updates.update(extra)
    if new_status == "完成":
        updates["completed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return update_after_sale(as_id, **updates)


def get_after_sale_stats() -> Dict:
    with get_db() as (conn, cursor):
        cursor.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN status = '待审核' THEN 1 ELSE 0 END) as pending,
                SUM(CASE WHEN status = '待买家寄回' THEN 1 ELSE 0 END) as return_pending,
                SUM(CASE WHEN status = '待签收' THEN 1 ELSE 0 END) as received,
                SUM(CASE WHEN status = '待质检' THEN 1 ELSE 0 END) as qc,
                SUM(CASE WHEN status = '待退款' THEN 1 ELSE 0 END) as refund,
                SUM(CASE WHEN status = '完成' THEN 1 ELSE 0 END) as completed,
                SUM(COALESCE(refund_total, 0)) as total_refund_amount
            FROM after_sales
        """)
        return _row_to_dict(cursor.fetchone(), _col(cursor)) or {}


# ========== 企业增强：审计日志 ==========

def write_audit_log(event_type: str, operator: str = None, target_type: str = None,
                     target_id: str = None, detail: str = None,
                     ip_address: str = None, user_agent: str = None) -> int:
    with get_db() as (conn, cursor):
        cursor.execute(_q("""
            INSERT INTO audit_logs (event_type, operator, target_type, target_id, detail, ip_address, user_agent)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (event_type, operator, target_type, target_id, detail, ip_address, user_agent)),
            (event_type, operator, target_type, target_id, detail, ip_address, user_agent))
        conn.commit()
        return cursor.lastrowid


def get_audit_logs(event_type: str = None, operator: str = None,
                    target_type: str = None, limit: int = 100,
                    page: int = 1, page_size: int = 20) -> tuple:
    with get_db() as (conn, cursor):
        conditions = []
        params = []
        ph = '%s' if _use_mysql() else '?'
        if event_type:
            conditions.append(f"event_type = {ph}"); params.append(event_type)
        if operator:
            conditions.append(f"operator LIKE {ph}"); params.append(f"%{operator}%")
        if target_type:
            conditions.append(f"target_type = {ph}"); params.append(target_type)
        where = " AND ".join(conditions) if conditions else "1=1"
        offset = (page - 1) * page_size
        cursor.execute(f"SELECT * FROM audit_logs WHERE {where} ORDER BY created_at DESC LIMIT {ph} OFFSET {ph}",
                      params + [page_size, offset])
        cols = _col(cursor)
        rows = cursor.fetchall()
        cursor.execute(f"SELECT COUNT(*) FROM audit_logs WHERE {where}", params)
        total = cursor.fetchone()[0]
        return [_row_to_dict(row, cols) for row in rows], total


# ========== 企业增强：通知系统 ==========

def create_notification(notify_type: str, title: str, content: str = None,
                       priority: str = "normal", related_type: str = None,
                       related_id: str = None, created_by: str = None) -> int:
    with get_db() as (conn, cursor):
        cursor.execute(_q("""
            INSERT INTO notifications (notify_type, title, content, priority, related_type, related_id, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (notify_type, title, content, priority, related_type, related_id, created_by)),
            (notify_type, title, content, priority, related_type, related_id, created_by))
        conn.commit()
        return cursor.lastrowid


def get_notifications(is_read: bool = None, notify_type: str = None,
                      priority: str = None, limit: int = 100,
                      page: int = 1, page_size: int = 20) -> tuple:
    with get_db() as (conn, cursor):
        conditions = []
        params = []
        ph = '%s' if _use_mysql() else '?'
        if is_read is not None:
            conditions.append(f"is_read = {ph}"); params.append(1 if is_read else 0)
        if notify_type:
            conditions.append(f"notify_type = {ph}"); params.append(notify_type)
        if priority:
            conditions.append(f"priority = {ph}"); params.append(priority)
        where = " AND ".join(conditions) if conditions else "1=1"
        offset = (page - 1) * page_size
        cursor.execute(f"SELECT * FROM notifications WHERE {where} ORDER BY created_at DESC LIMIT {ph} OFFSET {ph}",
                      params + [page_size, offset])
        cols = _col(cursor)
        rows = cursor.fetchall()
        cursor.execute(f"SELECT COUNT(*) FROM notifications WHERE {where}", params)
        total = cursor.fetchone()[0]
        return [_row_to_dict(row, cols) for row in rows], total


def mark_notification_read(notify_id: int) -> bool:
    with get_db() as (conn, cursor):
        cursor.execute(_q("UPDATE notifications SET is_read = 1 WHERE id = ?"), (notify_id,))
        conn.commit()
        return cursor.rowcount > 0


def get_unread_notification_count() -> int:
    with get_db() as (conn, cursor):
        cursor.execute(_q("SELECT COUNT(*) FROM notifications WHERE is_read = 0"))
        return cursor.fetchone()[0]


# ========== 企业增强：系统设置 ==========

def get_system_setting(key: str, default=None):
    with get_db() as (conn, cursor):
        cursor.execute(_q("SELECT value FROM system_settings WHERE `key` = ?"), (key,))
        row = cursor.fetchone()
        return row[0] if row else default


def set_system_setting(key: str, value: str, description: str = None, updated_by: str = None) -> bool:
    with get_db() as (conn, cursor):
        if _use_mysql():
            cursor.execute(f"""
                INSERT INTO system_settings (`key`, value, description, updated_by, updated_at)
                VALUES (%s, %s, %s, %s, NOW())
                ON DUPLICATE KEY UPDATE value = %s, description = COALESCE(%s, description), updated_by = COALESCE(%s, updated_by), updated_at = NOW()
            """, (key, value, description, updated_by, value, description, updated_by))
        else:
            cursor.execute(_q("SELECT id FROM system_settings WHERE `key` = ?"), (key,))
            exists = cursor.fetchone()
            if exists:
                cursor.execute(_q("""
                    UPDATE system_settings SET value = ?, description = COALESCE(?, description), updated_by = COALESCE(?, updated_by) WHERE `key` = ?
                """, (value, description, updated_by, key)), (value, description, updated_by, key))
            else:
                cursor.execute(_q("""
                    INSERT INTO system_settings (`key`, value, description, updated_by) VALUES (?, ?, ?, ?)
                """, (key, value, description, updated_by)), (key, value, description, updated_by))
        conn.commit()
        return True


def get_all_system_settings() -> dict:
    with get_db() as (conn, cursor):
        cursor.execute("SELECT `key`, value, description, updated_at FROM system_settings")
        cols = _col(cursor)
        return {r['key']: {"value": r['value'], "description": r.get('description'), "updated_at": r.get('updated_at')}
               for r in [_row_to_dict(row, cols) for row in cursor.fetchall()] if r.get('key')}


# ========== 企业增强：高级统计分析 ==========

def get_advanced_stats() -> dict:
    with get_db() as (conn, cursor):
        stats = {}
        cursor.execute("SELECT COUNT(*) FROM customers")
        stats["total_customers"] = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM sessions WHERE status = 'active'")
        stats["active_sessions"] = cursor.fetchone()[0]
        if _use_mysql():
            cursor.execute("SELECT COUNT(*) FROM sessions WHERE DATE(created_at) = CURDATE()")
            stats["today_sessions"] = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM messages WHERE DATE(created_at) = CURDATE()")
            stats["today_messages"] = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM pre_sale_notes WHERE DATE(created_at) = CURDATE()")
            stats["today_pre_sale_notes"] = cursor.fetchone()[0]
        else:
            cursor.execute("SELECT COUNT(*) FROM sessions WHERE DATE(created_at) = DATE('now')")
            stats["today_sessions"] = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM messages WHERE DATE(created_at) = DATE('now')")
            stats["today_messages"] = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM pre_sale_notes WHERE DATE(created_at) = DATE('now')")
            stats["today_pre_sale_notes"] = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM after_sales WHERE status = '待审核'")
        stats["pending_after_sales"] = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM reviews WHERE status = 'pending'")
        stats["pending_reviews"] = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*), AVG(star_rating) FROM reviews WHERE star_rating IS NOT NULL")
        row = cursor.fetchone()
        stats["total_reviews"] = row[0]
        stats["avg_rating"] = round(float(row[1] or 0), 2)
        cursor.execute("SELECT COUNT(*) FROM reviews WHERE star_rating <= 2 AND status = 'pending'")
        stats["negative_pending_reviews"] = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*), SUM(refund_total) FROM after_sales WHERE status = '完成'")
        row = cursor.fetchone()
        stats["completed_after_sales"] = row[0]
        stats["total_refund_amount"] = round(float(row[1] or 0), 2)
        cursor.execute("SELECT COUNT(*) FROM sellers WHERE is_online = 1")
        stats["online_agents"] = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM sellers")
        stats["total_agents"] = cursor.fetchone()[0]
        stats["unread_notifications"] = get_unread_notification_count()
        if _use_mysql():
            cursor.execute("SELECT COUNT(*) FROM audit_logs WHERE DATE(created_at) = CURDATE()")
            stats["today_audit_logs"] = cursor.fetchone()[0]
            cursor.execute("""
                SELECT platform, COUNT(*) as cnt FROM (
                    SELECT platform FROM pre_sale_notes
                    UNION ALL SELECT platform FROM after_sales
                    UNION ALL SELECT platform FROM reviews
                ) t GROUP BY platform ORDER BY cnt DESC LIMIT 10
            """)
        else:
            cursor.execute("SELECT COUNT(*) FROM audit_logs WHERE DATE(created_at) = DATE('now')")
            stats["today_audit_logs"] = cursor.fetchone()[0]
            cursor.execute("""
                SELECT platform, COUNT(*) as cnt FROM (
                    SELECT platform FROM pre_sale_notes
                    UNION ALL SELECT platform FROM after_sales
                    UNION ALL SELECT platform FROM reviews
                ) GROUP BY platform ORDER BY cnt DESC LIMIT 10
            """)
        stats["platform_distribution"] = [{"platform": r[0], "count": r[1]} for r in cursor.fetchall()]
        if _use_mysql():
            cursor.execute("""
                SELECT DATE(created_at) as date, COUNT(*) as cnt
                FROM sessions
                WHERE created_at >= DATE_SUB(CURDATE(), INTERVAL 7 DAY)
                GROUP BY DATE(created_at)
                ORDER BY date
            """)
        else:
            cursor.execute("""
                SELECT DATE(created_at) as date, COUNT(*) as cnt
                FROM sessions
                WHERE created_at >= DATE('now', '-7 days')
                GROUP BY DATE(created_at)
                ORDER BY date
            """)
        stats["session_trend_7d"] = [{"date": str(r[0]), "count": r[1]} for r in cursor.fetchall()]
        if _use_mysql():
            cursor.execute("""
                SELECT DATE(created_at) as date, COUNT(*) as cnt, AVG(star_rating) as avg_star
                FROM reviews
                WHERE created_at >= DATE_SUB(CURDATE(), INTERVAL 7 DAY) AND star_rating IS NOT NULL
                GROUP BY DATE(created_at)
                ORDER BY date
            """)
        else:
            cursor.execute("""
                SELECT DATE(created_at) as date, COUNT(*) as cnt, AVG(star_rating) as avg_star
                FROM reviews
                WHERE created_at >= DATE('now', '-7 days') AND star_rating IS NOT NULL
                GROUP BY DATE(created_at)
                ORDER BY date
            """)
        stats["review_trend_7d"] = [
            {"date": str(r[0]), "count": r[1], "avg_rating": round(float(r[2] or 0), 2)}
            for r in cursor.fetchall()
        ]
        if _use_mysql():
            cursor.execute("""
                SELECT DATE(created_at) as date, COUNT(*) as cnt
                FROM after_sales
                WHERE created_at >= DATE_SUB(CURDATE(), INTERVAL 7 DAY)
                GROUP BY DATE(created_at)
                ORDER BY date
            """)
        else:
            cursor.execute("""
                SELECT DATE(created_at) as date, COUNT(*) as cnt
                FROM after_sales
                WHERE created_at >= DATE('now', '-7 days')
                GROUP BY DATE(created_at)
                ORDER BY date
            """)
        stats["after_sale_trend_7d"] = [{"date": str(r[0]), "count": r[1]} for r in cursor.fetchall()]
        cursor.execute("""
            SELECT status, COUNT(*) as cnt, SUM(refund_total) as total
            FROM after_sales
            GROUP BY status
        """)
        stats["after_sale_by_status"] = [
            {"status": r[0], "count": r[1], "total_refund": round(float(r[2] or 0), 2)}
            for r in cursor.fetchall()
        ]
        cursor.execute("""
            SELECT reason_category, COUNT(*) as cnt
            FROM after_sales
            WHERE reason_category IS NOT NULL AND reason_category != ''
            GROUP BY reason_category
            ORDER BY cnt DESC
            LIMIT 10
        """)
        stats["refund_reason_distribution"] = [
            {"reason": r[0], "count": r[1]} for r in cursor.fetchall()
        ]
        return stats
