# -*- coding: utf-8 -*-
"""
配置管理 - 从统一配置加载配置
优先级（高→低）：
  1. 系统环境变量（最高，用于容器化/CI/CD）
  2. 项目根目录统一配置 .env
  3. 本地覆盖 backend/.env（可选，用于开发时的本地覆盖）

唯一配置入口: 项目根目录/.env
"""
import os
import hashlib
import hmac
import secrets
from pathlib import Path
from dotenv import load_dotenv

# ============== 配置路径 ==============
_SCRIPT_DIR = Path(__file__).parent
_PROJECT_ROOT = _SCRIPT_DIR.parent  # 卖方终端根目录
_ROOT_ENV_PATH = _PROJECT_ROOT.parent / ".env"  # d:\Ruitalk1\.env（唯一入口）
_LOCAL_ENV_PATH = _SCRIPT_DIR / ".env"  # backend/.env（旧位置，向后兼容）

# ============== 加载配置（按优先级，高→低）=============
# 1. 根目录 .env（唯一配置入口）
if _ROOT_ENV_PATH.exists():
    load_dotenv(_ROOT_ENV_PATH, override=False)
    _CONFIG_SOURCE = str(_ROOT_ENV_PATH)
elif False:  # 已废弃：.env.master 已删除，统一配置移至 d:\Ruitalk1\.env
    # 旧: load_dotenv(_UNIFIED_ENV_PATH, override=False)
    pass
else:
    _CONFIG_SOURCE = "env_vars"

# 3. 本地覆盖（可选，用于开发时的本地覆盖）
if _LOCAL_ENV_PATH.exists():
    load_dotenv(_LOCAL_ENV_PATH, override=True)

# Neo4j 配置
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")

# DeepSeek API 配置
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_API_URL = os.getenv("DEEPSEEK_API_URL", "https://api.deepseek.com/v1/chat/completions")

# GraphRAG 配置
GRAPHRAG_API_URL = os.getenv("GRAPHRAG_API_URL", "http://localhost:5050/query")

# 买方API地址（独立部署时为买方公网地址，如 https://buyer.yourcompany.com）
BUYER_API_HOST = os.getenv("BUYER_API_HOST", "http://127.0.0.1:8001")

# 服务端口（与 启动_调试.bat / 启动_生产环境.bat 一致，可在 .env 覆盖）
GOLD_CS_PORT = int(os.getenv("GOLD_CS_PORT", "5001"))
# 金牌客服 Flask 根地址（FastAPI 代理客户入口 / API 时用）
GOLD_CS_BASE_URL = os.getenv("GOLD_CS_BASE_URL", f"http://127.0.0.1:{GOLD_CS_PORT}")
GRAPHRAG_PROXY_PORT = int(os.getenv("GRAPHRAG_PROXY_PORT", "5050"))
FASTAPI_PORT = int(os.getenv("FASTAPI_PORT", "8000"))

# ============== 售后服务 API 配置 ==============
AFTER_SALES_LIST_API = os.getenv("AFTER_SALES_LIST_API", "")
AFTER_SALES_CREATE_API = os.getenv("AFTER_SALES_CREATE_API", "")
AFTER_SALES_DETAIL_API = os.getenv("AFTER_SALES_DETAIL_API", "")
AFTER_SALES_UPDATE_API = os.getenv("AFTER_SALES_UPDATE_API", "")
AFTER_SALES_STATUS_API = os.getenv("AFTER_SALES_STATUS_API", "")
AFTER_SALES_STATS_API = os.getenv("AFTER_SALES_STATS_API", "")

# ============== 售前处理 API 配置 ==============
PRESALE_LIST_API = os.getenv("PRESALE_LIST_API", "")
PRESALE_CREATE_API = os.getenv("PRESALE_CREATE_API", "")
PRESALE_UPDATE_API = os.getenv("PRESALE_UPDATE_API", "")
PRESALE_ORDER_API = os.getenv("PRESALE_ORDER_API", "")

# ============== 客户评价 API 配置 ==============
EVALUATION_LIST_API = os.getenv("EVALUATION_LIST_API", "")
EVALUATION_DETAIL_API = os.getenv("EVALUATION_DETAIL_API", "")
EVALUATION_REPLY_API = os.getenv("EVALUATION_REPLY_API", "")
EVALUATION_STATS_API = os.getenv("EVALUATION_STATS_API", "")

# ============== 物流渠道配置 ==============
LOGISTICS_API = os.getenv("LOGISTICS_API", "")
RETURN_LABEL_API = os.getenv("RETURN_LABEL_API", "")

# ============== 支付/退款渠道配置 ==============
REFUND_API = os.getenv("REFUND_API", "")
PAYMENT_QUERY_API = os.getenv("PAYMENT_QUERY_API", "")

# ============== 跨境电商平台 API 配置 ==============
# TikTok Shop
TIKTOK_API_URL = os.getenv("TIKTOK_API_URL", "")
TIKTOK_API_KEY = os.getenv("TIKTOK_API_KEY", "")
TIKTOK_API_SECRET = os.getenv("TIKTOK_API_SECRET", "")
TIKTOK_ACCESS_TOKEN = os.getenv("TIKTOK_ACCESS_TOKEN", "")
TIKTOK_SHOP_ID = os.getenv("TIKTOK_SHOP_ID", "")

# Shopee
SHOPEE_API_URL = os.getenv("SHOPEE_API_URL", "")
SHOPEE_API_KEY = os.getenv("SHOPEE_API_KEY", "")
SHOPEE_API_SECRET = os.getenv("SHOPEE_API_SECRET", "")
SHOPEE_ACCESS_TOKEN = os.getenv("SHOPEE_ACCESS_TOKEN", "")
SHOPEE_SHOP_ID = os.getenv("SHOPEE_SHOP_ID", "")

# Lazada
LAZADA_API_URL = os.getenv("LAZADA_API_URL", "")
LAZADA_API_KEY = os.getenv("LAZADA_API_KEY", "")
LAZADA_API_SECRET = os.getenv("LAZADA_API_SECRET", "")
LAZADA_ACCESS_TOKEN = os.getenv("LAZADA_ACCESS_TOKEN", "")
LAZADA_SHOP_ID = os.getenv("LAZADA_SHOP_ID", "")

# Amazon
AMAZON_API_URL = os.getenv("AMAZON_API_URL", "")
AMAZON_API_KEY = os.getenv("AMAZON_API_KEY", "")
AMAZON_API_SECRET = os.getenv("AMAZON_API_SECRET", "")
AMAZON_ACCESS_TOKEN = os.getenv("AMAZON_ACCESS_TOKEN", "")
AMAZON_SELLER_ID = os.getenv("AMAZON_SELLER_ID", "")
AMAZON_MARKETPLACE_ID = os.getenv("AMAZON_MARKETPLACE_ID", "")

# AliExpress (速卖通)
ALIEXPRESS_API_URL = os.getenv("ALIEXPRESS_API_URL", "")
ALIEXPRESS_API_KEY = os.getenv("ALIEXPRESS_API_KEY", "")
ALIEXPRESS_API_SECRET = os.getenv("ALIEXPRESS_API_SECRET", "")
ALIEXPRESS_ACCESS_TOKEN = os.getenv("ALIEXPRESS_ACCESS_TOKEN", "")
ALIEXPRESS_APP_ID = os.getenv("ALIEXPRESS_APP_ID", "")

# eBay
EBAY_API_URL = os.getenv("EBAY_API_URL", "")
EBAY_API_KEY = os.getenv("EBAY_API_KEY", "")
EBAY_API_SECRET = os.getenv("EBAY_API_SECRET", "")
EBAY_ACCESS_TOKEN = os.getenv("EBAY_ACCESS_TOKEN", "")
EBAY_SELLER_ID = os.getenv("EBAY_SELLER_ID", "")

# Shopify
SHOPIFY_API_URL = os.getenv("SHOPIFY_API_URL", "")
SHOPIFY_API_KEY = os.getenv("SHOPIFY_API_KEY", "")
SHOPIFY_API_SECRET = os.getenv("SHOPIFY_API_SECRET", "")
SHOPIFY_ACCESS_TOKEN = os.getenv("SHOPIFY_ACCESS_TOKEN", "")
SHOPIFY_SHOP_DOMAIN = os.getenv("SHOPIFY_SHOP_DOMAIN", "")

# ============== 物流渠道配置 ==============
# DHL
DHL_API_URL = os.getenv("DHL_API_URL", "")
DHL_API_KEY = os.getenv("DHL_API_KEY", "")
DHL_API_SECRET = os.getenv("DHL_API_SECRET", "")

# FedEx
FEDEX_API_URL = os.getenv("FEDEX_API_URL", "")
FEDEX_API_KEY = os.getenv("FEDEX_API_KEY", "")
FEDEX_API_SECRET = os.getenv("FEDEX_API_SECRET", "")

# UPS
UPS_API_URL = os.getenv("UPS_API_URL", "")
UPS_API_KEY = os.getenv("UPS_API_KEY", "")
UPS_API_SECRET = os.getenv("UPS_API_SECRET", "")

# 燕文物流
YANWEN_API_URL = os.getenv("YANWEN_API_URL", "")
YANWEN_API_KEY = os.getenv("YANWEN_API_KEY", "")
YANWEN_API_SECRET = os.getenv("YANWEN_API_SECRET", "")

# 4PX (递四方)
FPX_API_URL = os.getenv("FPX_API_URL", "")
FPX_API_KEY = os.getenv("FPX_API_KEY", "")
FPX_API_SECRET = os.getenv("FPX_API_SECRET", "")

# 系统配置
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "123456")
# 可选：设置后启用「运营」账号（用户名见 OPERATOR_USERNAME），密码与超级管理员不同，权限见 jwt_auth.get_current_super_admin 说明
OPERATOR_USERNAME = os.getenv("OPERATOR_USERNAME", "operator").strip() or "operator"
OPERATOR_PASSWORD = os.getenv("OPERATOR_PASSWORD", "").strip()

# ============== 统一 MySQL 数据库配置（卖方主库）==============
# 优先级: MYSQL_* > SHOP_MYSQL_*（SHOP_MYSQL_* 为旧版兼容别名）
_MYSQL_HOST = os.getenv("MYSQL_HOST") or os.getenv("SHOP_MYSQL_HOST") or "localhost"
_MYSQL_PORT = int(os.getenv("MYSQL_PORT") or os.getenv("SHOP_MYSQL_PORT") or "3306")
_MYSQL_USER = os.getenv("MYSQL_USER") or os.getenv("SHOP_MYSQL_USER") or "root"
_MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD") or os.getenv("SHOP_MYSQL_PASSWORD") or ""
_MYSQL_DATABASE = os.getenv("MYSQL_DATABASE") or os.getenv("SHOP_MYSQL_DATABASE") or "ruitalk"

MYSQL_HOST = _MYSQL_HOST
MYSQL_PORT = _MYSQL_PORT
MYSQL_USER = _MYSQL_USER
MYSQL_PASSWORD = _MYSQL_PASSWORD
MYSQL_DATABASE = _MYSQL_DATABASE

# 兼容旧变量名（供 shop_router 等旧代码使用）
SHOP_MYSQL_HOST = MYSQL_HOST
SHOP_MYSQL_PORT = MYSQL_PORT
SHOP_MYSQL_USER = MYSQL_USER
SHOP_MYSQL_PASSWORD = MYSQL_PASSWORD
SHOP_MYSQL_DATABASE = MYSQL_DATABASE
SHOP_USE_MYSQL = os.getenv("SHOP_USE_MYSQL", "false").lower() in ("1", "true", "yes")

# 是否强制禁用 SQLite 回退（生产必须为 false，生产时服务启动时 MySQL 不可用则报错）
USE_SQLITE_FALLBACK = os.getenv("USE_SQLITE_FALLBACK", "false").lower() in ("1", "true", "yes")

# ============== 买方系统 MySQL 数据库配置 ==============
BUYER_MYSQL_HOST = os.getenv("BUYER_MYSQL_HOST", "") or MYSQL_HOST
BUYER_MYSQL_PORT = int(os.getenv("BUYER_MYSQL_PORT", "") or str(MYSQL_PORT))
BUYER_MYSQL_USER = os.getenv("BUYER_MYSQL_USER", "") or MYSQL_USER
BUYER_MYSQL_PASSWORD = os.getenv("BUYER_MYSQL_PASSWORD", "") or MYSQL_PASSWORD
BUYER_MYSQL_DATABASE = os.getenv("BUYER_MYSQL_DATABASE", "") or "ruitalk_buyer"

# ============== MySQL 连接池配置（生产推荐）==============
MYSQL_POOL_SIZE = int(os.getenv("MYSQL_POOL_SIZE", "50"))
MYSQL_MAX_OVERFLOW = int(os.getenv("MYSQL_MAX_OVERFLOW", "20"))
MYSQL_POOL_TIMEOUT = int(os.getenv("MYSQL_POOL_TIMEOUT", "30"))
MYSQL_POOL_RECYCLE = int(os.getenv("MYSQL_POOL_RECYCLE", "3600"))
MYSQL_CONNECT_TIMEOUT = int(os.getenv("MYSQL_CONNECT_TIMEOUT", "10"))
MYSQL_READ_TIMEOUT = int(os.getenv("MYSQL_READ_TIMEOUT", "30"))
MYSQL_WRITE_TIMEOUT = int(os.getenv("MYSQL_WRITE_TIMEOUT", "30"))

# ============== Redis 分布式锁配置 ==============
ENABLE_DISTRIBUTED_LOCK = os.getenv("ENABLE_DISTRIBUTED_LOCK", "false").lower() not in ("0", "false", "no", "")
LOCK_TIMEOUT = int(os.getenv("LOCK_TIMEOUT", "10"))  # 锁默认超时（秒）
LOCK_BLOCKING_TIMEOUT = int(os.getenv("LOCK_BLOCKING_TIMEOUT", "5"))  # 阻塞获取锁超时（秒）

# ============== Redis 配置 ==============
REDIS_HOST = os.getenv("REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("REDIS_DB", "0"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")
# ⚠️ 生产默认 false（必须连接真实 Redis/Memurai）。开发调试可设为 true。
REDIS_USE_FAKE = os.getenv("REDIS_USE_FAKE", "0").lower() not in ("0", "false", "no", "")
REDIS_MAX_CONNECTIONS = int(os.getenv("REDIS_MAX_CONNECTIONS", "50"))

# ============== 1688 货源平台配置 ==============
ALIBABA_API_URL = os.getenv("ALIBABA_API_URL", "https://gw.open.1688.com/openapi/")
ALIBABA_APP_KEY = os.getenv("ALIBABA_APP_KEY", "")
ALIBABA_APP_SECRET = os.getenv("ALIBABA_APP_SECRET", "")

# ============== 汇率服务配置 ==============
EXCHANGE_RATE_API_URL = os.getenv("EXCHANGE_RATE_API_URL", "https://api.exchangerate-api.com/v4/latest/")
EXCHANGE_RATE_API_KEY = os.getenv("EXCHANGE_RATE_API_KEY", "")

# ============== 商品采集配置 ==============
SCRAPER_API_URL = os.getenv("SCRAPER_API_URL", "")
SCRAPER_API_KEY = os.getenv("SCRAPER_API_KEY", "")

# ============== CORS 配置（生产环境必须，禁止 *）==============
# 从环境变量读取，允许的域名列表，逗号分隔
_ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173")
ALLOWED_ORIGINS = [origin.strip() for origin in _ALLOWED_ORIGINS.split(",") if origin.strip()]

# ============== JWT 认证配置 ==============
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "dev-jwt-secret-change-in-production-please")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "480"))  # 8小时
JWT_REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("JWT_REFRESH_TOKEN_EXPIRE_DAYS", "7"))


# ============== 密码安全配置 ==============
_ADMIN_PASSWORD_SALT = None  # 延迟初始化，读取一次


def _get_password_salt() -> str:
    """获取密码哈希盐（只读一次，避免重复读取环境变量）"""
    global _ADMIN_PASSWORD_SALT
    if _ADMIN_PASSWORD_SALT is None:
        _ADMIN_PASSWORD_SALT = os.getenv("ADMIN_PASSWORD_SALT", "")
        if not _ADMIN_PASSWORD_SALT:
            _ADMIN_PASSWORD_SALT = "ruitalk-dev-salt-2026"
            print("[WARNING] ADMIN_PASSWORD_SALT 未设置，密码哈希使用默认盐！生产环境请设置环境变量。")
    return _ADMIN_PASSWORD_SALT


def _hash_password(password: str, salt: str = "") -> str:
    """
    PBKDF2-SHA256 密码哈希（防止彩虹表攻击）。
    生产环境必须设置 ADMIN_PASSWORD_SALT 环境变量。
    """
    if not salt:
        salt = _get_password_salt()
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        100000  # 迭代次数，防止暴力破解
    ).hex()


def verify_admin_password(input_password: str, stored_hash: str) -> bool:
    """验证管理员密码（支持明文兼容和哈希验证）"""
    if not stored_hash:
        return False
    # 如果存储的是明文密码（首次启动/旧格式），自动升级为哈希
    if stored_hash == input_password:
        return True
    # PBKDF2 哈希验证
    try:
        salt = _get_password_salt()
        computed = hashlib.pbkdf2_hmac(
            "sha256",
            input_password.encode("utf-8"),
            salt.encode("utf-8"),
            100000
        ).hex()
        return hmac.compare_digest(computed, stored_hash)
    except Exception:
        return False


def _generate_secure_password() -> str:
    """生成强随机密码（16位）"""
    import string
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(16))


# ============== JWT 内部通信密钥 ==============
INTERNAL_API_SECRET = os.getenv("INTERNAL_API_SECRET", "buyer-seller-internal-secret-2026")
INTERNAL_API_HEADER = "X-Internal-Token"

# ============== 运行环境与生产安全门禁 ==============
# RUITALK_ENV=production 时，卖方服务拒绝使用下列「开发默认」敏感配置启动（见 enforce_production_security_or_exit）
RUITALK_ENV = os.getenv("RUITALK_ENV", os.getenv("ENV", "development")).strip().lower()

_DEV_SECRET_KEY = "dev-secret-key-change-in-production"
_WEAK_JWT_VALUES = frozenset(
    {
        "dev-jwt-secret-change-in-production-please",
        "jwt-secret-key-change-in-production-please-change-it",
    }
)
_DEV_ADMIN_PASSWORD = "123456"
_DEV_INTERNAL_SECRET = "buyer-seller-internal-secret-2026"
_DEV_ADMIN_SALT = "ruitalk-dev-salt-2026"


def enforce_production_security_or_exit() -> None:
    """
    生产候选 / 上线环境必须设置强密钥。
    设置 RUITALK_ENV=production（或 ENV=production）且仍存在开发默认值时，进程退出。
    """
    if RUITALK_ENV not in ("production", "prod"):
        return
    import sys

    fatal: list[str] = []
    if SECRET_KEY == _DEV_SECRET_KEY:
        fatal.append("SECRET_KEY")
    if JWT_SECRET_KEY in _WEAK_JWT_VALUES:
        fatal.append("JWT_SECRET_KEY")
    if ADMIN_PASSWORD == _DEV_ADMIN_PASSWORD:
        fatal.append("ADMIN_PASSWORD")
    if INTERNAL_API_SECRET == _DEV_INTERNAL_SECRET:
        fatal.append("INTERNAL_API_SECRET")
    salt = os.getenv("ADMIN_PASSWORD_SALT", "").strip()
    if not salt or salt == _DEV_ADMIN_SALT:
        fatal.append("ADMIN_PASSWORD_SALT")
    raw_origins = os.getenv("ALLOWED_ORIGINS", "")
    if "*" in raw_origins:
        fatal.append("ALLOWED_ORIGINS（禁止 *）")
    if fatal:
        print(
            "[FATAL] RUITALK_ENV=production 但存在不安全默认配置: "
            + ", ".join(fatal)
            + "\n请使用环境变量设置随机 SECRET_KEY、JWT_SECRET_KEY、ADMIN_PASSWORD、ADMIN_PASSWORD_SALT、INTERNAL_API_SECRET，"
            "并收紧 ALLOWED_ORIGINS。\n"
            "生成随机 hex（任选其一）：openssl rand -hex 32\n"
            "PowerShell: "
            "[Convert]::ToHexString([System.Security.Cryptography.RandomNumberGenerator]::GetBytes(32))\n"
        )
        sys.exit(1)


def warn_if_insecure_defaults_in_development() -> None:
    """开发模式下提示尚未轮换的敏感项（不中断启动）。"""
    if RUITALK_ENV in ("production", "prod"):
        return
    hints: list[str] = []
    if SECRET_KEY == _DEV_SECRET_KEY:
        hints.append("SECRET_KEY")
    if JWT_SECRET_KEY in _WEAK_JWT_VALUES:
        hints.append("JWT_SECRET_KEY")
    if ADMIN_PASSWORD == _DEV_ADMIN_PASSWORD:
        hints.append("ADMIN_PASSWORD")
    if INTERNAL_API_SECRET == _DEV_INTERNAL_SECRET:
        hints.append("INTERNAL_API_SECRET")
    salt = os.getenv("ADMIN_PASSWORD_SALT", "").strip()
    if not salt or salt == _DEV_ADMIN_SALT:
        hints.append("ADMIN_PASSWORD_SALT")
    if hints:
        print(
            "[SECURITY] 仍为开发默认敏感项: "
            + ", ".join(hints)
            + " — 交付前请在根目录 .env 替换；生产环境设置 RUITALK_ENV=production 将强制拒绝弱配置。"
        )
