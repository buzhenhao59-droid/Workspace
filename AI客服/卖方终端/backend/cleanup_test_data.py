# -*- coding: utf-8 -*-
"""
清理测试数据脚本
删除测试过程中创建的测试数据，保留系统正常运行所需的数据
"""
import sqlite3
import os
from datetime import datetime
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
DB_PATH = str(_SCRIPT_DIR / "data" / "seller.db")

def get_connection():
    return sqlite3.connect(DB_PATH)

def cleanup_test_data():
    """清理测试数据"""
    print("="*60)
    print("  清理测试数据")
    print("="*60)
    print(f"Database: {DB_PATH}")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    conn = get_connection()
    cursor = conn.cursor()
    
    deleted_counts = {}
    
    # 1. 清理售前备注 (以TEST开头的测试数据)
    cursor.execute("SELECT COUNT(*) FROM pre_sale_notes WHERE customer_name LIKE '%Test%' OR customer_name LIKE '%测试%'")
    count = cursor.fetchone()[0]
    if count > 0:
        cursor.execute("DELETE FROM pre_sale_notes WHERE customer_name LIKE '%Test%' OR customer_name LIKE '%测试%'")
        deleted_counts["pre_sale_notes (测试客户)"] = count
    
    # 2. 清理售后单 (以TEST开头的订单)
    cursor.execute("SELECT COUNT(*) FROM after_sales WHERE order_id LIKE 'TEST%'")
    count = cursor.fetchone()[0]
    if count > 0:
        cursor.execute("DELETE FROM after_sales WHERE order_id LIKE 'TEST%'")
        deleted_counts["after_sales (测试订单)"] = count
    
    # 3. 清理快捷回复 (测试创建的)
    cursor.execute("SELECT COUNT(*) FROM quick_replies WHERE title LIKE '%Test%' OR title LIKE '%测试%'")
    count = cursor.fetchone()[0]
    if count > 0:
        cursor.execute("DELETE FROM quick_replies WHERE title LIKE '%Test%' OR title LIKE '%测试%'")
        deleted_counts["quick_replies (测试)"] = count
    
    # 4. 清理回复模板 (测试创建的)
    cursor.execute("SELECT COUNT(*) FROM reply_templates WHERE name LIKE '%Test%' OR name LIKE '%测试%'")
    count = cursor.fetchone()[0]
    if count > 0:
        cursor.execute("DELETE FROM reply_templates WHERE name LIKE '%Test%' OR name LIKE '%测试%'")
        deleted_counts["reply_templates (测试)"] = count
    
    # 5. 清理测试会话
    cursor.execute("SELECT COUNT(*) FROM sessions WHERE customer_id LIKE 'CUST%' OR customer_id LIKE 'TEST%'")
    count = cursor.fetchone()[0]
    if count > 0:
        cursor.execute("DELETE FROM sessions WHERE customer_id LIKE 'CUST%' OR customer_id LIKE 'TEST%'")
        deleted_counts["sessions (测试)"] = count
    
    # 6. 清理测试客户
    cursor.execute("SELECT COUNT(*) FROM customers WHERE name LIKE '%Test%' OR name LIKE '%测试%' OR phone = '13800138000'")
    count = cursor.fetchone()[0]
    if count > 0:
        cursor.execute("DELETE FROM customers WHERE name LIKE '%Test%' OR name LIKE '%测试%' OR phone = '13800138000'")
        deleted_counts["customers (测试)"] = count
    
    # 7. 清理测试消息
    cursor.execute("SELECT COUNT(*) FROM messages WHERE content LIKE '%Test%' OR content LIKE '%测试%'")
    count = cursor.fetchone()[0]
    if count > 0:
        cursor.execute("DELETE FROM messages WHERE content LIKE '%Test%' OR content LIKE '%测试%'")
        deleted_counts["messages (测试)"] = count
    
    conn.commit()
    
    print("[已删除的测试数据]")
    print("-"*40)
    total_deleted = 0
    for table, count in deleted_counts.items():
        print(f"  {table}: {count} 条")
        total_deleted += count
    
    if total_deleted == 0:
        print("  无测试数据需要清理")
    
    print()
    print(f"总计删除: {total_deleted} 条记录")
    
    # 显示保留的数据统计
    print()
    print("[保留数据统计]")
    print("-"*40)
    tables = [
        "customers", "sessions", "messages", "sellers",
        "pre_sale_notes", "after_sales", "quick_replies",
        "reply_templates", "notifications", "audit_logs"
    ]
    
    for table in tables:
        try:
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            count = cursor.fetchone()[0]
            print(f"  {table}: {count} 条")
        except:
            print(f"  {table}: N/A")
    
    conn.close()
    
    print()
    print("="*60)
    print("  清理完成!")
    print("="*60)
    
    return total_deleted

if __name__ == "__main__":
    cleanup_test_data()
