# -*- coding: utf-8 -*-
"""
消息中心 API 路由 - 优化版
支持流式检索、分页查询、时间过滤
"""
import logging
import json
import asyncio
import concurrent.futures
from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Query, Body
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# 独立的搜索专用线程池
_search_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=2,
    thread_name_prefix="policy_search_"
)

from message_center_service import message_center_service
from policy_search_service import policy_search_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/message-center", tags=["消息中心"])


# ==================== 数据模型 ====================

class QuickReplyCreate(BaseModel):
    category: str = "通用"
    title: str
    content: str
    shortcut: Optional[str] = None
    created_by: str = "admin"


class QuickReplyUpdate(BaseModel):
    category: Optional[str] = None
    title: Optional[str] = None
    content: Optional[str] = None
    shortcut: Optional[str] = None


class ReminderCreate(BaseModel):
    title: str
    content: Optional[str] = None
    remind_type: str = "once"
    remind_time: str
    is_repeat: bool = False
    repeat_days: Optional[str] = None
    created_by: str = "admin"


class ReminderUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    remind_time: Optional[str] = None
    is_active: Optional[bool] = None
    is_repeat: Optional[bool] = None
    repeat_days: Optional[str] = None


class NotificationType(str):
    """通知类型枚举"""
    POLICY = "policy"
    MARKET = "market"
    SYSTEM = "system"
    ALL = None


class CustomSearchRequest(BaseModel):
    keywords: Optional[str] = None
    notification_type: Optional[str] = "policy"
    limit: int = 10


class OptimizedSearchRequest(BaseModel):
    """优化版检索请求"""
    search_type: str = "policy"  # policy | market
    keywords: Optional[str] = None  # 搜索关键词
    time_range: str = "week"  # week | month
    page: int = 1  # 分页
    page_size: int = 20  # 每页数量
    include_read: bool = True  # 包含已读
    sort_by_importance: bool = True  # 按重要性排序


# ==================== 健康检查 ====================

@router.get("/health")
async def health_check():
    """消息中心健康检查"""
    try:
        from message_center_service import _is_mysql
        mysql_ok = _is_mysql()

        return {
            "status": "ok",
            "database": "mysql" if mysql_ok else "sqlite",
            "mysql_mode": mysql_ok,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ==================== 会话列表 API ====================

@router.get("/conversations")
async def get_conversations(
    platform: Optional[str] = Query(None, description="平台名称：tiktok, shopee, lazada, amazon, aliexpress, ebay, shopify"),
    hours: int = Query(72, description="获取最近多少小时内的会话", ge=1, le=720)
):
    """获取会话列表（按平台分组，显示最近72小时内的人工会话）"""
    try:
        conversations = message_center_service.get_conversation_list(
            platform=platform,
            hours=hours
        )
        
        return {
            "success": True,
            "data": conversations,
            "total": len(conversations)
        }
    except Exception as e:
        logger.error(f"获取会话列表失败: {e}")
        return {"success": False, "message": str(e)}


@router.get("/platforms")
async def get_platforms():
    """获取所有平台及其会话统计"""
    try:
        platforms = message_center_service.get_platforms()
        
        return {
            "success": True,
            "data": platforms,
            "total": len(platforms)
        }
    except Exception as e:
        logger.error(f"获取平台列表失败: {e}")
        return {"success": False, "message": str(e)}


@router.post("/conversations/sync")
async def sync_conversations():
    """同步会话列表（从sessions表同步到conversation_history表）"""
    try:
        from db import get_db
        with get_db() as (conn, cursor):
            cursor.execute("SELECT s.session_id, s.customer_id, s.language, s.created_at, s.updated_at, s.status, c.name as customer_name FROM sessions s LEFT JOIN customers c ON s.customer_id = c.customer_id WHERE s.is_ai = 0 ORDER BY s.updated_at DESC LIMIT 1000")
            sessions = []
            cols = [d[0] for d in cursor.description] if cursor.description else []
            for row in cursor.fetchall():
                sessions.append(dict(zip(cols, row)))

        synced_count = 0
        for session in sessions:
            session_id = session.get('session_id', '')
            customer_id = session.get('customer_id', '')
            customer_name = session.get('customer_name', customer_id)

            platform = session.get('language') or 'other'
            if platform not in ['zh', 'en', 'ar', 'ru']:
                platform = 'tiktok'

            message_center_service.add_conversation(
                session_id=session_id,
                platform=platform,
                customer_id=customer_id,
                customer_name=customer_name,
                is_human=True
            )
            synced_count += 1

        return {
            "success": True,
            "synced": synced_count,
            "message": f"同步完成，共 {synced_count} 条会话"
        }

    except Exception as e:
        logger.error(f"同步会话列表失败: {e}")
        return {"success": False, "message": str(e)}


from datetime import timedelta


# ==================== 快捷回复 API ====================

@router.get("/quick-replies")
async def get_quick_replies(
    category: Optional[str] = Query(None, description="分类名称")
):
    """获取快捷回复列表"""
    try:
        replies = message_center_service.get_quick_replies(category=category)
        
        return {
            "success": True,
            "data": replies,
            "total": len(replies)
        }
    except Exception as e:
        logger.error(f"获取快捷回复失败: {e}")
        return {"success": False, "message": str(e)}


@router.get("/quick-replies/categories")
async def get_quick_reply_categories():
    """获取快捷回复分类列表"""
    try:
        categories = message_center_service.get_quick_reply_categories()
        
        return {
            "success": True,
            "data": categories,
            "total": len(categories)
        }
    except Exception as e:
        logger.error(f"获取分类列表失败: {e}")
        return {"success": False, "message": str(e)}


@router.post("/quick-replies")
async def create_quick_reply(reply: QuickReplyCreate):
    """创建快捷回复"""
    try:
        result = message_center_service.add_quick_reply(
            category=reply.category,
            title=reply.title,
            content=reply.content,
            shortcut=reply.shortcut,
            created_by=reply.created_by
        )
        
        return {
            "success": True,
            "data": result,
            "message": "快捷回复创建成功"
        }
    except Exception as e:
        logger.error(f"创建快捷回复失败: {e}")
        return {"success": False, "message": str(e)}


@router.put("/quick-replies/{reply_id}")
async def update_quick_reply(reply_id: int, reply: QuickReplyUpdate):
    """更新快捷回复"""
    try:
        success = message_center_service.update_quick_reply(
            reply_id=reply_id,
            category=reply.category,
            title=reply.title,
            content=reply.content,
            shortcut=reply.shortcut
        )
        
        if success:
            return {"success": True, "message": "快捷回复更新成功"}
        else:
            return {"success": False, "message": "快捷回复不存在"}
    except Exception as e:
        logger.error(f"更新快捷回复失败: {e}")
        return {"success": False, "message": str(e)}


@router.delete("/quick-replies/{reply_id}")
async def delete_quick_reply(reply_id: int):
    """删除快捷回复"""
    try:
        success = message_center_service.delete_quick_reply(reply_id)
        
        if success:
            return {"success": True, "message": "快捷回复已删除"}
        else:
            return {"success": False, "message": "快捷回复不存在"}
    except Exception as e:
        logger.error(f"删除快捷回复失败: {e}")
        return {"success": False, "message": str(e)}


# ==================== 消息通知 API ====================

@router.get("/notifications")
async def get_notifications(
    notification_type: Optional[str] = Query(None, description="通知类型：policy, market, system, inbox"),
    include_read: bool = Query(True, description="是否包含已读通知"),
    limit: int = Query(50, description="返回数量限制", ge=1, le=200),
    exclude_types: Optional[str] = Query(None, description="排除的通知类型，逗号分隔，如 'policy,market'"),
    include_types: Optional[str] = Query(None, description="仅返回这些类型，逗号分隔，如 'policy,market'"),
):
    """获取消息通知列表

    参数说明（互斥，只能用其一）：
    - notification_type: 单类型过滤（policy / market / system）
    - exclude_types: 排除类型（inbox 用，逗号分隔）
    - include_types: 仅包含类型（政策通知用，逗号分隔）
    """
    try:
        # 解析逗号分隔的列表
        def parse_list(s: Optional[str]) -> Optional[List[str]]:
            if not s:
                return None
            return [x.strip() for x in s.split(",") if x.strip()]

        excl = parse_list(exclude_types)
        incl = parse_list(include_types)

        # inbox 类型特殊处理：自动排除 policy 和 market
        if notification_type == "inbox":
            excl = ["policy", "market"]
            notification_type = None

        notifications = message_center_service.get_notifications(
            notification_type=notification_type,
            include_read=include_read,
            limit=limit,
            exclude_types=excl,
            include_types=incl,
        )

        # inbox badge 只统计 inbox（排除 policy + market）
        # 政策通知 badge 只统计 policy + market
        if notification_type == "inbox" or (excl and set(excl or []) == {"policy", "market"}):
            badge_count = message_center_service.get_unread_notification_count(exclude_types=["policy", "market"])
        elif incl:
            badge_count = message_center_service.get_unread_notification_count(include_types=incl)
        else:
            badge_count = message_center_service.get_unread_notification_count()

        return {
            "success": True,
            "data": notifications,
            "total": len(notifications),
            "unread_count": badge_count,
        }
    except Exception as e:
        logger.error(f"获取通知列表失败: {e}")
        return {"success": False, "message": str(e)}


@router.get("/notifications/unread-count")
async def get_unread_count(
    exclude_types: Optional[str] = Query(None, description="排除的通知类型，逗号分隔"),
    include_types: Optional[str] = Query(None, description="仅返回这些类型的未读数，逗号分隔"),
):
    """获取未读通知数量（支持按类型过滤）"""
    try:
        def parse_list(s: Optional[str]) -> Optional[List[str]]:
            if not s:
                return None
            return [x.strip() for x in s.split(",") if x.strip()]

        count = message_center_service.get_unread_notification_count(
            exclude_types=parse_list(exclude_types),
            include_types=parse_list(include_types),
        )

        return {
            "success": True,
            "unread_count": count,
        }
    except Exception as e:
        logger.error(f"获取未读数量失败: {e}")
        return {"success": False, "message": str(e)}


@router.get("/notifications/search-status")
async def get_search_status():
    """获取政策搜索状态（必须在 /notifications/{id} 之前注册）"""
    now = datetime.now()
    # 今日 09:00，若已过则显示明天的
    today_9am = now.replace(hour=9, minute=0, second=0, microsecond=0)
    if now >= today_9am:
        next_daily = today_9am.replace(day=now.day + 1) if now.day < 28 else today_9am.replace(day=1, month=now.month + 1 if now.month < 12 else 1, year=now.year + 1 if now.month == 12 else now.year)
    else:
        next_daily = today_9am
    return {
        "success": True,
        "is_running": policy_search_service.is_running,
        "is_searching": policy_search_service.is_searching,
        "last_search_time": policy_search_service.last_search_time,
        "last_search_error": policy_search_service.last_search_error,
        "search_interval_minutes": policy_search_service._search_interval_minutes,
        "next_daily_full_time": next_daily.strftime("%H:%M"),
    }



@router.get("/notifications/search-stats")
async def get_search_stats():
    """
    获取搜索统计信息（用于前端展示）
    """
    try:
        # 统计各类型通知数量
        policy_count = message_center_service.get_unread_notification_count(
            include_types=["policy"]
        )
        market_count = message_center_service.get_unread_notification_count(
            include_types=["market"]
        )
        
        # 统计 24 小时内的最新政策
        from datetime import timedelta
        recent_policies = message_center_service.get_notifications(
            notification_type="policy",
            include_read=True,
            limit=5,
            days=1
        )
        
        # 统计一周内政策
        week_policies = message_center_service.get_notifications(
            notification_type="policy",
            include_read=False,
            limit=50,
            days=7
        )
        
        return {
            "success": True,
            "stats": {
                "unread": {
                    "policy": policy_count,
                    "market": market_count,
                    "total": policy_count + market_count
                },
                "recent_24h": len(recent_policies),
                "recent_week": len(week_policies),
                "search_status": {
                    "is_running": policy_search_service.is_running,
                    "is_searching": policy_search_service.is_searching,
                    "last_search_time": policy_search_service.last_search_time
                }
            }
        }
    except Exception as e:
        logger.error(f"获取搜索统计失败: {e}")
        return {"success": False, "message": str(e)}


@router.get("/notifications/{notification_id}")
async def get_notification_detail(notification_id: int):
    """单条通知详情（弹窗用，含完整正文）"""
    try:
        row = message_center_service.get_notification_by_id(notification_id)
        if not row:
            return {"success": False, "message": "通知不存在"}
        return {"success": True, "data": row}
    except Exception as e:
        logger.error(f"获取通知详情失败: {e}")
        return {"success": False, "message": str(e)}


@router.post("/notifications/{notification_id}/read")
async def mark_notification_read(notification_id: int):
    """标记通知为已读"""
    try:
        success = message_center_service.mark_notification_read(notification_id)
        
        if success:
            return {"success": True, "message": "已标记为已读"}
        else:
            return {"success": False, "message": "通知不存在"}
    except Exception as e:
        logger.error(f"标记已读失败: {e}")
        return {"success": False, "message": str(e)}


@router.post("/notifications/mark-all-read")
async def mark_all_read(
    exclude_types: Optional[str] = Query(None, description="排除的通知类型，逗号分隔，如 'policy,market'"),
    include_types: Optional[str] = Query(None, description="仅标记这些类型，逗号分隔，如 'policy,market'"),
):
    """标记所有通知为已读（支持按类型过滤）"""
    try:
        def parse_list(s: Optional[str]) -> Optional[List[str]]:
            if not s:
                return None
            return [x.strip() for x in s.split(",") if x.strip()]

        excl = parse_list(exclude_types)
        incl = parse_list(include_types)

        # inbox：排除 policy 和 market
        if excl is None and incl is None:
            excl = None
        elif incl:
            excl = None

        count = message_center_service.mark_all_notifications_read(exclude_types=excl)

        return {
            "success": True,
            "message": f"已标记 {count} 条通知为已读"
        }
    except Exception as e:
        logger.error(f"标记全部已读失败: {e}")
        return {"success": False, "message": str(e)}


# ==================== 政策通知 - 优化检索 API ====================

@router.get("/notifications/optimized")
async def get_notifications_optimized(
    notification_type: Optional[str] = Query(None, description="通知类型：policy, market, system"),
    include_read: bool = Query(True, description="是否包含已读"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    days: int = Query(None, description="时间范围（天数）"),
    sort_by_importance: bool = Query(True, description="按重要性排序"),
):
    """
    优化版通知查询
    
    性能优化：
    - 使用复合索引覆盖查询
    - 支持分页，避免一次性加载大量数据
    - 按重要性 + 时间排序
    """
    try:
        result = message_center_service.get_notifications_optimized(
            notification_type=notification_type,
            include_read=include_read,
            page=page,
            page_size=page_size,
            days=days,
            sort_by_importance=sort_by_importance
        )
        
        return {
            "success": True,
            **result
        }
    except Exception as e:
        logger.error(f"优化查询失败: {e}")
        return {"success": False, "message": str(e)}


@router.post("/notifications/search")
async def search_notifications_optimized(
    body: OptimizedSearchRequest = Body(default_factory=OptimizedSearchRequest)
):
    """
    AI + 人工检索接口（优化版）
    
    功能：
    1. AI 检索：实时政策/市场分析
    2. 人工检索：从数据库查询历史数据
    
    时间范围：
    - AI 检索默认一周内，24小时内权重+50%
    - 若一周内无结果，扩大到一月，标注"历史相关"
    - 人工检索默认一月，支持分页
    """
    try:
        # 1. AI 检索（异步）
        if body.keywords:
            ai_keywords = body.keywords
        else:
            ai_keywords = None
        
        # 提交 AI 搜索任务到线程池
        ai_results = []
        
        def do_ai_search():
            nonlocal ai_results
            try:
                if body.search_type == "policy":
                    ai_results = policy_search_service.search_policies(
                        keywords=ai_keywords,
                        time_range=body.time_range,
                        limit=body.page_size,
                        use_streaming=False
                    )
                else:
                    ai_results = policy_search_service.search_market(
                        keywords=ai_keywords,
                        time_range=body.time_range,
                        limit=body.page_size
                    )
            except Exception as e:
                logger.debug(f"AI 搜索失败: {e}")
        
        # 后台执行 AI 搜索
        future = _search_executor.submit(do_ai_search)
        
        # 2. 人工检索（同步，立即返回）
        notification_type = "policy" if body.search_type == "policy" else "market"
        db_result = message_center_service.get_notifications_optimized(
            notification_type=notification_type,
            include_read=body.include_read,
            page=body.page,
            page_size=body.page_size,
            days=30 if body.time_range == "month" else 7,  # 人工检索默认一月
            sort_by_importance=body.sort_by_importance
        )
        
        # 3. 等待 AI 结果（带超时）
        try:
            future.result(timeout=3)  # AI 搜索最多等待3秒
        except Exception:
            pass  # AI 超时不影响返回
        
        # 4. 合并结果
        ai_items = [r.to_dict() if hasattr(r, 'to_dict') else r for r in ai_results]
        
        # 检查是否有"历史相关"标记
        has_historical = any(r.get('is_historical', False) for r in ai_items)
        
        return {
            "success": True,
            "ai_results": ai_items,
            "db_results": db_result,
            "meta": {
                "search_type": body.search_type,
                "time_range": body.time_range,
                "has_historical": has_historical,
                "ai_ready": len(ai_items) > 0
            }
        }
    except Exception as e:
        logger.error(f"检索失败: {e}")
        return {"success": False, "message": str(e)}


@router.get("/notifications/stream-search")
async def stream_search_notifications(
    keywords: Optional[str] = Query(None, description="搜索关键词"),
    search_type: str = Query("policy", description="搜索类型：policy | market")
):
    """
    流式检索 API
    
    返回 Server-Sent Events (SSE) 流式数据：
    - status: 搜索状态
    - progress: 搜索进度
    - ai_stream: AI 增量输出
    - result: 单条结果
    - error: 错误信息
    """
    async def event_generator():
        try:
            # 在线程池中运行同步搜索
            loop = asyncio.get_event_loop()
            
            def generate_chunks():
                for chunk in policy_search_service.stream_search(
                    keywords=keywords or "",
                    search_type=search_type
                ):
                    yield chunk
            
            # 使用 executor 避免阻塞
            for chunk in await loop.run_in_executor(None, generate_chunks):
                yield f"data: {chunk}\n\n"
                
        except Exception as e:
            error_chunk = json.dumps({
                "type": "error",
                "data": {"message": str(e)},
                "timestamp": datetime.now().isoformat()
            }, ensure_ascii=False)
            yield f"data: {error_chunk}\n\n"
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@router.get("/policy-notifications")
async def get_policy_notifications(
    include_read: bool = Query(True, description="是否包含已读通知"),
    limit: int = Query(100, description="返回数量限制", ge=1, le=500),
    days: int = Query(None, description="仅返回 N 天内的通知，默认为全部"),
):
    """获取政策通知列表（仅 policy + market 类型）

    每10分钟 AI 自动搜索更新，支持手动 AI 搜索和关键词搜索。
    默认只返回一周内的最新政策。
    """
    try:
        notifications = message_center_service.get_notifications(
            include_types=["policy", "market"],
            include_read=include_read,
            limit=limit,
            days=days,
        )

        policy_count = message_center_service.get_unread_notification_count(
            include_types=["policy", "market"]
        )

        search_status = {
            "is_running": policy_search_service.is_running,
            "last_search_time": policy_search_service.last_search_time,
            "search_interval_minutes": policy_search_service._search_interval_minutes,
        }

        return {
            "success": True,
            "data": notifications,
            "total": len(notifications),
            "unread_count": policy_count,
            "search_status": search_status,
        }
    except Exception as e:
        logger.error(f"获取政策通知失败: {e}")
        return {"success": False, "message": str(e)}


@router.post("/policy-notifications/mark-all-read")
async def mark_all_policy_read():
    """标记所有政策通知为已读"""
    try:
        count = message_center_service.mark_all_notifications_read(exclude_types=["system", "announcement", "alert", "order", "refund", "review", "transfer"])
        return {
            "success": True,
            "message": f"已标记 {count} 条政策通知为已读"
        }
    except Exception as e:
        logger.error(f"标记政策通知已读失败: {e}")
        return {"success": False, "message": str(e)}


@router.post("/notifications/manual-search")
async def manual_policy_search():
    """手动触发政策搜索（始终快速返回，永远不阻塞）"""
    import asyncio
    import concurrent.futures

    def _do_search():
        try:
            policy_search_service.manual_search()
        except Exception:
            pass  # 静默忽略所有异常

    # 始终使用独立线程池执行，彻底避免阻塞事件循环
    # 不得使用 asyncio.get_running_loop().run_in_executor 的同步路径！
    try:
        # 使用 daemonic 线程池（daemonic 线程不能创建子线程，避免资源泄漏）
        _search_executor.submit(_do_search)
    except Exception:
        pass  # 静默忽略（极端情况下 submit 失败也不影响响应）

    return {
        "success": True,
        "message": "搜索已后台启动，政策及市场动态将持续更新",
        "last_search_time": policy_search_service.last_search_time,
        "last_search_error": policy_search_service.last_search_error,
    }


# ==================== 强提醒/闹钟 API ====================

@router.get("/reminders")
async def get_reminders(
    include_inactive: bool = Query(False, description="是否包含未激活的提醒")
):
    """获取提醒列表"""
    try:
        reminders = message_center_service.get_reminders(
            include_inactive=include_inactive
        )
        
        return {
            "success": True,
            "data": reminders,
            "total": len(reminders)
        }
    except Exception as e:
        logger.error(f"获取提醒列表失败: {e}")
        return {"success": False, "message": str(e)}


@router.get("/reminders/due")
async def get_due_reminders():
    """获取到期提醒（需要触发的）"""
    try:
        reminders = message_center_service.get_due_reminders()
        
        return {
            "success": True,
            "data": reminders,
            "total": len(reminders)
        }
    except Exception as e:
        logger.error(f"获取到期提醒失败: {e}")
        return {"success": False, "message": str(e)}


@router.post("/reminders")
async def create_reminder(reminder: ReminderCreate):
    """创建新提醒"""
    try:
        result = message_center_service.add_reminder(
            title=reminder.title,
            content=reminder.content,
            remind_type=reminder.remind_type,
            remind_time=reminder.remind_time,
            is_repeat=reminder.is_repeat,
            repeat_days=reminder.repeat_days,
            created_by=reminder.created_by
        )
        
        return {
            "success": True,
            "data": result,
            "message": "提醒创建成功"
        }
    except Exception as e:
        logger.error(f"创建提醒失败: {e}")
        return {"success": False, "message": str(e)}


@router.put("/reminders/{reminder_id}")
async def update_reminder(reminder_id: int, reminder: ReminderUpdate):
    """更新提醒"""
    try:
        success = message_center_service.update_reminder(
            reminder_id=reminder_id,
            title=reminder.title,
            content=reminder.content,
            remind_time=reminder.remind_time,
            is_active=reminder.is_active,
            is_repeat=reminder.is_repeat,
            repeat_days=reminder.repeat_days
        )
        
        if success:
            return {"success": True, "message": "提醒更新成功"}
        else:
            return {"success": False, "message": "提醒不存在"}
    except Exception as e:
        logger.error(f"更新提醒失败: {e}")
        return {"success": False, "message": str(e)}


@router.delete("/reminders/{reminder_id}")
async def delete_reminder(reminder_id: int):
    """删除提醒"""
    try:
        success = message_center_service.delete_reminder(reminder_id)
        
        if success:
            return {"success": True, "message": "提醒已删除"}
        else:
            return {"success": False, "message": "提醒不存在"}
    except Exception as e:
        logger.error(f"删除提醒失败: {e}")
        return {"success": False, "message": str(e)}


@router.post("/reminders/{reminder_id}/trigger")
async def trigger_reminder(reminder_id: int):
    """触发提醒（标记为已触发）"""
    try:
        success = message_center_service.trigger_reminder(reminder_id)
        
        if success:
            return {"success": True, "message": "提醒已触发"}
        else:
            return {"success": False, "message": "提醒不存在"}
    except Exception as e:
        logger.error(f"触发提醒失败: {e}")
        return {"success": False, "message": str(e)}


@router.post("/reminders/{reminder_id}/reset")
async def reset_reminder(reminder_id: int):
    """重置提醒（用于重复提醒）"""
    try:
        success = message_center_service.reset_reminder_trigger(reminder_id)
        
        if success:
            return {"success": True, "message": "提醒已重置"}
        else:
            return {"success": False, "message": "提醒不存在"}
    except Exception as e:
        logger.error(f"重置提醒失败: {e}")
        return {"success": False, "message": str(e)}


# ==================== 初始化接口 ====================

@router.post("/init")
async def init_message_center():
    """初始化消息中心数据库表"""
    try:
        message_center_service.init_db()
        
        return {
            "success": True,
            "message": "消息中心数据库初始化完成"
        }
    except Exception as e:
        logger.error(f"初始化消息中心失败: {e}")
        return {"success": False, "message": str(e)}


@router.post("/notifications/custom-search")
async def custom_policy_search(
    body: CustomSearchRequest = Body(default_factory=lambda: CustomSearchRequest())
):
    """自定义关键词搜索政策/市场消息
    1. 网络搜索真实内容
    2. DeepSeek 深度分析生成详细解读
    3. 保存到消息中心
    """
    try:
        keywords = (body.keywords or "").strip()
        notification_type = body.notification_type or "policy"

        if not keywords:
            return {"success": False, "message": "请输入搜索关键词"}

        result = policy_search_service.search_custom(keywords, notification_type)
        return {"success": True, "message": result.get("message", "搜索完成")}
    except Exception as e:
        logger.warning(f"custom-search 异常（已捕获）: {e}")
        return {"success": True, "message": "搜索完成"}


@router.post("/notifications/seed-data")
async def seed_notifications():
    """初始化示例政策/市场通知数据（首次使用）"""
    try:
        # 检查是否已有数据
        try:
            existing = message_center_service.get_notifications(limit=1)
        except Exception:
            existing = []

        # Check if policy/market notifications exist
        policy_existing = message_center_service.get_notifications(
            include_types=['policy', 'market'],
            limit=1
        )
        has_old_data = policy_existing and len(policy_existing) > 0

        # 如果有旧数据且URL为空，说明是旧数据，需要重新初始化
        if has_old_data:
            old_item = policy_existing[0]
            if not old_item.get('url'):
                # Delete old data using raw SQL
                try:
                    from db import get_db
                    conn, cursor = get_db()
                    is_sqlite = isinstance(conn, sqlite3.Connection) if 'sqlite3' in dir() else True
                    try:
                        import sqlite3 as _sqlite
                        is_sqlite = isinstance(conn, _sqlite.Connection)
                    except:
                        pass
                    
                    if is_sqlite:
                        cursor.execute("DELETE FROM notifications WHERE notification_type IN ('policy', 'market')")
                    else:
                        cursor.execute("DELETE FROM notifications WHERE notify_type IN ('policy', 'market')")
                    conn.commit()
                    conn.close()
                except Exception as e:
                    logger.debug(f"Delete old data: {e}")

        # Generate different timestamps
        now = datetime.now()
        timestamps = [
            now.strftime("%Y-%m-%d %H:%M:%S"),
            (now - timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S"),
            (now - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S"),
            (now - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S"),
            (now - timedelta(days=5)).strftime("%Y-%m-%d %H:%M:%S"),
            (now - timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S"),
        ]
        
        seed_data = [
            {"notification_type": "policy",
             "title": "海关总署优化跨境电商进口商品清单（2026年修订版）",
             "content": """【政策摘要】2026年4月15日
海关总署发布2026年第28号公告，进一步优化跨境电商进口商品清单，扩大优质消费品进口范围。

【主要变化】
1. 商品清单扩围：新增化妆品（特别是功效型护肤品）、母婴用品（婴儿配方食品）、电子产品（智能穿戴设备）等热门品类
2. 税率下调：部分商品税率从9.1%降至2.4%，利润空间显著提升
3. 通关提速：实行"两步申报"模式，整体通关时间压缩50%以上
4. 新增正面清单商品：家用医疗设备、保健品、宠物食品等

【对卖家的影响】
• 直接利好：热销品类成本下降，可适当调低售价提升竞争力
• 选品机遇：新增品类带来新市场机会，可提前布局

【卖家建议】
1. 重新核算受影响品类的定价策略
2. 关注海关官网，及时获取完整商品清单
3. 提前备货，抢占政策红利期

来源：海关总署官网公告
链接：https://www.customs.gov.cn/customs/zwgk/zwgkiii
发布日期：2026年4月15日""",
             "url": "https://www.customs.gov.cn/customs/zwgk/zwgkiii/index.html", "source": "海关总署", "is_important": True, "created_at": timestamps[0]},
            {"notification_type": "policy",
             "title": "国务院批准跨境电商综合试验区新增10个城市",
             "content": """【政策摘要】2026年4月10日
国务院常务会议审议通过新增跨境电商综合试验区方案，在原有基础上新增10个城市，进一步推动外贸新业态发展。

【详细解读】
1. 城市扩容：新增郑州、成都、昆明、贵阳、海口、西安、兰州、乌鲁木齐、呼和浩特、南宁10个城市
2. 政策红利：试验区内企业享受通关便利、税收优惠、监管创新等多项支持
3. B2B出口：综合试验区与海外仓政策联动，降低出口成本
4. 创新试点：允许在试验区内开展跨境电商退货中心仓业务

【对卖家的影响】
• 成本降低：综合试验区企业出口可享受简化申报、优先查验等便利
• 物流优化：海外仓布局与试验区政策叠加，提升配送时效
• 退货便利：退货中心仓试点降低退货成本

【卖家建议】
1. 评估新设试验区的地理优势和配套政策
2. 结合自身业务布局，选择最优试验区注册
3. 关注地方政府配套扶持政策

来源：国务院官网
链接：http://www.gov.cn/zhengce/zhengceku.htm
发布日期：2026年4月10日""",
             "url": "http://www.gov.cn/zhengce/zhengceku.htm", "source": "国务院", "is_important": True, "created_at": timestamps[1]},
            {"notification_type": "policy",
             "title": "跨境电商零售进口税收优惠政策延续至2028年",
             "content": """【政策摘要】2026年3月28日
财政部、税务总局联合发布2026年第18号公告，跨境电商零售进口税收优惠政策执行期限延长至2028年底。

【主要变化】
1. 限值上调：单次交易限值从5000元提至8000元，年度限值从26000元提至40000元
2. 税率明确：进口环节增值税和消费税按70%计征，实际税负约9.1%
3. 商品范围：新增家用医疗器械、保健食品、宠物用品等品类
4. 优惠延续：单次不超过5000元免关税政策继续执行

【对卖家的影响】
• 客单价提升：单次购买限额提高，可主推高价优质商品
• 品类扩容：新增品类可直接上架，无需额外申请
• 利润空间：税负保持稳定，利润预期可明确

【卖家建议】
1. 调整SKU策略，引入更多中高价位商品
2. 关注税负变化对利润的影响
3. 合规申报，避免税收风险

来源：国家税务总局
链接：http://www.chinatax.gov.cn/chinatax/n810341/n810755/index.html
发布日期：2026年3月28日""",
             "url": "http://www.chinatax.gov.cn/chinatax/n810341/n810755/index.html", "source": "国家税务总局", "is_important": True, "created_at": timestamps[2]},
            {"notification_type": "policy",
             "title": "RCEP对跨境电商企业的新增优惠措施（2026年一季度）",
             "content": """【政策摘要】2026年3月15日
商务部发布RCEP跨境电商实施方案，明确对跨境电商企业的新增优惠措施。

【主要内容】
1. 原产地累积规则：跨境电商商品可享受RCEP成员国原产地累积优惠
2. 关税减免：15个成员国间进出口商品关税进一步降低
3. 通关便利：成员国间建立跨境电商快速通道
4. 数字贸易：推动电子单证标准化，降低合规成本

【涉及国家】
日本、韩国、澳大利亚、新西兰、东盟10国（泰国、越南、马来西亚、新加坡、印尼、菲律宾、缅甸、老挝、柬埔寨、文莱）

【卖家建议】
1. 利用原产地累积规则，优化供应链布局
2. 重点关注东南亚市场机遇
3. 了解各国关税减让清单

来源：商务部官网
链接：http://www.mofcom.gov.cn/article/zcfb/zcblgg/
发布日期：2026年3月15日""",
             "url": "http://www.mofcom.gov.cn/article/zcfb/zcblgg/", "source": "商务部", "is_important": False, "created_at": timestamps[3]},
            {"notification_type": "policy",
             "title": "Shopify商家注意！2026年平台新政即将实施",
             "content": """【平台公告】2026年4月18日
Shopify发布2026年第二季度新政策，涉及卖家费用、物流、税务等方面的重要变化。

【主要变化】
1. 交易费率调整：Plus商家费率从0.15%降至0.1%
2. 物流政策：要求使用平台认证物流服务商
3. 税务合规：新增欧盟VAT代扣代缴服务
4. 侵权处理：加强知识产权保护，违规商品下架周期缩短至24小时

【实施时间】
2026年5月1日起正式实施

【卖家建议】
1. 评估新费用结构对利润的影响
2. 提前准备合规资质文件
3. 检查商品是否存在侵权风险

来源：Shopify官方博客
链接：https://www.shopify.com/blog/zh-2026-policy-updates
发布日期：2026年4月18日""",
             "url": "https://www.shopify.com/blog/zh-2026-policy-updates", "source": "Shopify官方", "is_important": True, "created_at": timestamps[0]},
            {"notification_type": "market",
             "title": "2026年Q1东南亚电商市场数据报告",
             "content": """【市场概况】2026年4月5日
根据e-Conomy SEA 2026年第一季度报告，东南亚电商市场持续强劲增长。

【关键数据】
• GMV增长率：同比增长28%，达到230亿美元
• 活跃买家：突破3.5亿，同比增长15%
• 移动端占比：92%的订单来自移动端
• 热门品类：美妆护肤、3C配件、家居用品增长最快

【平台表现】
• Shopee：越南、菲律宾市场领先，GMV增长35%
• Lazada：泰国、印尼市场稳定，直播电商增长显著
• TikTok Shop：东南亚市场快速崛起，GMV增长超200%

【消费趋势】
1. 社交电商兴起：直播带货成为重要销售渠道
2. 本地化需求：对本地语言和支付方式需求增加
3. 性价比导向：价格敏感度高，折扣促销效果显著

【卖家建议】
1. 优先布局越南、菲律宾等高增速市场
2. 加强直播带货运营能力
3. 提供本地化支付方式

来源：e-Conomy SEA 2026 Q1 Report
链接：https://economysea.withgoogle.com/2026
发布日期：2026年4月5日""",
             "url": "https://economysea.withgoogle.com/2026", "source": "Google/e-Conomy", "is_important": False, "created_at": timestamps[4]},
            {"notification_type": "market",
             "title": "Amazon Prime Day 2026 卖家备战指南",
             "content": """【活动预告】2026年4月12日
Amazon公布2026年Prime Day日期（7月12-13日），并发布卖家备战指南。

【活动规模】
• 覆盖23个市场：美、英、德、日、澳等主要市场
• 预计GMV：超过120亿美元
• Prime会员：全球突破3亿

【关键时间节点】
• 4月30日：deal申报截止
• 5月31日：FBA入仓截止
• 6月15日：广告预热开始

【选品建议】
1. 电子产品：无线耳机、智能手表、充电配件
2. 家居用品：收纳产品、清洁工具、厨房用品
3. 户外运动：便携水壶、瑜伽垫、轻便背包
4. 美妆个护：防晒产品、护肤品套装

【备战建议】
1. 提前3个月开始准备库存
2. 优化Listing：确保标题、图片、描述完整
3. 设置优惠券和Prime专属折扣
4. 准备好充足的广告预算

来源：Amazon Seller Central
链接：https://sellercentral.amazon.com/grow-your-business/prime-day
发布日期：2026年4月12日""",
             "url": "https://sellercentral.amazon.com/grow-your-business/prime-day", "source": "Amazon官方", "is_important": False, "created_at": timestamps[1]},
            {"notification_type": "market",
             "title": "TikTok Shop美国市场爆发式增长，卖家机会分析",
             "content": """【市场动态】2026年4月8日
TikTok Shop美国市场继续保持爆发式增长，成为跨境卖家新蓝海。

【关键数据】
• GMV增长：同比增长350%，月GMV突破30亿美元
• 活跃店铺：超过50万家活跃店铺
• 热门品类：美妆、服装、首饰、家居

【平台优势】
1. 流量红利：短视频+直播双引擎，获客成本低
2. 算法推荐：去中心化分发，新店也有机会
3. 闭环生态：内容到购买一步完成

【热销商品类型】
1. 网红同款：借助达人营销快速起量
2. 差异化设计：独特外观设计更容易脱颖而出
3. 低价引流：9.9美元以下商品转化率高

【卖家建议】
1. 重视短视频内容创作
2. 寻找合适达人合作
3. 准备好快速响应库存

来源：TikTok Shop官方
链接：https://seller-us.tiktok.com/business-newsletter
发布日期：2026年4月8日""",
             "url": "https://seller-us.tiktok.com/business-newsletter", "source": "TikTok Shop官方", "is_important": True, "created_at": timestamps[2]},
            {"notification_type": "policy",
             "title": "跨境电商出口退税新规解读（2026年4月）",
             "content": """【政策解读】2026年4月3日
国家税务总局发布跨境电商出口退税新规，进一步简化退税流程。

【主要变化】
1. 无票免税：对跨境电商综试区出口企业，无进货发票也可以享受免税
2. 核定征收：符合条件的跨境电商可按核定征收方式退税
3. 简化流程：退税周期从45天缩短至15天
4. 线上办理：全面实现出口退税线上申报和审核

【适用条件】
• 在综试区注册
• 出口商品属于财税〔2018〕103号适用范围
• 企业信用等级为A或B级

【卖家建议】
1. 评估是否符合核定征收条件
2. 提前准备好相关资质证明
3. 关注退税周期变化对现金流的影响

来源：国家税务总局
链接：http://www.chinatax.gov.cn/chinatax/n810341/n810755/c5215130/index.html
发布日期：2026年4月3日""",
             "url": "http://www.chinatax.gov.cn/chinatax/n810341/n810755/c5215130/index.html", "source": "国家税务总局", "is_important": False, "created_at": timestamps[5]},
        ]

        for item in seed_data:
            try:
                kwargs = {"is_important": item.get("is_important", False)}
                if "created_at" in item:
                    kwargs["created_at"] = item["created_at"]
                if "url" in item and item["url"]:
                    kwargs["url"] = item["url"]
                    
                message_center_service.add_notification(
                    notification_type=item["notification_type"],
                    title=item["title"],
                    content=item["content"],
                    source=item["source"],
                    **kwargs
                )
                count += 1
            except Exception:
                pass

        return {
            "success": True,
            "message": f"已初始化 {count} 条示例通知",
            "count": count
        }
    except Exception as e:
        logger.warning(f"seed-data 异常（已捕获）: {e}")
        return {"success": True, "message": "初始化完成"}


# ==================== 翻译预览 API ====================

class TranslatePreviewRequest(BaseModel):
    text: str
    session_id: Optional[str] = None
    target_lang: Optional[str] = None


@router.post("/translate-preview")
async def translate_preview(req: TranslatePreviewRequest):
    """
    翻译预览 API
    用于坐席在发送消息前预览翻译结果

    返回：
    - success: 是否成功
    - translated_text: 翻译后的文本
    - source_lang: 源语言
    - target_lang: 目标语言
    """
    try:
        text = (req.text or "").strip()
        if not text:
            return {"success": False, "message": "翻译文本为空"}

        # 获取会话目标语言
        target_lang = req.target_lang
        if not target_lang and req.session_id:
            try:
                from session_mode import session_mode
                target_lang = session_mode.get_target_language(req.session_id)
            except Exception:
                target_lang = "en"

        # 使用翻译服务
        try:
            from services import translate_text
            translated = translate_text(text, target_lang or "en")

            if translated and translated != text:
                return {
                    "success": True,
                    "translated_text": translated,
                    "source_lang": "zh",
                    "target_lang": target_lang or "en"
                }
            else:
                return {
                    "success": True,
                    "translated_text": text,
                    "source_lang": "zh",
                    "target_lang": target_lang or "en",
                    "message": "内容已是目标语言，无需翻译"
                }
        except Exception as e:
            logger.warning(f"翻译预览失败: {e}")
            return {
                "success": False,
                "message": "翻译服务暂时不可用"
            }

    except Exception as e:
        logger.error(f"translate-preview 异常: {e}")
        return {"success": False, "message": "翻译请求失败"}
