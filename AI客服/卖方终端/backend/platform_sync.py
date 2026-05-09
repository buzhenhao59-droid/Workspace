# -*- coding: utf-8 -*-
"""
平台数据同步服务
定时从各电商平台拉取数据，写入本地 SQLite 数据库
所有管理页面读取本地数据库，而非直接调平台 API
这样即使平台 API 挂了，本地也有缓存数据可用
"""
import time
import logging
import threading
import sqlite3
import json
import hashlib
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from pathlib import Path

from config import (
    # 平台配置
    TIKTOK_API_URL, TIKTOK_API_KEY, TIKTOK_API_SECRET, TIKTOK_ACCESS_TOKEN, TIKTOK_SHOP_ID,
    SHOPEE_API_URL, SHOPEE_API_KEY, SHOPEE_API_SECRET, SHOPEE_ACCESS_TOKEN, SHOPEE_SHOP_ID,
    LAZADA_API_URL, LAZADA_API_KEY, LAZADA_API_SECRET, LAZADA_ACCESS_TOKEN, LAZADA_SHOP_ID,
    AMAZON_API_URL, AMAZON_API_KEY, AMAZON_API_SECRET, AMAZON_ACCESS_TOKEN, AMAZON_SELLER_ID, AMAZON_MARKETPLACE_ID,
    ALIEXPRESS_API_URL, ALIEXPRESS_API_KEY, ALIEXPRESS_API_SECRET, ALIEXPRESS_ACCESS_TOKEN, ALIEXPRESS_APP_ID,
    EBAY_API_URL, EBAY_API_KEY, EBAY_API_SECRET, EBAY_ACCESS_TOKEN, EBAY_SELLER_ID,
    SHOPIFY_API_URL, SHOPIFY_API_KEY, SHOPIFY_API_SECRET, SHOPIFY_ACCESS_TOKEN, SHOPIFY_SHOP_DOMAIN,
    # 物流配置
    DHL_API_URL, DHL_API_KEY, DHL_API_SECRET,
    FEDEX_API_URL, FEDEX_API_KEY, FEDEX_API_SECRET,
    UPS_API_URL, UPS_API_KEY, UPS_API_SECRET,
    YANWEN_API_URL, YANWEN_API_KEY, YANWEN_API_SECRET,
    FPX_API_URL, FPX_API_KEY, FPX_API_SECRET,
    # 汇率
    EXCHANGE_RATE_API_URL, EXCHANGE_RATE_API_KEY,
)

logger = logging.getLogger(__name__)

# 数据库路径（与 db.py 共用 backend/data 目录）
DB_PATH = Path(__file__).parent / "data" / "platform_sync.db"


def _ensure_sync_db():
    """确保同步数据库存在"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sync_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id TEXT UNIQUE,
            platform TEXT,
            customer_id TEXT,
            customer_name TEXT,
            status TEXT,
            total_amount REAL,
            currency TEXT,
            items_count INTEGER,
            payment_method TEXT,
            shipping_address TEXT,
            raw_data TEXT,
            created_at TEXT,
            updated_at TEXT,
            synced_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sync_returns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            return_id TEXT UNIQUE,
            order_id TEXT,
            platform TEXT,
            customer_id TEXT,
            customer_name TEXT,
            type TEXT,
            reason TEXT,
            status TEXT,
            amount REAL,
            currency TEXT,
            raw_data TEXT,
            created_at TEXT,
            updated_at TEXT,
            synced_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sync_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            review_id TEXT UNIQUE,
            order_id TEXT,
            platform TEXT,
            customer_id TEXT,
            customer_name TEXT,
            star_rating INTEGER,
            content TEXT,
            product_name TEXT,
            product_image TEXT,
            reply_content TEXT,
            status TEXT,
            review_date TEXT,
            raw_data TEXT,
            synced_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sync_exchange_rates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            base_currency TEXT,
            target_currency TEXT,
            rate REAL,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(base_currency, target_currency)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sync_status (
            id INTEGER PRIMARY KEY,
            platform TEXT,
            last_sync TEXT,
            sync_status TEXT,
            error_message TEXT,
            order_count INTEGER,
            return_count INTEGER,
            review_count INTEGER
        )
    """)
    conn.commit()
    conn.close()


def _get_sync_conn():
    """获取同步数据库连接"""
    _ensure_sync_db()
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def _upsert_order(order: dict):
    """插入或更新订单"""
    conn = _get_sync_conn()
    try:
        conn.execute("""
            INSERT INTO sync_orders
            (order_id, platform, customer_id, customer_name, status, total_amount,
             currency, items_count, payment_method, shipping_address, raw_data, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(order_id) DO UPDATE SET
                status = excluded.status,
                total_amount = excluded.total_amount,
                updated_at = excluded.updated_at,
                synced_at = CURRENT_TIMESTAMP
        """, (
            order.get("order_id", ""),
            order.get("platform", ""),
            order.get("customer_id", ""),
            order.get("customer_name", ""),
            order.get("status", ""),
            order.get("total_amount", 0),
            order.get("currency", "USD"),
            order.get("items_count", 1),
            order.get("payment_method", ""),
            order.get("shipping_address", ""),
            json.dumps(order, ensure_ascii=False),
            order.get("created_at", ""),
            order.get("updated_at", ""),
        ))
        conn.commit()
    finally:
        conn.close()


def _upsert_return(ret: dict):
    """插入或更新退换货"""
    conn = _get_sync_conn()
    try:
        conn.execute("""
            INSERT INTO sync_returns
            (return_id, order_id, platform, customer_id, customer_name, type, reason,
             status, amount, currency, raw_data, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(return_id) DO UPDATE SET
                status = excluded.status,
                amount = excluded.amount,
                updated_at = excluded.updated_at,
                synced_at = CURRENT_TIMESTAMP
        """, (
            ret.get("return_id", ""),
            ret.get("order_id", ""),
            ret.get("platform", ""),
            ret.get("customer_id", ""),
            ret.get("customer_name", ""),
            ret.get("type", "退货退款"),
            ret.get("reason", ""),
            ret.get("status", ""),
            ret.get("amount", 0),
            ret.get("currency", "USD"),
            json.dumps(ret, ensure_ascii=False),
            ret.get("created_at", ""),
            ret.get("updated_at", ""),
        ))
        conn.commit()
    finally:
        conn.close()


def _upsert_review(rev: dict):
    """插入或更新评价"""
    conn = _get_sync_conn()
    try:
        conn.execute("""
            INSERT INTO sync_reviews
            (review_id, order_id, platform, customer_id, customer_name, star_rating, content,
             product_name, product_image, reply_content, status, review_date, raw_data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(review_id) DO UPDATE SET
                reply_content = excluded.reply_content,
                status = excluded.status,
                raw_data = excluded.raw_data
        """, (
            rev.get("review_id", ""),
            rev.get("order_id", ""),
            rev.get("platform", ""),
            rev.get("customer_id", ""),
            rev.get("customer_name", "匿名用户"),
            rev.get("star_rating", 5),
            rev.get("content", ""),
            rev.get("product_name", ""),
            rev.get("product_image", ""),
            rev.get("reply_content", ""),
            rev.get("status", "pending"),
            rev.get("review_date", ""),
            json.dumps(rev, ensure_ascii=False),
        ))
        conn.commit()
    finally:
        conn.close()


# ============== 各平台同步函数 ==============

def sync_shopee():
    """同步 Shopee 数据"""
    try:
        from platforms.shopee import ShopeeClient
        client = ShopeeClient(
            api_url=SHOPEE_API_URL,
            api_key=SHOPEE_API_KEY,
            api_secret=SHOPEE_API_SECRET,
            access_token=SHOPEE_ACCESS_TOKEN,
            shop_id=SHOPEE_SHOP_ID,
        )
        if not client.is_configured:
            return {"ok": False, "message": "Shopee 未配置 API 凭证"}

        # 同步最近 30 天的订单
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        orders = client.get_orders(start_date=start_date, end_date=end_date, page_size=100)
        for o in orders:
            _upsert_order(o)

        returns = client.get_returns(page_size=50)
        for r in returns:
            _upsert_return(r)

        reviews = client.get_reviews(page_size=50)
        for rv in reviews:
            _upsert_review(rv)

        _update_sync_status("shopee", "ok", order_count=len(orders),
                          return_count=len(returns), review_count=len(reviews))
        return {"ok": True, "orders": len(orders), "returns": len(returns), "reviews": len(reviews)}
    except Exception as e:
        _update_sync_status("shopee", "error", error=str(e))
        logger.error(f"Shopee 同步失败: {e}")
        return {"ok": False, "message": str(e)}


def sync_tiktok():
    """同步 TikTok Shop 数据"""
    try:
        from platforms.tiktok import TikTokClient
        client = TikTokClient(
            api_url=TIKTOK_API_URL,
            api_key=TIKTOK_API_KEY,
            api_secret=TIKTOK_API_SECRET,
            access_token=TIKTOK_ACCESS_TOKEN,
            shop_id=TIKTOK_SHOP_ID,
        )
        if not client.is_configured:
            return {"ok": False, "message": "TikTok 未配置 API 凭证"}

        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        orders = client.get_orders(start_date=start_date, end_date=end_date, page_size=50)
        for o in orders:
            _upsert_order(o)

        returns = client.get_returns(page_size=50)
        for r in returns:
            _upsert_return(r)

        reviews = client.get_reviews(page_size=50)
        for rv in reviews:
            _upsert_review(rv)

        _update_sync_status("tiktok", "ok", order_count=len(orders),
                          return_count=len(returns), review_count=len(reviews))
        return {"ok": True, "orders": len(orders), "returns": len(returns), "reviews": len(reviews)}
    except Exception as e:
        _update_sync_status("tiktok", "error", error=str(e))
        logger.error(f"TikTok 同步失败: {e}")
        return {"ok": False, "message": str(e)}


def sync_amazon():
    """同步 Amazon 数据"""
    try:
        from platforms.amazon import AmazonClient
        client = AmazonClient(
            api_url=AMAZON_API_URL,
            api_key=AMAZON_API_KEY,
            api_secret=AMAZON_API_SECRET,
            access_token=AMAZON_ACCESS_TOKEN,
            seller_id=AMAZON_SELLER_ID,
            marketplace_id=AMAZON_MARKETPLACE_ID,
        )
        if not client.is_configured:
            return {"ok": False, "message": "Amazon 未配置 API 凭证"}

        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        orders = client.get_orders(start_date=start_date, end_date=end_date, page_size=50)
        for o in orders:
            _upsert_order(o)

        returns = client.get_returns(page_size=50)
        for r in returns:
            _upsert_return(r)

        _update_sync_status("amazon", "ok", order_count=len(orders),
                          return_count=len(returns), review_count=0)
        return {"ok": True, "orders": len(orders), "returns": len(returns)}
    except Exception as e:
        _update_sync_status("amazon", "error", error=str(e))
        logger.error(f"Amazon 同步失败: {e}")
        return {"ok": False, "message": str(e)}


def sync_lazada():
    """同步 Lazada 数据"""
    try:
        from platforms.lazada import LazadaClient
        client = LazadaClient(
            api_url=LAZADA_API_URL,
            api_key=LAZADA_API_KEY,
            api_secret=LAZADA_API_SECRET,
            access_token=LAZADA_ACCESS_TOKEN,
            shop_id=LAZADA_SHOP_ID,
        )
        if not client.is_configured:
            return {"ok": False, "message": "Lazada 未配置 API 凭证"}

        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        orders = client.get_orders(start_date=start_date, end_date=end_date, page_size=100)
        for o in orders:
            _upsert_order(o)

        returns = client.get_returns(page_size=50)
        for r in returns:
            _upsert_return(r)

        reviews = client.get_reviews(page_size=50)
        for rv in reviews:
            _upsert_review(rv)

        _update_sync_status("lazada", "ok", order_count=len(orders),
                          return_count=len(returns), review_count=len(reviews))
        return {"ok": True, "orders": len(orders), "returns": len(returns), "reviews": len(reviews)}
    except Exception as e:
        _update_sync_status("lazada", "error", error=str(e))
        logger.error(f"Lazada 同步失败: {e}")
        return {"ok": False, "message": str(e)}


def sync_aliexpress():
    """同步 AliExpress 数据"""
    try:
        from platforms.aliexpress import AliExpressClient
        client = AliExpressClient(
            api_url=ALIEXPRESS_API_URL,
            api_key=ALIEXPRESS_API_KEY,
            api_secret=ALIEXPRESS_API_SECRET,
            access_token=ALIEXPRESS_ACCESS_TOKEN,
            app_id=ALIEXPRESS_APP_ID,
        )
        if not client.is_configured:
            return {"ok": False, "message": "AliExpress 未配置 API 凭证"}

        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        orders = client.get_orders(start_date=start_date, end_date=end_date, page_size=100)
        for o in orders:
            _upsert_order(o)

        returns = client.get_returns(page_size=50)
        for r in returns:
            _upsert_return(r)

        _update_sync_status("aliexpress", "ok", order_count=len(orders),
                          return_count=len(returns), review_count=0)
        return {"ok": True, "orders": len(orders), "returns": len(returns)}
    except Exception as e:
        _update_sync_status("aliexpress", "error", error=str(e))
        logger.error(f"AliExpress 同步失败: {e}")
        return {"ok": False, "message": str(e)}


def sync_ebay():
    """同步 eBay 数据"""
    try:
        from platforms.ebay import EbayClient
        client = EbayClient(
            api_url=EBAY_API_URL,
            api_key=EBAY_API_KEY,
            api_secret=EBAY_API_SECRET,
            access_token=EBAY_ACCESS_TOKEN,
            seller_id=EBAY_SELLER_ID,
        )
        if not client.is_configured:
            return {"ok": False, "message": "eBay 未配置 API 凭证"}

        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        orders = client.get_orders(start_date=start_date, end_date=end_date, page_size=50)
        for o in orders:
            _upsert_order(o)

        returns = client.get_returns(page_size=50)
        for r in returns:
            _upsert_return(r)

        _update_sync_status("ebay", "ok", order_count=len(orders),
                          return_count=len(returns), review_count=0)
        return {"ok": True, "orders": len(orders), "returns": len(returns)}
    except Exception as e:
        _update_sync_status("ebay", "error", error=str(e))
        logger.error(f"eBay 同步失败: {e}")
        return {"ok": False, "message": str(e)}


def sync_shopify():
    """同步 Shopify 数据"""
    try:
        from platforms.shopify import ShopifyClient
        client = ShopifyClient(
            api_url=SHOPIFY_API_URL,
            api_key=SHOPIFY_API_KEY,
            api_secret=SHOPIFY_API_SECRET,
            access_token=SHOPIFY_ACCESS_TOKEN,
            shop_domain=SHOPIFY_SHOP_DOMAIN,
        )
        if not client.is_configured:
            return {"ok": False, "message": "Shopify 未配置 API 凭证"}

        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        orders = client.get_orders(start_date=start_date, end_date=end_date, page_size=250)
        for o in orders:
            _upsert_order(o)

        returns = client.get_returns(page_size=100)
        for r in returns:
            _upsert_return(r)

        _update_sync_status("shopify", "ok", order_count=len(orders),
                          return_count=len(returns), review_count=0)
        return {"ok": True, "orders": len(orders), "returns": len(returns)}
    except Exception as e:
        _update_sync_status("shopify", "error", error=str(e))
        logger.error(f"Shopify 同步失败: {e}")
        return {"ok": False, "message": str(e)}


def _update_sync_status(platform: str, status: str,
                        order_count: int = 0, return_count: int = 0,
                        review_count: int = 0, error: str = ""):
    """更新同步状态"""
    conn = _get_sync_conn()
    try:
        conn.execute("""
            INSERT INTO sync_status (id, platform, last_sync, sync_status, error_message,
                                     order_count, return_count, review_count)
            VALUES (1, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                platform = excluded.platform,
                last_sync = CURRENT_TIMESTAMP,
                sync_status = excluded.sync_status,
                error_message = excluded.error_message,
                order_count = excluded.order_count,
                return_count = excluded.return_count,
                review_count = excluded.review_count
        """, (platform, status, error, order_count, return_count, review_count))
        conn.commit()
    finally:
        conn.close()


def sync_all_platforms():
    """同步所有已配置平台（按顺序调用）"""
    results = {}
    # Shopee 优先级最高（国内跨境最常用）
    results["shopee"] = sync_shopee()
    results["tiktok"] = sync_tiktok()
    results["lazada"] = sync_lazada()
    results["amazon"] = sync_amazon()
    results["aliexpress"] = sync_aliexpress()
    results["ebay"] = sync_ebay()
    results["shopify"] = sync_shopify()

    total_orders = sum(r.get("orders", 0) for r in results.values() if r.get("ok"))
    total_returns = sum(r.get("returns", 0) for r in results.values() if r.get("ok"))
    total_reviews = sum(r.get("reviews", 0) for r in results.values() if r.get("ok"))
    ok_count = sum(1 for r in results.values() if r.get("ok"))

    logger.info(f"平台同步完成: {ok_count}/{len(results)} 个平台成功，"
                f"订单 {total_orders} 条，退货 {total_returns} 条，评价 {total_reviews} 条")
    return {
        "ok": True,
        "results": results,
        "summary": {
            "total_orders": total_orders,
            "total_returns": total_returns,
            "total_reviews": total_reviews,
            "ok_platforms": ok_count,
            "total_platforms": len(results),
        }
    }


# ============== 数据查询接口（供后端路由调用） ==============

# 管理后台「全部订单」筛选：中文 Tab ↔ platform_sync.db 中英状态
_ADMIN_ORDER_STATUS_GROUPS = {
    "待付款": ("pending", "pending_payment"),
    "待发货": ("processing", "pending_shipment"),
    "已发货": ("shipped",),
    "已完成": ("delivered", "completed"),
}


def synthetic_buyer_phone(seed: str) -> str:
    """演示用稳定伪造买家手机号（同一订单/客户始终相同，非真实号段）。"""
    if not seed:
        seed = "demo"
    h = hashlib.md5(seed.encode("utf-8")).hexdigest()
    n = int(h[:10], 16)
    body = f"{(n % 900000000) + 100000000:09d}"
    return "+86 13" + body[0] + " " + body[1:5] + " " + body[5:9]


def synthetic_buyer_email(seed: str) -> str:
    if not seed:
        seed = "demo"
    return f"buyer.{hashlib.md5(seed.encode('utf-8')).hexdigest()[:10]}@demo.swim.local"


def format_sync_order_for_admin(row: dict) -> dict:
    """将 sync_orders 行转为 admin/orders.html 所需结构。"""
    raw = {}
    rd = row.get("raw_data")
    if rd:
        try:
            raw = json.loads(rd) if isinstance(rd, str) else (rd if isinstance(rd, dict) else {})
        except Exception:
            raw = {}
    products = []
    for it in (raw.get("items") or raw.get("line_items") or []):
        if isinstance(it, dict):
            n = it.get("name") or it.get("product_name")
            if n:
                products.append({"name": n})
    if not products:
        ic = int(row.get("items_count") or 1)
        products = [{"name": f"商品（{ic}件）"}]

    db_st = (row.get("status") or "").strip()
    ui_status = _SYNC_DB_STATUS_TO_UI_LABEL.get(db_st, db_st)

    oid = str(row.get("order_id") or "")
    cid = str(row.get("customer_id") or "")
    phone = (raw.get("phone") or raw.get("buyer_phone") or "").strip()
    if not phone or phone == "—":
        phone = synthetic_buyer_phone(f"{oid}|{cid}")

    return {
        "id": row.get("order_id"),
        "customer_name": row.get("customer_name") or "—",
        "customer_id": row.get("customer_id") or "—",
        "customer_phone": phone,
        "customer_email": (raw.get("email") or raw.get("buyer_email") or "").strip()
        or synthetic_buyer_email(oid + cid),
        "products": products,
        "total": row.get("total_amount"),
        "amount": row.get("total_amount"),
        "status": ui_status,
        "platform": row.get("platform"),
        "created_at": row.get("created_at"),
        "display_date": row.get("created_at"),
        "order_date": row.get("created_at"),
        "currency": row.get("currency") or "USD",
    }


_SYNC_DB_STATUS_TO_UI_LABEL = {
    "pending": "待付款",
    "pending_payment": "待付款",
    "processing": "待发货",
    "pending_shipment": "待发货",
    "shipped": "已发货",
    "delivered": "已完成",
    "completed": "已完成",
    "cancelled": "已取消",
    "refund_requested": "退款申请",
    "refunded": "已退款",
    "disputed": "纠纷中",
}


def get_synced_orders(status: str = "", platform: str = "",
                     start_date: str = "", end_date: str = "",
                     page: int = 1, page_size: int = 50) -> tuple:
    """查询本地同步的订单"""
    conn = _get_sync_conn()
    try:
        cond = []
        params = []
        if status and status != "全部":
            codes = _ADMIN_ORDER_STATUS_GROUPS.get(status)
            if codes:
                ph = ",".join("?" * len(codes))
                cond.append(f"status IN ({ph})")
                params.extend(codes)
            else:
                cond.append("status = ?")
                params.append(status)
        if platform:
            cond.append("platform = ?")
            params.append(platform)
        if start_date:
            cond.append("created_at >= ?")
            params.append(start_date)
        if end_date:
            cond.append("created_at <= ?")
            params.append(end_date)
        where = "WHERE " + " AND ".join(cond) if cond else ""

        total = conn.execute(f"SELECT COUNT(*) FROM sync_orders {where}", params).fetchone()[0]
        offset = (page - 1) * page_size
        rows = conn.execute(
            f"SELECT * FROM sync_orders {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params + [page_size, offset]
        ).fetchall()
        return [dict(r) for r in rows], total
    finally:
        conn.close()


def get_synced_returns(status: str = "", platform: str = "",
                       page: int = 1, page_size: int = 50) -> tuple:
    """查询本地同步的退换货"""
    conn = _get_sync_conn()
    try:
        cond = []
        params = []
        if status:
            cond.append("status = ?")
            params.append(status)
        if platform:
            cond.append("platform = ?")
            params.append(platform)
        where = "WHERE " + " AND ".join(cond) if cond else ""

        total = conn.execute(f"SELECT COUNT(*) FROM sync_returns {where}", params).fetchone()[0]
        offset = (page - 1) * page_size
        rows = conn.execute(
            f"SELECT * FROM sync_returns {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params + [page_size, offset]
        ).fetchall()
        return [dict(r) for r in rows], total
    finally:
        conn.close()


def get_synced_reviews(status: str = "", platform: str = "",
                       page: int = 1, page_size: int = 50) -> tuple:
    """查询本地同步的评价"""
    conn = _get_sync_conn()
    try:
        cond = []
        params = []
        if status:
            cond.append("status = ?")
            params.append(status)
        if platform:
            cond.append("platform = ?")
            params.append(platform)
        where = "WHERE " + " AND ".join(cond) if cond else ""

        total = conn.execute(f"SELECT COUNT(*) FROM sync_reviews {where}", params).fetchone()[0]
        offset = (page - 1) * page_size
        rows = conn.execute(
            f"SELECT * FROM sync_reviews {where} ORDER BY review_date DESC LIMIT ? OFFSET ?",
            params + [page_size, offset]
        ).fetchall()
        return [dict(r) for r in rows], total
    finally:
        conn.close()


def get_synced_stats() -> dict:
    """获取同步统计"""
    conn = _get_sync_conn()
    try:
        orders_total = conn.execute("SELECT COUNT(*) FROM sync_orders").fetchone()[0]
        orders_today = conn.execute(
            "SELECT COUNT(*) FROM sync_orders WHERE date(synced_at) = date('now')"
        ).fetchone()[0]
        returns_total = conn.execute("SELECT COUNT(*) FROM sync_returns").fetchone()[0]
        returns_pending = conn.execute(
            "SELECT COUNT(*) FROM sync_returns WHERE status NOT IN ('completed','approved','退款完成','已退款')"
        ).fetchone()[0]
        reviews_total = conn.execute("SELECT COUNT(*) FROM sync_reviews").fetchone()[0]
        reviews_pending = conn.execute(
            "SELECT COUNT(*) FROM sync_reviews WHERE status = 'pending' OR status = ''"
        ).fetchone()[0]
        avg_rating = conn.execute(
            "SELECT AVG(star_rating) FROM sync_reviews WHERE star_rating > 0"
        ).fetchone()[0] or 0

        rows = conn.execute("SELECT * FROM sync_status").fetchall()
        platforms_status = {dict(r)["platform"]: dict(r) for r in rows}

        return {
            "orders_total": orders_total,
            "orders_today": orders_today,
            "returns_total": returns_total,
            "returns_pending": returns_pending,
            "reviews_total": reviews_total,
            "reviews_pending": reviews_pending,
            "avg_rating": round(avg_rating, 1),
            "platforms_status": platforms_status,
        }
    finally:
        conn.close()


# ============== 定时同步守护线程 ==============

_sync_timer: Optional[threading.Timer] = None
_SYNC_INTERVAL = 10 * 60  # 默认每 10 分钟同步一次


def _background_sync():
    """后台定时同步"""
    global _sync_timer
    try:
        sync_all_platforms()
    except Exception as e:
        logger.error(f"后台同步异常: {e}")
    finally:
        _sync_timer = threading.Timer(_SYNC_INTERVAL, _background_sync)
        _sync_timer.daemon = True
        _sync_timer.start()


def start_auto_sync(interval_minutes: int = 10):
    """启动定时同步"""
    global _SYNC_INTERVAL, _sync_timer
    _SYNC_INTERVAL = interval_minutes * 60
    if _sync_timer is not None:
        _sync_timer.cancel()
    _background_sync()
    logger.info(f"平台自动同步已启动，每 {interval_minutes} 分钟执行一次")


def stop_auto_sync():
    """停止定时同步"""
    global _sync_timer
    if _sync_timer is not None:
        _sync_timer.cancel()
        _sync_timer = None
        logger.info("平台自动同步已停止")


def get_sync_status() -> dict:
    """获取当前同步状态"""
    conn = _get_sync_conn()
    try:
        rows = conn.execute("SELECT * FROM sync_status ORDER BY last_sync DESC").fetchall()
        return {"ok": True, "platforms": [dict(r) for r in rows]}
    finally:
        conn.close()


# ============== 初始化 ==============
_ensure_sync_db()
