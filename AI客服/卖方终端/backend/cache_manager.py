# -*- coding: utf-8 -*-
"""
Redis 缓存模块 - 用于高并发下的数据缓存
减少对 MySQL 的直接压力
"""
import json
import time
import logging
from typing import Optional, Any

logger = logging.getLogger(__name__)

_cache_client = None
_cache_enabled = False


def _init_cache():
    """初始化缓存连接"""
    global _cache_client, _cache_enabled
    
    if _cache_client is not None:
        return
    
    try:
        from config import REDIS_USE_FAKE, ENABLE_DISTRIBUTED_LOCK
        
        if not ENABLE_DISTRIBUTED_LOCK:
            logger.info("[Cache] ENABLE_DISTRIBUTED_LOCK=false，缓存禁用")
            return
        
        if REDIS_USE_FAKE:
            try:
                import fakeredis
                _cache_client = fakeredis.FakeRedis(decode_responses=True)
                _cache_enabled = True
                logger.info("[Cache] 使用 fakeredis（开发模式）")
            except ImportError:
                logger.warning("[Cache] fakeredis 未安装")
        else:
            try:
                import redis
                from config import REDIS_HOST, REDIS_PORT, REDIS_DB, REDIS_PASSWORD
                _cache_client = redis.Redis(
                    host=REDIS_HOST,
                    port=REDIS_PORT,
                    db=REDIS_DB,
                    password=REDIS_PASSWORD or None,
                    decode_responses=True,
                    socket_connect_timeout=5,
                )
                _cache_client.ping()
                _cache_enabled = True
                logger.info(f"[Cache] Redis 连接成功")
            except Exception as e:
                logger.warning(f"[Cache] Redis 连接失败: {e}")
    except ImportError:
        logger.warning("[Cache] config 模块导入失败")


class CacheManager:
    """缓存管理器"""
    
    DEFAULT_TTL = 300  # 默认5分钟
    
    @classmethod
    def get(cls, key: str) -> Optional[Any]:
        """获取缓存"""
        if _cache_client is None:
            _init_cache()
        
        if not _cache_enabled or _cache_client is None:
            return None
        
        try:
            value = _cache_client.get(f"cache:{key}")
            if value:
                return json.loads(value)
        except Exception as e:
            logger.warning(f"[Cache] 获取失败: {e}")
        return None
    
    @classmethod
    def set(cls, key: str, value: Any, ttl: int = None) -> bool:
        """设置缓存"""
        if _cache_client is None:
            _init_cache()
        
        if not _cache_enabled or _cache_client is None:
            return False
        
        ttl = ttl or cls.DEFAULT_TTL
        
        try:
            _cache_client.setex(f"cache:{key}", ttl, json.dumps(value, ensure_ascii=False))
            return True
        except Exception as e:
            logger.warning(f"[Cache] 设置失败: {e}")
            return False
    
    @classmethod
    def delete(cls, key: str) -> bool:
        """删除缓存"""
        if _cache_client is None:
            _init_cache()
        
        if not _cache_enabled or _cache_client is None:
            return False
        
        try:
            _cache_client.delete(f"cache:{key}")
            return True
        except Exception:
            return False
    
    @classmethod
    def get_or_set(cls, key: str, factory, ttl: int = None) -> Any:
        """获取缓存，不存在则调用 factory 生成"""
        cached = cls.get(key)
        if cached is not None:
            return cached
        
        value = factory()
        cls.set(key, value, ttl)
        return value


# 初始化
_init_cache()
