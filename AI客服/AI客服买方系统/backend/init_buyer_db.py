# -*- coding: utf-8 -*-
"""
买方AI客服系统 - 独立数据库初始化脚本
生成 buyer.db（会话/客户/消息）
"""
import sqlite3, os, sys
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = Path(__file__).resolve().parent
DB_PATH = SCRIPT_DIR / "data" / "buyer.db"

def get_connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_buyer_db():
    conn = get_connection()
    cur = conn.cursor()

    # 客户档案
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

    # 会话表
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT UNIQUE NOT NULL,
            customer_id TEXT,
            status TEXT DEFAULT 'active',
            is_ai INTEGER DEFAULT 1,
            assign_to TEXT,
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

    # 创建索引
    cur.execute("CREATE INDEX IF NOT EXISTS idx_sessions_sid ON sessions(session_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_sessions_cid ON sessions(customer_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_messages_sid ON messages(session_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_customers_cid ON customers(customer_id)")

    conn.commit()
    print(f"[OK] buyer.db initialized at {DB_PATH}")
    print(f"     Tables: customers, sessions, messages")
    return conn

if __name__ == "__main__":
    init_buyer_db()
