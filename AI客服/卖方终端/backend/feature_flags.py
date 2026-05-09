# -*- coding: utf-8 -*-
"""
Feature Flag 金丝雀 & A/B 测试框架

支持:
- 布尔开关（开/关）
- 百分比灰度（Canary Release）
- 用户/租户白名单
- 多维度配置（平台、地区、时间窗口）
- 实时变更（无需重启）
- 与 Redis 集成，支持分布式

使用方式:
    from feature_flags import feature_is_enabled, get_feature_config

    if feature_is_enabled("new_ai_model", user_id="user_123"):
        response = new_ai_service.generate(...)
    else:
        response = old_ai_service.generate(...)
"""
import os
import time
import json
import hashlib
import logging
from typing import Optional, Dict, Any, List, Callable
from dataclasses import dataclass, field, asdict
from enum import Enum
from datetime import datetime, timezone
import threading

logger = logging.getLogger(__name__)

# ============== 配置 ==============

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB_FLAG = int(os.getenv("REDIS_DB_FLAG", "1"))  # 用 DB 1 存放 feature flags
REDIS_KEY_PREFIX = "ff:"
FLAG_CONFIG_TTL = 60  # 配置文件缓存秒数


# ============== 数据模型 ==============

class RolloutStrategy(str, Enum):
    """灰度策略"""
    ALL_OFF = "all_off"     # 全部关闭
    ALL_ON = "all_on"       # 全部开启
    PERCENTAGE = "percentage"  # 百分比
    USER_LIST = "user_list"    # 用户白名单
    TENANT_LIST = "tenant_list"  # 租户白名单
    USER_HASH = "user_hash"  # 基于用户 ID hash 的确定性分配


@dataclass
class FeatureConfig:
    """Feature Flag 配置"""
    name: str
    enabled: bool
    rollout_strategy: RolloutStrategy = RolloutStrategy.ALL_OFF
    rollout_percentage: int = 0  # 0-100
    user_ids: List[str] = field(default_factory=list)
    tenant_ids: List[str] = field(default_factory=list)
    description: str = ""
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    # 时间窗口
    start_time: Optional[str] = None  # ISO 8601
    end_time: Optional[str] = None
    # 多维度条件
    platforms: List[str] = field(default_factory=list)  # ["web", "ios", "android"]
    countries: List[str] = field(default_factory=list)  # ["CN", "US", "ALL"]
    rollout_groups: List[str] = field(default_factory=list)  # ["beta", "premium"]
    updated_at: str = ""


# ============== 默认 Feature Flags ==============

DEFAULT_FLAGS: Dict[str, FeatureConfig] = {
    "new_ai_model": FeatureConfig(
        name="new_ai_model",
        enabled=False,
        rollout_strategy=RolloutStrategy.PERCENTAGE,
        rollout_percentage=10,
        description="新版 DeepSeek 模型（更准确但响应稍慢）",
        tags=["ai", "experiment"],
    ),
    "canary_seller_api": FeatureConfig(
        name="canary_seller_api",
        enabled=True,
        rollout_strategy=RolloutStrategy.PERCENTAGE,
        rollout_percentage=5,
        description="新版本 Seller API（Canary 5%）",
        tags=["api", "canary"],
    ),
    "multi_language_ai": FeatureConfig(
        name="multi_language_ai",
        enabled=True,
        rollout_strategy=RolloutStrategy.ALL_ON,
        description="多语言 AI 自动回复",
        tags=["ai", "i18n"],
    ),
    "realtime_typing_indicator": FeatureConfig(
        name="realtime_typing_indicator",
        enabled=True,
        rollout_strategy=RolloutStrategy.USER_LIST,
        user_ids=[],  # 可通过 admin API 动态添加
        description="实时打字状态指示器",
        tags=["ux", "realtime"],
    ),
    "graphrag_knowledge_base": FeatureConfig(
        name="graphrag_knowledge_base",
        enabled=False,
        rollout_strategy=RolloutStrategy.TENANT_LIST,
        tenant_ids=[],
        description="GraphRAG 知识库增强搜索",
        tags=["ai", "knowledge", "beta"],
    ),
    "rate_limit_lua_script": FeatureConfig(
        name="rate_limit_lua_script",
        enabled=True,
        rollout_strategy=RolloutStrategy.ALL_ON,
        description="Redis Lua 原子限流脚本",
        tags=["infra", "performance"],
    ),
    "structured_logging": FeatureConfig(
        name="structured_logging",
        enabled=True,
        rollout_strategy=RolloutStrategy.ALL_ON,
        description="结构化 JSON 日志",
        tags=["infra", "observability"],
    ),
    "dark_mode": FeatureConfig(
        name="dark_mode",
        enabled=False,
        rollout_strategy=RolloutStrategy.PERCENTAGE,
        rollout_percentage=30,
        description="深色模式 UI",
        tags=["ux", "experiment"],
    ),
    "logistics_tracking": FeatureConfig(
        name="logistics_tracking",
        enabled=True,
        rollout_strategy=RolloutStrategy.PLATFORM_LIST,
        platforms=["web"],
        description="物流轨迹追踪",
        tags=["feature", "logistics"],
    ),
    "ai_sentiment_analysis": FeatureConfig(
        name="ai_sentiment_analysis",
        enabled=False,
        rollout_strategy=RolloutStrategy.PERCENTAGE,
        rollout_percentage=20,
        description="AI 情感分析（自动识别客户情绪）",
        tags=["ai", "experiment"],
        rollout_groups=["premium"],
    ),
}


# ============== Feature Flag 服务 ==============

class FeatureFlagService:
    """
    Feature Flag 服务（线程安全）

    支持:
    - Redis 集中存储（生产）
    - 内存缓存（Redis 不可用时降级）
    - 百分比灰度（一致性 hash，保证同一用户每次命中相同）
    """

    def __init__(self, redis_client=None):
        self._redis = redis_client
        self._memory_cache: Dict[str, tuple] = {}  # key -> (config, expires_at)
        self._lock = threading.RLock()
        self._redis_available = redis_client is not None

    def _get_redis(self):
        if not self._redis:
            try:
                import redis
                self._redis = redis.Redis(
                    host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB_FLAG,
                    decode_responses=True, socket_timeout=2,
                )
                self._redis.ping()
                self._redis_available = True
            except Exception:
                self._redis_available = False
                logger.warning("Redis 不可用，Feature Flag 使用内存缓存")
        return self._redis if self._redis_available else None

    def _redis_key(self, name: str) -> str:
        return f"{REDIS_KEY_PREFIX}{name}"

    def _is_cache_valid(self, name: str) -> bool:
        if name not in self._memory_cache:
            return False
        _, expires = self._memory_cache[name]
        return time.time() < expires

    def get_config(self, name: str) -> FeatureConfig:
        """获取 Feature Flag 配置（Redis → 内存 → 默认）"""
        if self._is_cache_valid(name):
            return self._memory_cache[name][0]

        r = self._get_redis()
        if r:
            raw = r.get(self._redis_key(name))
            if raw:
                data = json.loads(raw)
                cfg = FeatureConfig(**data)
                with self._lock:
                    self._memory_cache[name] = (cfg, time.time() + FLAG_CONFIG_TTL)
                return cfg

        # 回退到默认
        default = DEFAULT_FLAGS.get(name)
        if default:
            return default

        # Flag 不存在 → 默认关闭
        return FeatureConfig(name=name, enabled=False)

    def is_enabled(
        self,
        name: str,
        user_id: str = "",
        tenant_id: str = "",
        platform: str = "",
        country: str = "",
        group: str = "",
    ) -> bool:
        """
        判断 Feature Flag 是否开启

        所有维度必须同时满足（AND 逻辑）
        """
        cfg = self.get_config(name)

        # 1. 全局开关
        if not cfg.enabled:
            return False

        # 2. 时间窗口
        now = datetime.now(timezone.utc)
        if cfg.start_time:
            start = datetime.fromisoformat(cfg.start_time.replace("Z", "+00:00"))
            if now < start:
                return False
        if cfg.end_time:
            end = datetime.fromisoformat(cfg.end_time.replace("Z", "+00:00"))
            if now > end:
                return False

        # 3. 用户/租户白名单
        if user_id and cfg.user_ids and user_id in cfg.user_ids:
            return True
        if tenant_id and cfg.tenant_ids and tenant_id in cfg.tenant_ids:
            return True

        # 4. 平台限制
        if cfg.platforms and platform and platform not in cfg.platforms:
            return False

        # 5. 地区限制
        if cfg.countries and country and country not in cfg.countries and "ALL" not in cfg.countries:
            return False

        # 6. 组限制
        if cfg.rollout_groups and group and group not in cfg.rollout_groups:
            return False

        # 7. 灰度策略
        return self._check_rollout(cfg, user_id, tenant_id)

    def _check_rollout(
        self,
        cfg: FeatureConfig,
        user_id: str,
        tenant_id: str,
    ) -> bool:
        """检查灰度策略"""
        if cfg.rollout_strategy == RolloutStrategy.ALL_ON:
            return True
        if cfg.rollout_strategy == RolloutStrategy.ALL_OFF:
            return False

        if cfg.rollout_strategy == RolloutStrategy.PERCENTAGE:
            # 基于 hash 的确定性百分比（同一用户始终命中同一决策）
            identifier = tenant_id or user_id
            if not identifier:
                return False
            hash_input = f"{cfg.name}:{identifier}"
            hash_val = int(hashlib.md5(hash_input.encode()).hexdigest(), 16)
            bucket = (hash_val % 100) + 1
            return bucket <= cfg.rollout_percentage

        if cfg.rollout_strategy == RolloutStrategy.USER_LIST:
            return bool(user_id and cfg.user_ids and user_id in cfg.user_ids)

        if cfg.rollout_strategy == RolloutStrategy.TENANT_LIST:
            return bool(tenant_id and cfg.tenant_ids and tenant_id in cfg.tenant_ids)

        if cfg.rollout_strategy == RolloutStrategy.USER_HASH:
            identifier = tenant_id or user_id
            if not identifier:
                return False
            hash_val = int(hashlib.md5(f"{cfg.name}:{identifier}".encode()).hexdigest(), 16)
            return hash_val % 2 == 0

        return False

    # ---- 管理 API ----

    def set_flag(self, name: str, config: FeatureConfig) -> bool:
        """设置/更新 Feature Flag"""
        r = self._get_redis()
        key = self._redis_key(name)

        data = json.dumps(asdict(config), ensure_ascii=False, default=str)

        if r:
            try:
                r.set(key, data)
                r.expire(key, 86400)  # 24h TTL
            except Exception as e:
                logger.error(f"Redis set flag failed: {e}")
                return False

        with self._lock:
            self._memory_cache[name] = (config, time.time() + FLAG_CONFIG_TTL)

        logger.info(f"Feature Flag updated: {name}, enabled={config.enabled}")
        return True

    def add_user_to_whitelist(self, flag_name: str, user_id: str) -> bool:
        """将用户添加到白名单"""
        cfg = self.get_config(flag_name)
        if user_id not in cfg.user_ids:
            cfg.user_ids = cfg.user_ids + [user_id]
            return self.set_flag(flag_name, cfg)
        return True

    def remove_user_from_whitelist(self, flag_name: str, user_id: str) -> bool:
        """从白名单移除用户"""
        cfg = self.get_config(flag_name)
        cfg.user_ids = [u for u in cfg.user_ids if u != user_id]
        return self.set_flag(flag_name, cfg)

    def list_flags(self) -> List[FeatureConfig]:
        """列出所有 Feature Flags"""
        r = self._get_redis()
        if r:
            keys = r.keys(f"{REDIS_KEY_PREFIX}*")
            flags = []
            for key in keys:
                raw = r.get(key)
                if raw:
                    flags.append(FeatureConfig(**json.loads(raw)))
            return flags
        return list(DEFAULT_FLAGS.values())

    def evaluate_all(self, **context) -> Dict[str, bool]:
        """评估所有 flag（用于前端/监控）"""
        all_names = list(DEFAULT_FLAGS.keys())
        if self._get_redis():
            r = self._get_redis()
            keys = r.keys(f"{REDIS_KEY_PREFIX}*")
            for key in keys:
                name = key[len(REDIS_KEY_PREFIX):]
                if name not in all_names:
                    all_names.append(name)

        return {
            name: self.is_enabled(name, **context)
            for name in all_names
        }

    def get_metadata(self, name: str) -> Dict[str, Any]:
        """获取 flag 元数据（用于管理后台）"""
        cfg = self.get_config(name)
        return {
            "name": cfg.name,
            "enabled": cfg.enabled,
            "strategy": cfg.rollout_strategy.value,
            "percentage": cfg.rollout_percentage,
            "user_count": len(cfg.user_ids),
            "tenant_count": len(cfg.tenant_ids),
            "tags": cfg.tags,
            "description": cfg.description,
        }


# ============== 全局单例 ==============

_flag_service: Optional[FeatureFlagService] = None


def get_flag_service(redis_client=None) -> FeatureFlagService:
    global _flag_service
    if _flag_service is None:
        _flag_service = FeatureFlagService(redis_client)
    return _flag_service


def feature_is_enabled(name: str, **context) -> bool:
    """快捷函数：判断 flag 是否开启"""
    return get_flag_service().is_enabled(name, **context)


def get_feature_config(name: str) -> FeatureConfig:
    """快捷函数：获取 flag 配置"""
    return get_flag_service().get_config(name)


# ============== FastAPI 集成 ==============

async def flag_middleware(request: Request, call_next: Callable):
    """FastAPI 中间件：将 flag 评估结果注入请求状态"""
    service = get_flag_service()
    ctx = {
        "user_id": getattr(request.state, "user_id", ""),
        "tenant_id": getattr(request.state, "tenant_id", ""),
    }
    flags = service.evaluate_all(**ctx)
    request.state.feature_flags = flags
    response = await call_next(request)
    response.headers["X-Feature-Flags"] = ",".join(
        k for k, v in flags.items() if v
    )
    return response
