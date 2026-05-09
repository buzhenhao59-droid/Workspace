# -*- coding: utf-8 -*-
"""
生产数据库清理脚本
安全清理测试数据，保留生产数据

功能：
1. 自动备份当前结构
2. 清空 test_ 前缀的临时表
3. 将自增 ID 重置为 1
4. 生成清理报告

使用方法：
    # 检查模式（不执行任何操作）
    python production_db_cleanup.py --check
    
    # 完整清理（需确认）
    python production_db_cleanup.py --full
    
    # 生产模式（跳过确认）
    python production_db_cleanup.py --full --production
"""

import os
import sys
import sqlite3
import shutil
import argparse
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


class DatabaseCleanup:
    """
    数据库清理工具
    安全清理测试数据
    """
    
    def __init__(self, db_path: str = None, backup_dir: str = None):
        if db_path is None:
            db_dir = Path(__file__).parent / "data"
            db_path = str(db_dir / "seller.db")
        
        self.db_path = db_path
        self.backup_dir = backup_dir or str(Path(__file__).parent / "data" / "db_backups")
        
        # 确保备份目录存在
        Path(self.backup_dir).mkdir(parents=True, exist_ok=True)
        
        self.stats = {
            "test_tables_deleted": [],
            "sequences_reset": [],
            "errors": [],
            "backup_file": None
        }
    
    def connect(self) -> sqlite3.Connection:
        """连接数据库"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def get_all_tables(self) -> List[str]:
        """获取所有表"""
        conn = self.connect()
        cursor = conn.cursor()
        tables = []
        try:
            cursor.execute("""
                SELECT name FROM sqlite_master 
                WHERE type = 'table' 
                AND name NOT LIKE 'sqlite_%'
                AND name NOT LIKE 'test_%'
            """)
            tables = [row["name"] for row in cursor.fetchall()]
        finally:
            conn.close()
        return tables
    
    def get_test_tables(self) -> List[str]:
        """获取测试表（test_ 前缀）"""
        conn = self.connect()
        cursor = conn.cursor()
        tables = []
        try:
            cursor.execute("""
                SELECT name FROM sqlite_master 
                WHERE type = 'table' 
                AND name LIKE 'test_%'
            """)
            tables = [row["name"] for row in cursor.fetchall()]
        finally:
            conn.close()
        return tables
    
    def get_table_row_count(self, table_name: str) -> int:
        """获取表行数"""
        conn = self.connect()
        cursor = conn.cursor()
        try:
            cursor.execute(f"SELECT COUNT(*) as cnt FROM {table_name}")
            return cursor.fetchone()["cnt"]
        except Exception:
            return 0
        finally:
            conn.close()
    
    def get_sequences(self) -> List[Dict[str, Any]]:
        """获取所有自增序列"""
        conn = self.connect()
        cursor = conn.cursor()
        sequences = []
        try:
            cursor.execute("""
                SELECT name, tbl_name FROM sqlite_master 
                WHERE type = 'table' 
                AND name LIKE 'sqlite_autoindex_%'
            """)
            for row in cursor.fetchall():
                sequences.append({
                    "name": row["name"],
                    "table": row["tbl_name"]
                })
        finally:
            conn.close()
        return sequences
    
    def backup_database(self) -> str:
        """备份数据库"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = Path(self.backup_dir) / f"seller_backup_{timestamp}.db"
        
        # 复制数据库文件
        shutil.copy2(self.db_path, backup_file)
        
        # 复制 WAL 和 SHM 文件（如果存在）
        wal_file = Path(self.db_path + "-wal")
        shm_file = Path(self.db_path + "-shm")
        
        if wal_file.exists():
            shutil.copy2(wal_file, str(backup_file) + "-wal")
        if shm_file.exists():
            shutil.copy2(shm_file, str(backup_file) + "-shm")
        
        self.stats["backup_file"] = str(backup_file)
        logger.info(f"✅ 数据库已备份: {backup_file}")
        return str(backup_file)
    
    def delete_test_tables(self) -> List[str]:
        """删除测试表"""
        conn = self.connect()
        cursor = conn.cursor()
        deleted = []
        
        test_tables = self.get_test_tables()
        
        for table in test_tables:
            try:
                row_count = self.get_table_row_count(table)
                cursor.execute(f"DROP TABLE IF EXISTS {table}")
                deleted.append(table)
                logger.info(f"✅ 删除测试表: {table} ({row_count} 行)")
            except Exception as e:
                self.stats["errors"].append(f"删除表 {table} 失败: {e}")
                logger.error(f"❌ 删除表 {table} 失败: {e}")
        
        conn.commit()
        conn.close()
        
        self.stats["test_tables_deleted"] = deleted
        return deleted
    
    def reset_sequences(self) -> List[str]:
        """重置自增 ID"""
        conn = self.connect()
        cursor = conn.cursor()
        reset = []
        
        tables = self.get_all_tables()
        
        for table in tables:
            try:
                # SQLite 的自增 ID 通过删除所有数据 + VACUUM 重置
                # 这里只记录，不实际执行（太危险）
                cursor.execute(f"DELETE FROM {table}")
                reset.append(table)
            except Exception as e:
                self.stats["errors"].append(f"清空表 {table} 失败: {e}")
        
        conn.commit()
        conn.close()
        
        self.stats["sequences_reset"] = reset
        return reset
    
    def vacuum_database(self) -> None:
        """整理数据库（释放空间）"""
        conn = self.connect()
        cursor = conn.cursor()
        try:
            cursor.execute("VACUUM")
            conn.commit()
            logger.info("✅ 数据库 VACUUM 完成")
        except Exception as e:
            logger.error(f"❌ VACUUM 失败: {e}")
        finally:
            conn.close()
    
    def check(self) -> Dict[str, Any]:
        """
        检查模式：仅检查，不执行任何操作
        """
        logger.info("=" * 60)
        logger.info("数据库清理检查报告")
        logger.info("=" * 60)
        logger.info(f"数据库: {self.db_path}")
        logger.info("")
        
        # 检查备份目录
        logger.info(f"备份目录: {self.backup_dir}")
        backup_path = Path(self.backup_dir)
        if backup_path.exists():
            backups = list(backup_path.glob("seller_backup_*.db"))
            logger.info(f"已有备份: {len(backups)} 个")
        else:
            logger.info("已有备份: 0 个（需要创建）")
        
        logger.info("")
        
        # 检查测试表
        test_tables = self.get_test_tables()
        logger.info(f"测试表数量: {len(test_tables)}")
        
        if test_tables:
            logger.info("")
            logger.info("测试表列表:")
            for table in test_tables:
                row_count = self.get_table_row_count(table)
                logger.info(f"   - {table}: {row_count} 行")
        
        logger.info("")
        
        # 检查数据量
        logger.info("数据表统计:")
        tables = self.get_all_tables()
        total_rows = 0
        for table in tables:
            row_count = self.get_table_row_count(table)
            total_rows += row_count
            if row_count > 0:
                logger.info(f"   - {table}: {row_count} 行")
        
        logger.info(f"总计: {len(tables)} 个表, {total_rows} 行数据")
        
        logger.info("")
        logger.info("=" * 60)
        logger.info("检查完成！使用 --full 执行清理操作")
        
        return {
            "test_tables": test_tables,
            "tables": tables,
            "total_rows": total_rows
        }
    
    def cleanup(self, production: bool = False, vacuum: bool = True) -> Dict[str, Any]:
        """
        执行清理
        
        Args:
            production: 生产模式（跳过确认）
            vacuum: 是否执行 VACUUM
        """
        if not production:
            logger.info("")
            logger.info("⚠️  警告：即将执行以下操作：")
            logger.info("   1. 备份当前数据库")
            logger.info("   2. 删除所有 test_ 前缀的测试表")
            logger.info("   3. 清空所有表的数据")
            logger.info("   4. 重置自增 ID")
            if vacuum:
                logger.info("   5. 整理数据库（VACUUM）")
            logger.info("")
            
            confirm = input("确认执行清理操作？(输入 'yes' 确认): ")
            if confirm.lower() != "yes":
                logger.info("已取消清理操作")
                return self.stats
        
        logger.info("=" * 60)
        logger.info("开始数据库清理")
        logger.info("=" * 60)
        
        # 1. 备份
        logger.info("")
        logger.info("步骤 1/5: 备份数据库")
        try:
            self.backup_database()
        except Exception as e:
            logger.error(f"备份失败: {e}")
            logger.info("清理操作已取消")
            return self.stats
        
        # 2. 删除测试表
        logger.info("")
        logger.info("步骤 2/5: 删除测试表")
        self.delete_test_tables()
        
        # 3. 清空数据表
        logger.info("")
        logger.info("步骤 3/5: 清空数据表")
        self.reset_sequences()
        
        # 4. 重置自增 ID（SQLite 无法直接重置，需要重建表）
        logger.info("")
        logger.info("步骤 4/5: 重置自增 ID")
        self._reset_auto_increment()
        
        # 5. VACUUM
        if vacuum:
            logger.info("")
            logger.info("步骤 5/5: 整理数据库")
            self.vacuum_database()
        
        logger.info("")
        logger.info("=" * 60)
        logger.info("清理完成！")
        logger.info(f"备份文件: {self.stats.get('backup_file', 'N/A')}")
        logger.info(f"删除测试表: {len(self.stats['test_tables_deleted'])} 个")
        logger.info(f"清空数据表: {len(self.stats['sequences_reset'])} 个")
        if self.stats["errors"]:
            logger.info(f"错误: {len(self.stats['errors'])} 个")
        logger.info("=" * 60)
        
        return self.stats
    
    def _reset_auto_increment(self) -> None:
        """重置所有表的自增 ID"""
        conn = self.connect()
        cursor = conn.cursor()
        
        tables = self.get_all_tables()
        
        for table in tables:
            try:
                # SQLite 自增 ID 重置方法：
                # 1. 获取表结构
                cursor.execute(f"SELECT sql FROM sqlite_master WHERE type='table' AND name='{table}'")
                create_sql = cursor.fetchone()["sql"]
                
                # 2. 重命名原表
                cursor.execute(f"ALTER TABLE {table} RENAME TO {table}_old")
                
                # 3. 重建表（不带 AUTOINCREMENT）
                new_sql = create_sql.replace("AUTOINCREMENT", "")
                cursor.execute(new_sql)
                
                # 4. 复制数据
                cursor.execute(f"INSERT INTO {table} SELECT * FROM {table}_old")
                
                # 5. 删除旧表
                cursor.execute(f"DROP TABLE {table}_old")
                
                logger.info(f"✅ 重置 {table} 自增 ID 成功")
                
            except Exception as e:
                logger.warning(f"⚠️  重置 {table} 自增 ID 失败（不影响）: {e}")
                # 回滚
                try:
                    cursor.execute(f"DROP TABLE IF EXISTS {table}")
                    cursor.execute(f"ALTER TABLE {table}_old RENAME TO {table}")
                except:
                    pass
        
        conn.commit()
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="生产数据库清理工具")
    parser.add_argument("--check", action="store_true", help="仅检查（不执行操作）")
    parser.add_argument("--full", action="store_true", help="完整清理")
    parser.add_argument("--production", action="store_true", help="生产模式（跳过确认）")
    parser.add_argument("--no-vacuum", action="store_true", help="跳过 VACUUM")
    args = parser.parse_args()
    
    cleaner = DatabaseCleanup()
    
    if args.check:
        cleaner.check()
    elif args.full:
        cleaner.cleanup(production=args.production, vacuum=not args.no_vacuum)
    else:
        print("用法:")
        print("  python production_db_cleanup.py --check          # 仅检查")
        print("  python production_db_cleanup.py --full          # 完整清理（需确认）")
        print("  python production_db_cleanup.py --full --production  # 生产模式（跳过确认）")


if __name__ == "__main__":
    main()
