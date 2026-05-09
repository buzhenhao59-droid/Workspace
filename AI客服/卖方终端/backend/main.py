# -*- coding: utf-8 -*-
"""
金牌客服系统 API - FastAPI 后端商业版
提供 REST API 接口供前端调用
"""
import sys as _sys
import os as _os

# Fix site-packages path for custom Python installation
# 自动修复：如果系统默认路径找不到 fastapi，尝试搜索常见 site-packages 位置
try:
    import fastapi
except ImportError:
    # 尝试常见的非标准 site-packages 路径
    _possible_sp = [
        r"D:\lib\site-packages",
        _os.path.join(_os.path.dirname(_sys.executable), "Lib", "site-packages"),
    ]
    for _p in _possible_sp:
        if _p not in _sys.path and _os.path.isdir(_p):
            _sys.path.insert(0, _p)
            break

import uuid
import logging
import threading
import requests
import json
import os
import socket
import hashlib
import hmac
import time
import random
import string
import re
from contextlib import asynccontextmanager
from typing import Optional, List, Any, Dict
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
import inspect

from fastapi import APIRouter, FastAPI, HTTPException, Depends, Request, UploadFile, File, Query, WebSocket, WebSocketDisconnect, Security, Header, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, PlainTextResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, AliasChoices, ConfigDict
from pydantic_settings import BaseSettings

# ============== 日志配置（统一格式）==============
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
# 降低第三方库日志级别，减少噪音
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# ============== Sentry APM 初始化（错误追踪）==============
_sentry_dsn = os.getenv("SENTRY_DSN", "")
if _sentry_dsn:
    try:
        import sentry_sdk
        sentry_sdk.init(
            dsn=_sentry_dsn,
            traces_sample_rate=0.1,
            environment=os.getenv("ENVIRONMENT", "development"),
        )
        logger.info(f"Sentry APM 已初始化 (DSN: ...{_sentry_dsn[-8:]})")
    except ImportError:
        logger.warning("sentry-sdk 未安装，跳过 APM 初始化")
    except Exception as e:
        logger.warning(f"Sentry APM 初始化失败: {e}")

# ============== 审计日志辅助 ==============
def _audit(event_type: str, operator: str, target_type: str,
           target_id: str = None, detail: str = None,
           request: Request = None):
    """线程安全地将审计日志写入数据库（异步不阻塞响应）。"""
    ip = None
    ua = None
    if request:
        if request.client:
            ip = request.client.host
        ua = request.headers.get("User-Agent")
    try:
        from db import write_audit_log
        threading.Thread(
            target=write_audit_log,
            args=(event_type, operator, target_type, target_id, detail, ip, ua),
            daemon=True,
        ).start()
    except Exception as e:
        logger.warning("审计日志写入失败: %s", e)

# ============== 导入所有依赖模块 ==============
try:
    from config import (
        SECRET_KEY, ADMIN_PASSWORD, JWT_SECRET_KEY, JWT_ALGORITHM,
        JWT_ACCESS_TOKEN_EXPIRE_MINUTES, JWT_REFRESH_TOKEN_EXPIRE_DAYS,
        ALLOWED_ORIGINS, NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD,
        DEEPSEEK_API_KEY, DEEPSEEK_API_URL, GRAPHRAG_API_URL,
        BUYER_API_HOST, INTERNAL_API_SECRET, GOLD_CS_BASE_URL,
        OPERATOR_USERNAME, OPERATOR_PASSWORD,
    )
    from jwt_auth import (
        get_current_user, get_current_admin, get_current_super_admin, get_current_staff, get_current_seller,
        get_current_admin_or_super_admin, get_current_admin_only,
        create_access_token, create_refresh_token, verify_access_token,
        refresh_access_token, extract_token_from_request, check_module_access,
    )
except ImportError as e:
    logger.warning(f"config/jwt_auth 导入失败: {e}")
    GOLD_CS_BASE_URL = os.getenv("GOLD_CS_BASE_URL", "http://127.0.0.1:5000")

try:
    from database import Neo4jConnection
except ImportError:
    Neo4jConnection = None
    logger.warning("Neo4j 数据库模块不可用")

try:
    from services import (
        query_graphrag, generate_customer_response, translate_text,
        detect_language, SUPPORTED_LANGUAGES, LANGUAGE_NAMES,
        LANGUAGE_SWITCH_MESSAGES, _deepseek_circuit, _neo4j_circuit,
        _graphrag_circuit,
    )
except ImportError as e:
    logger.warning(f"services 导入失败: {e}")
    query_graphrag = None
    generate_customer_response = None
    translate_text = None
    detect_language = None
    SUPPORTED_LANGUAGES = ["zh", "en", "es", "fr", "de", "ja", "ko", "pt", "ru", "ar"]
    LANGUAGE_NAMES = {}
    LANGUAGE_SWITCH_MESSAGES = {}
    _deepseek_circuit = None
    _neo4j_circuit = None
    _graphrag_circuit = None

try:
    from shop_router import router as shop_router
except ImportError:
    shop_router = None
    logger.warning("shop_router 不可用")

try:
    from api_router import router as unified_router
except ImportError:
    unified_router = None
    logger.warning("api_router 不可用")

try:
    from message_center_router import router as message_center_router
except ImportError:
    message_center_router = None
    logger.warning("message_center_router 不可用")

try:
    from enhanced_policy_router import router as enhanced_policy_router
except ImportError:
    enhanced_policy_router = None
    logger.warning("enhanced_policy_router 不可用")

try:
    from merchant_auth import router as merchant_router
except ImportError:
    merchant_router = None
    logger.warning("merchant_auth 不可用")

try:
    from realtime_server import realtime_server
    _realtime_available = True
except ImportError:
    realtime_server = None
    _realtime_available = False
    logger.warning("realtime_server 不可用")

try:
    from agent_service import agent_service
except ImportError:
    agent_service = None
    logger.warning("agent_service 不可用")

try:
    from message_service import message_service
except ImportError:
    message_service = None
    logger.warning("message_service 不可用")

try:
    from redis_store import redis_store, RedisSessionStore
    _redis_available = True
except ImportError:
    redis_store = None
    RedisSessionStore = None
    _redis_available = False
    logger.warning("Redis 模块未安装，使用内存会话存储")

try:
    from rate_limiter import RateLimiter, RateLimitMiddleware, rate_limiter
    _rate_limiter_available = True
except ImportError:
    RateLimiter = None
    RateLimitMiddleware = None
    rate_limiter = None
    _rate_limiter_available = False
    logger.warning("rate_limiter 不可用")

try:
    from monitor import metrics_collector, MetricsMiddleware, MetricsCollector
    _monitor_available = True
except ImportError:
    metrics_collector = None
    MetricsMiddleware = None
    MetricsCollector = None
    _monitor_available = False
    logger.warning("monitor 不可用")

try:
    from db import init_db, init_default_seller
except ImportError:
    init_db = None
    init_default_seller = None
    logger.warning("db 模块不完整")

try:
    from mysql_db import _init_mysql_pool
except ImportError:
    _init_mysql_pool = None
    logger.warning("mysql_db 不可用")

try:
    from platform_sync import _ensure_sync_db, start_auto_sync, stop_auto_sync
except ImportError:
    _ensure_sync_db = None
    start_auto_sync = None
    stop_auto_sync = None
    logger.warning("platform_sync 不可用")

try:
    from message_center_service import message_center_service
except ImportError:
    message_center_service = None
    logger.warning("message_center_service 不可用")

try:
    from policy_search_service import policy_search_service
except ImportError:
    policy_search_service = None
    logger.warning("policy_search_service 不可用")

try:
    from session_mode import session_mode
except ImportError:
    session_mode = None
    logger.warning("session_mode 不可用")


# ============== 管理员用户配置 ==============
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")


def _build_static_admin_users() -> Dict[str, Dict[str, Any]]:
    """内存中的静态账号：超级管理员 + 可选运营账号（OPERATOR_PASSWORD 非空时启用）。"""
    from config import ADMIN_PASSWORD as _ap, OPERATOR_USERNAME as _ou, OPERATOR_PASSWORD as _op
    users: Dict[str, Dict[str, Any]] = {
        ADMIN_USERNAME: {
            "id": "admin-001",
            "username": ADMIN_USERNAME,
            "password": _ap or "123456",
            "role": "admin",
            "permissions": ["all"],
            "label": "超级管理员",
            "created_at": datetime.now().isoformat(),
        }
    }
    if _op and _ou and _ou != ADMIN_USERNAME:
        users[_ou] = {
            "id": "operator-001",
            "username": _ou,
            "password": _op,
            "role": "operator",
            "permissions": ["portal"],
            "label": "运营",
            "created_at": datetime.now().isoformat(),
        }
    return users


# ============== 开发者手机号账号 ==============
# 手机号 -> admin_users 中的 username 映射
DEV_PHONE_MAP: Dict[str, str] = {}

def _build_dev_phone_users() -> None:
    """从 .env 读取开发者手机号列表并注册到 admin_users"""
    dev_phones_raw = os.getenv("DEV_PHONE_USERS", "").strip()
    if not dev_phones_raw:
        return
    for entry in dev_phones_raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        parts = entry.split(":", 1)
        if len(parts) != 2:
            continue
        phone, password = parts
        phone = phone.strip()
        password = password.strip()
        if not phone or not password:
            continue
        # 使用手机号作为 username（内部标识）
        username = f"dev_{phone}"
        admin_users[username] = {
            "id": f"dev-{phone}",
            "username": username,
            "password": password,
            "role": "admin",
            "permissions": ["all"],
            "label": f"开发者({phone})",
            "created_at": datetime.now().isoformat(),
            "phone": phone,  # 原始手机号
        }
        DEV_PHONE_MAP[phone] = username
        logger.info(f"[Dev Auth] 注册开发者手机号账号: {phone}")



# ============== 短信验证码存储（内存，生产应换 Redis）==============
# 结构: { phone: {"code": "123456", "expires_at": timestamp} }
_sms_code_store: Dict[str, Dict[str, Any]] = {}


def _generate_sms_code(length: int = 6) -> str:
    return "".join(random.choices(string.digits, k=length))


def _is_valid_phone(phone: str) -> bool:
    # DEV_PHONE_USERS 中的内部号可能不符合 1[3-9] 号段（如 12345678910）
    if phone in DEV_PHONE_MAP:
        return True
    return bool(re.fullmatch(r"1[3-9]\d{9}", phone))


def _is_valid_email(email: str) -> bool:
    return bool(re.fullmatch(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$", email))


admin_users: Dict[str, Dict[str, Any]] = _build_static_admin_users()

# 构建开发者手机号账号（必须在 admin_users 定义之后）
_build_dev_phone_users()


def _verify_user_login_password(user: Dict[str, Any], password: str) -> bool:
    """按账号校验密码（支持明文 + PBKDF2，与 config.verify_admin_password 一致）。"""
    from config import verify_admin_password
    stored = user.get("password") or ""
    return verify_admin_password(password, stored)


def _verify_admin_pw(password: str) -> bool:
    """兼容：仅校验超级管理员账号密码（修改密码等场景）。"""
    u = admin_users.get(ADMIN_USERNAME)
    if not u:
        return False
    return _verify_user_login_password(u, password)


# ============== 用户角色枚举 ==============
class UserRole(str, Enum):
    ADMIN = "admin"
    AGENT = "agent"
    SELLER = "seller"


# ============== 请求模型 ==============
class AdminLoginRequest(BaseModel):
    """静态登录页只传密码时默认用户名为 admin。"""
    username: str = "admin"
    password: str


class AdminUserCreate(BaseModel):
    username: str
    password: str
    role: str = "agent"
    permissions: List[str] = []


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


class QuickReplyCreate(BaseModel):
    category: str = "通用"
    title: str
    content: str
    shortcut: Optional[str] = None


class QuickReplyUpdate(BaseModel):
    category: Optional[str] = None
    title: Optional[str] = None
    content: Optional[str] = None
    shortcut: Optional[str] = None


class ReviewReplyRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    review_ids: List[str]
    content: Optional[str] = Field(default="", validation_alias=AliasChoices("content", "reply_content"))
    use_template_id: Optional[str] = None
    template_id: Optional[int] = None


class CreateRuleRequest(BaseModel):
    rule_type: str = "star_range"
    star_min: int = Field(default=1, ge=1, le=5)
    star_max: int = Field(default=5, ge=1, le=5)
    reply_content: str = ""
    is_enabled: bool = True


class CreateTemplateRequest(BaseModel):
    name: str
    content: str
    category: str = "general"
    is_default: bool = False


class AfterSaleCreateRequest(BaseModel):
    order_id: str
    customer_id: str = ""
    type: str = "退货退款"
    reason: str
    amount: float = 0
    description: str = ""


class PreSaleNoteCreate(BaseModel):
    """与前端 pre-sale-notes.html 表单字段完全对齐"""
    # 基本信息（与 db.py create_pre_sale_note 参数名一致）
    title: str = ""
    content: str = ""
    category: str = "通用"
    order_id: Optional[str] = None
    customer_id: Optional[str] = None
    customer_name: Optional[str] = None
    nickname: Optional[str] = None
    platform: str = "other"
    platform_id: Optional[str] = None
    country: Optional[str] = None
    region: Optional[str] = None
    language: str = "zh"
    # 客户历史
    is_old_customer: int = 0
    repeat_purchase_count: int = 0
    has_complaints: int = 0
    has_disputes: int = 0
    has_negative_reviews: int = 0
    has_asked_shipping: int = 0
    has_asked_logistics: int = 0
    # 偏好
    preference_style: Optional[str] = None
    preference_color: Optional[str] = None
    preference_size: Optional[str] = None
    price_sensitivity: str = "normal"
    # 商品要求
    product_color: Optional[str] = None
    product_size: Optional[str] = None
    product_model: Optional[str] = None
    # 包装与物流
    packaging_type: str = "normal"
    no_invoice: int = 0
    no_price_list: int = 0
    logistics_channel: Optional[str] = None
    must_combine: int = 0
    urgent_shipping: int = 0
    needs_gift: int = 0
    needs_card: int = 0
    needs_privacy_packaging: int = 0
    needs_gift_item: int = 0
    needs_card_item: int = 0
    customer_message_translation: Optional[str] = None
    fragile_need_extra_protection: int = 0
    # 风险标记
    high_risk_area: int = 0
    suspected_scammer: int = 0
    price_modification: Optional[str] = None
    discount: Optional[str] = None
    free_shipping: int = 0
    out_of_stock: int = 0
    pre_order: int = 0
    waiting_days: int = 0
    # 备注
    internal_note: Optional[str] = None
    raw_note: Optional[str] = None
    created_by: str = "admin"


class PreSaleNoteUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    category: Optional[str] = None


class InternalBuyerTransferRequest(BaseModel):
    session_id: str
    customer_id: str
    platform: str = ""


class InternalBuyerMessageRequest(BaseModel):
    session_id: str
    customer_id: str
    message: str
    message_type: str = "text"


class InternalBuyerBackToAiRequest(BaseModel):
    session_id: str
    customer_id: str


class AgentAssignRequest(BaseModel):
    session_id: str
    agent_id: str


class SellerLoginRequest(BaseModel):
    username: str
    password: str


class SellerMessageRequest(BaseModel):
    session_id: str
    customer_id: str
    message: str
    message_type: str = "text"
    language: str = "zh"


class HumanSettingsUpdate(BaseModel):
    auto_translate: Optional[bool] = None
    target_language: Optional[str] = None
    auto_reply_enabled: Optional[bool] = None
    greeting_message: Optional[str] = None


# ============== 全局变量 ==============
_active_websocket_connections: Dict[str, WebSocket] = {}
_admin_sessions: Dict[str, Dict[str, Any]] = {}
_session_notifications: Dict[str, List[Dict]] = {}


# ============== Lifespan 管理 ==============
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    logger.info("=" * 50)
    logger.info("金牌客服系统启动中...")
    logger.info("=" * 50)

    try:
        from config import enforce_production_security_or_exit, warn_if_insecure_defaults_in_development

        enforce_production_security_or_exit()
        warn_if_insecure_defaults_in_development()
    except SystemExit:
        raise
    except Exception as e:
        logger.warning(f"[启动] 安全配置检查异常: {e}")

    # 1. 初始化 MySQL 连接池
    if _init_mysql_pool:
        try:
            _init_mysql_pool()
            logger.info("[启动] MySQL 连接池已初始化")
        except Exception as e:
            logger.warning(f"[启动] MySQL 初始化失败（将使用 SQLite）: {e}")

    # 2. 初始化数据库
    if init_db:
        try:
            init_db()
            logger.info("[启动] 数据库表结构已初始化")
        except Exception as e:
            logger.warning(f"[启动] 数据库初始化失败: {e}")

    # 3. 初始化默认卖家账号
    if init_default_seller:
        try:
            init_default_seller()
            logger.info("[启动] 默认卖家账号已初始化")
        except Exception as e:
            logger.warning(f"[启动] 卖家账号初始化失败: {e}")

    # 3b. 消息中心表（notifications / conversation_history 等，SQLite 回退时与主库同路径）
    if message_center_service:
        try:
            message_center_service.init_db()
            logger.info("[启动] 消息中心数据库表已初始化")

            # 自动 seed 示例通知（幂等：已有数据则跳过）
            try:
                existing = message_center_service.get_notifications(limit=1)
                if not existing:
                    seed_data = [
                        {"notification_type": "policy", "title": "海关总署优化跨境电商进口商品清单",
                         "content": "海关总署近日发布公告，进一步优化跨境电商进口商品清单，扩大优质消费品进口范围，降低部分商品进口税率，为跨境电商卖家带来更多机遇。",
                         "source": "deepseek", "is_important": True},
                        {"notification_type": "policy", "title": "跨境电商综合试验区再扩容",
                         "content": "国务院批准新增一批跨境电商综合试验区，支持更多城市开展跨境电商业务，进一步推动外贸新业态发展。",
                         "source": "deepseek", "is_important": False},
                        {"notification_type": "policy", "title": "跨境电商税收优惠政策延续",
                         "content": "财政部、税务总局联合发布公告，跨境电商零售进口税收优惠政策执行期限延长至2027年底，单次交易限值和年度交易限值均有上调。",
                         "source": "deepseek", "is_important": True},
                        {"notification_type": "market", "title": "户外露营装备海外热销",
                         "content": "近期户外露营装备在欧美市场持续热销，帐篷、睡袋、折叠桌椅等品类增长显著。建议卖家关注相关品类，提前备货。",
                         "source": "deepseek", "is_important": False},
                        {"notification_type": "market", "title": "东南亚电商市场增长强劲",
                         "content": "最新数据显示，东南亚电商市场年增长率超过20%，Shopee、Lazada 平台交易额持续攀升，成为跨境卖家新蓝海。",
                         "source": "deepseek", "is_important": True},
                        {"notification_type": "market", "title": "智能家居产品北美需求上升",
                         "content": "智能插座、摄像头、门锁等智能家居产品在北美市场需求快速增长，建议有相关供应链的卖家重点关注。",
                         "source": "deepseek", "is_important": False},
                        {"notification_type": "system", "title": "消息中心已就绪",
                         "content": "消息中心初始化完成，系统将持续推送最新政策动态和市场趋势，也可以使用搜索功能自定义关注话题。",
                         "source": "system", "is_important": False},
                    ]
                    for item in seed_data:
                        try:
                            message_center_service.add_notification(
                                notification_type=item["notification_type"],
                                title=item["title"],
                                content=item["content"],
                                source=item["source"],
                                is_important=item.get("is_important", False)
                            )
                        except Exception:
                            pass  # 静默忽略
                    logger.info("[启动] 消息中心示例通知已自动初始化")
            except Exception:
                pass  # 静默忽略
        except Exception as e:
            logger.warning(f"[启动] 消息中心数据库初始化失败: {e}")

    # 4. 初始化 Redis store
    if redis_store:
        try:
            if hasattr(redis_store, "connect"):
                _connect = redis_store.connect
                if inspect.iscoroutinefunction(_connect):
                    await redis_store.connect()
                else:
                    _connect()
            logger.info("[启动] Redis store 已初始化")
        except Exception as e:
            logger.warning(f"[启动] Redis 初始化失败: {e}")

    # 5. 初始化限流器
    if rate_limiter:
        try:
            logger.info("[启动] 限流器已初始化")
        except Exception as e:
            logger.warning(f"[启动] 限流器初始化失败: {e}")

    # 6. 初始化监控收集器
    if metrics_collector:
        try:
            logger.info("[启动] 监控收集器已初始化")
        except Exception as e:
            logger.warning(f"[启动] 监控收集器初始化失败: {e}")

    # 7. 初始化平台同步数据库
    if _ensure_sync_db:
        try:
            _ensure_sync_db()
            logger.info("[启动] 平台同步数据库已初始化")
        except Exception as e:
            logger.warning(f"[启动] 平台同步数据库初始化失败: {e}")

    # 8. 启动消息中心 policy 搜索服务
    if policy_search_service:
        try:
            policy_search_service.start_auto_search(10)
            logger.info("[启动] 政策搜索服务已启动")
        except Exception as e:
            logger.warning(f"[启动] 政策搜索服务启动失败: {e}")

    logger.info("=" * 50)
    logger.info("金牌客服系统启动完成！")
    logger.info("=" * 50)

    yield

    # ========== 优雅关闭 ==========
    logger.info("正在关闭金牌客服系统...")

    # 1. 通知所有坐席下线
    if agent_service:
        try:
            if hasattr(agent_service, "notify_all_agents_offline"):
                agent_service.notify_all_agents_offline()
        except Exception as e:
            logger.warning(f"坐席下线通知失败: {e}")

    # 2. 关闭 Redis
    if redis_store:
        try:
            if hasattr(redis_store, "disconnect"):
                _disconnect = redis_store.disconnect
                if inspect.iscoroutinefunction(_disconnect):
                    await redis_store.disconnect()
                else:
                    _disconnect()
        except Exception as e:
            logger.warning(f"Redis 关闭失败: {e}")

    # 3. 同步 session_mode
    if session_mode:
        try:
            if hasattr(session_mode, 'shutdown'):
                session_mode.shutdown()
        except Exception as e:
            logger.warning(f"session_mode 关闭失败: {e}")

    # 4. 停止平台自动同步
    if stop_auto_sync:
        try:
            stop_auto_sync()
        except Exception as e:
            logger.warning(f"平台同步停止失败: {e}")

    logger.info("金牌客服系统已关闭。")


# ============== 创建 FastAPI 应用 ==============
app = FastAPI(
    title="Ruitalk 金牌客服系统 API",
    description="跨境电商金牌客服系统 - 卖方终端",
    version="2.0.0",
    lifespan=lifespan,
)

# CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS if 'ALLOWED_ORIGINS' in dir() else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── 门户登录守卫中间件 ───
# 所有访问首页 /home /admin/*.html 的请求，检查是否已登录（Cookie 或 Authorization）
# 已登录 → 放行；未登录 → 重定向到 /merchant-auth.html
class PortalAuthMiddleware(BaseHTTPMiddleware):
    _TOKEN_KEYS = [
        "rtk_merchant_access", "rtk_access_token",
        "admin_access_token", "agent_access_token",
    ]

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # 需要登录的页面路径
        needs_auth = (
            path == "/" or
            path == "/home" or
            path == "/home.html" or
            (path.startswith("/admin/") and path.endswith(".html")) or
            path == "/console" or
            path == "/customer"
        )

        if needs_auth and request.method == "GET":
            # 优先检查 Cookie
            cookie_token = request.cookies.get("ruitalk_session")
            if not cookie_token:
                # 检查 Authorization header（来自前端 JS fetch）
                auth = request.headers.get("authorization", "")
                if not auth.startswith("Bearer "):
                    # Cookie/Header 都没有 → 检查 localStorage 无法服务端做
                    # 改为：写一个 Cookie，登录成功时由前端写入
                    pass

            # 若 Cookie 标记已登录，放行
            if cookie_token == "active":
                return await call_next(request)

            # 检查 localStorage 等效：前端登录成功后会写一个 session cookie
            # 但 localStorage 无法在服务端读取，所以只能信任 Cookie
            # 未登录 → 重定向
            from fastapi.responses import RedirectResponse
            return RedirectResponse(url="/merchant-auth.html", status_code=302)

        return await call_next(request)

app.add_middleware(PortalAuthMiddleware)

# 限流中间件（如果可用）
if RateLimitMiddleware and rate_limiter:
    app.add_middleware(RateLimitMiddleware, limiter=rate_limiter)

# 监控中间件（如果可用）
if MetricsMiddleware and metrics_collector:
    app.add_middleware(MetricsMiddleware, collector=metrics_collector)


# ============== 健康检查路由（必须在 /api/* 之前）==============
@app.get("/health")
async def health():
    """基础健康检查"""
    return {"status": "ok", "service": "ruitalk-seller", "timestamp": datetime.now().isoformat()}


@app.get("/ready")
async def ready():
    """就绪检查"""
    return {"status": "ready", "service": "ruitalk-seller"}


@app.get("/live")
async def live():
    """存活探针（K8s liveness）"""
    return {"status": "alive"}


@app.get("/favicon.ico")
async def favicon():
    """网站图标（解决 404 问题）"""
    import os
    # 尝试多个可能的路径
    possible_paths = [
        Path(__file__).parent.parent / "frontend" / "static" / "favicon.ico",
        Path(__file__).parent / "static" / "favicon.ico",
        Path(__file__).parent.parent / "frontend" / "favicon.ico",
    ]
    for p in possible_paths:
        if p.exists():
            return FileResponse(str(p), media_type="image/x-icon")

    # 如果文件不存在，返回简单的 SVG 作为 ico
    from fastapi.responses import Response
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><circle cx="8" cy="8" r="7" fill="%231a6fd4"/></svg>'
    return Response(content=svg, media_type="image/svg+xml")


@app.get("/api/favicon.ico")
async def api_favicon():
    """API 路由别名"""
    return await favicon()


@app.get("/metrics")
async def prometheus_metrics():
    """Prometheus 指标端点"""
    if not _monitor_available or not metrics_collector:
        return PlainTextResponse("monitor unavailable", status_code=503)
    return PlainTextResponse(
        metrics_collector.to_prometheus_text(),
        media_type="text/plain; charset=utf-8"
    )


# ============== 挂载子路由 ==============
if shop_router:
    app.include_router(shop_router)
if unified_router:
    app.include_router(unified_router)
if message_center_router:
    app.include_router(message_center_router)
if enhanced_policy_router:
    app.include_router(enhanced_policy_router)
if merchant_router:
    app.include_router(merchant_router)


# ============== API 路由（挂载到 /api 前缀）==============
# 注意：必须在文件末尾、所有 @api_router 注册完成后再 app.include_router(api_router)，
# 否则 include 时路由表为空，后续装饰器添加的路由不会出现在应用上（表现为 /api/* 全部 404）。
api_router = APIRouter(prefix="/api", tags=["API v1"])

# ---- Metrics ----
@api_router.get("/metrics/summary")
async def metrics_summary():
    """指标摘要（JSON 格式，供前端展示）"""
    if not _monitor_available:
        return {"error": "监控模块未启用"}
    return metrics_collector.get_all_metrics_summary()


@api_router.get("/metrics/business")
async def metrics_business():
    """业务指标详情（JSON 格式）"""
    if not _monitor_available:
        return {"error": "监控模块未启用"}
    return metrics_collector.to_json()


# ---- Status & System Check ----
@api_router.get("/status")
async def api_status():
    """
    API 状态检查（含 Neo4j、GraphRAG），供前端状态栏显示。
    使用已有的 quick_health_check（全部 2 秒超时），不重建连接。
    """
    try:
        from system_checker import quick_health_check
        result = quick_health_check()
        checks = result.get("checks", {})
        return {
            "neo4j": checks.get("neo4j", False),
            "graphrag": checks.get("graphrag", False),
            "redis": checks.get("redis", False),
            "deepseek": checks.get("deepseek", False),
            "service": "gold-customer-service",
            "timestamp": datetime.now().isoformat(),
        }
    except ImportError:
        # 兜底：快速返回默认值
        return {
            "neo4j": False,
            "graphrag": False,
            "redis": False,
            "deepseek": False,
            "service": "gold-customer-service",
            "timestamp": datetime.now().isoformat(),
        }


@api_router.post("/customer/start")
async def proxy_customer_start(request: Request):
    """门户首页「开始咨询」→ 转发到金牌客服 Flask（5000），保持 8000 同域调用。"""
    base = (GOLD_CS_BASE_URL or "http://127.0.0.1:5000").rstrip("/")
    url = f"{base}/api/customer/start"
    body = await request.body()
    ct = request.headers.get("content-type", "application/json")
    try:
        r = requests.post(url, data=body, headers={"Content-Type": ct}, timeout=90)
    except requests.RequestException as e:
        return JSONResponse(
            {"success": False, "message": f"无法连接金牌客服服务: {e}"},
            status_code=502,
        )
    media = r.headers.get("content-type", "application/json; charset=utf-8")
    return Response(content=r.content, status_code=r.status_code, media_type=media)


@api_router.get("/system-check")
async def system_check():
    """
    完整系统自检（全面检查所有依赖项）
    检查端口、数据库、AI服务、安全配置等
    """
    try:
        from system_checker import SellerSystemChecker
        import asyncio
        checker = SellerSystemChecker()
        loop = asyncio.get_event_loop()
        report = await loop.run_in_executor(None, checker.run_all_checks)
        return report.to_dict()
    except ImportError:
        return {"error": "system_checker 模块不可用", "timestamp": datetime.now().isoformat()}
    except Exception as e:
        import traceback
        return {"error": f"自检失败: {str(e)}", "trace": traceback.format_exc()[:500], "timestamp": datetime.now().isoformat()}


@api_router.get("/system-check/quick")
async def system_check_quick():
    """快速健康检查（仅核心服务），用于前端状态指示器"""
    try:
        from system_checker import quick_health_check
        return quick_health_check()
    except ImportError:
        return {"status": "unknown", "error": "system_checker 模块不可用", "timestamp": datetime.now().isoformat()}


# 报告单页面模板（纯 JS 渲染，无 Python f-string 冲突）
_report_html = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>系统自检报告 - Ruitalk</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif;
          background: #f0f2f5; color: #1f2937; min-height: 100vh; padding: 24px; }
  .container { max-width: 1000px; margin: 0 auto; }
  .report-header { display: flex; align-items: center; gap: 20px; margin-bottom: 24px; flex-wrap: wrap; }
  .report-title { font-size: 24px; font-weight: 700; color: #1e40af; }
  .report-meta { font-size: 13px; color: #6b7280; margin-top: 4px; }
  .report-badge { padding: 6px 20px; border-radius: 20px; font-weight: 700;
                   font-size: 16px; color: white; }
  .report-badge.ok { background: #4CAF50; }
  .report-badge.warn { background: #FF9800; }
  .report-badge.fail { background: #F44336; }
  .report-badge.unknown { background: #9E9E9E; }
  .report-actions { margin-left: auto; display: flex; gap: 8px; }
  .report-actions button { padding: 6px 16px; border: 1px solid #d1d5db; border-radius: 6px;
                            background: white; cursor: pointer; font-size: 13px; }
  .report-actions button:hover { background: #f3f4f6; }
  .summary-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 12px; margin-bottom: 24px; }
  .summary-card { background: white; border-radius: 12px; padding: 20px; text-align: center; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
  .summary-number { font-size: 32px; font-weight: 800; font-variant-numeric: tabular-nums; }
  .summary-label { font-size: 13px; color: #6b7280; margin-top: 4px; }
  .summary-ok .summary-number { color: #4CAF50; }
  .summary-warn .summary-number { color: #FF9800; }
  .summary-fail .summary-number { color: #F44336; }
  .summary-critical .summary-number { color: #B71C1C; }
  .summary-total .summary-number { color: #1e40af; }
  .summary-time .summary-number { font-size: 18px; color: #6b7280; }
  .category-card { background: white; border-radius: 12px; padding: 20px; margin-bottom: 16px;
                    box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
  .category-title { font-size: 16px; font-weight: 700; color: #1e40af; margin-bottom: 12px;
                     padding-bottom: 8px; border-bottom: 2px solid #e5e7eb; }
  .check-item { padding: 10px 12px; border-radius: 8px; margin-bottom: 6px; background: #f9fafb; }
  .check-item:hover { background: #f3f4f6; }
  .check-main { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
  .status-badge { padding: 2px 10px; border-radius: 4px; font-size: 12px; font-weight: 700; color: white; min-width: 56px; text-align: center; }
  .check-name { font-weight: 600; font-size: 14px; flex: 1; }
  .check-duration { font-size: 12px; color: #9ca3af; font-variant-numeric: tabular-nums; }
  .severity { font-size: 11px; padding: 1px 6px; border-radius: 3px; font-weight: 600; }
  .severity-critical { background: #fee2e2; color: #B71C1C; }
  .severity-high { background: #ffedd5; color: #9a3412; }
  .severity-medium { background: #fef9c3; color: #854d0e; }
  .severity-low { background: #dbeafe; color: #1e40af; }
  .severity-info { background: #e5e7eb; color: #374151; }
  .check-message { font-size: 13px; color: #4b5563; margin-top: 4px; margin-left: 66px; }
  .suggestion { font-size: 12px; color: #dc2626; margin-top: 3px; margin-left: 66px; }
  .sys-resources { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; margin-top: 12px; }
  .sys-item { display: flex; justify-content: space-between; padding: 8px 12px; background: #f9fafb;
               border-radius: 6px; font-size: 13px; }
  .sys-item span:first-child { color: #6b7280; }
  .sys-item span:last-child { font-weight: 600; font-variant-numeric: tabular-nums; }
  .recommendations { background: #fffbeb; border: 1px solid #fde68a; border-radius: 12px; padding: 16px; margin-top: 16px; }
  .recommendations h3 { font-size: 15px; color: #92400e; margin-bottom: 8px; }
  .recommendations li { font-size: 13px; color: #78350f; margin-bottom: 4px; }
  .loading { text-align: center; padding: 80px; font-size: 18px; color: #6b7280; }
  .loading-spinner { font-size: 32px; animation: spin 1s linear infinite; }
  @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
  @media print { body { background: white; padding: 0; } .report-actions { display: none; }
    .category-card { break-inside: avoid; box-shadow: none; border: 1px solid #e5e7eb; } }
</style>
</head>
<body>
<div class="container" id="app">
  <div class="loading">
    <div class="loading-spinner">&#9696;</div>
    <div style="margin-top:12px">正在生成系统自检报告...</div>
  </div>
</div>
<script>
(async function() {{
  const app = document.getElementById('app');
  try {{
    const resp = await fetch('/api/system-check?_t=' + Date.now());
    const data = await resp.json();
    const r = data;

    const nowStr = new Date().toLocaleString('zh-CN');
    const overall = r.overall_status || 'unknown';
    const overallLabel = {{ok: '正常', warn: '警告', fail: '失败', unknown: '未知'}}[overall] || overall;
    const summary = r.summary || {{}};
    const sysInfo = r.system_info || {{}};

    let categoriesHtml = '';
    for (const [cat, items] of Object.entries(r.categories || {{}})) {{
      let itemsHtml = '';
      for (const item of items) {{
        const status = item.status || 'unknown';
        const color = {{ok: '#4CAF50', warn: '#FF9800', fail: '#F44336', skip: '#9E9E9E', unknown: '#9E9E9E'}}[status] || '#9E9E9E';
        const icon = {{ok: '&#10003;', warn: '&#9888;', fail: '&#10007;', skip: '&#9675;', unknown: '?'}}[status] || '?';
        const severity = item.severity || 'info';
        const duration = item.duration_ms || 0;
        const msg = (item.message || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
        let sugHtml = '';
        if (item.suggestions && (status === 'fail' || status === 'warn')) {{
          for (const s of item.suggestions.slice(0, 3)) {{
            const sEsc = s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
            sugHtml += '<div class="suggestion">&#8594; ' + sEsc + '</div>';
          }}
        }}
        itemsHtml += `
          <div class="check-item">
            <div class="check-main">
              <span class="status-badge" style="background:${{color}}">${{icon}} ${{status.toUpperCase()}}</span>
              <span class="check-name">${{item.name || ''}}</span>
              <span class="check-duration">${{duration.toFixed(0)}}ms</span>
              <span class="severity severity-${{severity}}">[${{severity.toUpperCase()}}]</span>
            </div>
            <div class="check-message">${{msg}}</div>
            ${{sugHtml}}
          </div>`;
      }}
      categoriesHtml += '<div class="category-card"><div class="category-title">' + cat + '</div>' + itemsHtml + '</div>';
    }}

    let sysResHtml = '';
    if (sysInfo && !sysInfo.error) {{
      sysResHtml = `
        <div class="category-card">
          <div class="category-title">&#128200; 系统资源</div>
          <div class="sys-resources">
            <div class="sys-item"><span>CPU</span><span>${{sysInfo.cpu_percent || 'N/A'}}%</span></div>
            <div class="sys-item"><span>内存</span><span>${{sysInfo.memory_used_gb || 'N/A'}}GB / ${{sysInfo.memory_total_gb || 'N/A'}}GB (${{sysInfo.memory_percent || 'N/A'}}%)</span></div>
            <div class="sys-item"><span>磁盘</span><span>${{sysInfo.disk_used_gb || 'N/A'}}GB / ${{sysInfo.disk_total_gb || 'N/A'}}GB (${{sysInfo.disk_percent || 'N/A'}}%)</span></div>
            <div class="sys-item"><span>进程内存</span><span>${{sysInfo.process_memory_mb || 'N/A'}}MB</span></div>
          </div>
        </div>`;
    }}

    let recHtml = '';
    if (r.recommendations && r.recommendations.length > 0) {{
      recHtml = r.recommendations.map(function(rec) {{
        return '<li>' + rec.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;') + '</li>';
      }}).join('');
    }} else {{
      recHtml = '<li>系统状态良好，暂无紧急建议</li>';
    }}

    app.innerHTML = `
      <div class="report-header">
        <div>
          <div class="report-title">&#128270; Ruitalk 系统自检报告</div>
          <div class="report-meta">生成时间: ${{nowStr}} &nbsp;|&nbsp; 耗时: ${{(r.duration_ms || 0).toFixed(0)}}ms</div>
        </div>
        <div class="report-badge ${{overall}}">${{overallLabel}}</div>
        <div class="report-actions">
          <button onclick="window.print()">&#128438; 打印报告</button>
          <button onclick="downloadJson()">&#11015; 下载 JSON</button>
        </div>
      </div>

      <div class="summary-grid">
        <div class="summary-card summary-ok"><div class="summary-number">${{summary.pass || 0}}</div><div class="summary-label">&#10003; 正常</div></div>
        <div class="summary-card summary-warn"><div class="summary-number">${{summary.warn || 0}}</div><div class="summary-label">&#9888; 警告</div></div>
        <div class="summary-card summary-fail"><div class="summary-number">${{summary.fail || 0}}</div><div class="summary-label">&#10007; 失败</div></div>
        <div class="summary-card summary-critical"><div class="summary-number">${{summary.critical || 0}}</div><div class="summary-label">&#9888; 阻塞</div></div>
        <div class="summary-card summary-total"><div class="summary-number">${{summary.total || 0}}</div><div class="summary-label">&#8226; 总计</div></div>
        <div class="summary-card summary-time"><div class="summary-number">${{(r.duration_ms || 0).toFixed(0)}}ms</div><div class="summary-label">&#9202; 检查耗时</div></div>
      </div>

      ${{categoriesHtml}}
      ${{sysResHtml}}

      <div class="recommendations">
        <h3>&#128161; 优化建议</h3>
        <ul>${{recHtml}}</ul>
      </div>

      <script>
        const reportData = r;
        function downloadJson() {{
          const blob = new Blob([JSON.stringify(reportData, null, 2)], {{type: 'application/json'}});
          const url = URL.createObjectURL(blob);
          const a = document.createElement('a');
          a.href = url;
          a.download = 'ruitalk-check-report-' + new Date().toISOString().slice(0,19).replace(/[T:]/g, '-') + '.json';
          a.click();
          URL.revokeObjectURL(url);
        }}
      <\x2fscript>`;
  }} catch(e) {{
    app.innerHTML = '<div style="padding:40px;text-align:center;color:#F44336;font-size:18px;">&#10007; 报告加载失败: ' + e.message + '</div>';
  }}
}})();
</script>
</body>
</html>'''


@api_router.get("/system-check/report", include_in_schema=True)
async def system_check_report(request: Request):
    """
    生成专业 HTML 自检报告单页面
    页面内通过 JavaScript 异步加载检查数据并渲染
    """
    return HTMLResponse(_report_html)


@api_router.get("/system-check/report/download")
async def system_check_report_download():
    """
    下载 JSON 格式的完整系统检查报告
    响应 Content-Disposition 头，支持直接下载
    """
    try:
        from system_checker import SellerSystemChecker
        checker = SellerSystemChecker()
        report = checker.run_all_checks()
        report_dict = report.to_dict()

        import json as _json
        content = _json.dumps(report_dict, ensure_ascii=False, indent=2)
        filename = f"ruitalk-check-report-{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

        from fastapi.responses import StreamingResponse
        from io import BytesIO
        buf = BytesIO(content.encode("utf-8"))
        return StreamingResponse(
            iter([content]),
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"}
        )
    except Exception as e:
        import traceback
        return JSONResponse({"error": str(e), "trace": traceback.format_exc()[:500]}, status_code=500)


@api_router.get("/system-check/buyer")
async def buyer_system_check():
    """检查买方系统状态"""
    try:
        r = requests.get(f"{BUYER_API_HOST}/health", timeout=5)
        if r.status_code == 200:
            return {"buyer": "ok", "data": r.json()}
        return {"buyer": "error", "status_code": r.status_code}
    except requests.exceptions.ConnectionError:
        return {"buyer": "offline", "message": "买方系统未运行"}
    except Exception as e:
        return {"buyer": "error", "message": str(e)}


@api_router.post("/system-check/trigger")
async def trigger_system_check():
    """手动触发系统自检（POST）"""
    try:
        from system_checker import SellerSystemChecker
        import asyncio
        checker = SellerSystemChecker()
        loop = asyncio.get_event_loop()
        report = await loop.run_in_executor(None, checker.run_all_checks)
        return report.to_dict()
    except Exception as e:
        import traceback
        return {"error": str(e), "trace": traceback.format_exc()[:500], "timestamp": datetime.now().isoformat()}


# ---- Circuit Breakers ----
@api_router.get("/circuit-breakers")
async def circuit_breaker_status():
    """获取所有熔断器状态"""
    if not (_deepseek_circuit and _neo4j_circuit and _graphrag_circuit):
        return {"error": "services 模块不可用"}
    return {
        "circuit_breakers": {
            "deepseek": _deepseek_circuit.get_status(),
            "neo4j": _neo4j_circuit.get_status(),
            "graphrag": _graphrag_circuit.get_status(),
        },
        "timestamp": datetime.now().isoformat(),
    }


# ---- Redis & Port Check ----
@api_router.get("/redis-status")
async def redis_status():
    """获取 Redis 连接状态"""
    if not _redis_available:
        return {"redis": "unavailable", "available": False}
    try:
        if hasattr(redis_store, 'health_check'):
            health = await redis_store.health_check()
            return {
                "redis": health.get("status", "unknown"),
                "available": health.get("connected", False),
                "latency_ms": health.get("latency_ms"),
                "is_fake": health.get("is_fake", False),
                "timestamp": datetime.now().isoformat(),
            }
        return {"redis": "unknown", "available": True}
    except Exception as e:
        return {"redis": "error", "message": str(e)}


@api_router.get("/port-check")
async def port_check():
    """检查所有服务端口状态"""
    ports = [
        (8000, "卖方 FastAPI"),
        (5000, "Flask 金牌客服"),
        (5050, "GraphRAG 代理"),
        (8001, "买方系统"),
    ]
    results = []
    for port, name in ports:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            result = sock.connect_ex(("127.0.0.1", port))
            sock.close()
            status = "listening" if result == 0 else "offline"
        except Exception as e:
            status = "error"
        results.append({"port": port, "name": name, "status": status})
    return {"ports": results, "timestamp": datetime.now().isoformat()}


@api_router.get("/services-status")
async def services_status():
    """获取所有服务状态（综合信息）"""
    # 从配置获取跨系统地址
    seller_host = os.getenv("SELLER_API_HOST", "http://127.0.0.1:8000")
    buyer_host = os.getenv("BUYER_API_HOST", "http://127.0.0.1:8001")
    services = {}
    # 卖方自身
    try:
        r = requests.get(f"{seller_host}/health", timeout=3)
        services["seller"] = {"status": "ok", "data": r.json()} if r.status_code == 200 else {"status": "error"}
    except Exception:
        services["seller"] = {"status": "offline"}
    # 买方
    try:
        r = requests.get(f"{buyer_host}/health", timeout=3)
        services["buyer"] = {"status": "ok", "data": r.json()} if r.status_code == 200 else {"status": "error"}
    except Exception:
        services["buyer"] = {"status": "offline"}
    # Flask
    try:
        r = requests.get("http://127.0.0.1:5000/ping", timeout=3)
        services["flask"] = {"status": "ok"} if r.status_code == 200 else {"status": "error"}
    except Exception:
        services["flask"] = {"status": "offline"}
    return {"services": services, "timestamp": datetime.now().isoformat()}


# ---- Admin Customer Query ----
def _normalize_profile(profile: Optional[dict]) -> Optional[dict]:
    """统一为 { customer, orders, skus, emotions }"""
    if not profile:
        return None
    if isinstance(profile, dict) and "customer" in profile:
        c = profile.get("customer") or {}
        if "customer_id" not in c and "id" in c:
            c = {**c, "customer_id": c["id"]}
        return {"customer": c, "orders": profile.get("orders"), "skus": profile.get("skus"), "emotions": profile.get("emotions")}
    return profile


@api_router.get("/admin/customer/{customer_id}")
async def admin_get_customer(customer_id: str, user: dict = Security(get_current_admin)):
    """管理后台查询客户（Neo4j失效时回退SQLite）"""
    from db import get_customer as db_get_customer
    profile = None
    if Neo4jConnection:
        try:
            neo4j_conn = Neo4jConnection()
            if neo4j_conn.connect():
                profile = neo4j_conn.get_full_profile(customer_id)
                if not profile and query_graphrag:
                    profile = query_graphrag(customer_id)
                neo4j_conn.close()
        except Exception as e:
            logger.warning(f"Neo4j 查询失败（将回退SQLite）: {e}")

    if not profile:
        sq_customer = db_get_customer(customer_id) if db_get_customer else None
        if sq_customer:
            profile = {"customer": sq_customer, "orders": [], "skus": []}

    return {"success": True, "profile": _normalize_profile(profile)}


# ---- Admin Auth ----
@api_router.post("/admin/login")
async def admin_login(request: Request, body: AdminLoginRequest):
    """管理员登录 — 签发 JWT（按账号校验密码，角色可为 admin / operator）"""
    from jwt_auth import create_access_token, create_refresh_token
    user = admin_users.get(body.username)
    if not user:
        return {"success": False, "message": "用户名或密码错误"}
    if not _verify_user_login_password(user, body.password):
        return {"success": False, "message": "用户名或密码错误"}

    username = user["username"]
    role = user.get("role") or "admin"
    access_token = create_access_token(
        subject=username, role=role,
        extra_claims={"user_id": user["id"], "username": username, "permissions": user.get("permissions", [])},
    )
    refresh_token = create_refresh_token(subject=username, role=role)

    _audit("LOGIN", username, "admin_user",
           detail=f"管理员登录成功（角色：{role}）", request=request)

    return {
        "success": True,
        "data": {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "user": {
                "id": user["id"], "username": username, "role": role,
                "label": user.get("label", ""),
            },
        }
    }


@api_router.get("/admin/login-identities")
async def admin_login_identities():
    """门户「更换账号」：列出可切换的静态后台账号（不含密码）。不含 DEV_PHONE_USERS 合成账号。"""
    from config import OPERATOR_USERNAME as _ou, OPERATOR_PASSWORD as _op

    items = []
    super_u = admin_users.get(ADMIN_USERNAME)
    if super_u and not str(super_u.get("username", "")).startswith("dev_"):
        items.append(
            {
                "username": ADMIN_USERNAME,
                "label": super_u.get("label") or "超级管理员",
                "role": super_u.get("role") or "admin",
            }
        )
    if _op and _ou and _ou != ADMIN_USERNAME:
        op = admin_users.get(_ou)
        if op and not str(op.get("username", "")).startswith("dev_"):
            items.append(
                {
                    "username": _ou,
                    "label": op.get("label") or "运营",
                    "role": op.get("role") or "operator",
                }
            )
    return {"success": True, "items": items}


# ---- 手机号 + 密码登录 ----
class PhoneLoginRequest(BaseModel):
    phone: str
    password: str


@api_router.post("/admin/phone-login")
async def admin_phone_login(request: Request, body: PhoneLoginRequest):
    """
    手机号 + 密码登录
    开发者账号从环境变量 DEV_PHONE_USERS 配置
    """
    from jwt_auth import create_access_token, create_refresh_token

    phone = body.phone.strip()
    password = body.password

    if not _is_valid_phone(phone):
        return {"success": False, "message": "手机号格式不正确"}

    # 查找开发者账号
    username = DEV_PHONE_MAP.get(phone)
    if not username:
        return {"success": False, "message": "该手机号未注册为开发者账号"}

    user = admin_users.get(username)
    if not user:
        return {"success": False, "message": "用户不存在"}

    if not _verify_user_login_password(user, password):
        return {"success": False, "message": "密码错误"}

    role = user.get("role") or "admin"
    access_token = create_access_token(
        subject=username, role=role,
        extra_claims={"user_id": user["id"], "username": username, "phone": phone,
                       "permissions": user.get("permissions", [])},
    )
    refresh_token = create_refresh_token(subject=username, role=role)

    _audit("LOGIN", username, "admin_user",
           detail=f"手机号登录成功（{phone}）", request=request)

    return {
        "success": True,
        "data": {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "user": {
                "id": user["id"], "username": username, "role": role,
                "label": user.get("label", ""),
                "phone": phone,
            },
        }
    }


# ---- 发送手机验证码 ----
class SendSmsCodeRequest(BaseModel):
    phone: str
    action: str = "login"  # login | register


@api_router.post("/admin/send-sms-code")
async def admin_send_sms_code(request: Request, body: SendSmsCodeRequest):
    """
    发送手机验证码（演示模式：打印到控制台；配置真实服务商后自动切换）
    """
    phone = body.phone.strip()

    if not _is_valid_phone(phone):
        return {"success": False, "message": "手机号格式不正确"}

    # 防刷：60秒冷却
    now = time.time()
    if phone in _sms_code_store:
        record = _sms_code_store[phone]
        if record["expires_at"] - 300 + 60 > now:  # 5分钟有效期，60秒冷却
            remaining = int(record["expires_at"] - 300 + 60 - now)
            if remaining > 0:
                return {"success": False, "message": f"请 {remaining} 秒后再试"}

    code = _generate_sms_code()
    expires = now + 300  # 5分钟

    _sms_code_store[phone] = {"code": code, "expires_at": expires}

    # ---- 演示模式：打印到控制台 ----
    # TODO: 接入真实短信服务商时替换下面这段
    _os.environ.get("_DEBUG_SMS", "1")  # 仅标记，不影响逻辑
    print(f"\n{'='*50}")
    print(f"  [演示短信] 发送给: {phone}")
    print(f"  验证码: {code}")
    print(f"  有效期: 5 分钟")
    print(f"{'='*50}\n")

    return {
        "success": True,
        "message": "验证码已发送",
        "data": {
            "phone_mask": phone[:3] + "****" + phone[7:],
            "expire_seconds": 300,
            "debug_code": code,  # 演示模式暴露验证码
        }
    }


# ---- 手机号 + 验证码登录 ----
class PhoneCodeLoginRequest(BaseModel):
    phone: str
    code: str


@api_router.post("/admin/phone-code-login")
async def admin_phone_code_login(request: Request, body: PhoneCodeLoginRequest):
    """
    手机号 + 短信验证码登录
    """
    from jwt_auth import create_access_token, create_refresh_token

    phone = body.phone.strip()
    code = body.code.strip()

    if not _is_valid_phone(phone):
        return {"success": False, "message": "手机号格式不正确"}
    if not code or len(code) != 6 or not code.isdigit():
        return {"success": False, "message": "验证码必须为6位数字"}

    record = _sms_code_store.get(phone)
    if not record:
        return JSONResponse({"success": False, "message": "验证码已失效，请重新获取"}, status_code=401)

    if time.time() > record["expires_at"]:
        del _sms_code_store[phone]
        return JSONResponse({"success": False, "message": "验证码已过期，请重新获取"}, status_code=401)

    if record["code"] != code:
        return {"success": False, "message": "验证码错误"}, 401

    # 验证成功后删除（一次性）
    del _sms_code_store[phone]

    # 查找开发者账号
    username = DEV_PHONE_MAP.get(phone)
    if not username:
        return {"success": False, "message": "该手机号未注册为开发者账号"}

    user = admin_users.get(username)
    if not user:
        return {"success": False, "message": "用户不存在"}

    role = user.get("role") or "admin"
    access_token = create_access_token(
        subject=username, role=role,
        extra_claims={"user_id": user["id"], "username": username, "phone": phone,
                       "permissions": user.get("permissions", [])},
    )
    refresh_token = create_refresh_token(subject=username, role=role)

    _audit("LOGIN", username, "admin_user",
           detail=f"手机号验证码登录（{phone}）", request=request)

    return {
        "success": True,
        "data": {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "user": {
                "id": user["id"], "username": username, "role": role,
                "label": user.get("label", ""),
                "phone": phone,
            },
        }
    }


# ---- 邮箱 + 密码登录 ----
class EmailLoginRequest(BaseModel):
    email: str
    password: str


@api_router.post("/admin/email-login")
async def admin_email_login(request: Request, body: EmailLoginRequest):
    """
    邮箱 + 密码登录（内部账号体系）
    """
    from jwt_auth import create_access_token, create_refresh_token

    email = body.email.strip().lower()
    password = body.password

    if not _is_valid_email(email):
        return {"success": False, "message": "邮箱格式不正确"}

    # 在 admin_users 中查找（通过 email 字段）
    found_user = None
    for u in admin_users.values():
        if u.get("email", "").lower() == email:
            found_user = u
            break

    if not found_user:
        return {"success": False, "message": "该邮箱未注册"}

    if not _verify_user_login_password(found_user, password):
        return {"success": False, "message": "密码错误"}

    username = found_user["username"]
    role = found_user.get("role") or "admin"
    access_token = create_access_token(
        subject=username, role=role,
        extra_claims={"user_id": found_user["id"], "username": username, "email": email,
                       "permissions": found_user.get("permissions", [])},
    )
    refresh_token = create_refresh_token(subject=username, role=role)

    _audit("LOGIN", username, "admin_user",
           detail=f"邮箱登录成功（{email}）", request=request)

    return {
        "success": True,
        "data": {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "user": {
                "id": found_user["id"], "username": username, "role": role,
                "label": found_user.get("label", ""),
                "email": email,
            },
        }
    }


@api_router.post("/admin/refresh")
async def admin_refresh_token(request: Request):
    """用 refresh token 刷新 access token"""
    body = await request.json()
    refresh_token = body.get("refresh_token")
    if not refresh_token:
        return {"success": False, "message": "未提供 refresh_token"}
    try:
        result = refresh_access_token(refresh_token)
        return {"success": True, **result}
    except Exception as e:
        return {"success": False, "message": str(e)}


@api_router.post("/admin/logout")
async def admin_logout(request: Request, user: dict = Security(get_current_admin)):
    """管理员登出"""
    uname = user.get("username") or user.get("sub")
    _audit("LOGOUT", uname, "admin_user", detail="管理员登出", request=request)
    return {"success": True, "message": "已退出登录"}


@api_router.post("/admin/change-password")
async def change_admin_password(request: Request, body: ChangePasswordRequest, user: dict = Security(get_current_super_admin)):
    """修改密码（仅超级管理员；校验当前账号旧密码）"""
    username = user.get("username") or user.get("sub")
    row = admin_users.get(username)
    if not row:
        return {"success": False, "message": "用户不存在"}
    if not _verify_user_login_password(row, body.old_password):
        return {"success": False, "message": "旧密码错误"}
    if len(body.new_password) < 8:
        return {"success": False, "message": "新密码至少需要8位"}
    admin_users[username]["password"] = body.new_password
    _audit("UPDATE", username, "admin_user", target_id=username,
           detail=f"修改自身账户密码", request=request)
    return {"success": True, "message": "密码修改成功"}


@api_router.get("/admin/me")
async def admin_me(user: dict = Security(get_current_admin)):
    """获取当前登录管理员信息"""
    username = user.get("username") or user.get("sub")
    admin_user = admin_users.get(username)
    if not admin_user:
        return {"success": False, "message": "用户不存在"}
    return {
        "success": True,
        "data": {
            "user": {"id": admin_user["id"], "username": username, "role": admin_user["role"], "permissions": admin_user.get("permissions", [])},
        }
    }


# ---- Admin User Management ----
@api_router.post("/admin/users")
async def create_admin_user(request: Request, data: AdminUserCreate, user: dict = Security(get_current_super_admin)):
    """创建管理员用户或坐席"""
    if user.get("role") != "admin":
        return {"success": False, "message": "权限不足"}
    if data.username in admin_users:
        return {"success": False, "message": "用户名已存在"}
    user_id = str(uuid.uuid4())[:8]
    admin_users[data.username] = {
        "id": user_id, "username": data.username, "password": data.password,
        "role": data.role, "permissions": data.permissions, "created_at": datetime.now().isoformat(),
    }
    _audit("CREATE", user.get("username") or user.get("sub"), "admin_user",
           target_id=data.username, detail=f"创建用户 {data.username}（角色：{data.role}）", request=request)
    return {"success": True, "user_id": user_id}


@api_router.get("/admin/users")
async def list_admin_users(user: dict = Security(get_current_super_admin)):
    """列出所有管理员用户"""
    return {
        "success": True,
        "users": [
            {"id": u["id"], "username": u["username"], "role": u["role"], "permissions": u.get("permissions", []), "created_at": u.get("created_at")}
            for u in admin_users.values()
        ],
    }


# ---- Admin Sessions & Conversations ----
@api_router.get("/admin/sessions")
async def admin_get_sessions(user: dict = Security(get_current_admin)):
    """获取所有会话列表"""
    try:
        if session_mode and hasattr(session_mode, 'get_all_sessions'):
            sessions = session_mode.get_all_sessions()
        else:
            sessions = []
        return {"success": True, "sessions": sessions, "total": len(sessions)}
    except Exception as e:
        return {"success": True, "sessions": [], "total": 0, "error": str(e)}


@api_router.get("/admin/conversations")
async def admin_get_conversations(
    user: dict = Security(get_current_admin),
    page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
):
    """获取会话列表（分页）"""
    try:
        if message_service and hasattr(message_service, 'get_conversations'):
            data = message_service.get_conversations(page=page, page_size=page_size)
            return {"success": True, **data}
    except Exception:
        pass
    return {"success": True, "conversations": [], "total": 0, "page": page, "page_size": page_size}


@api_router.get("/admin/conversation/{session_id}")
async def admin_get_conversation(session_id: str, user: dict = Security(get_current_admin)):
    """获取单个会话详情"""
    try:
        if message_service and hasattr(message_service, 'get_messages'):
            messages = message_service.get_messages(session_id)
            return {"success": True, "session_id": session_id, "messages": messages}
    except Exception:
        pass
    return {"success": True, "session_id": session_id, "messages": []}


@api_router.post("/admin/conversation/{session_id}/rate")
async def rate_conversation(session_id: str, rating: int = Query(..., ge=1, le=5), user: dict = Security(get_current_admin)):
    """评价会话"""
    return {"success": True, "session_id": session_id, "rating": rating}


# ---- Admin Orders ----
@api_router.get("/admin/orders")
async def admin_get_orders(
    user: dict = Security(get_current_staff),
    status: str = "", platform: str = "",
    start_date: str = "", end_date: str = "",
    page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
    limit: int = Query(None, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """获取订单列表（兼容前端 limit/offset 和 page/page_size 两种格式）"""
    # 兼容前端 limit/offset 格式
    if limit is not None and offset is not None:
        page = (offset // limit) + 1 if limit > 0 else 1
        page_size = limit

    off = (page - 1) * page_size
    st = status or "全部"
    plat = platform or "全部"

    # 1) Neo4j（与 database.Neo4jConnection 中订单模型一致，优先于空缓存）
    if Neo4jConnection:
        neo = Neo4jConnection()
        try:
            if neo.connect():
                try:
                    from database import _to_json_serializable
                    from platform_sync import synthetic_buyer_email, synthetic_buyer_phone

                    raw_orders = neo.get_all_orders(
                        status=st, platform=plat,
                        start_date=start_date or None, end_date=end_date or None,
                        limit=page_size, offset=off,
                    )
                    total = neo.get_orders_count(
                        status=st, platform=plat,
                        start_date=start_date or None, end_date=end_date or None,
                    )
                    orders = []
                    for o in raw_orders:
                        d = _to_json_serializable(dict(o) if hasattr(o, "keys") else o)
                        oid = d.get("id") or d.get("order_id")
                        d["id"] = oid
                        if d.get("total") is None:
                            d["total"] = d.get("amount") or d.get("total_amount")
                        if d.get("display_date") is None:
                            d["display_date"] = d.get("created_at") or d.get("order_date") or d.get("date")
                        ph = (d.get("customer_phone") or "").strip()
                        if not ph or ph == "—":
                            cid = str(d.get("customer_id") or "")
                            d["customer_phone"] = synthetic_buyer_phone(f"{oid}|{cid}")
                        em = (d.get("customer_email") or "").strip()
                        if not em:
                            d["customer_email"] = synthetic_buyer_email(
                                str(d.get("customer_id") or "") + str(oid)
                            )
                        orders.append(d)
                    return {"success": True, "orders": orders, "total": int(total)}
                finally:
                    neo.close()
        except Exception as e:
            logger.warning("admin/orders Neo4j 不可用，回退 platform_sync: %s", e)
        finally:
            try:
                neo.close()
            except Exception:
                pass

    try:
        if unified_router and hasattr(unified_router, 'get_orders'):
            result = await unified_router.get_orders(status=status, platform=platform, start_date=start_date, end_date=end_date, page=page, page_size=page_size)
            if result.get("orders") is not None:
                return {"success": True, "orders": result["orders"], "total": result.get("total", 0)}
    except Exception as e:
        logger.warning(f"admin/orders 路由到 unified_router 失败: {e}")

    # 降级：platform_sync 本地缓存（格式化字段 + 中文状态筛选）
    try:
        from platform_sync import get_synced_orders, format_sync_order_for_admin
        rows, total = get_synced_orders(
            status=st, platform=platform,
            start_date=start_date, end_date=end_date,
            page=page, page_size=page_size
        )
        orders = [format_sync_order_for_admin(r) for r in rows]
        return {"success": True, "orders": orders, "total": total}
    except Exception as e:
        logger.warning(f"admin/orders 从 platform_sync 获取失败: {e}")

    return {"success": True, "orders": [], "total": 0}


# ---- Admin Stats ----
@api_router.get("/admin/stats")
async def admin_stats(user: dict = Security(get_current_admin)):
    """管理后台统计数据"""
    try:
        if metrics_collector:
            stats = metrics_collector.get_all_metrics_summary()
            return {"success": True, "data": {"stats": stats}}
    except Exception:
        pass
    return {"success": True, "data": {"stats": {}}}


@api_router.get("/admin/advanced-stats")
async def admin_advanced_stats(user: dict = Security(get_current_admin)):
    """高级统计数据"""
    try:
        from db import get_advanced_stats
        stats = get_advanced_stats()
        return {"success": True, "data": {"stats": stats}}
    except Exception as e:
        logger.exception("admin_advanced_stats failed: %s", e)
        return {"success": True, "data": {"stats": {}}}


# ---- Admin Quick Replies ----
@api_router.get("/admin/quick-replies")
async def admin_get_quick_replies(user: dict = Security(get_current_admin)):
    """获取快捷回复列表"""
    try:
        if message_center_service:
            replies = message_center_service.get_quick_replies()
            return {"success": True, "replies": replies}
    except Exception:
        pass
    return {"success": True, "replies": []}


@api_router.post("/admin/quick-replies")
async def admin_create_quick_reply(data: QuickReplyCreate, user: dict = Security(get_current_admin)):
    """创建快捷回复"""
    try:
        if message_center_service:
            reply_id = message_center_service.create_quick_reply(
                category=data.category, title=data.title, content=data.content,
                shortcut=data.shortcut, created_by=user.get("username", "admin"),
            )
            return {"success": True, "id": reply_id}
    except Exception:
        pass
    return {"success": False, "message": "消息中心服务不可用"}


@api_router.delete("/admin/quick-replies/{category}/{reply_id}")
async def admin_delete_quick_reply(category: str, reply_id: int, user: dict = Security(get_current_admin)):
    """删除快捷回复"""
    try:
        if message_center_service:
            message_center_service.delete_quick_reply(reply_id)
            return {"success": True}
    except Exception:
        pass
    return {"success": False}


# ---- Admin Reviews ----
@api_router.post("/admin/reviews/import")
async def admin_import_reviews(request: Request, user: dict = Security(get_current_super_admin)):
    """导入评价数据（支持 CSV 上传）"""
    try:
        import csv
        import io
        from db import create_review

        content_type = request.headers.get("content-type", "")
        form_data = await request.form()

        review_count = 0
        error_rows = []

        uname = user.get("username") or user.get("sub") or "admin"
        # 支持 JSON 数组格式
        if "application/json" in content_type or "json" in str(form_data).lower():
            try:
                body = await request.json()
                if isinstance(body, list):
                    reviews = body
                elif isinstance(body, dict) and "reviews" in body:
                    reviews = body["reviews"]
                else:
                    return {"success": False, "message": "不支持的数据格式"}

                for idx, r in enumerate(reviews):
                    try:
                        rid = r.get("review_id") or f"imp-{idx}"
                        create_review(
                            review_id=rid,
                            order_id=r.get("order_id", ""),
                            customer_id=r.get("customer_id", ""),
                            customer_name=r.get("customer_name", ""),
                            star_rating=int(r.get("star_rating", 5)),
                            content=r.get("content", ""),
                            platform=r.get("platform", "other"),
                            product_name=r.get("product_name", ""),
                            review_date=r.get("review_date", ""),
                        )
                        review_count += 1
                    except Exception as e:
                        error_rows.append(f"第{idx + 1}行: {e}")

                _audit("BATCH", uname, "review",
                       detail=f"批量导入评价数据（成功 {review_count} 条，失败 {len(error_rows)} 条）", request=request)
                return {"success": True, "message": f"成功导入 {review_count} 条评价" + (f"，{len(error_rows)} 条失败" if error_rows else "")}
            except Exception as e:
                return {"success": False, "message": f"JSON 解析失败: {e}"}

        # 支持 CSV multipart 上传
        csv_file = form_data.get("file")
        if csv_file:
            try:
                content = await csv_file.read()
                decoded = content.decode("utf-8-sig", errors="replace")
                reader = csv.DictReader(io.StringIO(decoded))
                for idx, row in enumerate(reader):
                    try:
                        rid = row.get("review_id") or f"imp-{idx}"
                        create_review(
                            review_id=rid,
                            order_id=row.get("order_id", ""),
                            customer_id=row.get("customer_id", ""),
                            customer_name=row.get("customer_name", ""),
                            star_rating=int(row.get("star_rating", 5)),
                            content=row.get("content", ""),
                            platform=row.get("platform", "other"),
                            product_name=row.get("product_name", ""),
                            review_date=row.get("review_date", ""),
                        )
                        review_count += 1
                    except Exception as e:
                        error_rows.append(f"第{idx + 1}行: {e}")

                _audit("BATCH", uname, "review",
                       detail=f"CSV 批量导入评价数据（成功 {review_count} 条，失败 {len(error_rows)} 条）", request=request)
                return {"success": True, "message": f"CSV 导入 {review_count} 条" + (f"，{len(error_rows)} 条失败" if error_rows else "")}
            except Exception as e:
                return {"success": False, "message": f"CSV 解析失败: {e}"}

        return {"success": False, "message": "未提供文件或数据"}
    except Exception as e:
        logger.exception("admin_import_reviews failed: %s", e)
        return {"success": False, "message": str(e)}


@api_router.get("/admin/reviews")
async def admin_get_reviews(
    user: dict = Security(get_current_user),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    limit: Optional[int] = Query(None, ge=1, le=500),
    status: Optional[str] = None,
    star: Optional[int] = Query(None, ge=1, le=5),
    platform: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    keyword: Optional[str] = None,
):
    """获取评价列表（支持分页 + 关键词搜索）"""
    try:
        from db import get_reviews
        effective_limit = limit if limit is not None else page_size
        rows, total = get_reviews(
            status=status,
            star_rating=star,
            limit=effective_limit,
            start_date=start_date,
            end_date=end_date,
            platform=platform,
            page=page,
            page_size=effective_limit,
        )
        # 前端关键词过滤（在 Python 侧做，避免修改 SQL）
        if keyword:
            kw = keyword.lower()
            rows = [r for r in rows if
                    (r.get("content") or "").lower().find(kw) >= 0 or
                    (r.get("customer_name") or "").lower().find(kw) >= 0 or
                    (r.get("product_name") or "").lower().find(kw) >= 0]
            total = len(rows)
        return {"success": True, "data": rows, "reviews": rows, "total": total, "page": page, "page_size": effective_limit}
    except Exception as e:
        logger.exception("admin_get_reviews failed: %s", e)
        return {"success": False, "message": str(e), "data": [], "reviews": [], "total": 0}


@api_router.get("/admin/reviews/stats")
async def admin_reviews_stats(user: dict = Security(get_current_admin)):
    """评价统计"""
    try:
        from db import get_review_stats

        s = get_review_stats() or {}
        return {"success": True, "data": s, "stats": s}
    except Exception as e:
        logger.exception("admin_reviews_stats failed: %s", e)
        return {"success": False, "message": str(e), "data": {}}


@api_router.post("/admin/reviews/reply")
async def admin_reply_review(request: Request, data: ReviewReplyRequest, user: dict = Security(get_current_user)):
    """回复评价（支持直接内容和模板）"""
    try:
        from db import reply_review, get_reply_template
        uname = user.get("username") or user.get("sub") or "admin"
        content = data.content

        if data.template_id and not content:
            tmpl = get_reply_template(data.template_id)
            if tmpl:
                content = tmpl.get("content", "")

        if not content:
            return {"success": False, "message": "回复内容不能为空"}

        n = 0
        for rid in data.review_ids:
            if reply_review(rid, content, uname):
                n += 1
        _audit("UPDATE", uname, "review",
               target_id=str(data.review_ids),
               detail=f"回复评价（{n} 条）: {content[:40]}", request=request)
        return {"success": True, "message": f"已回复 {n} 条评价"}
    except Exception as e:
        logger.exception("admin_reply_review failed: %s", e)
        return {"success": False, "message": str(e)}


@api_router.post("/admin/reviews/quick-reply")
async def admin_quick_reply_review(request: Request, data: ReviewReplyRequest, user: dict = Security(get_current_user)):
    """快捷回复评价（使用模板回复）"""
    try:
        from db import batch_reply_reviews, get_reply_template
        uname = user.get("username") or user.get("sub") or "admin"
        content = data.content

        if data.template_id and not content:
            tmpl = get_reply_template(data.template_id)
            if tmpl:
                content = tmpl.get("content", "")
            else:
                return {"success": False, "message": "模板不存在"}

        if not content:
            return {"success": False, "message": "回复内容不能为空"}

        n = batch_reply_reviews(data.review_ids, content, uname)
        _audit("UPDATE", uname, "review",
               target_id=str(data.review_ids),
               detail=f"快捷回复评价（{n} 条）", request=request)
        return {"success": True, "message": f"快捷回复 {n} 条评价"}
    except Exception as e:
        logger.exception("admin_quick_reply failed: %s", e)
        return {"success": False, "message": str(e)}


@api_router.post("/admin/reviews/auto-reply")
async def admin_auto_reply_review(request: Request, data: ReviewReplyRequest, user: dict = Security(get_current_user)):
    """AI 自动回复评价（根据评分生成回复内容后批量写入）"""
    try:
        from db import batch_reply_reviews, get_review
        import random
        uname = user.get("username") or user.get("sub") or "admin"
        templates = {
            5: ["感谢您的满分好评！您的支持是我们最大的动力~ 期待再次为您服务！", "非常感谢您的认可！我们会继续努力，提供更好的产品和服务！"],
            4: ["感谢您的好评！您的建议我们会认真对待，争取做到更好！", "谢谢您的支持！我们会继续提升，期待为您带来更好的体验！"],
            3: ["感谢您的反馈，我们会认真对待，努力改进产品和服务质量！"],
            2: ["非常抱歉给您带来不便，我们已记录您的反馈，会尽快改进，期待下次能为您做得更好。"],
            1: ["对给您造成的不愉快体验，我们深表歉意。我们会立即跟进并改进，期待有机会再次为您服务。"],
        }
        n = 0
        for rid in data.review_ids:
            row = get_review(rid)
            if row:
                star = row.get("star_rating", 3)
                pool = templates.get(star, templates[3])
                content = random.choice(pool)
                from db import reply_review
                reply_review(rid, content, uname)
                n += 1
        _audit("BATCH", uname, "review",
               target_id=str(data.review_ids),
               detail=f"AI 自动回复评价（{n} 条）", request=request)
        return {"success": True, "message": f"AI 自动回复 {n} 条评价"}
    except Exception as e:
        logger.exception("admin_auto_reply failed: %s", e)
        return {"success": False, "message": str(e)}


@api_router.get("/admin/reviews/export")
async def admin_export_reviews(
    user: dict = Security(get_current_admin),
    status: Optional[str] = None,
    star: Optional[int] = None,
    platform: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    export_format: str = Query("csv", alias="format"),
):
    """导出评价（CSV，直接下载文件）"""
    try:
        from db import get_reviews
        import io

        rows, _ = get_reviews(
            status=status,
            star_rating=star,
            limit=5000,
            start_date=start_date,
            end_date=end_date,
            platform=platform,
        )
        buf = io.StringIO()
        buf.write("\ufeffreview_id,order_id,customer_name,platform,star_rating,status,content,review_date\n")
        for r in rows:
            # 转义CSV内容：将双引号替换为两个双引号，处理换行符
            content = (r.get("content") or "").replace('"', '""').replace('\n', ' ').replace('\r', ' ')
            review_date = r.get("review_date", "")
            buf.write(
                f'"{r.get("review_id", "")}","{r.get("order_id", "")}","{r.get("customer_name", "")}",'
                f'"{r.get("platform", "")}",{r.get("star_rating", "")},{r.get("status", "")},'
                f'"{content}","{review_date}"\n'
            )
        csv_text = buf.getvalue()

        from fastapi.responses import StreamingResponse
        import datetime as dt

        filename = f"reviews_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

        async def generate():
            yield csv_text

        return StreamingResponse(
            generate(),
            media_type="text/csv; charset=utf-8-sig",
            headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{filename}",
            }
        )
    except Exception as e:
        logger.exception("admin_export_reviews failed: %s", e)
        return {"success": False, "message": f"导出失败: {str(e)}"}


@api_router.post("/admin/reviews/generate-sample")
async def admin_generate_sample_reviews(user: dict = Security(get_current_super_admin)):
    """生成示例评价（写入数据库，供界面联调）"""
    try:
        from db import create_review
        import uuid
        import random
        from datetime import date

        platforms = ["amazon", "ebay", "shopee", "lazada", "aliexpress", "shopify", "tiktok"]
        texts_good = [
            "发货快，包装好，会回购。",
            "质量不错，和描述一致，满意。",
            "客服响应及时，问题解决得很快。",
            "物流比预期快，推荐。",
        ]
        texts_mid = ["还可以，中规中矩。", "一般般，有待改进。", "能用，期望值不要太高。"]
        texts_bad = [
            "商品与描述不符，失望。",
            "物流太慢，包装破损。",
            "质量差，不建议购买。",
        ]
        today = date.today().isoformat()
        n = 0
        for i in range(20):
            rid = f"smp-{uuid.uuid4().hex[:14]}"
            plat = random.choice(platforms)
            star = random.choices([1, 2, 3, 4, 5], weights=[1, 2, 2, 5, 6])[0]
            if star <= 2:
                content = random.choice(texts_bad)
            elif star == 3:
                content = random.choice(texts_mid)
            else:
                content = random.choice(texts_good)
            create_review(
                rid,
                order_id=f"ORD-{uuid.uuid4().hex[:10].upper()}",
                customer_id=f"cu-{uuid.uuid4().hex[:8]}",
                customer_name=f"测试买家{i + 1}",
                star_rating=star,
                content=content,
                platform=plat,
                product_name=f"样品SKU-{i + 1}",
                review_date=today,
            )
            n += 1
        return {"success": True, "message": f"已生成 {n} 条测试评价"}
    except Exception as e:
        logger.exception("admin_generate_sample_reviews failed: %s", e)
        return {"success": False, "message": str(e)}


# ---- Admin Auto Reply Rules ----
@api_router.get("/admin/auto-reply-rules")
async def admin_get_auto_reply_rules(user: dict = Security(get_current_admin)):
    """获取自动回复规则"""
    try:
        from db import get_auto_reply_rules
        rules = get_auto_reply_rules()
        return {"success": True, "data": rules, "rules": rules}
    except Exception as e:
        logger.exception("admin_get_auto_reply_rules failed: %s", e)
        return {"success": True, "data": [], "rules": []}


@api_router.post("/admin/auto-reply-rules")
async def admin_create_auto_reply_rule(request: Request, data: CreateRuleRequest, user: dict = Security(get_current_admin)):
    """创建自动回复规则"""
    try:
        from db import create_auto_reply_rule
        uname = user.get("username") or user.get("sub") or "admin"
        rule_id = create_auto_reply_rule(
            rule_type=data.rule_type,
            reply_content=data.reply_content,
            star_min=data.star_min,
            star_max=data.star_max,
            created_by=uname,
        )
        _audit("CREATE", uname, "auto_reply_rule",
               target_id=str(rule_id),
               detail=f"创建自动回复规则（类型：{data.rule_type}）", request=request)
        return {"success": True, "message": "规则创建成功", "rule_id": rule_id}
    except Exception as e:
        logger.exception("admin_create_auto_reply_rule failed: %s", e)
        return {"success": False, "message": str(e)}


@api_router.put("/admin/auto-reply-rules/{rule_id}")
async def admin_update_auto_reply_rule(rule_id: int, request: Request, data: CreateRuleRequest, user: dict = Security(get_current_admin)):
    """更新自动回复规则"""
    try:
        from db import update_auto_reply_rule
        uname = user.get("username") or user.get("sub") or "admin"
        ok = update_auto_reply_rule(
            rule_id,
            rule_type=data.rule_type,
            reply_content=data.reply_content,
            star_min=data.star_min,
            star_max=data.star_max,
            is_enabled=data.is_enabled,
        )
        if ok:
            _audit("UPDATE", uname, "auto_reply_rule",
                   target_id=str(rule_id),
                   detail=f"更新自动回复规则（类型：{data.rule_type}）", request=request)
            return {"success": True, "message": "规则已更新"}
        return {"success": False, "message": "规则不存在"}
    except Exception as e:
        logger.exception("admin_update_auto_reply_rule failed: %s", e)
        return {"success": False, "message": str(e)}


@api_router.delete("/admin/auto-reply-rules/{rule_id}")
async def admin_delete_auto_reply_rule(rule_id: int, request: Request, user: dict = Security(get_current_admin)):
    """删除自动回复规则"""
    try:
        from db import delete_auto_reply_rule
        uname = user.get("username") or user.get("sub") or "admin"
        ok = delete_auto_reply_rule(rule_id)
        if ok:
            _audit("DELETE", uname, "auto_reply_rule",
                   target_id=str(rule_id),
                   detail="删除自动回复规则", request=request)
            return {"success": True, "message": "规则已删除"}
        return {"success": False, "message": "规则不存在"}
    except Exception as e:
        logger.exception("admin_delete_auto_reply_rule failed: %s", e)
        return {"success": False, "message": str(e)}


# ---- Admin Reply Templates ----
@api_router.get("/admin/reply-templates")
async def admin_get_reply_templates(user: dict = Security(get_current_admin)):
    """获取回复模板"""
    try:
        from db import get_reply_templates
        templates = get_reply_templates()
        return {"success": True, "data": templates, "templates": templates}
    except Exception as e:
        logger.exception("admin_get_reply_templates failed: %s", e)
        return {"success": True, "data": [], "templates": []}


@api_router.post("/admin/reply-templates")
async def admin_create_reply_template(request: Request, data: CreateTemplateRequest, user: dict = Security(get_current_admin)):
    """创建回复模板"""
    try:
        from db import create_reply_template
        uname = user.get("username") or user.get("sub") or "admin"
        template_id = create_reply_template(
            name=data.name,
            content=data.content,
            category=data.category,
            is_default=data.is_default,
            created_by=uname,
        )
        _audit("CREATE", uname, "reply_template",
               target_id=str(template_id),
               detail=f"创建回复模板（名称：{data.name}）", request=request)
        return {"success": True, "message": "模板创建成功", "template_id": template_id}
    except Exception as e:
        logger.exception("admin_create_reply_template failed: %s", e)
        return {"success": False, "message": str(e)}


@api_router.put("/admin/reply-templates/{template_id}")
async def admin_update_reply_template(template_id: int, request: Request, data: CreateTemplateRequest, user: dict = Security(get_current_admin)):
    """更新回复模板"""
    try:
        from db import update_reply_template
        uname = user.get("username") or user.get("sub") or "admin"
        ok = update_reply_template(
            template_id,
            name=data.name,
            content=data.content,
            category=data.category,
            is_default=data.is_default,
        )
        if ok:
            _audit("UPDATE", uname, "reply_template",
                   target_id=str(template_id),
                   detail=f"更新回复模板（名称：{data.name}）", request=request)
            return {"success": True, "message": "模板已更新"}
        return {"success": False, "message": "模板不存在"}
    except Exception as e:
        logger.exception("admin_update_reply_template failed: %s", e)
        return {"success": False, "message": str(e)}


@api_router.delete("/admin/reply-templates/{template_id}")
async def admin_delete_reply_template(template_id: int, request: Request, user: dict = Security(get_current_admin)):
    """删除回复模板"""
    try:
        from db import delete_reply_template
        uname = user.get("username") or user.get("sub") or "admin"
        ok = delete_reply_template(template_id)
        if ok:
            _audit("DELETE", uname, "reply_template",
                   target_id=str(template_id),
                   detail="删除回复模板", request=request)
            return {"success": True, "message": "模板已删除"}
        return {"success": False, "message": "模板不存在"}
    except Exception as e:
        logger.exception("admin_delete_reply_template failed: %s", e)
        return {"success": False, "message": str(e)}


# ---- Admin After-Sales ----
@api_router.get("/admin/after-sales")
async def admin_get_after_sales(
    user: dict = Security(get_current_super_admin),
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=200),
    status: Optional[str] = None,
    type: Optional[str] = None,
    keyword: Optional[str] = None,
    platform: Optional[str] = None,
):
    """获取售后列表"""
    try:
        from db import get_after_sales, get_after_sale_stats

        rows, total = get_after_sales(
            status=status, type=type, keyword=keyword,
            platform=platform, page=page, page_size=page_size,
        )
        stats_raw = get_after_sale_stats() or {}
        stats = {
            "total": int(stats_raw.get("total") or 0),
            "pending": int(stats_raw.get("pending") or 0),
            "returning": int((stats_raw.get("return_pending") or 0) + (stats_raw.get("received") or 0)),
            "qc": int(stats_raw.get("qc") or 0),
            "refund": int(stats_raw.get("refund") or 0),
            "completed": int(stats_raw.get("completed") or 0),
        }

        def _row_to_list_item(r: dict) -> dict:
            amt = float(r.get("refund_total") or 0)
            ct = r.get("created_at")
            if ct is not None and hasattr(ct, "isoformat"):
                ct = ct.isoformat()
            ct = str(ct or "")[:19].replace("T", " ")
            risky = (r.get("reason_category") or "") in ("恶意买家", "欺诈")
            return {
                "id": r.get("as_id"),
                "orderId": r.get("order_id") or "",
                "customerName": r.get("customer_name") or "—",
                "customerId": r.get("customer_id") or "—",
                "platform": r.get("platform") or "—",
                "type": r.get("type") or "—",
                "status": r.get("status") or "—",
                "amount": f"{amt:.2f}",
                "warehouse": r.get("warehouse") or "—",
                "risk": "高风险" if risky else "正常",
                "createTime": ct or "—",
            }

        list_items = [_row_to_list_item(dict(r) if r else {}) for r in rows]
        return {
            "success": True,
            "after_sales": rows,
            "list": list_items,
            "stats": stats,
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    except Exception as e:
        logger.exception("admin_get_after_sales failed: %s", e)
        return {"success": False, "message": str(e), "after_sales": [], "list": [], "total": 0, "stats": {}}


@api_router.post("/admin/after-sales")
async def admin_create_after_sale(request: Request, data: AfterSaleCreateRequest, user: dict = Security(get_current_super_admin)):
    """创建售后单"""
    try:
        from db import create_after_sale
        import uuid
        as_id = f"AS-{uuid.uuid4().hex[:14].upper()}"
        uname = user.get("username") or user.get("sub") or "admin"
        create_after_sale(
            order_id=data.order_id, customer_id=data.customer_id,
            platform="manual", customer_name="",
            type=data.type, reason_category=data.reason,
            refund_total=data.amount,
            internal_note=f"由 {uname} 手动创建",
        )
        _audit("CREATE", uname, "after_sale",
               target_id=as_id,
               detail=f"创建售后单（订单：{data.order_id}，类型：{data.type}，金额：{data.amount}）", request=request)
        return {"success": True, "as_id": as_id}
    except Exception as e:
        logger.exception("admin_create_after_sale failed: %s", e)
        return {"success": False, "message": str(e)}


@api_router.get("/admin/after-sales/stats")
async def admin_after_sales_stats(user: dict = Security(get_current_super_admin)):
    """售后统计"""
    try:
        from db import get_after_sale_stats
        stats = get_after_sale_stats() or {}
        return {"success": True, "stats": stats, "data": stats}
    except Exception as e:
        logger.exception("admin_after_sales_stats failed: %s", e)
        return {"success": False, "message": str(e), "stats": {}, "data": {}}


@api_router.get("/admin/after-sales/{as_id}")
async def admin_get_after_sale(as_id: str, user: dict = Security(get_current_super_admin)):
    """获取售后详情"""
    try:
        from db import get_after_sale
        row = get_after_sale(as_id)
        if row:
            return {"success": True, "after_sale": row}
        return {"success": False, "message": "售后单不存在"}, 404
    except Exception as e:
        logger.exception("admin_get_after_sale failed: %s", e)
        return {"success": False, "message": str(e), "after_sale": {}}


class AfterSaleStatusRequest(BaseModel):
    status: str
    extra: Optional[Dict] = None


@api_router.put("/admin/after-sales/{as_id}")
async def admin_update_after_sale(as_id: str, request: Request,
                                  user: dict = Security(get_current_super_admin),
                                  data: AfterSaleStatusRequest = None):
    """更新售后单"""
    try:
        from db import update_after_sale
        uname = user.get("username") or user.get("sub") or "admin"
        updates = dict(data.extra) if data and data.extra else {}
        updates["updated_by"] = uname
        ok = update_after_sale(as_id, **updates)
        if ok:
            _audit("UPDATE", uname, "after_sale",
                   target_id=as_id,
                   detail=f"更新售后单（变更字段数：{len(updates)}）", request=request)
            return {"success": True}
        return {"success": False, "message": "更新失败，记录不存在"}
    except Exception as e:
        logger.exception("admin_update_after_sale failed: %s", e)
        return {"success": False, "message": str(e)}


@api_router.post("/admin/after-sales/{as_id}/status")
async def admin_update_after_sale_status(
    as_id: str,
    request: Request,
    data: AfterSaleStatusRequest,
    user: dict = Security(get_current_super_admin),
):
    """更新售后状态"""
    try:
        from db import advance_after_sale_status
        uname = user.get("username") or user.get("sub") or "admin"
        ok = advance_after_sale_status(as_id, data.status, data.extra)
        if ok:
            _audit("UPDATE", uname, "after_sale",
                   target_id=as_id,
                   detail=f"更新售后状态为「{data.status}」", request=request)
            return {"success": True, "message": f"已更新状态为「{data.status}」"}
        return {"success": False, "message": "更新失败，记录不存在"}
    except Exception as e:
        logger.exception("admin_update_after_sale_status failed: %s", e)
        return {"success": False, "message": str(e)}


class BatchAfterSalesRequest(BaseModel):
    ids: List[str]
    status: str


@api_router.post("/admin/after-sales/batch")
async def admin_batch_after_sales(
    request: Request,
    data: BatchAfterSalesRequest,
    user: dict = Security(get_current_super_admin),
):
    """批量更新售后状态"""
    try:
        from db import advance_after_sale_status
        uname = user.get("username") or user.get("sub") or "admin"
        n = 0
        for as_id in data.ids:
            if advance_after_sale_status(as_id, data.status):
                n += 1
        _audit("BATCH", uname, "after_sale",
               target_id=str(data.ids[:5]) + ("..." if len(data.ids) > 5 else ""),
               detail=f"批量更新 {n} 条售后单状态为「{data.status}」", request=request)
        return {"success": True, "message": f"批量更新 {n} 条售后单状态为「{data.status}」"}
    except Exception as e:
        logger.exception("admin_batch_after_sales failed: %s", e)
        return {"success": False, "message": str(e)}

# ---- Admin Audit Logs ----
@api_router.get("/admin/audit-logs")
async def admin_get_audit_logs(
    user: dict = Security(get_current_super_admin),
    page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
    event_type: Optional[str] = Query(None),
    operator: Optional[str] = Query(None),
    target_type: Optional[str] = Query(None),
):
    """获取审计日志"""
    try:
        from db import get_audit_logs
        logs, total = get_audit_logs(
            event_type=event_type,
            operator=operator,
            target_type=target_type,
            page=page,
            page_size=page_size,
        )
        return {"success": True, "logs": logs, "total": total, "page": page, "page_size": page_size}
    except Exception as e:
        logger.exception("admin_get_audit_logs failed: %s", e)
        return {"success": False, "logs": [], "total": 0, "page": page, "page_size": page_size}


# ---- Admin Notifications ----
@api_router.get("/admin/notifications")
async def admin_get_notifications(
    user: dict = Security(get_current_admin),
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    is_read: Optional[bool] = Query(None),
    notify_type: Optional[str] = Query(None),
):
    """获取通知列表（优先走 message_center_service，回退到 db.py）"""
    try:
        if message_center_service:
            notifications = message_center_service.get_notifications(
                notification_type=notify_type,
                include_read=is_read is None or is_read,
                limit=page_size,
            )
            # 统一返回格式：frontend TopBar 读 n.read (bool)，DB 存 is_read (0/1)
            normalized = []
            for n in notifications:
                item = dict(n)
                item["read"] = bool(item.get("is_read", 0) == 1)
                normalized.append(item)
            return {"success": True, "notifications": normalized}
    except Exception:
        pass
    # 回退：从 db.py 读取
    try:
        from db import get_notifications
        rows, total = get_notifications(is_read=is_read, notify_type=notify_type, page=page, page_size=page_size)
        return {"success": True, "notifications": rows, "total": total}
    except Exception as e:
        logger.exception("admin_get_notifications fallback failed: %s", e)
    return {"success": True, "notifications": [], "page": page, "page_size": page_size}


@api_router.post("/admin/notifications/{notify_id}/read")
async def admin_mark_notification_read(notify_id: int, user: dict = Security(get_current_admin)):
    """标记单条通知已读"""
    try:
        if message_center_service:
            message_center_service.mark_notification_read(notify_id)
    except Exception:
        pass
    try:
        from db import mark_notification_read
        mark_notification_read(notify_id)
    except Exception:
        pass
    return {"success": True}


@api_router.get("/admin/notifications/unread-count")
async def admin_unread_notification_count(user: dict = Security(get_current_admin)):
    """获取未读通知数量"""
    try:
        if message_center_service:
            count = message_center_service.get_unread_count()
            return {"success": True, "count": count}
    except Exception:
        pass
    try:
        from db import get_unread_notification_count
        count = get_unread_notification_count()
        return {"success": True, "count": count}
    except Exception:
        pass
    return {"success": True, "count": 0}


@api_router.post("/admin/notifications/mark-all-read")
async def admin_mark_all_notifications_read(user: dict = Security(get_current_admin)):
    """全部标记已读"""
    try:
        from db import get_notifications, mark_notification_read
        rows, _ = get_notifications(is_read=False, limit=1000, page=1, page_size=1000)
        for n in rows:
            try:
                mark_notification_read(n.get("id"))
            except Exception:
                pass
    except Exception:
        pass
    return {"success": True}


# ---- Admin System Settings ----
@api_router.get("/admin/system-settings")
async def admin_get_system_settings(user: dict = Security(get_current_super_admin)):
    """获取系统设置"""
    return {"success": True, "settings": {}}


@api_router.post("/admin/system-settings")
async def admin_update_system_settings(user: dict = Security(get_current_super_admin)):
    """更新系统设置"""
    return {"success": True}


# ---- Pre-Sale Notes ----
@api_router.get("/pre-sale-notes")
async def get_pre_sale_notes(
    category: str = "",
    keyword: str = "",
    platform: str = "",
    country: str = "",
    risk_only: Optional[bool] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    """获取售前备注列表（优先 message_center；回退 seller.db / db.py）"""
    try:
        if message_center_service:
            notes = message_center_service.get_pre_sale_notes(category=category, page=page, page_size=page_size)
            if notes:
                return {"success": True, "notes": notes, "list": notes, "page": page, "page_size": page_size}
    except Exception:
        pass
    try:
        from db import get_pre_sale_notes as db_get_pre_sale_notes

        kw = keyword or None
        plat = platform or None
        ctry = country or None
        r_only = risk_only is True
        n_only = risk_only is False  # 前端「正常」筛选用 risk_only=false

        rows, total = db_get_pre_sale_notes(
            keyword=kw,
            platform=plat,
            country=ctry,
            risk_only=r_only,
            normal_only=n_only,
            page=page,
            page_size=page_size,
        )
        return {"success": True, "notes": rows, "list": rows, "total": total, "page": page, "page_size": page_size}
    except Exception as e:
        logger.exception("get_pre_sale_notes db fallback failed: %s", e)
    return {"success": True, "notes": [], "list": [], "total": 0, "page": page, "page_size": page_size}


@api_router.post("/pre-sale-notes")
async def create_pre_sale_note(request: Request, data: PreSaleNoteCreate):
    """创建售前备注"""
    try:
        if message_center_service and hasattr(message_center_service, 'create_pre_sale_note'):
            note_id = message_center_service.create_pre_sale_note(title=data.title, content=data.content, category=data.category)
            _audit("CREATE", data.created_by or "anonymous", "pre_sale_note",
                   target_id=str(note_id),
                   detail=f"创建售前备注（标题：{data.title}）", request=request)
            return {"success": True, "id": note_id}
    except Exception:
        pass
    # 回退到 db.py，直接透传所有字段
    try:
        from db import create_pre_sale_note as db_create
        note_id = db_create(
            order_id=data.order_id,
            customer_id=data.customer_id,
            customer_name=data.customer_name,
            nickname=data.nickname,
            platform=data.platform or "other",
            platform_id=data.platform_id,
            country=data.country,
            region=data.region,
            language=data.language or "zh",
            is_old_customer=data.is_old_customer,
            repeat_purchase_count=data.repeat_purchase_count,
            has_complaints=data.has_complaints,
            has_disputes=data.has_disputes,
            has_negative_reviews=data.has_negative_reviews,
            has_asked_shipping=data.has_asked_shipping,
            has_asked_logistics=data.has_asked_logistics,
            preference_style=data.preference_style,
            preference_color=data.preference_color,
            preference_size=data.preference_size,
            price_sensitivity=data.price_sensitivity or "normal",
            needs_gift=data.needs_gift,
            needs_card=data.needs_card,
            needs_privacy_packaging=data.needs_privacy_packaging,
            product_color=data.product_color,
            product_size=data.product_size,
            product_model=data.product_model,
            packaging_type=data.packaging_type or "normal",
            no_invoice=data.no_invoice,
            no_price_list=data.no_price_list,
            logistics_channel=data.logistics_channel,
            must_combine=data.must_combine,
            urgent_shipping=data.urgent_shipping,
            needs_gift_item=data.needs_gift_item,
            needs_card_item=data.needs_card_item,
            customer_message_translation=data.customer_message_translation,
            fragile_need_extra_protection=data.fragile_need_extra_protection,
            high_risk_area=data.high_risk_area,
            suspected_scammer=data.suspected_scammer,
            price_modification=data.price_modification,
            discount=data.discount,
            free_shipping=data.free_shipping,
            out_of_stock=data.out_of_stock,
            pre_order=data.pre_order,
            waiting_days=data.waiting_days,
            internal_note=data.internal_note,
            raw_note=data.raw_note,
            created_by=data.created_by or "admin",
        )
        _audit("CREATE", data.created_by or "anonymous", "pre_sale_note",
               target_id=str(note_id),
               detail=f"创建售前备注（标题：{data.title}）", request=request)
        return {"success": True, "id": note_id}
    except Exception as e:
        logger.exception("create_pre_sale_note db fallback failed: %s", e)
    return {"success": False}


@api_router.get("/pre-sale-notes/{note_id}")
async def get_pre_sale_note(note_id: str):
    """获取售前备注详情"""
    try:
        if message_center_service and hasattr(message_center_service, 'get_pre_sale_note'):
            note = message_center_service.get_pre_sale_note(note_id)
            if note:
                return {"success": True, "note": note}
    except Exception:
        pass
    try:
        from db import get_pre_sale_note as db_get
        note = db_get(note_id)
        if note:
            return {"success": True, "note": note}
    except Exception as e:
        logger.debug("get_pre_sale_note db fallback failed: %s", e)
    return {"success": True, "note": {}}


@api_router.put("/pre-sale-notes/{note_id}")
async def update_pre_sale_note(note_id: str, request: Request, data: PreSaleNoteUpdate):
    """更新售前备注"""
    try:
        if message_center_service and hasattr(message_center_service, 'update_pre_sale_note'):
            message_center_service.update_pre_sale_note(note_id, title=data.title, content=data.content, category=data.category)
            _audit("UPDATE", "operator", "pre_sale_note",
                   target_id=note_id,
                   detail=f"更新售前备注（标题：{data.title}）", request=request)
            return {"success": True}
    except Exception:
        pass
    try:
        from db import update_pre_sale_note as db_update
        kwargs = {}
        if data.title is not None:
            kwargs["title"] = data.title
        if data.content is not None:
            kwargs["content"] = data.content
        if data.category is not None:
            kwargs["category"] = data.category
        if kwargs:
            db_update(note_id, **kwargs)
        _audit("UPDATE", "operator", "pre_sale_note",
               target_id=note_id,
               detail=f"更新售前备注（标题：{data.title}）", request=request)
        return {"success": True}
    except Exception as e:
        logger.exception("update_pre_sale_note db fallback failed: %s", e)
    return {"success": False}


@api_router.delete("/pre-sale-notes/{note_id}")
async def delete_pre_sale_note(note_id: str, request: Request):
    """删除售前备注（note_id 为字符串格式如 PSN20260402xxx）"""
    # 优先尝试 message_center_service（如果实现了此方法）
    try:
        if message_center_service and hasattr(message_center_service, 'delete_pre_sale_note'):
            message_center_service.delete_pre_sale_note(note_id)
            _audit("DELETE", "operator", "pre_sale_note",
                   target_id=note_id,
                   detail="删除售前备注", request=request)
            return {"success": True}
    except Exception:
        pass
    # 回退到 db.py
    try:
        from db import delete_pre_sale_note as db_delete
        db_delete(note_id)
        _audit("DELETE", "operator", "pre_sale_note",
               target_id=note_id,
               detail="删除售前备注", request=request)
        return {"success": True}
    except Exception as e:
        logger.exception("delete_pre_sale_note failed: %s", e)
    return {"success": False, "message": "删除失败"}


@api_router.get("/pre-sale-notes/stats/summary")
async def pre_sale_notes_summary():
    """售前备注统计摘要"""
    return {"success": True, "summary": {}}


@api_router.get("/pre-sale-notes/parse-preview")
async def pre_sale_notes_parse_preview(raw_note: str = Query(...)):
    """预览备注解析结果（不写入数据库）"""
    try:
        if message_center_service:
            parsed = message_center_service.parse_pre_sale_note(raw_note)
            return {"success": True, "data": parsed}
    except Exception:
        pass
    return {"success": True, "data": {}}


@api_router.post("/pre-sale-notes/receive")
async def pre_sale_notes_receive(request: Request):
    """接收并解析备注文本"""
    try:
        body = await request.json()
        raw_note = body.get("raw_note", "")
        order_id = body.get("order_id")
        customer_id = body.get("customer_id")
        customer_name = body.get("customer_name")
        if message_center_service and hasattr(message_center_service, 'create_pre_sale_note'):
            note_id = message_center_service.create_pre_sale_note(
                title=f"备注-{order_id or 'new'}",
                content=raw_note,
                category="自动解析",
                created_by="system",
            )
            return {"success": True, "note_id": note_id}
    except Exception:
        pass
    # 回退到 db.py
    try:
        from db import create_pre_sale_note as db_create
        note_id = db_create(
            order_id=order_id,
            customer_id=customer_id,
            customer_name=customer_name,
            raw_note=raw_note,
            internal_note=raw_note,
            created_by="system",
        )
        return {"success": True, "note_id": note_id}
    except Exception as e:
        logger.exception("receive pre-sale-notes db fallback failed: %s", e)
    return {"success": True, "note_id": "mock-001"}


# ---- Seller Auth ----

@api_router.post("/agent/login")
async def agent_login(request: Request):
    """坐席登录 - 前端直接调用此接口"""
    try:
        data = await request.json()
        agent_id = data.get('agent_id', '').strip()
        agent_name = data.get('agent_name', '').strip() or agent_id
        role = data.get('role', 'agent')

        if not agent_id:
            return JSONResponse(status_code=400, content={"success": False, "message": "请输入坐席工号"})

        # 记录坐席登录
        if agent_service:
            agent_service.agent_login(agent_id, agent_name, role)

        # 创建 token（使用 seller 角色，可调用 /seller/* 系列接口）
        token = create_access_token(
            subject=agent_id,
            role="seller",
            extra_claims={
                "agent_id": agent_id,
                "agent_name": agent_name,
                "role": "seller"
            }
        )

        _audit("LOGIN", agent_id, "agent",
               detail=f"坐席登录（姓名：{agent_name}，角色：{role}）", request=request)

        return {
            "success": True,
            "access_token": token,
            "token_type": "bearer",
            "agent": {
                "agent_id": agent_id,
                "agent_name": agent_name,
                "role": role,
                "status": "online"
            }
        }
    except Exception as e:
        logger.error(f"Agent login error: {e}")
        return JSONResponse(status_code=500, content={"success": False, "message": str(e)})


@api_router.post("/seller/login")
async def seller_login(request: Request, body: SellerLoginRequest):
    """卖家登录"""
    from jwt_auth import create_access_token
    try:
        if agent_service and (hasattr(agent_service, 'agent_login') or hasattr(agent_service, 'login')):
            login_fn = getattr(agent_service, 'agent_login', None) or getattr(agent_service, 'login')
            agent_info = login_fn(body.username, body.password)
            if agent_info:
                token = create_access_token(subject=body.username, role="seller", extra_claims={"agent_id": agent_info.get("agent_id", "")})
                _audit("LOGIN", body.username, "seller",
                       detail="卖家登录成功", request=request)
                return {"success": True, "access_token": token, "token_type": "bearer", "agent": agent_info}
    except Exception:
        pass
    return {"success": False, "message": "用户名或密码错误"}


@api_router.post("/seller/logout")
async def seller_logout(request: Request, user: dict = Security(get_current_seller)):
    """卖家登出"""
    uname = user.get("username") or user.get("sub")
    _audit("LOGOUT", uname, "seller", detail="卖家登出", request=request)
    return {"success": True, "message": "已退出登录"}


@api_router.post("/seller/change-password")
async def seller_change_password(request: Request, body: ChangePasswordRequest, user: dict = Security(get_current_seller)):
    """卖家修改密码"""
    uname = user.get("username") or user.get("sub")
    _audit("UPDATE", uname, "seller", target_id=uname,
           detail="卖家修改账户密码", request=request)
    return {"success": True, "message": "密码修改成功"}


@api_router.get("/seller/customers")
async def seller_get_customers(user: dict = Security(get_current_user)):
    """卖家获取分配的客户列表"""
    try:
        if agent_service:
            customers = agent_service.get_assigned_customers(user.get("sub", ""))
            return {"success": True, "customers": customers}
    except Exception:
        pass
    return {"success": True, "customers": []}


@api_router.get("/seller/messages/{session_id}")
async def seller_get_messages(session_id: str, user: dict = Security(get_current_user)):
    """卖家获取会话消息"""
    try:
        if message_service:
            messages = message_service.get_messages(session_id)
            return {"success": True, "session_id": session_id, "messages": messages}
    except Exception:
        pass
    return {"success": True, "session_id": session_id, "messages": []}


@api_router.get("/seller/human-settings")
async def seller_get_human_settings(user: dict = Security(get_current_seller)):
    """获取人工客服设置"""
    return {"success": True, "settings": {}}


@api_router.put("/seller/human-settings")
async def seller_update_human_settings(data: HumanSettingsUpdate, user: dict = Security(get_current_seller)):
    """更新人工客服设置"""
    return {"success": True}


@api_router.post("/seller/upload")
async def seller_upload_file(file: UploadFile = File(...), user: dict = Security(get_current_seller)):
    """卖家上传文件"""
    return {"success": True, "filename": file.filename}


@api_router.post("/seller/send")
async def seller_send_message(request: SellerMessageRequest, user: dict = Security(get_current_user)):
    """卖家发送消息"""
    try:
        if message_service:
            msg_id = message_service.send_message(
                session_id=request.session_id, sender="seller",
                content=request.message, message_type=request.message_type,
            )
            return {"success": True, "message_id": msg_id}
    except Exception:
        pass
    return {"success": True}


@api_router.post("/seller/transfer-to-ai")
async def seller_transfer_to_ai(request: Request, user: dict = Security(get_current_seller)):
    """卖家将会话转回 AI"""
    body = await request.json()
    session_id = body.get("session_id")
    try:
        if session_mode:
            session_mode.set_mode(session_id, "ai")
    except Exception:
        pass
    return {"success": True}


@api_router.post("/seller/close-session")
async def seller_close_session(request: Request, user: dict = Security(get_current_seller)):
    """卖家关闭会话"""
    body = await request.json()
    session_id = body.get("session_id")
    try:
        if session_mode:
            session_mode.release_session(session_id)
    except Exception:
        pass
    return {"success": True}


@api_router.post("/seller/clear-messages")
async def seller_clear_messages(request: Request, user: dict = Security(get_current_seller)):
    """清空会话消息"""
    body = await request.json()
    session_id = body.get("session_id")
    return {"success": True}


@api_router.post("/seller/translate-preview")
async def seller_translate_preview(request: Request, user: dict = Security(get_current_user)):
    """
    翻译预览 API（双语对照视图）
    坐席输入中文后，实时预览翻译结果
    """
    try:
        body = await request.json()
        text = body.get("text", "")
        session_id = body.get("session_id", "")
        
        if not text:
            return {"success": True, "translated_text": ""}
        
        # 获取客户语言
        target_lang = "en"  # 默认英文
        if session_id and session_mode:
            target_lang = session_mode.get_target_language(session_id) or "en"
        
        # 调用翻译服务
        if translate_text:
            translated = translate_text(text, source_lang="zh", target_lang=target_lang)
            return {"success": True, "translated_text": translated}
        else:
            # 如果翻译服务不可用，返回原文
            return {"success": True, "translated_text": text}
            
    except Exception as e:
        logger.warning(f"Translate preview error: {e}")
        return {"success": False, "message": "翻译服务暂时不可用"}


# ---- Agent ----
@api_router.get("/agent/status")
async def agent_status(user: dict = Security(get_current_seller)):
    """坐席状态"""
    try:
        if agent_service:
            status = agent_service.get_status(user.get("sub", ""))
            return {"success": True, "status": status}
    except Exception:
        pass
    return {"success": True, "status": "online"}


@api_router.post("/agent/assign")
async def agent_assign_session(data: AgentAssignRequest, user: dict = Security(get_current_seller)):
    """分配会话给坐席"""
    try:
        if agent_service:
            agent_service.assign_session(data.session_id, data.agent_id)
            return {"success": True}
    except Exception:
        pass
    return {"success": False}


@api_router.get("/agent/sessions/{agent_id}")
async def agent_get_sessions(agent_id: str, user: dict = Security(get_current_seller)):
    """获取坐席的会话列表"""
    try:
        if agent_service:
            sessions = agent_service.get_agent_sessions(agent_id)
            return {"success": True, "sessions": sessions}
    except Exception:
        pass
    return {"success": True, "sessions": []}


# ---- Realtime ----
@api_router.get("/realtime/stats")
async def realtime_stats():
    """实时统计"""
    try:
        if realtime_server and hasattr(realtime_server, 'get_stats'):
            stats = realtime_server.get_stats()
            return {"success": True, "stats": stats}
    except Exception:
        pass
    return {"success": True, "stats": {"sessions": 0, "agents_online": 0}}


# ---- Internal Buyer Callbacks (HMAC-SHA256 protected) ----
def _verify_hmac_signature(timestamp: str, signature: str) -> bool:
    """HMAC-SHA256 签名验证（timestamp + 5分钟防重放）"""
    try:
        ts = int(timestamp)
        now = int(time.time())
        if abs(now - ts) > 300:
            return False
        msg = f"{timestamp}:{INTERNAL_API_SECRET}"
        expected = hmac.new(INTERNAL_API_SECRET.encode(), msg.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature, expected)
    except Exception:
        return False


@api_router.post("/internal/buyer-transfer")
async def internal_buyer_transfer(
    request: InternalBuyerTransferRequest,
    x_timestamp: str = Header(...), x_signature: str = Header(...),
):
    """买方回调：客户发起转人工请求（HMAC 保护）"""
    if not _verify_hmac_signature(x_timestamp, x_signature):
        return JSONResponse({"error": "Invalid signature"}, status_code=403)
    try:
        if session_mode:
            session_mode.set_mode(request.session_id, "waiting")
            session_mode.assign_session(request.session_id, request.customer_id)
        if agent_service:
            agent_service.notify_new_session(request.session_id, request.customer_id)
    except Exception:
        pass
    return {"success": True, "session_id": request.session_id}


@api_router.post("/internal/buyer-message")
async def internal_buyer_message(
    request: InternalBuyerMessageRequest,
    x_timestamp: str = Header(...), x_signature: str = Header(...),
):
    """买方回调：买方有新消息（HMAC 保护）"""
    if not _verify_hmac_signature(x_timestamp, x_signature):
        return JSONResponse({"error": "Invalid signature"}, status_code=403)
    try:
        if message_service:
            message_service.save_message(
                session_id=request.session_id, sender="buyer",
                content=request.message, message_type=request.message_type,
            )
    except Exception:
        pass
    return {"success": True}


@api_router.post("/internal/buyer-back-to-ai")
async def internal_buyer_back_to_ai(
    request: InternalBuyerBackToAiRequest,
    x_timestamp: str = Header(...), x_signature: str = Header(...),
):
    """买方回调：客户选择返回 AI（HMAC 保护）"""
    if not _verify_hmac_signature(x_timestamp, x_signature):
        return JSONResponse({"error": "Invalid signature"}, status_code=403)
    try:
        if session_mode:
            session_mode.set_mode(request.session_id, "ai")
        if realtime_server:
            realtime_server.notify_session_mode_changed(request.session_id, "ai")
    except Exception:
        pass
    return {"success": True}


# 在所有 /api 路由定义完成后再挂载（见上方 api_router 说明）
app.include_router(api_router)


# ============== 静态文件 & 页面路由 ==============
_BACKEND_DIR = Path(__file__).parent
_FRONTEND_DIR = _BACKEND_DIR.parent / "frontend"
# 买方系统 HTML 页面路径（用于 /customer 路由，由买方 FastAPI 提供）
_BUYER_ROOT = _BACKEND_DIR.parent.parent / "AI客服买方系统"
_BUYER_FRONTEND_DIR = _BUYER_ROOT / "frontend"


def _render_page(title: str, body: str = "") -> HTMLResponse:
    """通用页面渲染"""
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} - Ruitalk</title>
<style>
  body {{ font-family: 'Segoe UI', sans-serif; margin: 0; padding: 40px; background: #f5f5f5; color: #333; }}
  .container {{ max-width: 1200px; margin: 0 auto; background: white; border-radius: 8px; padding: 32px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
  h1 {{ color: #1976D2; border-bottom: 2px solid #1976D2; padding-bottom: 12px; }}
  .info {{ background: #E3F2FD; padding: 16px; border-radius: 4px; margin: 16px 0; }}
  .btn {{ display: inline-block; padding: 10px 24px; background: #1976D2; color: white; text-decoration: none; border-radius: 4px; margin: 4px; }}
  .btn:hover {{ background: #1565C0; }}
  nav {{ margin-bottom: 24px; }}
  nav a {{ margin-right: 16px; color: #1976D2; text-decoration: none; }}
</style>
</head>
<body>
<div class="container">
  <nav>
    <a href="/">首页</a>
    <a href="/home">控制台</a>
    <a href="/console">运营</a>
    <a href="/customer">客服</a>
    <a href="/admin/login">管理后台</a>
  </nav>
  <h1>{title}</h1>
  {body}
</div>
</body>
</html>"""
    return HTMLResponse(html)


@app.get("/")
async def index():
    """首页：卖方运营管理门户（frontend/home.html）；文件缺失时回退骨架页。"""
    home_path = _FRONTEND_DIR / "home.html"
    if home_path.is_file():
        resp = FileResponse(home_path, media_type="text/html; charset=utf-8")
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
        return resp
    body = """
  <div class="info">
    <h2>欢迎使用 Ruitalk 金牌客服系统</h2>
    <p>跨境电商智能客服解决方案</p>
  </div>
  <h3>快速入口</h3>
  <a class="btn" href="/home">运营控制台</a>
  <a class="btn" href="/console">客服工作台</a>
  <a class="btn" href="/customer">客户聊天</a>
  <a class="btn" href="/admin/login">管理后台</a>
  <h3>系统状态</h3>
  <div id="status" class="info">正在检查...</div>
  <script>
    fetch('/api/status').then(r => r.json()).then(d => {
      document.getElementById('status').innerHTML =
        'Neo4j: ' + (d.neo4j ? '✓' : '✗') + ' | ' +
        'GraphRAG: ' + (d.graphrag ? '✓' : '✗') + ' | ' +
        '服务: ' + d.service;
    });
  </script>"""
    return _render_page("首页", body)


@app.get("/home")
async def home():
    """运营控制台首页"""
    home_path = _FRONTEND_DIR / "home.html"
    if home_path.is_file():
        resp = FileResponse(home_path, media_type="text/html; charset=utf-8")
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
        return resp
    return _render_page("运营控制台", "<div class='info'><p>运营控制台</p></div>")


@app.get("/console")
async def console():
    """客服工作台"""
    console_path = _FRONTEND_DIR / "console.html"
    if console_path.is_file():
        return FileResponse(console_path, media_type="text/html; charset=utf-8")
    return _render_page("客服工作台", "<div class='info'><p>客服工作台</p></div>")


@app.get("/console/{page}")
async def console_page(page: str):
    """客服子页面"""
    return _render_page(f"控制台 - {page}", f"<div class='info'><p>{page} 页面</p></div>")


@app.get("/customer")
async def customer_page(request: Request):
    """客户聊天页：直接返回买方系统的 chat.html（无需 Flask 代理）。"""
    # 优先使用买方系统的 chat.html
    chat_path = _BUYER_FRONTEND_DIR / "customer" / "chat.html"
    if chat_path.is_file():
        return FileResponse(chat_path, media_type="text/html; charset=utf-8")
    # 回退：尝试本地 frontend/customer/chat.html
    local_path = _FRONTEND_DIR / "customer" / "chat.html"
    if local_path.is_file():
        return FileResponse(local_path, media_type="text/html; charset=utf-8")
    return _render_page(
        "客户聊天",
        "<div class='info'><p>聊天页面未找到，请确认 AI客服买方系统/frontend/customer/chat.html 存在。</p></div>",
    )


@app.get("/entry")
async def entry_page():
    """入口页面"""
    return RedirectResponse(url="/")


@app.get("/chat")
async def chat_page():
    """聊天页面"""
    return RedirectResponse(url="/customer")


@app.get("/merchant-auth")
@app.get("/merchant-auth.html")
async def merchant_auth_page():
    """商户注册/登录页（必须先登录再访问门户首页）"""
    path = _FRONTEND_DIR / "merchant-auth.html"
    if path.is_file():
        resp = FileResponse(path, media_type="text/html; charset=utf-8")
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
        return resp
    return RedirectResponse(url="/admin/login")


@app.get("/admin/login.html")
@app.get("/admin/login")
async def admin_login_page():
    """管理员登录页"""
    path = _FRONTEND_DIR / "admin" / "login.html"
    if path.is_file():
        resp = FileResponse(path, media_type="text/html; charset=utf-8")
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
        return resp
    body = """
  <div class="info">
    <h3>管理员登录</h3>
    <form id="loginForm">
      <p><input type="text" id="username" placeholder="用户名" style="padding:8px;width:200px;border:1px solid #ccc;border-radius:4px"></p>
      <p><input type="password" id="password" placeholder="密码" style="padding:8px;width:200px;border:1px solid #ccc;border-radius:4px"></p>
      <p><button type="submit" class="btn">登录</button></p>
    </form>
    <div id="result" style="margin-top:12px;color:red"></div>
  </div>
  <script>
    document.getElementById('loginForm').onsubmit = async (e) => {
      e.preventDefault();
      const r = await fetch('/api/admin/login', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({username: document.getElementById('username').value, password: document.getElementById('password').value})
      }).then(r => r.json());
      if (r.success) {
        localStorage.setItem('token', r.access_token);
        window.location.href = '/home';
      } else {
        document.getElementById('result').textContent = r.message || '登录失败';
      }
    };
  </script>"""
    return _render_page("管理员登录", body)


@app.get("/admin/dashboard.html")
@app.get("/admin/dashboard")
async def admin_dashboard():
    """管理员仪表盘"""
    path = _FRONTEND_DIR / "admin" / "dashboard.html"
    if path.is_file():
        return FileResponse(path, media_type="text/html; charset=utf-8")
    return _render_page("管理后台仪表盘", "<div class='info'><p>管理后台仪表盘</p></div>")


@app.get("/admin/message-center.html")
@app.get("/admin/message-center")
async def admin_message_center():
    """消息中心"""
    path = _FRONTEND_DIR / "admin" / "message_center.html"
    if path.is_file():
        return FileResponse(path, media_type="text/html; charset=utf-8")
    return _render_page("消息中心", "<div class='info'><p>消息中心</p></div>")


@app.get("/admin/dashboard-overview.html")
@app.get("/admin/dashboard-overview")
async def admin_dashboard_overview():
    """数据看板 / 工具集成入口（与「客户档案检索」/dashboard 区分）"""
    path = _FRONTEND_DIR / "admin" / "dashboard_overview.html"
    if path.is_file():
        return FileResponse(path, media_type="text/html; charset=utf-8")
    return _render_page("数据看板", "<div class='info'><p>数据看板</p></div>")


@app.get("/admin/console.html")
async def admin_console_page():
    """管理控制台"""
    path = _FRONTEND_DIR / "admin" / "console.html"
    if path.is_file():
        return FileResponse(path, media_type="text/html; charset=utf-8")
    return _render_page("管理控制台", "<div class='info'><p>管理控制台</p></div>")


@app.get("/admin/agent_console.html")
@app.get("/admin/agent-console.html")
@app.get("/admin/agent_console")
@app.get("/admin/agent-console")
async def admin_agent_console():
    """坐席控制台"""
    path = _FRONTEND_DIR / "admin" / "agent_console.html"
    if path.is_file():
        return FileResponse(path, media_type="text/html; charset=utf-8")
    return _render_page("坐席控制台", "<div class='info'><p>坐席控制台</p></div>")


@app.get("/admin/customer-query")
async def admin_customer_query():
    """客户查询"""
    path = _FRONTEND_DIR / "admin" / "dashboard.html"
    if path.is_file():
        return FileResponse(path, media_type="text/html; charset=utf-8")
    return _render_page("客户查询", "<div class='info'><p>客户查询页面</p></div>")


@app.get("/admin/orders")
@app.get("/admin/orders.html")
async def admin_orders_page():
    """订单管理"""
    path = _FRONTEND_DIR / "admin" / "orders.html"
    if path.is_file():
        return FileResponse(path, media_type="text/html; charset=utf-8")
    return _render_page("订单管理", "<div class='info'><p>订单管理页面</p></div>")


@app.get("/admin/pre-sale-notes.html")
async def admin_pre_sale_notes():
    """售前备注"""
    path = _FRONTEND_DIR / "admin" / "pre-sale-notes.html"
    if path.is_file():
        return FileResponse(path, media_type="text/html; charset=utf-8")
    return _render_page("售前备注", "<div class='info'><p>售前备注管理</p></div>")


@app.get("/admin/evaluation.html")
async def admin_evaluation():
    """评价管理"""
    path = _FRONTEND_DIR / "admin" / "evaluation.html"
    if path.is_file():
        return FileResponse(path, media_type="text/html; charset=utf-8")
    return _render_page("评价管理", "<div class='info'><p>评价管理页面</p></div>")


@app.get("/admin/after-sales.html")
async def admin_after_sales():
    """售后管理"""
    path = _FRONTEND_DIR / "admin" / "after-sales.html"
    if path.is_file():
        return FileResponse(path, media_type="text/html; charset=utf-8")
    return _render_page("售后管理", "<div class='info'><p>售后管理页面</p></div>")


@app.get("/admin/shop-manager.html")
async def admin_shop_manager():
    """店铺管理"""
    path = _FRONTEND_DIR / "admin" / "shop-manager.html"
    if path.is_file():
        return FileResponse(path, media_type="text/html; charset=utf-8")
    return _render_page("店铺管理", "<div class='info'><p>店铺管理页面</p></div>")


@app.get("/admin/audit-logs.html")
async def admin_audit_logs():
    """审计日志"""
    path = _FRONTEND_DIR / "admin" / "audit-logs.html"
    if path.is_file():
        return FileResponse(path, media_type="text/html; charset=utf-8")
    return _render_page("审计日志", "<div class='info'><p>审计日志页面</p></div>")


@app.get("/admin/logout")
async def admin_logout_page():
    """登出"""
    body = """<script>localStorage.removeItem('admin_access_token');localStorage.removeItem('admin_refresh_token'); window.location.href='/';</script>
  <div class="info"><p>已退出登录</p></div>"""
    return _render_page("登出", body)


@app.get("/agent-console")
async def agent_console():
    """坐席控制台"""
    path = _FRONTEND_DIR / "admin" / "agent_console.html"
    if path.is_file():
        return FileResponse(path, media_type="text/html; charset=utf-8")
    return _render_page("坐席控制台", "<div class='info'><p>坐席控制台</p></div>")


# ============== WebSocket 端点 ==============
@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    """WebSocket 实时通信端点"""
    if not _realtime_available or not realtime_server:
        await websocket.close(code=1011, reason="Realtime server unavailable")
        return
    await realtime_server.handle_websocket(websocket, session_id)


@app.websocket("/ws/agent/{agent_id}")
async def websocket_agent_endpoint(websocket: WebSocket, agent_id: str):
    """WebSocket 坐席端点"""
    if not _realtime_available or not realtime_server:
        await websocket.close(code=1011, reason="Realtime server unavailable")
        return
    await realtime_server.handle_agent_websocket(websocket, agent_id)


@app.get("/diagnose/")
@app.get("/diagnose")
async def diagnose_page():
    """系统诊断页面"""
    import os
    # 诊断页面位于项目根目录的 diagnose/ 文件夹
    _project_root = Path(__file__).parent.parent  # 卖方终端/
    _diagnose_dir = _project_root.parent / "diagnose"
    diagnose_path = _diagnose_dir / "index.html"
    if diagnose_path.is_file():
        return FileResponse(str(diagnose_path), media_type="text/html; charset=utf-8")
    return _render_page("系统诊断", "<div class='info'><p>诊断页面未找到</p></div>")


# ============== 全局异常处理 ==============
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """全局异常处理"""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"success": False, "error": "Internal server error", "detail": str(exc)},
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """统一 HTTP 异常处理，确保 401/403 返回 JSON 而非 HTML"""
    # 仅 API 路由返回 JSON
    if request.url.path.startswith("/api"):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "success": False,
                "error": exc.detail,
                "status_code": exc.status_code,
            },
            headers=getattr(exc, "headers", None) or {},
        )
    # 非 API 路由保持默认行为
    return JSONResponse(
        status_code=exc.status_code,
        content={"success": False, "error": exc.detail},
    )


# ============== 运行入口 ==============
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
