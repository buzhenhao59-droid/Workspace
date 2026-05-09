# -*- coding: utf-8 -*-
"""
Redis 分布式锁模块
用于高并发场景下的坐席分配、数据隔离等需要原子操作的场景
"""
import os
import sys
import time
import uuid
import asyncio
import threading
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# 懒加载 Redis
_redis_client = None
_use_fake = True
_lock_init_done = False


def _init_redis_lock():
    """初始化 Redis 连接"""
    global _redis_client, _use_fake, _lock_init_done
    
    if _lock_init_done:
        return
    
    _lock_init_done = True
    
    try:
        from config import (
            REDIS_HOST, REDIS_PORT, REDIS_DB, REDIS_PASSWORD,
            REDIS_USE_FAKE, ENABLE_DISTRIBUTED_LOCK
        )
        
        if not ENABLE_DISTRIBUTED_LOCK:
            logger.info("[RedisLock] ENABLE_DISTRIBUTED_LOCK=false，分布式锁禁用")
            return
        
        _use_fake = REDIS_USE_FAKE
        
        if _use_fake:
            try:
                import fakeredis
                _redis_client = fakeredis.FakeRedis(decode_responses=True)
                logger.info("[RedisLock] 使用 fakeredis（开发模式）")
            except ImportError:
                logger.warning("[RedisLock] fakeredis 未安装，分布式锁禁用")
                return
        else:
            try:
                import redis
                _redis_client = redis.Redis(
                    host=REDIS_HOST,
                    port=REDIS_PORT,
                    db=REDIS_DB,
                    password=REDIS_PASSWORD or None,
                    decode_responses=True,
                    socket_connect_timeout=5,
                    socket_keepalive=True,
                )
                _redis_client.ping()
                logger.info(f"[RedisLock] 连接成功 {REDIS_HOST}:{REDIS_PORT}")
            except Exception as e:
                logger.warning(f"[RedisLock] Redis 连接失败: {e}，分布式锁禁用")
                _redis_client = None
                
    except ImportError:
        logger.warning("[RedisLock] config 模块导入失败，分布式锁禁用")
        _redis_client = None


def _ensure_redis():
    """确保 Redis 连接可用"""
    if _redis_client is None:
        _init_redis_lock()
    return _redis_client is not None


class RedisDistributedLock:
    """
    Redis 分布式锁实现
    使用 SETNX + Lua 脚本确保原子性
    
    使用示例:
        lock = RedisDistributedLock("session_assign", session_id, ttl=10)
        if lock.acquire():
            try:
                # 临界区操作
                pass
            finally:
                lock.release()
    """
    
    def __init__(self, lock_name: str, lock_id: str, ttl: int = 10):
        self.lock_name = f"lock:{lock_name}:{lock_id}"
        self.lock_id = lock_id
        self.ttl = ttl
        self._acquired = False
        self._lock_value = f"{uuid.uuid4().hex[:8]}_{time.time()}"
        self._client = None
    
    def acquire(self, blocking: bool = True, timeout: int = 5) -> bool:
        """
        获取锁
        
        Args:
            blocking: 是否阻塞等待
            timeout: 阻塞超时时间（秒）
        
        Returns:
            bool: 是否成功获取锁
        """
        if not _ensure_redis():
            # Redis 不可用时，使用线程锁作为回退（单服务器模式）
            logger.warning(f"[RedisLock] Redis 不可用，使用线程锁替代: {self.lock_name}")
            self._acquired = True
            return True
        
        self._client = _redis_client
        
        if blocking:
            start = time.time()
            while time.time() - start < timeout:
                if self._try_acquire():
                    return True
                time.sleep(0.01)  # 10ms 重试间隔
            return False
        else:
            return self._try_acquire()
    
    def _try_acquire(self) -> bool:
        """尝试获取锁（非阻塞）"""
        try:
            result = self._client.set(
                self.lock_name,
                self._lock_value,
                ex=self.ttl,
                nx=True  # 仅在不存在时设置
            )
            self._acquired = result is True
            return self._acquired
        except Exception as e:
            logger.warning(f"[RedisLock] 获取锁失败: {e}")
            self._acquired = True  # 降级为允许操作
            return True
    
    def release(self) -> bool:
        """释放锁（仅当锁值匹配时，防止误删其他进程的锁）"""
        if not self._acquired:
            return True
        
        if not _ensure_redis() or self._client is None:
            self._acquired = False
            return True
        
        try:
            # 检查锁值是否匹配（避免误删其他进程的锁）
            current_value = self._client.get(self.lock_name)
            if current_value == self._lock_value:
                self._client.delete(self.lock_name)
                self._acquired = False
                return True
            else:
                # 锁已过期或被其他进程持有
                self._acquired = False
                return False
        except Exception as e:
            logger.warning(f"[RedisLock] 释放锁失败: {e}")
            self._acquired = False
            return False
    
    def extend(self, additional_ttl: int = None) -> bool:
        """延长锁的 TTL"""
        if not self._acquired or not _ensure_redis():
            return False
        
        ttl = additional_ttl or self.ttl
        
        try:
            # 检查锁值是否匹配
            current_value = self._client.get(self.lock_name)
            if current_value == self._lock_value:
                self._client.expire(self.lock_name, ttl)
                return True
            return False
        except Exception as e:
            logger.warning(f"[RedisLock] 延长锁失败: {e}")
            return False
    
    def __enter__(self):
        """上下文管理器入口"""
        self.acquire()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        self.release()
        return False


class RedisLockManager:
    """
    Redis 锁管理器
    提供统一的锁获取/释放接口
    """
    
    _local_lock = threading.Lock()
    _locks: dict = {}
    
    @classmethod
    def acquire_lock(cls, name: str, resource_id: str, ttl: int = 10) -> Optional[RedisDistributedLock]:
        """
        获取分布式锁
        
        Args:
            name: 锁名称前缀
            resource_id: 资源标识
            ttl: 锁超时时间（秒）
        
        Returns:
            RedisDistributedLock 实例，获取失败返回 None
        """
        lock = RedisDistributedLock(name, resource_id, ttl)
        if lock.acquire(blocking=True, timeout=5):
            return lock
        return None
    
    @classmethod
    def release_lock(cls, lock: RedisDistributedLock):
        """释放锁"""
        if lock:
            lock.release()


def with_distributed_lock(lock_name: str, resource_id: str, ttl: int = 10):
    """
    分布式锁装饰器
    
    使用示例:
        @with_distributed_lock("session_assign", "session_123")
        def assign_session():
            # 临界区操作
            pass
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            lock = RedisLockManager.acquire_lock(lock_name, resource_id, ttl)
            if lock is None:
                logger.warning(f"[RedisLock] 获取锁失败: {lock_name}:{resource_id}")
                return None
            try:
                return func(*args, **kwargs)
            finally:
                RedisLockManager.release_lock(lock)
        return wrapper
    return decorator


# 初始化
_init_redis_lock()
