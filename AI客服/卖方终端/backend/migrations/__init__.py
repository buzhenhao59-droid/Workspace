# -*- coding: utf-8 -*-
"""
Flyway 风格数据库迁移脚本
用于 MySQL schema 版本化管理

使用方式:
    # 创建新迁移
    python -m migrations create add_customer_tags

    # 运行所有待执行迁移
    python -m migrations upgrade

    # 查看当前版本
    python -m migrations version

    # 回滚一个版本
    python -m migrations downgrade

迁移文件命名规范:
    V{版本号}__{描述}.sql
    例: V001__add_customer_tags.sql
        V002__add_session_metadata.sql
        R001__rollback_customer_tags.sql  (回滚脚本)

版本表自动创建（首次运行 upgrade 时）
"""
import os
import re
import sys
import hashlib
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Tuple

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ============== 配置 ==============
MIGRATIONS_DIR = Path(__file__).parent / "migrations"
SCHEMA_TABLE = "schema_migrations"

# MySQL 连接配置（从环境变量读取）
MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "123456")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "ruitalk")


def _get_connection():
    """获取 MySQL 连接"""
    try:
        import pymysql
        conn = pymysql.connect(
            host=MYSQL_HOST,
            port=MYSQL_PORT,
            user=MYSQL_USER,
            password=MYSQL_PASSWORD,
            database=MYSQL_DATABASE,
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=False
        )
        return conn
    except ImportError:
        logger.error("请安装 pymysql: pip install pymysql")
        sys.exit(1)
    except Exception as e:
        logger.error(f"MySQL 连接失败: {e}")
        sys.exit(1)


def _ensure_schema_table(conn):
    """确保版本记录表存在"""
    cursor = conn.cursor()
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS `{SCHEMA_TABLE}` (
            version VARCHAR(50) PRIMARY KEY,
            description VARCHAR(255) NOT NULL,
            checksum VARCHAR(64) NOT NULL,
            applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            rolled_back_at DATETIME NULL,
            rollback_version VARCHAR(50) NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """)
    conn.commit()
    cursor.close()


def _get_applied_versions(conn) -> set:
    """获取已执行版本"""
    _ensure_schema_table(conn)
    cursor = conn.cursor()
    cursor.execute(f"SELECT version FROM `{SCHEMA_TABLE}` WHERE rolled_back_at IS NULL")
    versions = {row["version"] for row in cursor.fetchall()}
    cursor.close()
    return versions


def _get_pending_migrations(conn) -> List[Tuple[str, str]]:
    """
    获取待执行的迁移
    返回: [(version, description, filepath), ...]
    """
    applied = _get_applied_versions(conn)
    pending = []

    if not MIGRATIONS_DIR.exists():
        logger.info(f"迁移目录不存在: {MIGRATIONS_DIR}，将自动创建")
        MIGRATIONS_DIR.mkdir(parents=True, exist_ok=True)
        return pending

    sql_files = sorted(MIGRATIONS_DIR.glob("V*.sql"))
    for f in sql_files:
        m = re.match(r'^V(\d+)__(.+)\.sql$', f.name)
        if not m:
            continue
        version = f"V{m.group(1).lstrip('0') or '0'}"
        if m.group(1):
            version = f"V{m.group(1)}"
        if version not in applied:
            pending.append((version, m.group(2), str(f)))

    return pending


def _compute_checksum(filepath: str) -> str:
    """计算文件 MD5"""
    with open(filepath, 'rb') as f:
        return hashlib.md5(f.read()).hexdigest()


def _upgrade(conn):
    """执行所有待执行迁移"""
    pending = _get_pending_migrations(conn)
    if not pending:
        logger.info("没有待执行的迁移")
        return

    logger.info(f"发现 {len(pending)} 个待执行迁移:")
    for v, desc, _ in pending:
        logger.info(f"  {v}: {desc}")

    cursor = conn.cursor()
    for version, description, filepath in pending:
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                sql_content = f.read()

            logger.info(f"执行迁移 {version}: {description}...")
            for statement in sql_content.split(';'):
                stmt = stmt.strip()
                if stmt:
                    cursor.execute(stmt)
            conn.commit()

            checksum = _compute_checksum(filepath)
            cursor.execute(
                f"INSERT INTO `{SCHEMA_TABLE}` (version, description, checksum) VALUES (%s, %s, %s)",
                (version, description, checksum)
            )
            conn.commit()
            logger.info(f"  [OK] {version} 已执行")

        except Exception as e:
            conn.rollback()
            logger.error(f"  [FAIL] {version} 执行失败: {e}")
            raise

    cursor.close()


def _version(conn):
    """查看当前版本"""
    _ensure_schema_table(conn)
    cursor = conn.cursor()
    cursor.execute(f"""
        SELECT version, description, applied_at
        FROM `{SCHEMA_TABLE}`
        WHERE rolled_back_at IS NULL
        ORDER BY applied_at DESC
        LIMIT 10
    """)
    rows = cursor.fetchall()
    cursor.close()

    if not rows:
        logger.info("尚未执行任何迁移")
        return

    logger.info(f"当前版本: {rows[0]['version']} ({rows[0]['description']})")
    logger.info(f"执行时间: {rows[0]['applied_at']}")
    if len(rows) > 1:
        logger.info("历史版本:")
        for r in rows[1:]:
            logger.info(f"  {r['version']}: {r['description']} ({r['applied_at']})")


def _create(name: str):
    """创建新的迁移文件"""
    MIGRATIONS_DIR.mkdir(parents=True, exist_ok=True)

    existing = list(MIGRATIONS_DIR.glob("V*.sql"))
    if existing:
        latest = max(existing, key=lambda f: f.name)
        m = re.match(r'^V(\d+)__', latest.name)
        next_num = int(m.group(1)) + 1 if m else 1
    else:
        next_num = 1

    version = f"V{next_num:03d}"
    filename = f"{version}__{name}.sql"
    filepath = MIGRATIONS_DIR / filename

    content = f"""-- ============================================================
-- 迁移: {version} - {name}
-- 创建时间: {datetime.now().isoformat()}
-- 说明: [填写迁移说明]
-- ============================================================

-- 执行迁移
BEGIN;

-- TODO: 添加你的 SQL 语句


COMMIT;

-- ============================================================
-- 回滚（仅记录，操作时复制上方 SQL 并反向修改）
-- ============================================================
-- R001__rollback_{name}.sql
"""
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

    logger.info(f"已创建迁移文件: {filepath}")
    logger.info("请编辑此文件，填写实际的 SQL 语句")


def _downgrade(conn, steps: int = 1):
    """回滚指定数量的迁移"""
    cursor = conn.cursor()
    cursor.execute(f"""
        SELECT version, description, applied_at
        FROM `{SCHEMA_TABLE}`
        WHERE rolled_back_at IS NULL
        ORDER BY applied_at DESC
        LIMIT %s
    """, (steps,))
    to_rollback = cursor.fetchall()
    cursor.close()

    if not to_rollback:
        logger.info("没有可回滚的迁移")
        return

    for row in to_rollback:
        logger.info(f"回滚: {row['version']} - {row['description']}")

    logger.warning("注意：请确保已创建回滚脚本（命名: R*__rollback_*.sql）")
    logger.warning("手动回滚后，运行以下 SQL 更新版本记录：")
    for row in to_rollback:
        logger.warning(
            f"  UPDATE `{SCHEMA_TABLE}` SET rolled_back_at=NOW() WHERE version='{row['version']}';"
        )


# ============== CLI 入口 ==============
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python -m migrations [command] [args]")
        print("  upgrade        - 执行所有待执行迁移")
        print("  version        - 查看当前版本")
        print("  create <name>  - 创建新迁移文件")
        print("  downgrade [n]  - 回滚 n 个迁移（默认 1）")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "upgrade":
        conn = _get_connection()
        try:
            _upgrade(conn)
        finally:
            conn.close()

    elif cmd == "version":
        conn = _get_connection()
        try:
            _version(conn)
        finally:
            conn.close()

    elif cmd == "create":
        if len(sys.argv) < 3:
            logger.error("请提供迁移名称: python -m migrations create add_customer_tags")
            sys.exit(1)
        _create(sys.argv[2])

    elif cmd == "downgrade":
        steps = int(sys.argv[2]) if len(sys.argv) > 2 else 1
        conn = _get_connection()
        try:
            _downgrade(conn, steps)
        finally:
            conn.close()

    else:
        logger.error(f"未知命令: {cmd}")
        sys.exit(1)
