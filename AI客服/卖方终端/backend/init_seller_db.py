# -*- coding: utf-8 -*-
"""
卖方终端系统 - 独立数据库初始化脚本
生成 seller.db（会话/客户/消息/坐席/队列/运营数据）
"""
import sqlite3, os, sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DB_PATH = SCRIPT_DIR / "data" / "seller.db"

def get_connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_seller_db():
    conn = get_connection()
    cur = conn.cursor()

    # 客户档案（人工客服需要查看客户信息）
    cur.execute("""
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id TEXT UNIQUE NOT NULL,
            phone TEXT,
            name TEXT,
            region TEXT DEFAULT '未知',
            level TEXT DEFAULT '普通',
            m_value INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 会话表（来自买方系统的转移会话）
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT UNIQUE NOT NULL,
            customer_id TEXT,
            status TEXT DEFAULT 'waiting',
            assign_to TEXT,
            is_ai INTEGER DEFAULT 0,
            language TEXT DEFAULT 'zh',
            system_source TEXT DEFAULT 'buyer',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 消息记录
    cur.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            role TEXT,
            content TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 坐席账号
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sellers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            name TEXT,
            role TEXT DEFAULT 'agent',
            is_online INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            last_login TEXT,
            password_changed INTEGER DEFAULT 0,
            must_change_password INTEGER DEFAULT 0
        )
    """)

    # 转接队列
    cur.execute("""
        CREATE TABLE IF NOT EXISTS transfer_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT UNIQUE NOT NULL,
            customer_id TEXT,
            language TEXT DEFAULT 'zh',
            enqueued_at TEXT DEFAULT CURRENT_TIMESTAMP,
            assigned_to TEXT,
            status TEXT DEFAULT 'waiting'
        )
    """)

    # 快捷回复
    cur.execute("""
        CREATE TABLE IF NOT EXISTS quick_replies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT,
            title TEXT,
            content TEXT,
            shortcut TEXT,
            is_active INTEGER DEFAULT 1,
            created_by TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 通知
    cur.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            notification_type TEXT,
            title TEXT,
            content TEXT,
            source TEXT DEFAULT 'system',
            is_read INTEGER DEFAULT 0,
            is_important INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            read_at TEXT
        )
    """)

    # 售后记录
    cur.execute("""
        CREATE TABLE IF NOT EXISTS after_sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            as_id TEXT UNIQUE,
            order_id TEXT,
            platform TEXT,
            customer_id TEXT,
            customer_name TEXT,
            type TEXT,
            reason_category TEXT,
            reason_detail TEXT,
            status TEXT DEFAULT 'pending',
            warehouse TEXT,
            return_address_type TEXT,
            refund_product REAL DEFAULT 0,
            refund_shipping REAL DEFAULT 0,
            refund_subsidy REAL DEFAULT 0,
            refund_customs REAL DEFAULT 0,
            refund_commission REAL DEFAULT 0,
            refund_other REAL DEFAULT 0,
            refund_total REAL DEFAULT 0,
            refund_method TEXT,
            return_tracking TEXT,
            return_carrier TEXT,
            return_shipping_cost REAL DEFAULT 0,
            qc_result TEXT,
            qc_note TEXT,
            exchange_product TEXT,
            exchange_qty INTEGER DEFAULT 0,
            internal_note TEXT,
            buyer_note TEXT,
            created_by TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            completed_at TEXT
        )
    """)

    # 售前记录
    cur.execute("""
        CREATE TABLE IF NOT EXISTS pre_sale_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            note_id TEXT,
            order_id TEXT,
            customer_id TEXT,
            customer_name TEXT,
            nickname TEXT,
            platform TEXT,
            platform_id TEXT,
            country TEXT,
            region TEXT,
            language TEXT DEFAULT 'zh',
            is_old_customer INTEGER DEFAULT 0,
            repeat_purchase_count INTEGER DEFAULT 0,
            has_complaints INTEGER DEFAULT 0,
            has_disputes INTEGER DEFAULT 0,
            has_negative_reviews INTEGER DEFAULT 0,
            has_asked_shipping INTEGER DEFAULT 0,
            has_asked_logistics INTEGER DEFAULT 0,
            preference_style TEXT,
            preference_color TEXT,
            preference_size TEXT,
            price_sensitivity TEXT,
            needs_gift INTEGER DEFAULT 0,
            needs_card INTEGER DEFAULT 0,
            needs_privacy_packaging INTEGER DEFAULT 0,
            product_color TEXT,
            product_size TEXT,
            product_model TEXT,
            packaging_type TEXT,
            no_invoice INTEGER DEFAULT 0,
            no_price_list INTEGER DEFAULT 0,
            logistics_channel TEXT,
            must_combine INTEGER DEFAULT 0,
            urgent_shipping INTEGER DEFAULT 0,
            needs_gift_item INTEGER DEFAULT 0,
            needs_card_item INTEGER DEFAULT 0,
            customer_message_translation TEXT,
            fragile_need_extra_protection INTEGER DEFAULT 0,
            high_risk_area INTEGER DEFAULT 0,
            suspected_scammer INTEGER DEFAULT 0,
            price_modification TEXT,
            discount TEXT,
            free_shipping INTEGER DEFAULT 0,
            out_of_stock INTEGER DEFAULT 0,
            pre_order INTEGER DEFAULT 0,
            waiting_days INTEGER DEFAULT 0,
            internal_note TEXT,
            raw_note TEXT,
            created_by TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 审计日志
    cur.execute("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT,
            operator TEXT,
            target_type TEXT,
            target_id TEXT,
            detail TEXT,
            ip_address TEXT,
            user_agent TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 创建索引
    cur.execute("CREATE INDEX IF NOT EXISTS idx_sessions_sid ON sessions(session_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_sessions_cid ON sessions(customer_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_messages_sid ON messages(session_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_customers_cid ON customers(customer_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_queue_status ON transfer_queue(status)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_queue_sid ON transfer_queue(session_id)")

    # 插入默认管理员账号
    try:
        import hashlib
        pw_hash = hashlib.sha256("admin123".encode()).hexdigest()
        cur.execute(
            "INSERT OR IGNORE INTO sellers (username, password_hash, name, role) VALUES (?, ?, ?, ?)",
            ("admin", pw_hash, "管理员", "admin")
        )
        conn.commit()
        print("[OK] Default admin account: admin / admin123")
    except Exception as e:
        print(f"[WARN] Could not create admin account: {e}")

    conn.commit()
    print(f"[OK] seller.db initialized at {DB_PATH}")
    print(f"     Tables: customers, sessions, messages, sellers, transfer_queue,")
    print(f"             quick_replies, notifications, after_sales, pre_sale_notes, audit_logs")
    return conn

if __name__ == "__main__":
    init_seller_db()
