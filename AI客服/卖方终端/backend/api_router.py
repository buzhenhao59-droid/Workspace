# -*- coding: utf-8 -*-
"""
统一 API 路由层
整合所有管理后台 API，统一认证、统一返回格式
挂载到 main.py
"""
import logging
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter(tags=["统一数据接口"])

# ============== 请求模型 ==============

class PlatformSyncRequest(BaseModel):
    platforms: List[str] = []  # 空=全部
    force: bool = False


class OrderQueryRequest(BaseModel):
    status: str = ""
    platform: str = ""
    start_date: str = ""
    end_date: str = ""
    page: int = 1
    page_size: int = 50


class AfterSaleCreateRequest(BaseModel):
    order_id: str
    customer_id: str = ""
    type: str = "退货退款"
    reason: str
    amount: float = 0
    description: str = ""


class ReviewReplyRequest(BaseModel):
    review_ids: List[str]
    content: str
    use_template_id: Optional[str] = None


# ============== 辅助函数 ==============

def check_token(token: str) -> bool:
    """检查 token 是否有效（在函数内部导入避免循环引用）"""
    import main as _main_module
    return token in _main_module.admin_sessions


def platform_info() -> dict:
    """返回平台配置状态"""
    from config import (
        TIKTOK_API_URL, SHOPEE_API_URL, LAZADA_API_URL,
        AMAZON_API_URL, ALIEXPRESS_API_URL, EBAY_API_URL, SHOPIFY_API_URL,
    )
    platforms = {
        "tiktok": TIKTOK_API_URL,
        "shopee": SHOPEE_API_URL,
        "lazada": LAZADA_API_URL,
        "amazon": AMAZON_API_URL,
        "aliexpress": ALIEXPRESS_API_URL,
        "ebay": EBAY_API_URL,
        "shopify": SHOPIFY_API_URL,
    }
    return {
        "platforms": {
            name: {"configured": bool(url), "name": _platform_display_name(name)}
            for name, url in platforms.items()
        }
    }


def _platform_display_name(name: str) -> str:
    names = {
        "tiktok": "TikTok Shop",
        "shopee": "Shopee",
        "lazada": "Lazada",
        "amazon": "Amazon",
        "aliexpress": "速卖通",
        "ebay": "eBay",
        "shopify": "Shopify",
    }
    return names.get(name, name)


# ============== 平台数据接口 ==============

@router.get("/platforms")
async def get_platforms():
    """获取平台配置状态"""
    return {"ok": True, **platform_info()}


@router.post("/sync")
async def sync_platforms(req: PlatformSyncRequest = None):
    """手动触发平台同步"""
    from platform_sync import (
        sync_all_platforms,
        sync_shopee, sync_tiktok, sync_lazada,
        sync_amazon, sync_aliexpress, sync_ebay, sync_shopify,
    )
    if req and req.platforms:
        results = {}
        if "shopee" in req.platforms:
            results["shopee"] = sync_shopee()
        if "tiktok" in req.platforms:
            results["tiktok"] = sync_tiktok()
        if "lazada" in req.platforms:
            results["lazada"] = sync_lazada()
        if "amazon" in req.platforms:
            results["amazon"] = sync_amazon()
        if "aliexpress" in req.platforms:
            results["aliexpress"] = sync_aliexpress()
        if "ebay" in req.platforms:
            results["ebay"] = sync_ebay()
        if "shopify" in req.platforms:
            results["shopify"] = sync_shopify()
        return {"ok": True, "results": results}
    return sync_all_platforms()


@router.get("/sync/status")
async def get_sync_status():
    """获取同步状态"""
    from platform_sync import get_sync_status as _get_sync_status
    return _get_sync_status()


@router.get("/orders")
async def get_orders(
    status: str = "",
    platform: str = "",
    start_date: str = "",
    end_date: str = "",
    page: int = 1,
    page_size: int = 50,
    token: str = "",
):
    """获取订单列表（优先读本地同步缓存）"""
    from platform_sync import get_synced_orders
    orders, total = get_synced_orders(
        status=status, platform=platform,
        start_date=start_date, end_date=end_date,
        page=page, page_size=page_size
    )
    return {
        "ok": True,
        "orders": orders,
        "total": total,
        "page": page,
        "page_size": page_size,
        "source": "cache",
    }


@router.get("/orders/{order_id}")
async def get_order_detail(order_id: str, token: str = ""):
    """获取订单详情"""
    from platform_sync import _get_sync_conn
    conn = _get_sync_conn()
    try:
        row = conn.execute(
            "SELECT * FROM sync_orders WHERE order_id = ?", (order_id,)
        ).fetchone()
        if row:
            return {"ok": True, "order": dict(row)}
        return {"ok": False, "message": "订单不存在"}
    finally:
        conn.close()


@router.get("/returns")
async def get_returns(
    status: str = "",
    platform: str = "",
    page: int = 1,
    page_size: int = 50,
    token: str = "",
):
    """获取退换货列表"""
    from platform_sync import get_synced_returns
    data, total = get_synced_returns(
        status=status, platform=platform,
        page=page, page_size=page_size
    )
    return {
        "ok": True,
        "returns": data,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.post("/returns")
async def create_return(req: AfterSaleCreateRequest, token: str = ""):
    """创建售后单（写入本地库 + 调用外部API）"""
    from platform_sync import _upsert_return
    from config import AFTER_SALES_CREATE_API
    import httpx

    ret_data = {
        "return_id": f"RET{datetime.now().strftime('%Y%m%d%H%M%S')}",
        "order_id": req.order_id,
        "customer_id": req.customer_id,
        "type": req.type,
        "reason": req.reason,
        "status": "待处理",
        "amount": req.amount,
        "description": req.description,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    _upsert_return(ret_data)

    # 如果配置了外部API则转发
    if AFTER_SALES_CREATE_API:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(AFTER_SALES_CREATE_API, json=req.dict())
                if resp.status_code == 200:
                    return {"ok": True, "message": "已同步到外部系统"}
        except Exception as e:
            logger.warning(f"转发售后单到外部API失败: {e}")

    return {"ok": True, "return_id": ret_data["return_id"], "message": "已创建售后单"}


@router.get("/reviews")
async def get_reviews(
    status: str = "",
    platform: str = "",
    page: int = 1,
    page_size: int = 50,
    token: str = "",
):
    """获取评价列表"""
    from platform_sync import get_synced_reviews
    data, total = get_synced_reviews(
        status=status, platform=platform,
        page=page, page_size=page_size
    )
    return {
        "ok": True,
        "reviews": data,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.post("/reviews/reply")
async def reply_reviews(req: ReviewReplyRequest, token: str = ""):
    """回复评价"""
    from platform_sync import _get_sync_conn
    import httpx

    conn = _get_sync_conn()
    try:
        for review_id in req.review_ids:
            conn.execute(
                "UPDATE sync_reviews SET reply_content = ?, status = 'replied', "
                "synced_at = CURRENT_TIMESTAMP WHERE review_id = ?",
                (req.content, review_id)
            )
        conn.commit()

        from config import EVALUATION_REPLY_API
        if EVALUATION_REPLY_API:
            try:
                async with httpx.AsyncClient(timeout=15) as client:
                    resp = await client.post(EVALUATION_REPLY_API, json=req.dict())
                    if resp.status_code == 200:
                        return {"ok": True, "message": "已同步到外部系统"}
            except Exception as e:
                logger.warning(f"转发评价回复到外部API失败: {e}")

        return {"ok": True, "message": f"已回复 {len(req.review_ids)} 条评价"}
    finally:
        conn.close()


@router.get("/logistics/{tracking_number}")
async def query_logistics(tracking_number: str, carrier: str = ""):
    """查询物流轨迹"""
    from logistics import DHLClient, FedExClient, UPSClient, YanwenClient, FPXClient
    from config import (
        DHL_API_URL, DHL_API_KEY, DHL_API_SECRET,
        FEDEX_API_URL, FEDEX_API_KEY, FEDEX_API_SECRET,
        UPS_API_URL, UPS_API_KEY, UPS_API_SECRET,
        YANWEN_API_URL, YANWEN_API_KEY, YANWEN_API_SECRET,
        FPX_API_URL, FPX_API_KEY, FPX_API_SECRET,
    )
    carrier_map = {
        "dhl": DHLClient(DHL_API_URL, DHL_API_KEY, DHL_API_SECRET),
        "fedex": FedExClient(FEDEX_API_URL, FEDEX_API_KEY, FEDEX_API_SECRET),
        "ups": UPSClient(UPS_API_URL, UPS_API_KEY, UPS_API_SECRET),
        "yanwen": YanwenClient(YANWEN_API_URL, YANWEN_API_KEY, YANWEN_API_SECRET),
        "fpx": FPXClient(FPX_API_URL, FPX_API_KEY, FPX_API_SECRET),
    }
    if carrier and carrier in carrier_map:
        client = carrier_map[carrier]
        result = client.query_tracking(tracking_number)
        return {"ok": True, "carrier": carrier, **result}

    for name, client in carrier_map.items():
        if client.is_configured:
            result = client.query_tracking(tracking_number)
            if result.get("ok"):
                return {"ok": True, "carrier": name, **result}

    return {"ok": False, "message": "未配置任何物流渠道或查询失败"}


@router.get("/dashboard/stats")
async def get_dashboard_stats():
    """获取仪表盘统计数据"""
    from platform_sync import get_synced_stats, _get_sync_conn
    stats = get_synced_stats()
    conn = _get_sync_conn()
    try:
        rows = conn.execute(
            "SELECT platform, COUNT(*) as count FROM sync_orders GROUP BY platform"
        ).fetchall()
        by_platform = {dict(r)["platform"]: dict(r)["count"] for r in rows}
        return {
            "ok": True,
            "stats": stats,
            "orders_by_platform": by_platform,
        }
    finally:
        conn.close()


# ============== 审计日志 ==============

@router.get("/audit-logs")
async def get_audit_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    event_type: str = Query("", description="事件类型：LOGIN/LOGOUT/ORDER_UPDATE 等"),
    operator: str = Query("", description="操作人"),
    target_type: str = Query("", description="操作对象类型"),
    target_id: str = Query("", description="操作对象ID"),
    start_date: str = Query("", description="开始日期 YYYY-MM-DD"),
    end_date: str = Query("", description="结束日期 YYYY-MM-DD"),
):
    """
    分页查询审计日志（支持多条件筛选）

    前端: audit-logs.html → loadLogs()
    """
    from db import get_db
    import sqlite3

    try:
        conn = get_db()
        is_sqlite = isinstance(conn, sqlite3.Connection)

        # 动态构建 WHERE 子句
        conditions = []
        params = []
        if event_type:
            conditions.append("event_type = ?")
            params.append(event_type)
        if operator:
            conditions.append("operator LIKE ?")
            params.append(f"%{operator}%")
        if target_type:
            conditions.append("target_type = ?")
            params.append(target_type)
        if target_id:
            conditions.append("target_id LIKE ?")
            params.append(f"%{target_id}%")
        if start_date:
            conditions.append("created_at >= ?")
            params.append(start_date + " 00:00:00")
        if end_date:
            conditions.append("created_at <= ?")
            params.append(end_date + " 23:59:59")

        where = " AND ".join(conditions) if conditions else "1=1"

        # SQLite 分页
        if is_sqlite:
            offset = (page - 1) * page_size
            cursor = conn.cursor()
            cursor.execute(f"SELECT COUNT(*) as cnt FROM audit_logs WHERE {where}", params)
            total = cursor.fetchone()[0] or 0
            cursor.execute(
                f"""SELECT id, event_type, operator, target_type, target_id,
                           detail, ip_address, user_agent, created_at
                    FROM audit_logs
                    WHERE {where}
                    ORDER BY created_at DESC
                    LIMIT ? OFFSET ?""",
                params + [page_size, offset],
            )
            rows = cursor.fetchall()
            conn.close()

            # 列名
            col_names = [d[0] for d in cursor.description]
            logs = [dict(zip(col_names, row)) for row in rows]
            # 转换 datetime
            for log in logs:
                if log.get("created_at"):
                    log["created_at"] = str(log["created_at"])
        else:
            # MySQL
            offset = (page - 1) * page_size
            cursor = conn.cursor()
            cursor.execute(f"SELECT COUNT(*) as cnt FROM audit_logs WHERE {where}", params)
            total = cursor.fetchone()[0]
            cursor.execute(
                f"""SELECT id, event_type, operator, target_type, target_id,
                           detail, ip_address, user_agent, created_at
                    FROM audit_logs
                    WHERE {where}
                    ORDER BY created_at DESC
                    LIMIT %s OFFSET %s""",
                params + [page_size, offset],
            )
            rows = cursor.fetchall()
            conn.close()
            col_names = [d[0] for d in cursor.description]
            logs = [dict(zip(col_names, row)) for row in rows]
            for log in logs:
                if log.get("created_at"):
                    log["created_at"] = str(log["created_at"])

        return {
            "ok": True,
            "success": True,
            "logs": logs,
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": (total + page_size - 1) // page_size if total else 0,
        }

    except Exception as e:
        logger.warning(f"[Audit] 查询失败: {e}")
        return {"ok": False, "success": False, "message": str(e), "logs": [], "total": 0}
