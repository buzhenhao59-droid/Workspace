# -*- coding: utf-8 -*-
"""
买方系统 MySQL 数据库初始化 SQL
由 main_buyer.py 启动时调用
"""
import os
import sys
import logging
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mysql_db_buyer import get_db, _get_mysql_config, is_mysql, _get_sqlite_path

logger = logging.getLogger(__name__)


# ============== MySQL 建表 SQL ==============

MYSQL_SCHEMA = """
CREATE DATABASE IF NOT EXISTS `ruitalk_buyer`
    DEFAULT CHARACTER SET utf8mb4
    DEFAULT COLLATE utf8mb4_unicode_ci;
USE `ruitalk_buyer`;

-- 客户档案表
CREATE TABLE IF NOT EXISTS `buyer_customers` (
    `id` BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    `customer_id` VARCHAR(64) NOT NULL UNIQUE COMMENT '客户唯一标识',
    `phone` VARCHAR(32) DEFAULT NULL COMMENT '手机号',
    `name` VARCHAR(128) DEFAULT NULL COMMENT '客户姓名',
    `region` VARCHAR(64) DEFAULT NULL COMMENT '所在地区',
    `level` VARCHAR(32) DEFAULT '普通' COMMENT '会员等级',
    `m_value` INT UNSIGNED DEFAULT 0 COMMENT 'M值积分',
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX `idx_bc_phone` (`phone`),
    INDEX `idx_bc_customer_id` (`customer_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='买方客户表';

-- 会话表
CREATE TABLE IF NOT EXISTS `buyer_sessions` (
    `id` BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    `session_id` VARCHAR(128) NOT NULL UNIQUE COMMENT '会话ID',
    `customer_id` VARCHAR(64) DEFAULT NULL COMMENT '关联客户',
    `status` VARCHAR(32) DEFAULT 'active' COMMENT 'active/waiting/closed',
    `assign_to` VARCHAR(64) DEFAULT NULL COMMENT '分配给坐席',
    `is_ai` TINYINT UNSIGNED DEFAULT 1 COMMENT '1=AI模式,0=人工模式',
    `language` VARCHAR(16) DEFAULT 'zh' COMMENT '会话语言',
    `system_source` VARCHAR(32) DEFAULT 'buyer' COMMENT 'seller/buyer',
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX `idx_bs_customer` (`customer_id`),
    INDEX `idx_bs_status` (`status`),
    INDEX `idx_bs_updated` (`updated_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='买方会话表';

-- 消息表
CREATE TABLE IF NOT EXISTS `buyer_messages` (
    `id` BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    `session_id` VARCHAR(128) NOT NULL COMMENT '关联会话',
    `role` VARCHAR(32) NOT NULL COMMENT 'user/assistant/agent',
    `content` TEXT NOT NULL COMMENT '消息内容',
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX `idx_bm_session` (`session_id`),
    INDEX `idx_bm_created` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='买方消息表';
"""


# ============== SQLite 兼容建表（回退用）==============

SQLITE_SCHEMA = """
-- buyer_customers
CREATE TABLE IF NOT EXISTS buyer_customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id TEXT UNIQUE NOT NULL,
    phone TEXT,
    name TEXT,
    region TEXT,
    level TEXT DEFAULT '普通',
    m_value INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- buyer_sessions
CREATE TABLE IF NOT EXISTS buyer_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT UNIQUE NOT NULL,
    customer_id TEXT,
    status TEXT DEFAULT 'active',
    assign_to TEXT,
    is_ai INTEGER DEFAULT 1,
    language TEXT DEFAULT 'zh',
    system_source TEXT DEFAULT 'buyer',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- buyer_messages
CREATE TABLE IF NOT EXISTS buyer_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_bc_phone ON buyer_customers(phone);
CREATE INDEX IF NOT EXISTS idx_bc_customer_id ON buyer_customers(customer_id);
CREATE INDEX IF NOT EXISTS idx_bs_customer ON buyer_sessions(customer_id);
CREATE INDEX IF NOT EXISTS idx_bs_status ON buyer_sessions(status);
CREATE INDEX IF NOT EXISTS idx_bm_session ON buyer_messages(session_id);
"""


def _split_sql_statements(sql: str) -> list:
    """分割 SQL 语句"""
    statements = []
    for stmt in sql.split(';'):
        stmt = stmt.strip()
        if not stmt or stmt.startswith('--') or stmt.startswith('/*'):
            continue
        lines = [l for l in stmt.split('\n') if not l.strip().startswith('--')]
        cleaned = '\n'.join(lines).strip()
        if cleaned:
            statements.append(cleaned)
    return statements


def _adapt_sql(sql: str) -> str:
    """将 SQLite SQL 转换为 MySQL 兼容 SQL"""
    import re
    sql = sql.replace('INSERT OR IGNORE', 'INSERT IGNORE')
    sql = re.sub(r"datetime\(\s*'now'\s*,\s*'-?\s*(\d+)\s*days?\s*\)",
                 lambda m: f"DATE_SUB(NOW(), INTERVAL {m.group(1)} DAY)", sql)
    sql = re.sub(r"datetime\(\s*'now'\s*\)", "NOW()", sql)
    sql = sql.replace('?', '%s')
    sql = sql.replace('"', '`')
    return sql


def init_mysql_schema() -> bool:
    """初始化 MySQL 表结构"""
    try:
        import pymysql
        config = _get_mysql_config()
        conn = pymysql.connect(
            host=config["host"],
            port=config["port"],
            user=config["user"],
            password=config["password"],
            charset=config["charset"],
            connect_timeout=10,
            read_timeout=30,
        )
        cursor = conn.cursor()
        statements = _split_sql_statements(MYSQL_SCHEMA)
        for stmt in statements:
            if not stmt.strip():
                continue
            try:
                cursor.execute(stmt)
                conn.commit()
            except Exception as e:
                if 'already exists' not in str(e).lower() and 'duplicate' not in str(e).lower():
                    logger.warning(f"[SQL] {stmt[:80]}... -> {e}")
        cursor.close()
        conn.close()
        logger.info("[BuyerMySQL] 表结构初始化完成")
        return True
    except Exception as e:
        logger.error(f"[BuyerMySQL] 表结构初始化失败: {e}")
        return False


def init_sqlite_schema() -> bool:
    """初始化 SQLite 表结构（回退用）"""
    try:
        from mysql_db_buyer import _get_sqlite_conn
        conn = _get_sqlite_conn()
        statements = _split_sql_statements(SQLITE_SCHEMA)
        for stmt in statements:
            if not stmt.strip():
                continue
            try:
                cursor = conn.cursor()
                cursor.execute(stmt)
                conn.commit()
            except Exception as e:
                if 'already exists' not in str(e).lower():
                    logger.warning(f"[BuyerSQLite] {stmt[:80]}... -> {e}")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.commit()
        logger.info("[BuyerSQLite] 表结构初始化完成")
        return True
    except Exception as e:
        logger.error(f"[BuyerSQLite] 表结构初始化失败: {e}")
        return False


def init_buyer_db_schema():
    """自动选择 MySQL / SQLite 执行建表"""
    if is_mysql():
        logger.info("[BuyerDB] MySQL 模式，正在初始化表结构...")
        init_mysql_schema()
    else:
        logger.info("[BuyerDB] SQLite 回退模式，正在初始化表结构...")
        init_sqlite_schema()


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    parser = argparse.ArgumentParser(description="买方 MySQL 数据库初始化工具")
    parser.add_argument("--mysql", action="store_true", help="强制使用 MySQL")
    parser.add_argument("--sqlite", action="store_true", help="强制使用 SQLite")
    args = parser.parse_args()

    if args.mysql:
        init_mysql_schema()
    elif args.sqlite:
        init_sqlite_schema()
    else:
        init_buyer_db_schema()
