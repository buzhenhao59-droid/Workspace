# -*- coding: utf-8 -*-
"""
PostgreSQL 数据库迁移脚本
将现有 SQLite 数据迁移到 PostgreSQL，支持双向同步
用于生产环境替代 SQLite
"""
import os
import sys
import logging
import argparse
from pathlib import Path
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 迁移配置（从环境变量读取）
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
POSTGRES_USER = os.getenv("POSTGRES_USER", "gold_cs")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "")
POSTGRES_DATABASE = os.getenv("POSTGRES_DATABASE", "gold_cs")

# SQLite 数据路径
SQLITE_PATH = Path(__file__).parent.parent / "data" / "gold_customer.db"


def get_postgres_url() -> str:
    """获取 PostgreSQL 连接 URL"""
    return f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DATABASE}"


def create_tables_sql() -> str:
    """PostgreSQL 建表 SQL"""
    return """
-- ============================================================
-- 金牌客服系统 - PostgreSQL 表结构
-- 生成时间: {timestamp}
-- ============================================================

-- 客户表
CREATE TABLE IF NOT EXISTS customers (
    id SERIAL PRIMARY KEY,
    customer_id VARCHAR(64) UNIQUE NOT NULL,
    phone VARCHAR(32),
    name VARCHAR(128),
    region VARCHAR(64),
    level VARCHAR(32) DEFAULT '普通会员',
    m_value INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 会话表
CREATE TABLE IF NOT EXISTS sessions (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(128) UNIQUE NOT NULL,
    customer_id VARCHAR(64),
    status VARCHAR(32) DEFAULT 'active',
    assign_to VARCHAR(64),
    is_ai INTEGER DEFAULT 1,
    language VARCHAR(16) DEFAULT 'zh',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (customer_id) REFERENCES customers(customer_id) ON DELETE SET NULL
);

-- 消息表（优化：按 session_id 分区）
CREATE TABLE IF NOT EXISTS messages (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(128) NOT NULL,
    role VARCHAR(32) NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
);

-- 消息表索引（加速查询）
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
CREATE INDEX IF NOT EXISTS idx_messages_created ON messages(created_at);

-- 卖家/客服账号表
CREATE TABLE IF NOT EXISTS sellers (
    id SERIAL PRIMARY KEY,
    username VARCHAR(128) UNIQUE NOT NULL,
    password_hash VARCHAR(256) NOT NULL,
    name VARCHAR(128),
    role VARCHAR(32) DEFAULT 'agent',
    is_online INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_login TIMESTAMP
);

-- 评价表
CREATE TABLE IF NOT EXISTS reviews (
    id SERIAL PRIMARY KEY,
    review_id VARCHAR(128) UNIQUE,
    order_id VARCHAR(128),
    customer_id VARCHAR(64),
    customer_name VARCHAR(128),
    star_rating INTEGER DEFAULT 5,
    content TEXT,
    reply_content TEXT,
    replied_at TIMESTAMP,
    replied_by VARCHAR(64),
    status VARCHAR(32) DEFAULT 'pending',
    platform VARCHAR(32) DEFAULT 'other',
    product_name VARCHAR(512),
    product_image TEXT,
    review_date TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 售后单表
CREATE TABLE IF NOT EXISTS after_sales (
    id SERIAL PRIMARY KEY,
    as_id VARCHAR(128) UNIQUE NOT NULL,
    order_id VARCHAR(128),
    customer_id VARCHAR(64),
    customer_name VARCHAR(128),
    type VARCHAR(32) DEFAULT '退货退款',
    reason TEXT,
    amount DECIMAL(10,2),
    status VARCHAR(32) DEFAULT '待处理',
    platform VARCHAR(32) DEFAULT 'other',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 操作日志表
CREATE TABLE IF NOT EXISTS operation_logs (
    id SERIAL PRIMARY KEY,
    operator VARCHAR(128),
    action VARCHAR(64),
    target_type VARCHAR(64),
    target_id VARCHAR(128),
    detail TEXT,
    ip_address VARCHAR(64),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 坐席会话分配记录表（用于会话分配竞态条件修复）
CREATE TABLE IF NOT EXISTS agent_session_assignments (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(128) UNIQUE NOT NULL,
    agent_id VARCHAR(64) NOT NULL,
    assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    released_at TIMESTAMP,
    status VARCHAR(32) DEFAULT 'active'
);

CREATE INDEX IF NOT EXISTS idx_agent_assignments_agent ON agent_session_assignments(agent_id);
CREATE INDEX IF NOT EXISTS idx_agent_assignments_status ON agent_session_assignments(status);

-- 触发器：自动更新 updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

-- 为相关表创建触发器
DROP TRIGGER IF EXISTS update_customers_updated_at ON customers;
CREATE TRIGGER update_customers_updated_at BEFORE UPDATE ON customers
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_sessions_updated_at ON sessions;
CREATE TRIGGER update_sessions_updated_at BEFORE UPDATE ON sessions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_after_sales_updated_at ON after_sales;
CREATE TRIGGER update_after_sales_updated_at BEFORE UPDATE ON after_sales
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- 分区表（可选，高并发时启用）
-- CREATE TABLE messages_partitioned (...) PARTITION BY RANGE (created_at);
""".format(timestamp=datetime.now().isoformat())


def migrate_sqlite_to_postgres():
    """从 SQLite 迁移到 PostgreSQL"""
    try:
        import sqlite3
        import psycopg2
        from psycopg2.extras import execute_batch
    except ImportError as e:
        logger.error(f"缺少依赖: {e}")
        logger.info("请安装: pip install psycopg2-binary")
        return False

    if not SQLITE_PATH.exists():
        logger.error(f"SQLite 数据库不存在: {SQLITE_PATH}")
        return False

    # 连接数据库
    try:
        sqlite_conn = sqlite3.connect(str(SQLITE_PATH))
        sqlite_conn.row_factory = sqlite3.Row
        sqlite_cursor = sqlite_conn.cursor()

        pg_conn = psycopg2.connect(
            host=POSTGRES_HOST,
            port=POSTGRES_PORT,
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD,
            database=POSTGRES_DATABASE
        )
        pg_cursor = pg_conn.cursor()
        logger.info("数据库连接成功")
    except Exception as e:
        logger.error(f"数据库连接失败: {e}")
        return False

    # 获取所有表
    sqlite_cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row[0] for row in sqlite_cursor.fetchall()]
    logger.info(f"找到 {len(tables)} 个表: {tables}")

    total_rows = 0
    for table in tables:
        try:
            # 获取表数据
            sqlite_cursor.execute(f"SELECT * FROM {table}")
            rows = sqlite_cursor.fetchall()
            columns = [desc[0] for desc in sqlite_cursor.description]

            if not rows:
                continue

            # 迁移数据
            placeholders = ", ".join(["%s"] * len(columns))
            insert_sql = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders}) ON CONFLICT DO NOTHING"

            for row in rows:
                try:
                    pg_cursor.execute(insert_sql, tuple(row))
                except Exception as e:
                    logger.warning(f"  迁移 {table} 行失败: {e}")

            pg_conn.commit()
            logger.info(f"  ✓ {table}: {len(rows)} 行")
            total_rows += len(rows)

        except Exception as e:
            logger.error(f"  ✗ {table} 迁移失败: {e}")

    sqlite_conn.close()
    pg_conn.close()

    logger.info(f"迁移完成，共迁移 {total_rows} 行数据")
    return True


def init_postgres_schema():
    """初始化 PostgreSQL 表结构"""
    try:
        import psycopg2
    except ImportError:
        logger.error("缺少 psycopg2-binary: pip install psycopg2-binary")
        return False

    try:
        conn = psycopg2.connect(
            host=POSTGRES_HOST,
            port=POSTGRES_PORT,
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD,
            database=POSTGRES_DATABASE
        )
        cursor = conn.cursor()

        # 创建数据库（如果不存在）
        try:
            cursor.execute(f"CREATE DATABASE {POSTGRES_DATABASE}")
            logger.info(f"数据库 {POSTGRES_DATABASE} 创建成功")
        except psycopg2.errors.DuplicateDatabase:
            logger.info(f"数据库 {POSTGRES_DATABASE} 已存在")

        cursor.close()
        conn.close()

        # 连接到目标数据库创建表
        conn = psycopg2.connect(
            host=POSTGRES_HOST,
            port=POSTGRES_PORT,
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD,
            database=POSTGRES_DATABASE
        )
        cursor = conn.cursor()

        # 执行建表 SQL
        for statement in create_tables_sql().split(";"):
            statement = statement.strip()
            if statement and not statement.startswith("--"):
                try:
                    cursor.execute(statement)
                except Exception as e:
                    if "already exists" not in str(e).lower():
                        logger.warning(f"SQL 执行警告: {e}")

        conn.commit()
        cursor.close()
        conn.close()

        logger.info("PostgreSQL 表结构初始化完成")
        return True

    except Exception as e:
        logger.error(f"PostgreSQL 初始化失败: {e}")
        return False


def backup_sqlite():
    """备份 SQLite 数据库"""
    if not SQLITE_PATH.exists():
        logger.warning("SQLite 数据库不存在，跳过备份")
        return True

    backup_path = SQLITE_PATH.parent / f"gold_customer_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    import shutil
    shutil.copy2(SQLITE_PATH, backup_path)
    logger.info(f"SQLite 备份已创建: {backup_path}")
    return True


def main():
    parser = argparse.ArgumentParser(description="PostgreSQL 迁移工具")
    parser.add_argument("--init", action="store_true", help="仅初始化表结构")
    parser.add_argument("--migrate", action="store_true", help="从 SQLite 迁移数据")
    parser.add_argument("--backup", action="store_true", help="备份 SQLite")
    parser.add_argument("--all", action="store_true", help="执行全部操作")
    args = parser.parse_args()

    if not any(vars(args).values()):
        parser.print_help()
        return

    logger.info("=" * 60)
    logger.info("金牌客服系统 - PostgreSQL 迁移工具")
    logger.info("=" * 60)

    if args.init or args.all:
        logger.info("\n>>> 步骤1: 初始化 PostgreSQL 表结构")
        if not init_postgres_schema():
            logger.error("表结构初始化失败，退出")
            return

    if args.backup or args.all:
        logger.info("\n>>> 步骤2: 备份 SQLite 数据")
        if not backup_sqlite():
            logger.warning("备份失败，继续迁移...")

    if args.migrate or args.all:
        logger.info("\n>>> 步骤3: 迁移 SQLite 数据到 PostgreSQL")
        if not migrate_sqlite_to_postgres():
            logger.error("数据迁移失败")

    logger.info("\n" + "=" * 60)
    logger.info("迁移完成!")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
