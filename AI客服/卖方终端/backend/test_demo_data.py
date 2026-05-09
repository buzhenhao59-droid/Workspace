# -*- coding: utf-8 -*-
"""
演示数据自测脚本
验证三库数据完整性和 API 链路可用性
"""
import os, sys, json
from pathlib import Path

# 确保项目路径在 sys.path
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

DATA_DIR = SCRIPT_DIR / "data"
os.environ.setdefault("USE_SQLITE_FALLBACK", "true")
os.environ.setdefault("SHOP_USE_MYSQL", "false")

def count_rows(db_path, table):
    """快速统计表行数"""
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    try:
        cur.execute(f"SELECT COUNT(*) as c FROM {table}")
        return cur.fetchone()["c"]
    except:
        return -1
    finally:
        conn.close()

def check_reviews_in_seller_db():
    """检查 seller.db 的 reviews 表"""
    import sqlite3
    conn = sqlite3.connect(str(DATA_DIR / "seller.db"))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) as c, COUNT(CASE WHEN status='pending' THEN 1 END) as pending, COUNT(CASE WHEN status='replied' THEN 1 END) as replied FROM reviews")
    row = cur.fetchone()
    cur.execute("SELECT star_rating, status, customer_name FROM reviews LIMIT 3")
    samples = [dict(r) for r in cur.fetchall()]
    conn.close()
    return dict(row), samples

def check_notifications():
    """检查 notifications 表"""
    import sqlite3
    conn = sqlite3.connect(str(DATA_DIR / "seller.db"))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) as c, COUNT(CASE WHEN is_read=0 THEN 1 END) as unread FROM notifications")
    row = cur.fetchone()
    cur.execute("SELECT title, is_read, notification_type FROM notifications LIMIT 3")
    samples = [dict(r) for r in cur.fetchall()]
    conn.close()
    return dict(row), samples

def check_audit_logs():
    """检查 audit_logs 表"""
    import sqlite3
    conn = sqlite3.connect(str(DATA_DIR / "seller.db"))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) as c FROM audit_logs")
    row = cur.fetchone()
    cur.execute("SELECT event_type, operator, created_at FROM audit_logs LIMIT 3")
    samples = [dict(r) for r in cur.fetchall()]
    conn.close()
    return dict(row), samples

def check_shop_db():
    """检查 shop_manager.db"""
    issues = []
    checks = {
        "shops": count_rows(DATA_DIR / "shop_manager.db", "shops"),
        "products": count_rows(DATA_DIR / "shop_manager.db", "products"),
        "product_skus": count_rows(DATA_DIR / "shop_manager.db", "product_skus"),
        "inventory": count_rows(DATA_DIR / "shop_manager.db", "inventory"),
        "pricing_rules": count_rows(DATA_DIR / "shop_manager.db", "pricing_rules"),
        "shop_products": count_rows(DATA_DIR / "shop_manager.db", "shop_products"),
        "collect_history": count_rows(DATA_DIR / "shop_manager.db", "collect_history"),
    }
    for name, count in checks.items():
        if count <= 0:
            issues.append(f"  [!] {name}: {count} 条（预期 > 0）")
    return checks, issues

def check_sync_db():
    """检查 platform_sync.db"""
    issues = []
    checks = {
        "sync_orders": count_rows(DATA_DIR / "platform_sync.db", "sync_orders"),
        "sync_returns": count_rows(DATA_DIR / "platform_sync.db", "sync_returns"),
        "sync_reviews": count_rows(DATA_DIR / "platform_sync.db", "sync_reviews"),
    }
    for name, count in checks.items():
        if count <= 0:
            issues.append(f"  [!] {name}: {count} 条（预期 > 0）")
    return checks, issues

def check_db_funcs():
    """验证 db.py 函数能否正常调用"""
    errors = []
    try:
        from db import get_reviews, get_review_stats, get_audit_logs
        from db import get_notifications, get_advanced_stats
        from db import get_after_sales, get_after_sale_stats

        rows, total = get_reviews(limit=5, page=1)
        if total == 0:
            errors.append(f"  [!] get_reviews: total=0（预期 > 0）")
        else:
            print(f"  [OK] get_reviews: total={total}")

        stats = get_review_stats()
        if stats.get("total", 0) == 0:
            errors.append(f"  [!] get_review_stats: total=0（预期 > 0）")
        else:
            print(f"  [OK] get_review_stats: {stats}")

        logs, log_total = get_audit_logs(page=1, page_size=5)
        if log_total == 0:
            errors.append(f"  [!] get_audit_logs: total=0（预期 > 0）")
        else:
            print(f"  [OK] get_audit_logs: total={log_total}")

        notifs, notif_total = get_notifications(limit=5)
        if notif_total == 0:
            errors.append(f"  [!] get_notifications: total=0（预期 > 0）")
        else:
            print(f"  [OK] get_notifications: total={notif_total}")

        adv = get_advanced_stats()
        if adv.get("total_customers", 0) == 0:
            errors.append(f"  [!] get_advanced_stats: total_customers=0（预期 > 0）")
        else:
            print(f"  [OK] get_advanced_stats: total_customers={adv.get('total_customers')}")

        sales, sales_total = get_after_sales(page=1, page_size=5)
        if sales_total == 0:
            errors.append(f"  [!] get_after_sales: total=0（预期 > 0）")
        else:
            print(f"  [OK] get_after_sales: total={sales_total}")

        sale_stats = get_after_sale_stats()
        print(f"  [OK] get_after_sale_stats: {sale_stats}")

    except Exception as e:
        errors.append(f"  [!] db.py 函数调用失败: {e}")
    return errors

def check_shop_funcs():
    """验证 shop_db.py 函数能否正常调用"""
    errors = []
    try:
        from shop import shop_db as db

        shops = db.get_shops()
        if len(shops) == 0:
            errors.append(f"  [!] shop_db.get_shops: 0 条（预期 > 0）")
        else:
            print(f"  [OK] shop_db.get_shops: {len(shops)} 条")

        prods = db.get_products(page=1, page_size=5)
        if prods.get("total", 0) == 0:
            errors.append(f"  [!] shop_db.get_products: total=0（预期 > 0）")
        else:
            print(f"  [OK] shop_db.get_products: total={prods.get('total')}")

        inv = db.get_inventory(sku_id=None, shop_id=None)
        if not inv:
            errors.append(f"  [!] shop_db.get_inventory: 空（预期 > 0）")
        else:
            print(f"  [OK] shop_db.get_inventory: {len(inv)} 条")

        rules = db.get_pricing_rules()
        if not rules:
            errors.append(f"  [!] shop_db.get_pricing_rules: 空（预期 > 0）")
        else:
            print(f"  [OK] shop_db.get_pricing_rules: {len(rules)} 条")

        stats = db.get_dashboard_stats()
        print(f"  [OK] shop_db.get_dashboard_stats: {stats}")

    except Exception as e:
        errors.append(f"  [!] shop_db 函数调用失败: {e}")
    return errors

def check_sync_funcs():
    """验证 platform_sync.py 能否正常调用"""
    errors = []
    try:
        from platform_sync import get_synced_reviews, _ensure_sync_db

        _ensure_sync_db()
        rows, total = get_synced_reviews(status="", platform="", page=1, page_size=5)
        if total == 0:
            errors.append(f"  [!] platform_sync.get_synced_reviews: total=0（预期 > 0）")
        else:
            print(f"  [OK] platform_sync.get_synced_reviews: total={total}")

    except Exception as e:
        errors.append(f"  [!] platform_sync 函数调用失败: {e}")
    return errors

# ============== 主检查流程 ==============
if __name__ == "__main__":
    print("=" * 60)
    print("  Ruitalk 演示数据自测")
    print("=" * 60)

    all_pass = True

    # 1. seller.db
    print("\n[1] seller.db 表数据量检查")
    for table, cnt in [
        ("sellers", count_rows(DATA_DIR / "seller.db", "sellers")),
        ("customers", count_rows(DATA_DIR / "seller.db", "customers")),
        ("sessions", count_rows(DATA_DIR / "seller.db", "sessions")),
        ("messages", count_rows(DATA_DIR / "seller.db", "messages")),
        ("after_sales", count_rows(DATA_DIR / "seller.db", "after_sales")),
        ("pre_sale_notes", count_rows(DATA_DIR / "seller.db", "pre_sale_notes")),
        ("quick_replies", count_rows(DATA_DIR / "seller.db", "quick_replies")),
        ("notifications", count_rows(DATA_DIR / "seller.db", "notifications")),
        ("audit_logs", count_rows(DATA_DIR / "seller.db", "audit_logs")),
        ("reviews", count_rows(DATA_DIR / "seller.db", "reviews")),
        ("reply_templates", count_rows(DATA_DIR / "seller.db", "reply_templates")),
        ("auto_reply_rules", count_rows(DATA_DIR / "seller.db", "auto_reply_rules")),
    ]:
        status = "[OK]" if cnt > 0 else "[!!]"
        if cnt <= 0:
            all_pass = False
        print(f"  {status} {table}: {cnt} 条")

    # 2. seller.db 详细检查
    print("\n[2] seller.db 关键表内容抽检")
    rev_data, rev_samples = check_reviews_in_seller_db()
    print(f"  [OK] reviews: total={rev_data['c']}, pending={rev_data['pending']}, replied={rev_data['replied']}")
    for s in rev_samples:
        print(f"      - {s['star_rating']}星 [{s['status']}] {s['customer_name']}")

    notif_data, notif_samples = check_notifications()
    print(f"  [OK] notifications: total={notif_data['c']}, unread={notif_data['unread']}")
    for s in notif_samples:
        print(f"      - [{s['notification_type']}] read={s['is_read']} {s['title'][:30]}")

    audit_data, audit_samples = check_audit_logs()
    print(f"  [OK] audit_logs: total={audit_data['c']}")
    for s in audit_samples:
        print(f"      - {s['event_type']} by {s['operator']}")

    # 3. shop_manager.db
    print("\n[3] shop_manager.db 表数据量检查")
    shop_data, shop_issues = check_shop_db()
    for name, cnt in shop_data.items():
        status = "[OK]" if cnt > 0 else "[!!]"
        if cnt <= 0:
            all_pass = False
        print(f"  {status} {name}: {cnt} 条")
    for issue in shop_issues:
        print(issue)

    # 4. platform_sync.db
    print("\n[4] platform_sync.db 表数据量检查")
    sync_data, sync_issues = check_sync_db()
    for name, cnt in sync_data.items():
        status = "[OK]" if cnt > 0 else "[!!]"
        if cnt <= 0:
            all_pass = False
        print(f"  {status} {name}: {cnt} 条")
    for issue in sync_issues:
        print(issue)

    # 5. db.py 函数层
    print("\n[5] db.py 函数调用验证")
    db_errors = check_db_funcs()
    if db_errors:
        all_pass = False
        for e in db_errors:
            print(e)
    else:
        print("  [OK] 所有 db.py 函数调用正常")

    # 6. shop_db.py 函数层
    print("\n[6] shop_db.py 函数调用验证")
    shop_func_errors = check_shop_funcs()
    if shop_func_errors:
        all_pass = False
        for e in shop_func_errors:
            print(e)
    else:
        print("  [OK] 所有 shop_db.py 函数调用正常")

    # 7. platform_sync.py 函数层
    print("\n[7] platform_sync.py 函数调用验证")
    sync_func_errors = check_sync_funcs()
    if sync_func_errors:
        all_pass = False
        for e in sync_func_errors:
            print(e)
    else:
        print("  [OK] 所有 platform_sync.py 函数调用正常")

    # 结论
    print("\n" + "=" * 60)
    if all_pass:
        print("  [PASS] 所有检查通过，演示数据可正常使用")
    else:
        print("  [FAIL] 部分检查未通过，请查看上方详情")
    print("=" * 60)
