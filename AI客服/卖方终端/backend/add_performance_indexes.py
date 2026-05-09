# -*- coding: utf-8 -*-
"""
数据库性能索引优化脚本
为常用查询添加索引，提升查询性能

使用方法：
    # 仅查看建议（不执行）
    python add_performance_indexes.py --check
    
    # 执行索引创建
    python add_performance_indexes.py --apply
    
    # 详细输出
    python add_performance_indexes.py --apply --verbose
"""

import os
import sys
import sqlite3
import argparse
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


class PerformanceIndexOptimizer:
    """
    性能索引优化器
    为高频查询创建最优索引
    """
    
    # SQLite 索引定义
    INDEXES = [
        {
            "name": "idx_customers_phone",
            "table": "customers",
            "columns": ["phone"],
            "unique": False,
            "description": "手机号快速查找"
        },
        {
            "name": "idx_customers_email",
            "table": "customers",
            "columns": ["email"],
            "unique": False,
            "description": "邮箱快速查找"
        },
        {
            "name": "idx_sessions_customer_status",
            "table": "sessions",
            "columns": ["customer_id", "status", "created_at"],
            "unique": False,
            "description": "客户会话列表查询"
        },
        {
            "name": "idx_messages_session_created",
            "table": "messages",
            "columns": ["session_id", "created_at"],
            "unique": False,
            "description": "消息历史分页查询"
        },
        {
            "name": "idx_orders_buyer_created",
            "table": "orders",
            "columns": ["buyer_id", "created_at"],
            "unique": False,
            "description": "买家订单列表查询"
        },
        {
            "name": "idx_reviews_status_star_date",
            "table": "reviews",
            "columns": ["status", "star", "created_at"],
            "unique": False,
            "description": "待回复差评查询"
        },
        {
            "name": "idx_audit_logs_operator_time",
            "table": "audit_logs",
            "columns": ["operator", "created_at"],
            "unique": False,
            "description": "审计日志按操作员查询"
        },
        {
            "name": "idx_notifications_user_read",
            "table": "notifications",
            "columns": ["user_id", "is_read"],
            "unique": False,
            "description": "未读通知查询"
        }
    ]
    
    def __init__(self, db_path: str = None):
        if db_path is None:
            # 默认数据库路径
            db_dir = Path(__file__).parent / "data"
            db_dir.mkdir(exist_ok=True)
            db_path = str(db_dir / "seller.db")
        
        self.db_path = db_path
        self.existing_indexes: Dict[str, List[str]] = {}
        self.applied_indexes: List[str] = []
    
    def connect(self) -> sqlite3.Connection:
        """连接数据库"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def get_existing_indexes(self) -> Dict[str, List[str]]:
        """获取已存在的索引"""
        conn = self.connect()
        cursor = conn.cursor()
        
        indexes = {}
        try:
            cursor.execute("""
                SELECT name, tbl_name 
                FROM sqlite_master 
                WHERE type = 'index' 
                AND name NOT LIKE 'sqlite_%'
            """)
            
            for row in cursor.fetchall():
                index_name = row["name"]
                table_name = row["tbl_name"]
                if table_name not in indexes:
                    indexes[table_name] = []
                indexes[table_name].append(index_name)
        finally:
            conn.close()
        
        self.existing_indexes = indexes
        return indexes
    
    def get_table_columns(self, table_name: str) -> List[str]:
        """获取表的所有列"""
        conn = self.connect()
        cursor = conn.cursor()
        
        columns = []
        try:
            cursor.execute(f"PRAGMA table_info({table_name})")
            for row in cursor.fetchall():
                columns.append(row["name"])
        finally:
            conn.close()
        
        return columns
    
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
    
    def check_index_applicable(self, index_def: Dict) -> tuple[bool, str]:
        """
        检查索引是否适用
        
        Returns:
            (is_applicable, reason)
        """
        table_name = index_def["table"]
        columns = index_def["columns"]
        
        # 检查表是否存在
        tables = self.get_all_tables()
        if table_name not in tables:
            return False, f"表 {table_name} 不存在"
        
        # 检查列是否存在
        table_columns = self.get_table_columns(table_name)
        for col in columns:
            if col not in table_columns:
                return False, f"列 {table_name}.{col} 不存在"
        
        # 检查索引是否已存在
        existing = self.existing_indexes.get(table_name, [])
        if index_def["name"] in existing:
            return False, "索引已存在"
        
        return True, "可创建"
    
    def create_index(self, index_def: Dict) -> bool:
        """
        创建索引
        
        Args:
            index_def: 索引定义
            
        Returns:
            是否成功
        """
        is_applicable, reason = self.check_index_applicable(index_def)
        
        if not is_applicable:
            logger.info(f"⏭️  跳过 {index_def['name']}: {reason}")
            return False
        
        table_name = index_def["table"]
        columns = index_def["columns"]
        index_name = index_def["name"]
        unique = "UNIQUE" if index_def.get("unique") else ""
        
        conn = self.connect()
        cursor = conn.cursor()
        
        try:
            sql = f"CREATE {unique} INDEX IF NOT EXISTS {index_name} ON {table_name}({', '.join(columns)})"
            cursor.execute(sql)
            conn.commit()
            
            self.applied_indexes.append(index_name)
            logger.info(f"✅ 创建索引: {index_name} ({table_name}.{', '.join(columns)})")
            return True
            
        except Exception as e:
            logger.error(f"❌ 创建索引失败 {index_name}: {e}")
            return False
        finally:
            conn.close()
    
    def apply_all_indexes(self, verbose: bool = False) -> Dict[str, Any]:
        """
        应用所有适用的索引
        
        Returns:
            应用结果统计
        """
        if verbose:
            logger.setLevel(logging.DEBUG)
        
        self.get_existing_indexes()
        
        stats = {
            "total": len(self.INDEXES),
            "applied": 0,
            "skipped": 0,
            "failed": 0,
            "details": []
        }
        
        logger.info("=" * 60)
        logger.info("开始应用性能索引优化")
        logger.info("=" * 60)
        logger.info(f"数据库: {self.db_path}")
        logger.info("")
        
        for index_def in self.INDEXES:
            is_applicable, reason = self.check_index_applicable(index_def)
            
            detail = {
                "name": index_def["name"],
                "table": index_def["table"],
                "description": index_def["description"],
                "status": "skipped" if not is_applicable else "applied",
                "reason": reason if not is_applicable else None
            }
            
            if is_applicable:
                success = self.create_index(index_def)
                if success:
                    stats["applied"] += 1
                else:
                    stats["failed"] += 1
                    detail["status"] = "failed"
            else:
                stats["skipped"] += 1
            
            stats["details"].append(detail)
        
        logger.info("")
        logger.info("=" * 60)
        logger.info("索引优化完成")
        logger.info(f"✅ 成功: {stats['applied']}")
        logger.info(f"⏭️  跳过: {stats['skipped']}")
        logger.info(f"❌ 失败: {stats['failed']}")
        logger.info("=" * 60)
        
        return stats
    
    def check_indexes(self) -> None:
        """仅检查索引状态"""
        self.get_existing_indexes()
        
        logger.info("=" * 60)
        logger.info("数据库索引检查报告")
        logger.info("=" * 60)
        logger.info(f"数据库: {self.db_path}")
        logger.info("")
        
        # 显示已有索引
        logger.info("📋 已存在的索引:")
        for table, indexes in self.existing_indexes.items():
            for idx in indexes:
                logger.info(f"   ✅ {idx} (表: {table})")
        
        if not self.existing_indexes:
            logger.info("   无自定义索引")
        
        logger.info("")
        logger.info("💡 建议创建的索引:")
        
        for index_def in self.INDEXES:
            is_applicable, reason = self.check_index_applicable(index_def)
            
            if is_applicable:
                logger.info(f"   ➕ {index_def['name']}")
                logger.info(f"      表: {index_def['table']}")
                logger.info(f"      列: {', '.join(index_def['columns'])}")
                logger.info(f"      用途: {index_def['description']}")
                logger.info("")
            else:
                logger.info(f"   ⏭️  {index_def['name']} - {reason}")
        
        logger.info("=" * 60)
        logger.info("")
        logger.info("执行命令:")
        logger.info("  python add_performance_indexes.py --apply")


def main():
    parser = argparse.ArgumentParser(description="数据库索引优化工具")
    parser.add_argument("--check", action="store_true", help="仅检查索引状态")
    parser.add_argument("--apply", action="store_true", help="应用索引优化")
    parser.add_argument("--verbose", action="store_true", help="详细输出")
    args = parser.parse_args()
    
    optimizer = PerformanceIndexOptimizer()
    
    if args.check:
        optimizer.check_indexes()
    elif args.apply:
        optimizer.apply_all_indexes(verbose=args.verbose)
    else:
        print("用法:")
        print("  python add_performance_indexes.py --check   # 仅检查")
        print("  python add_performance_indexes.py --apply   # 应用优化")


if __name__ == "__main__":
    main()
