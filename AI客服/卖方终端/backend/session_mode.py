# -*- coding: utf-8 -*-
"""
会话模式管理器 - 单例状态机

职责（修订版）：
1. Redis 主存储（会话模式、切换时间、分配关系）
2. 内存为缓存 + Redis 不可用时的回退
3. 解决 realtime_server 和 agent_service 双写问题
4. 记录每次切换到 AI 模式的时间，用于 AI 对话历史过滤
5. 定期（每 60s）将内存状态同步到 Redis（防数据漂移）
6. 进程启动时从 Redis 加载已存在的会话到内存
7. 语种状态管理：支持客户中途切换语言时的即时响应

【重要】realtime_server 中的内存字典（session_to_agent, agent_to_sessions,
waiting_queue）是本地连接池视图，session_mode 是全局持久化状态。

会话流转：
  新会话 → AI 模式
  客户点击转人工 → WAITING 模式（等待坐席）
  坐席接起 → HUMAN 模式
  坐席/客户点击转回AI → AI 模式（记录切换时间）
  坐席释放会话 → WAITING 模式（可重新分配或AI）
"""
import asyncio
import logging
import threading
import time
import os
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, List

logger = logging.getLogger(__name__)


class SessionMode(str, Enum):
    AI = "ai"           # AI 客服模式
    HUMAN = "human"     # 人工坐席模式
    WAITING = "waiting" # 等待分配（坐席释放后/转人工后等待中）


class SessionModeManager:
    """
    会话模式单例 - 替代 agent_service 和 realtime_server 中分散的会话映射。

    数据流（Redis 主 / 内存缓存）：
    - 启动：load_from_redis() 从 Redis 加载已存在会话
    - 写操作：先写 Redis（幂等），Redis 失败则写内存
    - 读操作：优先读内存（快），内存无则查 Redis
    - 同步任务：每 60s 将内存中的变更批量写回 Redis
    """

    # 允许从 .env 读配置的环境变量名
    ENV_REDIS_HOST = "REDIS_HOST"
    ENV_REDIS_PORT = "REDIS_PORT"
    ENV_REDIS_DB   = "REDIS_DB"
    ENV_REDIS_PWD  = "REDIS_PASSWORD"
    ENV_REDIS_FAKE = "REDIS_USE_FAKE"

    def __init__(self):
        # ── 内存缓存（始终最新） ──
        # session_id → SessionMode
        self._modes: Dict[str, SessionMode] = {}
        # session_id → 最后一次切换到 AI 模式的 UTC 时间戳（ISO字符串）
        self._ai_mode_since: Dict[str, str] = {}
        # session_id → agent_id（仅 HUMAN 模式下有效）
        self._session_to_agent: Dict[str, str] = {}
        # agent_id → [session_ids]（活跃会话）
        self._agent_to_sessions: Dict[str, List[str]] = {}
        # 已释放会话记录（用于内存泄漏清理）：session_id → released_at
        self._released_sessions: Dict[str, float] = {}
        # ── 语种状态管理（支持客户中途切换语言） ──
        # session_id → target_lang，当前会话的目标语言
        self._target_langs: Dict[str, str] = {}

        self._lock = threading.RLock()

        # ── Redis 集成 ──
        self._redis_store = self._build_redis_store()
        self._redis_available = False
        self._redis_load_done = False

        # ── 后台任务 ──
        self._gc_running = True
        self._sync_running = True
        self._sync_thread: Optional[threading.Thread] = None
        self._gc_thread: Optional[threading.Thread] = None

        # 启动后台 GC（清理已释放会话泄漏）
        self._gc_thread = threading.Thread(target=self._gc_loop, daemon=True)
        self._gc_thread.start()

        # 尝试连接 Redis（异步在后台做，不阻塞 __init__）
        threading.Thread(target=self._init_redis_async, daemon=True,
                         name="SessionMode-RedisInit").start()

        logger.info("SessionModeManager 初始化完成（含定期 GC 和语种管理）")

    # ==================== Redis 初始化 ====================

    def _build_redis_store(self):
        """从环境变量（或默认参数）构建 Redis 存储实例"""
        try:
            from redis_store import create_redis_store
            return create_redis_store()
        except ImportError:
            logger.warning("redis_store 未安装，session_mode 将在纯内存模式运行")
            return None

    def _init_redis_async(self):
        """异步初始化 Redis（后台线程中运行 asyncio）"""
        if self._redis_store is None:
            return
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(self._redis_store.connect())
            finally:
                loop.close()

            self._redis_available = self._redis_store.is_available
            if self._redis_available:
                logger.info("SessionMode: Redis 连接成功，开始加载会话数据...")
                self._load_from_redis()
            else:
                logger.warning("SessionMode: Redis 不可用，将使用纯内存模式")

            # 启动 Redis 同步线程（每 60s 同步一次）
            self._sync_thread = threading.Thread(
                target=self._sync_to_redis_loop, daemon=True, name="SessionMode-RedisSync"
            )
            self._sync_thread.start()
        except Exception as e:
            logger.warning(f"SessionMode: Redis 初始化失败: {e}，将使用纯内存模式")
            self._redis_available = False

    def _load_from_redis(self):
        """
        进程启动时从 Redis 加载所有会话数据到内存。
        防止 Redis 重启后内存状态丢失。
        """
        if not self._redis_available:
            return

        try:
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loaded = loop.run_until_complete(self._redis_store.get_all_agent_session_counts())
            finally:
                loop.close()
        except Exception as e:
            logger.warning(f"SessionMode: 从 Redis 加载会话数据失败: {e}")
            return

        if not loaded:
            self._redis_load_done = True
            logger.info("SessionMode: Redis 加载完成（无历史会话）")
            return

        count = 0
        with self._lock:
            for agent_id, session_list in loaded.items():
                if not session_list:
                    continue
                if agent_id not in self._agent_to_sessions:
                    self._agent_to_sessions[agent_id] = []
                for sid in session_list:
                    if sid not in self._agent_to_sessions[agent_id]:
                        self._agent_to_sessions[agent_id].append(sid)
                    self._session_to_agent[sid] = agent_id
                    self._modes[sid] = SessionMode.HUMAN
                    count += 1

        self._redis_load_done = True
        logger.info(f"SessionMode: 从 Redis 加载了 {count} 条会话分配记录（{len(loaded)} 个坐席）")

    def _sync_to_redis_loop(self):
        """每 60s 将内存中的会话分配数据同步到 Redis"""
        while self._sync_running:
            time.sleep(60)
            if not self._redis_available:
                continue
            try:
                self._sync_agent_assignments_to_redis()
            except Exception as e:
                logger.warning(f"SessionMode: Redis 同步失败: {e}")

    def _sync_agent_assignments_to_redis(self):
        """将内存中的坐席分配映射批量同步到 Redis"""
        try:
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(self._async_sync_agent_assignments())
            finally:
                loop.close()
        except Exception as e:
            logger.warning(f"SessionMode: Redis 同步（async）失败: {e}")

    async def _async_sync_agent_assignments(self):
        """异步同步坐席分配到 Redis"""
        if not self._redis_available or not self._redis_store.is_available:
            return

        with self._lock:
            items = list(self._session_to_agent.items())

        for session_id, agent_id in items:
            try:
                await self._redis_store.assign_session_to_agent(session_id, agent_id)
            except Exception:
                pass   # 单条失败不影响其他

    # ==================== Redis 状态查询 ====================

    @property
    def redis_available(self) -> bool:
        """Redis 是否当前可用"""
        if self._redis_store is None:
            return False
        return self._redis_store.is_available and self._redis_available

    # ==================== 模式读写 ====================

    def get_mode(self, session_id: str) -> SessionMode:
        """获取当前会话模式，未知会话默认 AI"""
        with self._lock:
            mode = self._modes.get(session_id)
            if mode is not None:
                return mode
            # 内存没有，查 Redis
            if self._redis_available and self._redis_store and self._redis_store.is_available:
                try:
                    import asyncio
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        data = loop.run_until_complete(
                            self._redis_store.get_session(session_id)
                        )
                    finally:
                        loop.close()
                    if data:
                        mode_str = data.get("status") or "ai"
                        if mode_str == "human":
                            return SessionMode.HUMAN
                        elif mode_str == "waiting":
                            return SessionMode.WAITING
                        return SessionMode.AI
                except Exception:
                    pass
            return SessionMode.AI

    def is_ai_mode(self, session_id: str) -> bool:
        return self.get_mode(session_id) == SessionMode.AI

    def is_human_mode(self, session_id: str) -> bool:
        return self.get_mode(session_id) == SessionMode.HUMAN

    # ==================== 模式切换 ====================

    def _sync_to_redis(self, session_id: str, mode: SessionMode, agent_id: str = "",
                       ai_since: str = ""):
        """将状态变更写入 Redis（后台，不阻塞主逻辑）"""
        if not self._redis_available:
            return

        def _do():
            try:
                import asyncio
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(self._async_sync_to_redis(
                        session_id, mode, agent_id, ai_since))
                finally:
                    loop.close()
            except Exception as e:
                logger.warning(f"SessionMode Redis 同步失败: {e}")

        threading.Thread(target=_do, daemon=True).start()

    async def _async_sync_to_redis(self, session_id: str, mode: SessionMode,
                                    agent_id: str, ai_since: str):
        """异步同步到 Redis"""
        if not self._redis_available or not self._redis_store or not self._redis_store.is_available:
            return

        try:
            if mode == SessionMode.HUMAN and agent_id:
                await self._redis_store.assign_session_to_agent(session_id, agent_id)
            elif mode == SessionMode.WAITING:
                await self._redis_store.unassign_session(session_id)
            elif mode == SessionMode.AI:
                await self._redis_store.unassign_session(session_id)
        except Exception as e:
            logger.warning(f"SessionMode async sync to Redis failed: {e}")

    def switch_to_ai(self, session_id: str) -> str:
        """
        切换到 AI 模式。
        记录切换时间（AI 对话历史过滤用）。
        返回 ai_mode_since 时间字符串。
        """
        with self._lock:
            self._modes[session_id] = SessionMode.AI
            # 释放坐席
            old_agent = self._session_to_agent.pop(session_id, None)
            if old_agent and old_agent in self._agent_to_sessions:
                lst = self._agent_to_sessions[old_agent]
                if session_id in lst:
                    lst.remove(session_id)
            ts = datetime.utcnow().isoformat()
            self._ai_mode_since[session_id] = ts
            logger.info(f"[Mode] session={session_id} 切换到 AI（ai_mode_since={ts}）")
            # 异步写 Redis
            self._sync_to_redis(session_id, SessionMode.AI, ai_since=ts)
            return ts

    def switch_to_waiting(self, session_id: str) -> bool:
        """切换到等待分配模式"""
        with self._lock:
            old = self._modes.get(session_id)
            self._modes[session_id] = SessionMode.WAITING
            if old != SessionMode.WAITING:
                logger.info(f"[Mode] session={session_id} → WAITING")
                self._sync_to_redis(session_id, SessionMode.WAITING)
                return True
            return False

    def switch_to_human(self, session_id: str, agent_id: str) -> bool:
        """
        切换到人工模式，并分配坐席。
        返回 True 表示成功，False 表示会话已被其他坐席接管。
        
        【安全优化 v2】使用 Redis 分布式锁防止多进程并发竞态条件。
        在集群环境下（多实例），仅靠 threading.Lock 无法保护跨进程数据。
        """
        lock_key = f"lock:switch_human:{session_id}"
        lock_acquired = False
        
        # 尝试获取 Redis 分布式锁（用于跨实例保护）
        try:
            from redis_lock import RedisDistributedLock, _ensure_redis
            if _ensure_redis():
                _lock = RedisDistributedLock("switch_human", session_id, ttl=5)
                if not _lock.acquire(blocking=True, timeout=3):
                    logger.warning(f"[Mode] 会话 {session_id} 切换 HUMAN 时获取锁失败，跳过")
                    return False
                lock_acquired = True
        except Exception as e:
            logger.debug(f"[Mode] Redis 锁不可用，使用线程锁保护: {e}")
        
        try:
            with self._lock:
                existing = self._session_to_agent.get(session_id)
                if existing and existing != agent_id:
                    logger.warning(f"[Mode] 会话 {session_id} 已被坐席 {existing} 接管，拒绝分配给 {agent_id}")
                    return False

                old = self._modes.get(session_id)
                self._modes[session_id] = SessionMode.HUMAN
                self._session_to_agent[session_id] = agent_id
                if agent_id not in self._agent_to_sessions:
                    self._agent_to_sessions[agent_id] = []
                if session_id not in self._agent_to_sessions[agent_id]:
                    self._agent_to_sessions[agent_id].append(session_id)
                logger.info(f"[Mode] session={session_id} → HUMAN (agent={agent_id})")
                # 异步写 Redis（立即，不等待60s同步）
                self._sync_to_redis(session_id, SessionMode.HUMAN, agent_id=agent_id)
                return True
        finally:
            if lock_acquired:
                try:
                    _lock.release()
                except Exception:
                    pass

    def unassign_agent(self, session_id: str) -> Optional[str]:
        """取消会话的坐席分配（不改变模式）"""
        with self._lock:
            old_agent = self._session_to_agent.pop(session_id, None)
            if old_agent and old_agent in self._agent_to_sessions:
                lst = self._agent_to_sessions[old_agent]
                if session_id in lst:
                    lst.remove(session_id)
            if old_agent:
                self._released_sessions[session_id] = time.time()
                logger.info(f"[Mode] session={session_id} 取消分配坐席 {old_agent}")
                # 异步写 Redis
                self._sync_to_redis(session_id, self._modes.get(session_id, SessionMode.AI))
            return old_agent

    def get_agent(self, session_id: str) -> Optional[str]:
        """获取会话当前分配的坐席ID"""
        with self._lock:
            if self._modes.get(session_id) == SessionMode.HUMAN:
                return self._session_to_agent.get(session_id)
            return None

    def get_ai_mode_since(self, session_id: str) -> str:
        """获取该会话切换到 AI 模式的 UTC 时间（ISO），供 AI 历史过滤用"""
        with self._lock:
            return self._ai_mode_since.get(session_id, "")

    def get_agent_sessions(self, agent_id: str) -> List[str]:
        """获取坐席负责的所有活跃会话"""
        with self._lock:
            return list(self._agent_to_sessions.get(agent_id, []))

    def get_all_agent_session_counts(self) -> Dict[str, int]:
        """获取所有坐席的会话数（用于负载均衡）"""
        with self._lock:
            return {aid: len(sids) for aid, sids in self._agent_to_sessions.items()}

    def get_waiting_sessions(self) -> List[str]:
        """获取所有 WAITING 状态的会话"""
        with self._lock:
            return [sid for sid, m in self._modes.items() if m == SessionMode.WAITING]

    def get_human_sessions(self) -> List[str]:
        """获取所有 HUMAN 状态的会话"""
        with self._lock:
            return [sid for sid, m in self._modes.items() if m == SessionMode.HUMAN]

    def get_ai_sessions(self) -> List[str]:
        """获取所有 AI 模式的会话"""
        with self._lock:
            return [sid for sid, m in self._modes.items() if m == SessionMode.AI]

    # ==================== GC ====================

    def _gc_loop(self):
        """每 5 分钟清理一次超过 1 小时的已释放会话条目"""
        while self._gc_running:
            time.sleep(300)
            try:
                self._gc_released_sessions()
            except Exception as e:
                logger.warning(f"[GC] 清理已释放会话失败: {e}")

    def _gc_released_sessions(self):
        """删除超过 1 小时的已释放会话记录"""
        cutoff = time.time() - 3600
        with self._lock:
            expired = [sid for sid, t in self._released_sessions.items() if t < cutoff]
            for sid in expired:
                self._released_sessions.pop(sid, None)
                self._modes.pop(sid, None)
                self._ai_mode_since.pop(sid, None)
                self._session_to_agent.pop(sid, None)
                self._target_langs.pop(sid, None)  # 同时清理语种记录
            if expired:
                logger.info(f"[GC] 清理了 {len(expired)} 条已释放会话记录（含语种）")

    def close(self):
        """停止 GC 和同步（进程退出时调用）"""
        self._gc_running = False
        self._sync_running = False
        # 退出前强制同步一次
        try:
            self._sync_agent_assignments_to_redis()
        except Exception:
            pass

    # ==================== 语种状态管理（支持客户中途切换语言） ====================

    def set_target_language(self, session_id: str, lang: str) -> bool:
        """
        设置会话的目标语言。
        当客户中途切换语言时调用，即时更新状态并刷新后续回复的 Prompt 语种指令。

        Args:
            session_id: 会话ID
            lang: 目标语言代码（如 'zh', 'en', 'ar' 等）

        Returns:
            bool: 是否成功设置
        """
        if not lang or lang not in ("zh", "en", "ar", "ru", "th", "vi", "id", "ms", "tl"):
            logger.warning(f"[i18n] 不支持的目标语言: {lang}")
            return False

        with self._lock:
            old_lang = self._target_langs.get(session_id)
            self._target_langs[session_id] = lang

        logger.info(f"[i18n] 会话 {session_id} 语言切换: {old_lang} -> {lang}")

        # 异步同步到 Redis
        self._sync_language_to_redis(session_id, lang)
        return True

    def get_target_language(self, session_id: str) -> str:
        """
        获取会话的目标语言。
        如果未设置，返回默认语言 'zh'。
        """
        with self._lock:
            return self._target_langs.get(session_id, "zh")

    def _sync_language_to_redis(self, session_id: str, lang: str):
        """异步同步语种到 Redis"""
        def _do():
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    if self._redis_available and self._redis_store and self._redis_store.is_available:
                        loop.run_until_complete(
                            self._redis_store.update_session_language(session_id, lang)
                        )
                finally:
                    loop.close()
            except Exception as e:
                logger.warning(f"[i18n] 语种同步到Redis失败: {e}")

        threading.Thread(target=_do, daemon=True).start()

    # ==================== 兼容层（供 agent_service 代理） ====================

    def get_session_agent(self, session_id: str) -> Optional[str]:
        return self.get_agent(session_id)

    def release_session(self, session_id: str) -> bool:
        """兼容 agent_service.release_session"""
        with self._lock:
            if self._modes.get(session_id) != SessionMode.HUMAN:
                return False
        self.unassign_agent(session_id)
        self.switch_to_waiting(session_id)
        return True

    def assign_session(self, session_id: str, agent_id: str) -> bool:
        """兼容 agent_service.assign_session"""
        return self.switch_to_human(session_id, agent_id)


# 全局单例
session_mode = SessionModeManager()
