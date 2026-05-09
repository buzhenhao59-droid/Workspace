# -*- coding: utf-8 -*-
"""
Redis 会话存储层 - 替代内存存储，支持分布式部署
所有会话数据存储在 Redis 中，服务重启不丢失，支持多实例部署

特性：
- 自动重连：连接断开后指数退避重连（最多 5 次）
- 连接保活：每 30s ping 一次，超时自动重连
- 无 Redis 时静默回退：所有操作返回 False/空，不抛异常
- 可选 fakeredis 模拟：开发环境无需安装 Redis
"""
import asyncio
import json
import logging
import threading
import time
from datetime import datetime
from typing import Optional, List, Dict

logger = logging.getLogger(__name__)

# 懒加载 redis（避免启动时就报错）
_redis_async: Optional[type] = None
_redis_sync: Optional[type] = None

try:
    import redis.asyncio as _ra
    import redis as _rs
    _redis_async = _ra
    _redis_sync = _rs
except ImportError:
    logger.warning("redis-py 未安装，请运行: pip install redis")
    _redis_async = None
    _redis_sync = None

# 可选 fakeredis（pip install fakeredis）
_fakeredis: Optional[type] = None
try:
    import fakeredis.aioredis as _fa
    _fakeredis = _fa
except ImportError:
    pass


class RedisSessionStore:
    """
    基于 Redis 的会话存储层

    Key 规划：
    - session:{session_id}        Hash   会话信息
    - messages:{session_id}        List   消息历史
    - customer:{customer_id}       String session_id（客户当前会话）
    - session_agent:{session_id}   Hash   {agent_id}
    - agent_sessions:{agent_id}     Set    [session_ids]
    - agent:{agent_id}              Hash   坐席状态
    - waiting_queue                List   等待队列
    - stats:{key}                  String 计数器

    特性：
    - Redis 不可用时所有操作静默回退，不抛异常
    - 启动时自动连接，失败后后台重连（指数退避，最多 5 次）
    - 每 30s ping 一次保活
    """

    def __init__(self,
                 host: str = "127.0.0.1",
                 port: int = 6379,
                 db: int = 0,
                 password: str = "",
                 use_fake: bool = False):
        self._host = host
        self._port = port
        self._db = db
        self._password = password if password else None
        self._use_fake = use_fake
        self._client: Optional[any] = None
        self._connected = False

        # 重连状态
        self._reconnect_attempts = 0
        self._max_reconnect = 5
        self._reconnect_delay = 2.0   # 初始 2s，后续 ×2
        self._reconnecting = False
        self._lock = threading.Lock()

        # 保活任务
        self._keepalive_running = True
        self._keepalive_thread: Optional[threading.Thread] = None

        # 记录最后一次可用时间
        self._last_healthy: Optional[float] = None

    # ==================== 连接管理 ====================

    async def connect(self):
        """建立 Redis 连接（幂等，可多次调用）"""
        if self._connected and self._client is not None:
            return

        with self._lock:
            if self._connected and self._client is not None:
                return
            await self._do_connect()

    async def _do_connect(self):
        """实际执行连接"""
        if _fakeredis is None and _redis_async is None:
            logger.warning("redis-py 未安装，Redis 存储层不可用")
            return

        try:
            if self._use_fake and _fakeredis:
                self._client = _fakeredis.FakeRedis(decode_responses=True)
                await asyncio.sleep(0)   # 让 event loop 继续
                await self._client.ping()
                self._connected = True
                logger.info("RedisSessionStore: fakeredis 模拟模式（开发环境）")
                self._start_keepalive()
                return

            if _redis_async:
                if self._password:
                    self._client = _redis_async.Redis(
                        host=self._host, port=self._port, db=self._db,
                        password=self._password,
                        decode_responses=True, encoding="utf-8",
                        socket_connect_timeout=5,
                        socket_keepalive=True,
                        health_check_interval=30,
                    )
                else:
                    self._client = _redis_async.Redis(
                        host=self._host, port=self._port, db=self._db,
                        decode_responses=True, encoding="utf-8",
                        socket_connect_timeout=5,
                        socket_keepalive=True,
                        health_check_interval=30,
                    )
                await self._client.ping()
                self._connected = True
                self._reconnect_attempts = 0
                self._reconnect_delay = 2.0
                self._last_healthy = time.time()
                logger.info(f"RedisSessionStore: 连接成功 {self._host}:{self._port}")
                self._start_keepalive()
        except Exception as e:
            self._connected = False
            self._client = None
            logger.warning(f"RedisSessionStore: 连接失败 {e}，将回退到内存存储")
            # 触发后台重连
            asyncio.create_task(self._bg_reconnect())

    async def _bg_reconnect(self):
        """后台指数退避重连"""
        if self._reconnecting:
            return
        self._reconnecting = True
        try:
            while self._reconnect_attempts < self._max_reconnect:
                delay = self._reconnect_delay * (2 ** self._reconnect_attempts)
                logger.info(f"RedisSessionStore: {delay:.0f}s 后第 {self._reconnect_attempts + 1} 次重连...")
                await asyncio.sleep(delay)
                try:
                    if self._use_fake and _fakeredis:
                        self._client = _fakeredis.FakeRedis(decode_responses=True)
                    else:
                        kwargs = dict(host=self._host, port=self._port, db=self._db,
                                      decode_responses=True, encoding="utf-8",
                                      socket_connect_timeout=5)
                        if self._password:
                            kwargs["password"] = self._password
                        self._client = _redis_async.Redis(**kwargs)
                    await self._client.ping()
                    self._connected = True
                    self._reconnect_attempts = 0
                    self._last_healthy = time.time()
                    self._start_keepalive()
                    logger.info("RedisSessionStore: 重连成功！")
                    return
                except Exception:
                    self._reconnect_attempts += 1
                    self._connected = False
                    self._client = None
            logger.warning("RedisSessionStore: 重连次数超限，停止重连。系统将在内存模式继续运行。")
        finally:
            self._reconnecting = False

    def _start_keepalive(self):
        """启动保活线程（仅在已连接时调用，须在 _lock 外）"""
        if self._keepalive_thread and self._keepalive_thread.is_alive():
            return
        self._keepalive_running = True
        self._keepalive_thread = threading.Thread(target=self._keepalive_loop, daemon=True)
        self._keepalive_thread.start()

    def _keepalive_loop(self):
        """每 30s ping 一次，失败触发重连"""
        while self._keepalive_running:
            time.sleep(30)
            if not self._connected or self._client is None:
                continue
            try:
                # ping 是同步方法，但在异步上下文中可能有问题，用 run_in_executor
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(self._client.ping())
                finally:
                    loop.close()
                self._last_healthy = time.time()
            except Exception:
                logger.warning("RedisSessionStore: ping 失败，标记为不可用，触发重连")
                self._connected = False
                asyncio.create_task(self._bg_reconnect())
                break

    async def disconnect(self):
        """断开连接"""
        self._keepalive_running = False
        if self._client:
            try:
                await self._client.close()
            except Exception:
                pass
            self._client = None
        self._connected = False
        logger.info("RedisSessionStore: 连接已关闭")

    @property
    def is_available(self) -> bool:
        """检查 Redis 是否当前可用"""
        return self._connected and self._client is not None

    @property
    def is_fake(self) -> bool:
        """是否使用 fakeredis 模拟"""
        return self._use_fake

    @property
    def last_healthy(self) -> Optional[float]:
        """最后一次健康检查时间戳"""
        return self._last_healthy

    # ==================== 会话操作 ====================

    async def create_session(self, session_id: str, customer_info: dict,
                              language: str = "zh") -> bool:
        """创建会话"""
        if not self.is_available:
            return False
        session_data = {
            "session_id": session_id,
            "customer_info": json.dumps(customer_info, ensure_ascii=False),
            "language": language,
            "conversation_history": "[]",
            "created_at": datetime.now().isoformat(),
            "status": "active"
        }
        try:
            pipe = self._client.pipeline(transaction=False)
            for k, v in session_data.items():
                val = json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v
                pipe.hset(f"session:{session_id}", k, val)
            pipe.expire(f"session:{session_id}", 86400 * 7)
            await pipe.execute()
            logger.info(f"Redis 创建会话: {session_id}")
            return True
        except Exception as e:
            logger.error(f"Redis 创建会话失败: {e}")
            return await self._handle_disconnect(e)

    async def get_session(self, session_id: str) -> Optional[dict]:
        """获取会话"""
        if not self.is_available:
            return None
        try:
            data = await self._client.hgetall(f"session:{session_id}")
            if not data:
                return None
            result = {}
            for k, v in data.items():
                try:
                    result[k] = json.loads(v)
                except (json.JSONDecodeError, TypeError):
                    result[k] = v
            return result
        except Exception as e:
            logger.error(f"Redis 获取会话失败: {e}")
            return None

    async def update_session_language(self, session_id: str, language: str) -> bool:
        """更新会话语言"""
        if not self.is_available:
            return False
        try:
            await self._client.hset(f"session:{session_id}", "language", language)
            return True
        except Exception as e:
            logger.error(f"Redis 更新语言失败: {e}")
            return await self._handle_disconnect(e)

    async def close_session(self, session_id: str) -> bool:
        """关闭会话"""
        if not self.is_available:
            return False
        try:
            await self._client.hset(f"session:{session_id}", "status", "closed")
            await self._client.expire(f"session:{session_id}", 3600)
            logger.info(f"Redis 关闭会话: {session_id}")
            return True
        except Exception as e:
            logger.error(f"Redis 关闭会话失败: {e}")
            return await self._handle_disconnect(e)

    # ==================== 消息操作 ====================

    async def add_message(self, session_id: str, role: str, content: str,
                          from_type: str = "user", from_id: str = "") -> bool:
        """添加消息"""
        if not self.is_available:
            return False
        msg = {
            "id": str(uuid_now()),
            "role": role,
            "content": content,
            "from_type": from_type,
            "from_id": from_id,
            "created_at": datetime.now().isoformat()
        }
        try:
            pipe = self._client.pipeline(transaction=False)
            pipe.rpush(f"messages:{session_id}", json.dumps(msg, ensure_ascii=False))
            pipe.expire(f"messages:{session_id}", 86400 * 7)
            await pipe.execute()
            return True
        except Exception as e:
            logger.error(f"Redis 添加消息失败: {e}")
            return await self._handle_disconnect(e)

    async def get_messages(self, session_id: str, limit: int = 100) -> List[dict]:
        """获取消息历史"""
        if not self.is_available:
            return []
        try:
            msgs = await self._client.lrange(f"messages:{session_id}", 0, limit - 1)
            return [json.loads(m) for m in msgs]
        except Exception as e:
            logger.error(f"Redis 获取消息失败: {e}")
            return []

    async def get_recent_messages(self, session_id: str, count: int = 3) -> List[dict]:
        """获取最近 N 条消息"""
        if not self.is_available:
            return []
        try:
            msgs = await self._client.lrange(f"messages:{session_id}", -count, -1)
            return [json.loads(m) for m in msgs]
        except Exception:
            return []

    # ==================== 客户连接管理 ====================

    async def set_customer_session(self, customer_id: str, session_id: str) -> bool:
        """绑定客户到会话"""
        if not self.is_available:
            return False
        try:
            await self._client.set(f"customer:{customer_id}", session_id, ex=86400 * 7)
            return True
        except Exception as e:
            logger.error(f"Redis 绑定客户失败: {e}")
            return await self._handle_disconnect(e)

    async def get_customer_session(self, customer_id: str) -> Optional[str]:
        """获取客户当前会话"""
        if not self.is_available:
            return None
        try:
            return await self._client.get(f"customer:{customer_id}")
        except Exception:
            return None

    # ==================== 坐席会话分配 ====================

    async def assign_session_to_agent(self, session_id: str, agent_id: str) -> bool:
        """分配会话给坐席"""
        if not self.is_available:
            return False
        try:
            pipe = self._client.pipeline(transaction=False)
            pipe.hset(f"session_agent:{session_id}", "agent_id", agent_id)
            pipe.hset(f"session:{session_id}", "assign_to", agent_id)
            pipe.sadd(f"agent_sessions:{agent_id}", session_id)
            await pipe.execute()
            logger.info(f"Redis 分配会话 {session_id} -> 坐席 {agent_id}")
            return True
        except Exception as e:
            logger.error(f"Redis 分配会话失败: {e}")
            return await self._handle_disconnect(e)

    async def unassign_session(self, session_id: str) -> bool:
        """取消会话分配"""
        if not self.is_available:
            return False
        try:
            agent_id = await self._client.hget(f"session_agent:{session_id}", "agent_id")
            pipe = self._client.pipeline(transaction=False)
            pipe.delete(f"session_agent:{session_id}")
            pipe.delete(f"session:{session_id}:assign_to")
            if agent_id:
                pipe.srem(f"agent_sessions:{agent_id}", session_id)
            await pipe.execute()
            return True
        except Exception as e:
            logger.error(f"Redis 取消分配失败: {e}")
            return await self._handle_disconnect(e)

    async def get_agent_by_session(self, session_id: str) -> Optional[str]:
        """获取会话分配的坐席"""
        if not self.is_available:
            return None
        try:
            return await self._client.hget(f"session_agent:{session_id}", "agent_id")
        except Exception:
            return None

    async def get_agent_sessions(self, agent_id: str) -> List[str]:
        """获取坐席负责的所有会话"""
        if not self.is_available:
            return []
        try:
            return list(await self._client.smembers(f"agent_sessions:{agent_id}"))
        except Exception:
            return []

    async def get_agent_session_count(self, agent_id: str) -> int:
        """获取坐席当前会话数"""
        if not self.is_available:
            return 0
        try:
            return await self._client.scard(f"agent_sessions:{agent_id}")
        except Exception:
            return 0

    async def get_all_agent_session_counts(self) -> Dict[str, int]:
        """获取所有坐席的会话数（SCAN 避免 KEYS 阻塞；fakeredis 用 KEYS 回退）"""
        if not self.is_available:
            return {}
        try:
            result = {}
            cursor = 0
            while True:
                try:
                    cursor, keys = await self._client.scan(cursor=cursor, match="agent_sessions:*", count=100)
                except Exception:
                    # fakeredis 不支持 SCAN，用 KEYS 代替（仅开发环境）
                    keys = await self._client.keys("agent_sessions:*")
                    cursor = 0
                for key in keys:
                    agent_id = key.split(":", 1)[1] if ":" in key else key.split("_")[-1]
                    result[agent_id] = await self._client.scard(key)
                if cursor == 0:
                    break
            return result
        except Exception:
            return {}

    # ==================== 等待队列 ====================

    async def add_to_waiting_queue(self, session_id: str) -> bool:
        """加入等待队列"""
        if not self.is_available:
            return False
        try:
            await self._client.rpush("waiting_queue", session_id)
            return True
        except Exception as e:
            logger.error(f"Redis 入队失败: {e}")
            return await self._handle_disconnect(e)

    async def remove_from_waiting_queue(self, session_id: str) -> bool:
        """从等待队列移除"""
        if not self.is_available:
            return False
        try:
            await self._client.lrem("waiting_queue", 1, session_id)
            return True
        except Exception as e:
            logger.error(f"Redis 出队失败: {e}")
            return await self._handle_disconnect(e)

    async def get_waiting_queue(self) -> List[str]:
        """获取等待队列"""
        if not self.is_available:
            return []
        try:
            return await self._client.lrange("waiting_queue", 0, -1)
        except Exception:
            return []

    async def get_waiting_count(self) -> int:
        """获取等待人数"""
        if not self.is_available:
            return 0
        try:
            return await self._client.llen("waiting_queue")
        except Exception:
            return 0

    # ==================== 坐席在线状态 ====================

    async def set_agent_online(self, agent_id: str, agent_name: str, role: str = "agent") -> bool:
        """坐席上线"""
        if not self.is_available:
            return False
        try:
            await self._client.hset(f"agent:{agent_id}", mapping={
                "name": agent_name,
                "role": role,
                "status": "online",
                "online_at": datetime.now().isoformat()
            })
            await self._client.expire(f"agent:{agent_id}", 86400)
            return True
        except Exception as e:
            logger.error(f"Redis 坐席上线失败: {e}")
            return await self._handle_disconnect(e)

    async def set_agent_offline(self, agent_id: str) -> bool:
        """坐席下线"""
        if not self.is_available:
            return False
        try:
            await self._client.hset(f"agent:{agent_id}", "status", "offline")
            return True
        except Exception:
            return False

    async def get_online_agents(self) -> List[dict]:
        """获取所有在线坐席（SCAN 避免 KEYS 阻塞；fakeredis 用 KEYS 回退）"""
        if not self.is_available:
            return []
        try:
            agents = []
            cursor = 0
            while True:
                try:
                    cursor, keys = await self._client.scan(cursor=cursor, match="agent:*", count=100)
                except Exception:
                    # fakeredis 不支持 SCAN，用 KEYS 代替（仅开发环境）
                    keys = await self._client.keys("agent:*")
                    cursor = 0
                for key in keys:
                    data = await self._client.hgetall(key)
                    if data and data.get("status") == "online":
                        agents.append(data)
                if cursor == 0:
                    break
            return agents
        except Exception:
            return []

    # ==================== 统计数据 ====================

    async def increment_stat(self, key: str, ttl: int = 3600) -> int:
        """递增统计值"""
        if not self.is_available:
            return 0
        try:
            val = await self._client.incr(key)
            if val == 1:
                await self._client.expire(key, ttl)
            return val
        except Exception:
            return 0

    async def get_stat(self, key: str) -> int:
        """获取统计值"""
        if not self.is_available:
            return 0
        try:
            val = await self._client.get(key)
            return int(val) if val else 0
        except Exception:
            return 0

    # ==================== 健康检查 ====================

    async def health_check(self) -> dict:
        """Redis 健康检查（详细版）"""
        if not self.is_available:
            return {
                "status": "unavailable",
                "connected": False,
                "reconnecting": self._reconnecting,
                "reconnect_attempts": self._reconnect_attempts,
            }
        try:
            start = datetime.now()
            await self._client.ping()
            latency_ms = (datetime.now() - start).total_seconds() * 1000
            health = {
                "status": "healthy",
                "connected": True,
                "latency_ms": round(latency_ms, 2),
                "is_fake": self._use_fake,
                "last_healthy": self._last_healthy,
            }
            # info 子命令在 fakeredis 中可能不完全支持，捕异常
            try:
                info = await self._client.info("memory")
                health["used_memory"] = info.get("used_memory_human", "unknown")
                health["connected_clients"] = info.get("connected_clients", 0)
                uptime = await self._client.info("server")
                health["uptime_seconds"] = uptime.get("uptime_in_seconds", 0)
            except Exception:
                health["used_memory"] = "n/a (fakeredis)"
            return health
        except Exception as e:
            self._connected = False
            asyncio.create_task(self._bg_reconnect())
            return {
                "status": "unhealthy",
                "connected": False,
                "error": str(e),
                "reconnecting": True,
            }

    # ==================== 内部工具 ====================

    async def _handle_disconnect(self, exc: Exception) -> bool:
        """操作失败时检测是否断开，触发重连"""
        if _is_connection_error(exc):
            logger.warning(f"Redis 连接断开，触发重连: {exc}")
            self._connected = False
            asyncio.create_task(self._bg_reconnect())
        return False


def _is_connection_error(exc: Exception) -> bool:
    """判断是否为连接类异常"""
    err_name = type(exc).__name__.lower()
    err_msg = str(exc).lower()
    markers = ("connection", "timeout", "reset", "refused", "disconnect",
              "pool", "timeout", "stream")
    return any(m in err_name or m in err_msg for m in markers)


def uuid_now() -> str:
    """生成时间戳 UUID（用于消息 ID）"""
    import uuid
    return str(uuid.uuid4())


# ==================== 全局单例工厂 ====================

def create_redis_store(host="127.0.0.1", port=6379, db=0,
                       password="", use_fake=False) -> RedisSessionStore:
    """
    创建 RedisSessionStore 实例。
    从 .env 读取配置（REDIS_HOST / REDIS_PORT / REDIS_DB / REDIS_PASSWORD）。
    也可通过参数覆盖。
    """
    # 如果参数未传，从环境变量读取
    import os
    actual_host = host or os.environ.get("REDIS_HOST", "127.0.0.1")
    actual_port = port or int(os.environ.get("REDIS_PORT", 6379))
    actual_db = db if db != 0 else int(os.environ.get("REDIS_DB", 0))
    actual_password = password or os.environ.get("REDIS_PASSWORD", "")
    actual_fake = use_fake or os.environ.get("REDIS_USE_FAKE", "0") == "1"

    store = RedisSessionStore(
        host=actual_host,
        port=actual_port,
        db=actual_db,
        password=actual_password,
        use_fake=actual_fake,
    )
    return store


# ==================== 翻译缓存功能 ====================

async def get_translation_cache(text: str, source_lang: str, target_lang: str) -> Optional[str]:
    """
    获取翻译缓存。
    使用 MD5 哈希作为缓存键，避免存储原文。
    """
    if not text or not str(text).strip():
        return None

    store = redis_store
    if not store.is_available:
        return None

    try:
        cache_key = _make_translation_cache_key(text, source_lang, target_lang)
        result = await store._client.get(f"translation:{cache_key}")
        if result:
            logger.debug(f"[TranslationCache] 命中缓存: {target_lang}")
            return result
        return None
    except Exception:
        return None


async def set_translation_cache(text: str, source_lang: str, target_lang: str, translation: str) -> bool:
    """
    设置翻译缓存。
    TTL: 1小时（可通过 TRANSLATION_CACHE_TTL 环境变量配置）
    """
    if not text or not translation:
        return False

    store = redis_store
    if not store.is_available:
        return False

    try:
        cache_key = _make_translation_cache_key(text, source_lang, target_lang)
        ttl = int(os.environ.get("TRANSLATION_CACHE_TTL", "3600"))  # 默认1小时
        await store._client.setex(f"translation:{cache_key}", ttl, translation)
        return True
    except Exception:
        return False


def _make_translation_cache_key(text: str, source_lang: str, target_lang: str) -> str:
    """
    生成翻译缓存键。
    使用原文的 MD5 哈希，确保相同内容产生相同键。
    """
    content = f"{source_lang}:{target_lang}:{text[:500]}"  # 截断避免过长
    return hashlib.md5(content.encode("utf-8")).hexdigest()


# 默认全局实例（兼容旧代码）
redis_store = create_redis_store()
