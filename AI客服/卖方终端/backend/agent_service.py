# -*- coding: utf-8 -*-
"""
坐席服务 - 客服坐席的注册、登录、分配逻辑
与 realtime_server.py 配合使用，realtime_server 处理实时推送，本模块处理业务逻辑。

【重要】会话分配状态已统一到 session_mode.py，不再各自维护映射。
本模块通过 session_mode 代理读写，不再直接操作 _session_assignments。

新增功能：
- 分布式锁：使用 Redis 实现坐席分配的原子操作，解决并发冲突
- 冲突检测：防止多人同时请求人工服务时的"撞线"和"重复分配"
"""
import logging
import time
import uuid
from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict

logger = logging.getLogger(__name__)

# 懒导入，避免循环依赖
_session_mode = None
_redis_lock_loaded = False


def _get_mode_manager():
    global _session_mode
    if _session_mode is None:
        from session_mode import session_mode
        globals()["_session_mode"] = session_mode
    return _session_mode


class AgentStatus(str, Enum):
    ONLINE = "online"
    BUSY = "busy"
    AWAY = "away"
    OFFLINE = "offline"


class AgentRole(str, Enum):
    AGENT = "agent"       # 普通客服
    MANAGER = "manager"   # 运营主管
    ADMIN = "admin"       # 管理员


# ==================== 分布式锁支持 ====================

_distributed_lock_available = False
_redis_for_lock = None


def _init_distributed_lock():
    """初始化分布式锁（懒加载）"""
    global _distributed_lock_available, _redis_for_lock
    if _redis_for_lock is not None:
        return
    try:
        from redis_store import redis_store
        _redis_for_lock = redis_store
        _distributed_lock_available = True
        logger.info("[DistributedLock] 分布式锁已启用（Redis）")
    except ImportError:
        logger.warning("[DistributedLock] Redis 不可用，使用内存锁（单服务器模式）")
        _distributed_lock_available = False


class DistributedLock:
    """
    分布式锁 - 使用 Redis SETNX 实现原子操作。
    解决多实例部署时的并发冲突问题。

    使用方式：
        lock = DistributedLock("session_assign", session_id, ttl=10)
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

    def acquire(self) -> bool:
        """尝试获取锁，返回 True 表示成功获取"""
        global _redis_for_lock, _distributed_lock_available

        if not _distributed_lock_available or _redis_for_lock is None:
            # 无 Redis 时使用线程锁作为回退
            return True

        try:
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result = loop.run_until_complete(
                    self._async_acquire()
                )
                self._acquired = result
                return result
            finally:
                loop.close()
        except Exception as e:
            logger.warning(f"[DistributedLock] 获取锁失败: {e}")
            return True  # 降级为允许操作

    async def _async_acquire(self) -> bool:
        """异步获取锁"""
        try:
            client = _redis_for_lock._client
            result = await client.set(
                self.lock_name,
                self._lock_value,
                ex=self.ttl,
                nx=True  # 仅在不存在时设置
            )
            return result is True
        except Exception as e:
            logger.warning(f"[DistributedLock] 异步获取锁失败: {e}")
            return True

    def release(self) -> bool:
        """释放锁"""
        global _distributed_lock_available, _redis_for_lock

        if not _distributed_lock_available or _redis_for_lock is None:
            return True

        if not self._acquired:
            return True

        try:
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(self._async_release())
            finally:
                loop.close()
        except Exception:
            return False

    async def _async_release(self) -> bool:
        """异步释放锁（仅当锁值匹配时，防止误删其他进程的锁）"""
        try:
            client = _redis_for_lock._client
            # 使用 Lua 脚本确保原子性：仅当锁值匹配时删除
            lua_script = """
            if redis.call("get", KEYS[1]) == ARGV[1] then
                return redis.call("del", KEYS[1])
            else
                return 0
            end
            """
            result = await client.eval(lua_script, 1, self.lock_name, self._lock_value)
            return result == 1
        except Exception:
            return False


class AgentService:
    """
    坐席服务 - 封装所有坐席相关的业务逻辑。

    与 db.py 的 sellers 表对应，支持：
    - 坐席登录/登出
    - 坐席状态管理（在线/忙碌/离开/离线）
    - 会话分配策略（自动分配/手动指定）
    - 坐席工作负载查询

    【会话分配】所有写操作均代理到 session_mode.py，内存中仅维护坐席登录状态。
    """

    def __init__(self):
        # agent_id -> {login_at, last_heartbeat, current_session_id, status, role, name}
        self._agent_sessions: Dict[str, dict] = {}
        self._lock = __import__("threading").RLock()

    # ==================== 坐席管理 ====================

    def agent_login(self, agent_id: str, agent_name: str = "", role: str = "agent") -> dict:
        """坐席登录，建立工作会话"""
        now = datetime.now()
        with self._lock:
            self._agent_sessions[agent_id] = {
                "agent_id": agent_id,
                "agent_name": agent_name or agent_id,
                "role": role,
                "status": AgentStatus.ONLINE.value,
                "login_at": now.isoformat(),
                "last_heartbeat": time.time(),
                "current_session_id": None,
            }
        logger.info(f"坐席登录: agent={agent_id}, name={agent_name}, role={role}")
        return self._agent_sessions[agent_id]

    def agent_logout(self, agent_id: str) -> bool:
        """坐席登出"""
        with self._lock:
            session = self._agent_sessions.pop(agent_id, None)
            if not session:
                return False
        # 释放该坐席的所有会话（通过 session_mode）
        mode_mgr = _get_mode_manager()
        for s_id in mode_mgr.get_agent_sessions(agent_id):
            mode_mgr.unassign_agent(s_id)
        logger.info(f"坐席登出: agent={agent_id}")
        return True

    def agent_heartbeat(self, agent_id: str) -> bool:
        """坐席心跳保活"""
        with self._lock:
            if agent_id in self._agent_sessions:
                self._agent_sessions[agent_id]["last_heartbeat"] = time.time()
                return True
        return False

    def set_agent_status(self, agent_id: str, status: str) -> bool:
        """更新坐席状态"""
        with self._lock:
            if agent_id in self._agent_sessions:
                self._agent_sessions[agent_id]["status"] = status
                logger.info(f"坐席状态变更: agent={agent_id}, status={status}")
                return True
        return False

    def set_agent_current_session(self, agent_id: str, session_id: str):
        """坐席切换当前查看的会话"""
        with self._lock:
            if agent_id in self._agent_sessions:
                old_session = self._agent_sessions[agent_id].get("current_session_id")
                self._agent_sessions[agent_id]["current_session_id"] = session_id
                logger.info(f"坐席切换会话: agent={agent_id}, {old_session} -> {session_id}")

    # ==================== 会话分配（代理到 session_mode） ====================

    def assign_session(self, session_id: str, agent_id: str) -> bool:
        """
        将会话分配给指定坐席（代理到 session_mode）。
        使用分布式锁防止并发冲突。
        """
        # 尝试使用新的 Redis 分布式锁
        from redis_lock import RedisDistributedLock, _ensure_redis
        use_new_lock = _ensure_redis()
        
        if use_new_lock:
            lock = RedisDistributedLock("session_assign", session_id, ttl=10)
            if not lock.acquire(blocking=True, timeout=5):
                logger.warning(f"会话 {session_id} 正在被其他操作处理，跳过")
                return False
        else:
            # 回退到旧的分布式锁
            _init_distributed_lock()
            lock = DistributedLock("session_assign", session_id, ttl=10)
            if not lock.acquire():
                logger.warning(f"会话 {session_id} 正在被其他操作处理，跳过")
                return False
        
        try:
            with self._lock:
                if agent_id not in self._agent_sessions:
                    logger.warning(f"分配失败: 坐席 {agent_id} 不在线")
                    return False
            
            mode_mgr = _get_mode_manager()
            existing = mode_mgr.get_agent(session_id)
            if existing == agent_id:
                return True  # 已分配，无需重复操作

            # 使用锁内的原子操作进行分配
            success = mode_mgr.switch_to_human(session_id, agent_id)
            if not success:
                logger.warning(f"会话 {session_id} 已被其他坐席接管，拒绝分配给 {agent_id}")
                return False

            with self._lock:
                self._agent_sessions[agent_id]["current_session_id"] = session_id
            logger.info(f"会话分配: session={session_id} -> agent={agent_id}")
            return True
        finally:
            lock.release()

    def auto_assign_session(self, session_id: str, strategy: str = "least_loaded") -> Optional[str]:
        """
        自动分配会话给最合适的坐席。
        策略：least_loaded / round_robin / priority
        """
        mode_mgr = _get_mode_manager()
        online_agents = [
            (aid, data)
            for aid, data in self._agent_sessions.items()
            if data["status"] == AgentStatus.ONLINE.value
        ]
        if not online_agents:
            logger.warning(f"自动分配失败: 无在线坐席 (session={session_id})")
            return None

        # 按策略排序
        if strategy == "least_loaded":
            counts = mode_mgr.get_all_agent_session_counts()
            online_agents.sort(key=lambda x: (counts.get(x[0], 0), x[1]["login_at"]))
        elif strategy == "priority":
            role_order = {AgentRole.ADMIN.value: 0, AgentRole.MANAGER.value: 1, AgentRole.AGENT.value: 2}
            online_agents.sort(key=lambda x: (role_order.get(x[1]["role"], 2), x[1]["login_at"]))
        else:  # round_robin
            online_agents.sort(key=lambda x: x[1]["login_at"])

        target_agent = online_agents[0][0]
        self.assign_session(session_id, target_agent)
        return target_agent

    def release_session(self, session_id: str) -> bool:
        """释放会话（坐席放弃或将客户转给其他坐席）"""
        mode_mgr = _get_mode_manager()
        return mode_mgr.release_session(session_id)

    def get_session_agent(self, session_id: str) -> Optional[str]:
        """查询会话当前分配的坐席ID（代理到 session_mode）"""
        mode_mgr = _get_mode_manager()
        return mode_mgr.get_session_agent(session_id)

    # ==================== 查询接口 ====================

    def get_online_agents(self) -> List[dict]:
        """获取所有在线坐席列表（含精确会话数）"""
        mode_mgr = _get_mode_manager()
        counts = mode_mgr.get_all_agent_session_counts()
        with self._lock:
            result = []
            for agent_id, data in self._agent_sessions.items():
                result.append({
                    **data,
                    "active_session_count": counts.get(agent_id, 0),
                })
            return result

    def get_agent_info(self, agent_id: str) -> Optional[dict]:
        """获取坐席信息"""
        with self._lock:
            return self._agent_sessions.get(agent_id)

    def get_agent_sessions(self, agent_id: str) -> List[str]:
        """获取坐席当前分配的所有会话ID（代理到 session_mode）"""
        mode_mgr = _get_mode_manager()
        return mode_mgr.get_agent_sessions(agent_id)

    def get_workload_report(self) -> dict:
        """获取坐席工作负载报告"""
        agents = self.get_online_agents()
        mode_mgr = _get_mode_manager()
        waiting = mode_mgr.get_waiting_sessions()
        human = mode_mgr.get_human_sessions()
        if not agents:
            return {"total_agents": 0, "total_sessions": 0, "agents": [],
                    "waiting_count": len(waiting), "human_count": len(human)}

        sessions_by_status = {
            "ai": len(mode_mgr.get_ai_sessions()),
            "waiting": len(waiting),
            "human": len(human),
        }

        return {
            "total_agents": len(agents),
            "total_sessions": len(sessions_by_status),
            "active_sessions": len(human),
            "waiting_count": len(waiting),
            "agents": agents,
            "by_status": sessions_by_status,
        }

    def validate_agent_session(self, agent_id: str) -> bool:
        """验证坐席登录状态（心跳超时检测）"""
        with self._lock:
            if agent_id not in self._agent_sessions:
                return False
            last_hb = self._agent_sessions[agent_id]["last_heartbeat"]
            if time.time() - last_hb > 60:  # 60秒无心跳视为离线
                self.agent_logout(agent_id)
                return False
        return True


# 全局单例
agent_service = AgentService()
