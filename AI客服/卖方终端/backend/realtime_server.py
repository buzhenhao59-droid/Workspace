# -*- coding: utf-8 -*-
"""
实时消息服务 - WebSocket 核心模块
支持客户与坐席的实时双向通信，用于商用多客服协作场景。
Redis 集成：会话分配、会话计数、等待队列支持 Redis 存储（分布式部署）

【重要】会话分配状态统一到 session_mode.py，不再各自维护。
realtime_server 是 session_mode 的单一写入方（负责分配/释放/切换）；
agent_service 和所有 API 只读 session_mode。
"""
import asyncio
import json
import logging
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

from fastapi.websockets import WebSocketDisconnect

logger = logging.getLogger(__name__)

# 会话模式单例（单一数据源）
_session_mode = None


def _get_mode_manager():
    global _session_mode
    if _session_mode is None:
        from session_mode import session_mode as m
        globals()["_session_mode"] = m
    return _session_mode


# Redis 集成（可选，无 Redis 时回退到内存）
_redis_store = None
try:
    from redis_store import redis_store as _redis_store
    _redis_available = True
except ImportError:
    _redis_available = False
    _redis_store = None
    logger.warning("Redis 模块未加载，realtime_server 使用内存存储（单服务器模式）")


class UserType(str, Enum):
    CUSTOMER = "customer"
    AGENT = "agent"


class MessageType(str, Enum):
    TEXT = "text"
    IMAGE = "image"
    VOICE = "voice"
    SYSTEM = "system"


@dataclass
class ChatMessage:
    """聊天消息数据结构"""
    id: str
    session_id: str
    from_type: str  # 'customer' | 'agent' | 'ai' | 'system'
    from_id: str    # customer_id / agent_id
    content: str
    msg_type: str = "text"
    created_at: str = ""
    is_read: bool = False

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
        if not self.id:
            self.id = str(uuid.uuid4())

    def to_ws_payload(self) -> dict:
        return {
            "type": "message",
            "data": {
                "id": self.id,
                "session_id": self.session_id,
                "from_type": self.from_type,
                "from_id": self.from_id,
                "content": self.content,
                "msg_type": self.msg_type,
                "created_at": self.created_at,
                "is_read": self.is_read,
            }
        }

    def to_broadcast_payload(self, exclude_id: str = "") -> dict:
        return {
            "type": "new_message",
            "data": {
                "id": self.id,
                "session_id": self.session_id,
                "from_type": self.from_type,
                "from_id": self.from_id,
                "content": self.content,
                "msg_type": self.msg_type,
                "created_at": self.created_at,
            }
        }


@dataclass
class CustomerConnection:
    """客户连接状态"""
    ws: any  # WebSocket
    customer_id: str
    session_id: str
    language: str = "zh"
    connected_at: float = field(default_factory=time.time)


@dataclass
class AgentConnection:
    """坐席连接状态"""
    ws: any  # WebSocket
    agent_id: str
    agent_name: str
    role: str = "agent"  # 'agent' | 'manager' | 'admin'
    assigned_sessions: list = field(default_factory=list)
    status: str = "online"  # 'online' | 'busy' | 'away' | 'offline'
    connected_at: float = field(default_factory=time.time)
    current_session: Optional[str] = None  # 当前正在查看的会话ID


class RealtimeMessageServer:
    """
    实时消息服务器 - 管理所有 WebSocket 连接和消息路由。

    核心功能：
    1. 客户连接管理 - 客户浏览器与服务器的实时通道
    2. 坐席连接管理 - 人工客服工作台的实时通道
    3. 消息路由 - 客户 ↔ 坐席 消息的实时推送
    4. 会话分配 - 新会话自动/手动分配给坐席
    5. 状态同步 - 坐席在线状态、客户等待队列实时更新

    内存管理：
    - 消息缓冲区大小限制（单会话最多100条）
    - 定期清理过期缓冲区
    - WebSocket 连接健康监控
    """

    def __init__(self):
        # 客户连接池: session_id -> CustomerConnection
        self.customer_connections: dict[str, CustomerConnection] = {}
        # 坐席连接池: agent_id -> AgentConnection
        self.agent_connections: dict[str, AgentConnection] = {}
        # 【移除】session_to_agent / agent_to_sessions 已统一到 session_mode
        # 锁，保证线程安全
        self._lock = asyncio.Lock()
        # 【保留】本地等待队列视图（session_mode.WAITING 的子集，仅含客户已连 WS 的）
        self.waiting_queue: list[str] = []
        # 消息缓冲（客户离线时缓冲消息）
        self._message_buffer: dict[str, list] = defaultdict(list)
        # 消息缓冲区大小限制（内存泄漏防护）
        self._MAX_BUFFER_SIZE = 100
        # 连接统计（用于健康监控）
        self._stats = {
            "total_customers_served": 0,
            "total_agents_served": 0,
            "peak_customers_online": 0,
            "peak_agents_online": 0,
        }
        logger.info("RealtimeMessageServer 初始化完成（含内存管理）")

    # ==================== 连接管理 ====================

    async def connect_customer(
        self,
        ws,
        session_id: str,
        customer_id: str = "",
        language: str = "zh"
    ) -> CustomerConnection:
        """客户建立 WebSocket 连接"""
        conn = CustomerConnection(
            ws=ws,
            customer_id=customer_id,
            session_id=session_id,
            language=language,
        )
        async with self._lock:
            self.customer_connections[session_id] = conn
            # 注意：不在此处从 waiting_queue 移除；未分配坐席时仍应在队列中，
            # 由 assign_session_to_agent 成功分配后再移除，否则会出现「客户已上线但永远未分配」
            # 推送离线缓冲消息
            buffered = self._message_buffer.pop(session_id, [])
            for msg in buffered:
                await self._send_ws_json(ws, msg)
            # 通知坐席有新连接
            await self._broadcast_to_agents({
                "type": "customer_connected",
                "data": {
                    "session_id": session_id,
                    "customer_id": customer_id,
                    "timestamp": time.time()
                }
            })
        logger.info(f"客户连接: session={session_id}, customer={customer_id}")
        # 若已转人工但仍未绑定坐席（例如先前无坐席在线），客户上线后再尝试自动分配
        mode_mgr = _get_mode_manager()
        if not mode_mgr.is_human_mode(session_id):
            try:
                from db import get_session as _gs
                row = _gs(session_id)
                if row and (row.get("is_ai") in (0, False)):
                    await self.auto_assign_session(session_id)
            except Exception as e:
                logger.warning(f"客户上线后尝试补分配失败: {e}")
        return conn

    async def connect_agent(
        self,
        ws,
        agent_id: str,
        agent_name: str = "",
        role: str = "agent"
    ) -> AgentConnection:
        """坐席建立 WebSocket 连接"""
        conn = AgentConnection(
            ws=ws,
            agent_id=agent_id,
            agent_name=agent_name or agent_id,
            role=role,
        )
        async with self._lock:
            self.agent_connections[agent_id] = conn
            # 通知所有坐席在线状态变化
            await self._broadcast_to_agents({
                "type": "agent_status_changed",
                "data": self.get_all_agents_status()
            }, exclude_agent=agent_id)

        # ========== Redis 坐席上线（分布式支持）==========
        if _redis_store and _redis_store.is_available:
            try:
                await _redis_store.set_agent_online(agent_id, agent_name, role)
            except Exception as e:
                logger.warning(f"Redis 坐席 {agent_id} 上线失败: {e}")

        logger.info(f"坐席连接: agent={agent_id}, role={role}")
        return conn

    async def disconnect_customer(self, session_id: str):
        """客户断开连接"""
        async with self._lock:
            conn = self.customer_connections.pop(session_id, None)
            if conn:
                logger.info(f"客户断开: session={session_id}")
                self._stats["total_customers_served"] += 1
            # 清理消息缓冲区（内存泄漏防护）
            if session_id in self._message_buffer:
                del self._message_buffer[session_id]
                logger.debug(f"[Memory] 清理会话缓冲区: session={session_id}")
            # 等待队列中的客户断开后从等待队列移除（session_mode 内部也跟踪）
            mode_mgr = _get_mode_manager()
            waiting = mode_mgr.get_waiting_sessions()
            if session_id in waiting:
                mode_mgr.unassign_agent(session_id)

    async def disconnect_agent(self, agent_id: str):
        """坐席断开连接"""
        async with self._lock:
            conn = self.agent_connections.pop(agent_id, None)
            if not conn:
                return
            # 从 session_mode 释放该坐席的所有会话
            mode_mgr = _get_mode_manager()
            sessions = mode_mgr.get_agent_sessions(agent_id)
            for s_id in sessions:
                mode_mgr.unassign_agent(s_id)
                if s_id in self.customer_connections:
                    mode_mgr.switch_to_waiting(s_id)
                    await self._notify_customer_session_update(s_id, {
                        "type": "agent_offline",
                        "data": {"session_id": s_id}
                    })
            # 通知其他坐席
            await self._broadcast_to_agents({
                "type": "agent_status_changed",
                "data": self.get_all_agents_status()
            }, exclude_agent=agent_id)

        # ========== Redis 清理（分布式支持）已由 session_mode.unassign_agent 异步处理 ==========
        if _redis_store and _redis_store.is_available:
            try:
                for s_id in sessions:
                    await _redis_store.unassign_session(s_id)
                    await _redis_store.add_to_waiting_queue(s_id)
                await _redis_store.set_agent_offline(agent_id)
            except Exception as e:
                logger.warning(f"Redis 清理坐席 {agent_id} 会话失败: {e}")

        logger.info(f"坐席断开: agent={agent_id}")

    # ==================== 消息发送 ====================

    async def send_message(
        self,
        session_id: str,
        from_type: str,
        from_id: str,
        content: str,
        msg_type: str = "text"
    ) -> ChatMessage:
        """发送消息 - 消息入库后推送给对方"""
        msg = ChatMessage(
            id=str(uuid.uuid4()),
            session_id=session_id,
            from_type=from_type,
            from_id=from_id,
            content=content,
            msg_type=msg_type,
        )

        # 确定接收方（读 session_mode 单一数据源）
        mode_mgr = _get_mode_manager()
        if from_type == "customer":
            target_agent_id = mode_mgr.get_agent(session_id)
            if target_agent_id and target_agent_id in self.agent_connections:
                # 在线坐席 - 直接推送
                await self._send_ws_json(
                    self.agent_connections[target_agent_id].ws,
                    msg.to_broadcast_payload()
                )
            else:
                # 离线或未分配 - 缓冲消息（带大小限制，防止内存泄漏）
                self._add_to_buffer(session_id, msg.to_ws_payload())
        elif from_type in ("agent", "ai", "system"):
            # 推送给客户
            if session_id in self.customer_connections:
                await self._send_ws_json(
                    self.customer_connections[session_id].ws,
                    msg.to_broadcast_payload()
                )
            else:
                # 客户离线 - 缓冲（带大小限制）
                self._add_to_buffer(session_id, msg.to_ws_payload())

        return msg

    def _add_to_buffer(self, session_id: str, msg: dict):
        """
        添加消息到缓冲区，带大小限制。
        内存泄漏防护：单会话最多保留100条消息。
        """
        buffer = self._message_buffer[session_id]
        buffer.append(msg)
        # 超过限制时，移除最老的消息
        if len(buffer) > self._MAX_BUFFER_SIZE:
            buffer.pop(0)
            logger.debug(f"[Memory] 缓冲区超过限制，清理最老消息: session={session_id}")

    async def send_system_message(self, session_id: str, content: str):
        """发送系统消息"""
        await self.send_message(session_id, "system", "system", content, "system")

    # ==================== 会话分配 ====================

    async def assign_session_to_agent(self, session_id: str, agent_id: str) -> bool:
        """
        将会话分配给指定坐席（单一数据源：session_mode）。
        客户未连 WebSocket 时仍完成模式切换（坐席可接待、统计正确）；客户上线后再推送 agent_assigned。
        """
        async with self._lock:
            if agent_id not in self.agent_connections:
                logger.warning(f"坐席 {agent_id} 不在线")
                return False

            mode_mgr = _get_mode_manager()
            customer_online = session_id in self.customer_connections

            # ── P1 FIX: switch_to_human 已加入防重复分配检查，False 时中止 ──
            if not mode_mgr.switch_to_human(session_id, agent_id):
                logger.warning(f"会话 {session_id} 已被其他坐席接管，跳过分配")
                return False

            # 从等待队列移除（读 session_mode）
            from session_mode import SessionMode
            if mode_mgr.get_mode(session_id) == SessionMode.WAITING:
                pass  # 已由 switch_to_human 处理

            # 客户信息
            cust_id = ""
            cust_lang = "zh"
            if customer_online:
                cust_id = self.customer_connections[session_id].customer_id
                cust_lang = self.customer_connections[session_id].language or "zh"
            else:
                try:
                    from db import get_session as _get_sess
                    row = _get_sess(session_id)
                    if row:
                        cust_id = row.get("customer_id") or ""
                        cust_lang = (row.get("language") or "zh").strip() or "zh"
                except Exception as e:
                    logger.warning(f"读取会话 {session_id} 客户信息失败: {e}")

            # 同步到 agent_service（仅读，不写）
            try:
                from agent_service import agent_service
                agent_service.assign_session(session_id, agent_id)
            except Exception as e:
                logger.warning(f"agent_service.assign_session 同步失败: {e}")

            # Redis 持久化已由 session_mode.switch_to_human 异步处理
            # 这里仅记录日志供调试（可选：读回 Redis 确认）
            if _redis_store and _redis_store.is_available:
                try:
                    await _redis_store.remove_from_waiting_queue(session_id)
                except Exception:
                    pass

            # 通知坐席有新会话
            await self._send_ws_json(
                self.agent_connections[agent_id].ws,
                {
                    "type": "session_assigned",
                    "data": {
                        "session_id": session_id,
                        "customer_id": cust_id,
                        "language": cust_lang,
                    }
                }
            )

            # 通知客户已被接起（仅当客户已连 WS）
            if customer_online:
                await self._send_ws_json(
                    self.customer_connections[session_id].ws,
                    {
                        "type": "agent_assigned",
                        "data": {
                            "session_id": session_id,
                            "agent_id": agent_id,
                            "agent_name": self.agent_connections[agent_id].agent_name,
                        }
                    }
                )

            # 广播坐席状态
            await self._broadcast_to_agents({
                "type": "agent_status_changed",
                "data": self.get_all_agents_status()
            })

        logger.info(
            f"会话分配: session={session_id} -> agent={agent_id} (customer_ws={'on' if customer_online else 'off'})"
        )
        return True

    async def auto_assign_session(self, session_id: str) -> Optional[str]:
        """
        自动分配会话给最空闲的坐席（轮询负载均衡）。
        写 session_mode（单一数据源）。
        """
        async with self._lock:
            mode_mgr = _get_mode_manager()

            online_agents = [
                (aid, len(mode_mgr.get_agent_sessions(aid)))
                for aid in self.agent_connections
                if self.agent_connections[aid].status == "online"
            ]
            if not online_agents:
                return None

            # 选择负载最轻的坐席
            online_agents.sort(key=lambda x: x[1])
            target_agent = online_agents[0][0]

            if target_agent in self.agent_connections:
                # 检查会话是否已被分配（防止并发重复分配）
                existing_agent = mode_mgr.get_agent(session_id)
                if existing_agent:
                    logger.info(f"会话 {session_id} 已被坐席 {existing_agent} 抢先分配，跳过")
                    return existing_agent

                customer_online = session_id in self.customer_connections
                cust_id = ""
                cust_lang = "zh"
                if customer_online:
                    cust_id = self.customer_connections[session_id].customer_id
                    cust_lang = self.customer_connections[session_id].language or "zh"
                else:
                    try:
                        from db import get_session as _get_sess
                        row = _get_sess(session_id)
                        if row:
                            cust_id = row.get("customer_id") or ""
                            cust_lang = (row.get("language") or "zh").strip() or "zh"
                    except Exception as e:
                        logger.warning(f"读取会话 {session_id} 客户信息失败: {e}")

                # 写单一数据源
                mode_mgr.switch_to_human(session_id, target_agent)

                # 同步到 agent_service
                try:
                    from agent_service import agent_service
                    agent_service.assign_session(session_id, target_agent)
                except Exception as e:
                    logger.warning(f"agent_service.assign_session 同步失败: {e}")

                # Redis 持久化已由 session_mode.switch_to_human 异步处理
                if _redis_store and _redis_store.is_available:
                    try:
                        await _redis_store.remove_from_waiting_queue(session_id)
                    except Exception:
                        pass

                # 通知坐席
                await self._send_ws_json(
                    self.agent_connections[target_agent].ws,
                    {
                        "type": "session_assigned",
                        "data": {
                            "session_id": session_id,
                            "customer_id": cust_id,
                            "language": cust_lang,
                        }
                    }
                )

                # 通知客户
                if customer_online:
                    await self._send_ws_json(
                        self.customer_connections[session_id].ws,
                        {
                            "type": "agent_assigned",
                            "data": {
                                "session_id": session_id,
                                "agent_id": target_agent,
                                "agent_name": self.agent_connections[target_agent].agent_name,
                            }
                        }
                    )

                # 广播状态
                await self._broadcast_to_agents({
                    "type": "agent_status_changed",
                    "data": self.get_all_agents_status()
                })

                logger.info(f"自动分配会话: session={session_id} -> agent={target_agent}")
                return target_agent

        return None

    async def release_session(self, session_id: str) -> bool:
        """
        释放会话（坐席放弃或转接）：从 HUMAN 切到 WAITING。
        """
        async with self._lock:
            mode_mgr = _get_mode_manager()
            old_agent = mode_mgr.unassign_agent(session_id)
            mode_mgr.switch_to_waiting(session_id)
            if session_id in self.customer_connections:
                # 保持等待，不自动加 waiting_queue（已在 switch_to_waiting 跟踪）
                pass
            try:
                from agent_service import agent_service
                agent_service.release_session(session_id)
            except Exception as e:
                logger.warning(f"agent_service.release_session 同步失败: {e}")
            await self._broadcast_to_agents({
                "type": "session_released",
                "data": {
                    "session_id": session_id,
                    "agent_id": old_agent
                }
            })
        logger.info(f"会话释放: session={session_id}, old_agent={old_agent}")
        return True

    # ==================== 坐席状态 ====================

    async def set_agent_status(self, agent_id: str, status: str):
        """设置坐席状态"""
        async with self._lock:
            if agent_id not in self.agent_connections:
                return
            self.agent_connections[agent_id].status = status
            await self._broadcast_to_agents({
                "type": "agent_status_changed",
                "data": self.get_all_agents_status()
            })

    async def set_agent_current_session(self, agent_id: str, session_id: str):
        """坐席切换当前查看的会话"""
        async with self._lock:
            if agent_id in self.agent_connections:
                self.agent_connections[agent_id].current_session = session_id

    def get_all_agents_status(self) -> list:
        """获取所有在线坐席状态列表"""
        mode_mgr = _get_mode_manager()
        result = []
        for agent_id, conn in self.agent_connections.items():
            session_count = len(mode_mgr.get_agent_sessions(agent_id))
            result.append({
                "agent_id": agent_id,
                "agent_name": conn.agent_name,
                "role": conn.role,
                "status": conn.status,
                "session_count": session_count,
                "current_session": conn.current_session,
            })
        return result

    def get_session_info(self, session_id: str) -> Optional[dict]:
        """获取会话详情"""
        from session_mode import SessionMode
        mode_mgr = _get_mode_manager()
        current_mode = mode_mgr.get_mode(session_id)
        info = {
            "session_id": session_id,
            "mode": current_mode.value,
            "agent_id": mode_mgr.get_agent(session_id),
            "ai_mode_since": mode_mgr.get_ai_mode_since(session_id),
            "is_waiting": current_mode == SessionMode.WAITING,
            "is_human": mode_mgr.is_human_mode(session_id),
            "is_ai": mode_mgr.is_ai_mode(session_id),
            "customer_online": session_id in self.customer_connections,
        }
        if session_id in self.customer_connections:
            c = self.customer_connections[session_id]
            info["customer_id"] = c.customer_id
            info["language"] = c.language
        return info

    def get_waiting_count(self) -> int:
        """获取等待队列长度"""
        mode_mgr = _get_mode_manager()
        return len(mode_mgr.get_waiting_sessions())

    def get_online_stats(self) -> dict:
        """获取实时统计数据"""
        mode_mgr = _get_mode_manager()
        waiting = mode_mgr.get_waiting_sessions()
        human = mode_mgr.get_human_sessions()
        return {
            "online_agents": len(self.agent_connections),
            "total_sessions": len(mode_mgr.get_human_sessions()) + len(mode_mgr.get_waiting_sessions()),
            "waiting_count": len(waiting),
            "human_count": len(human),
            "customer_online": len(self.customer_connections),
            "redis_available": (_redis_store and _redis_store.is_available),
        }

    # ==================== 内部工具 ====================

    async def _send_ws_json(self, ws, data: dict):
        """安全发送 JSON 到 WebSocket"""
        try:
            await ws.send_json(data)
        except Exception as e:
            logger.warning(f"WebSocket 发送失败: {e}")

    async def _broadcast_to_agents(self, message: dict, exclude_agent: str = ""):
        """广播消息给所有在线坐席（可选排除）"""
        for agent_id, conn in self.agent_connections.items():
            if agent_id != exclude_agent:
                await self._send_ws_json(conn.ws, message)

    async def _notify_customer_session_update(self, session_id: str, message: dict):
        """通知客户会话状态变更"""
        if session_id in self.customer_connections:
            await self._send_ws_json(
                self.customer_connections[session_id].ws,
                message
            )


    # ==================== FastAPI WebSocket 端点适配 ====================

    async def handle_websocket(self, websocket, session_id: str):
        """
        供 main.py @app.websocket("/ws/{session_id}") 调用。
        接收客户连接 → 进入消息循环 → 客户断开时清理。
        """
        await websocket.accept()
        # 从客户端第一个消息读认证信息（customer_id, language）
        try:
            first = await asyncio.wait_for(websocket.receive_text(), timeout=10)
            info = {}
            try:
                info = json.loads(first)
            except Exception:
                # 纯文本时当作 customer_id
                info = {"customer_id": first.strip()}
        except asyncio.TimeoutError:
            logger.warning(f"WS {session_id} 认证超时，关闭")
            await websocket.close(code=1011, reason="Auth timeout")
            return

        customer_id = info.get("customer_id", "")
        language = info.get("language", "zh")

        await self.connect_customer(websocket, session_id, customer_id=customer_id, language=language)

        # 消息循环：客户端发消息 → 路由
        try:
            while True:
                raw = await websocket.receive_text()
                msg_data = {}
                try:
                    msg_data = json.loads(raw)
                except Exception:
                    msg_data = {"content": raw, "type": "text"}

                msg_type = msg_data.get("type", "text")
                content = msg_data.get("content", "")

                if msg_type == "ping":
                    await self._send_ws_json(websocket, {"type": "pong"})
                    continue

                if msg_type in ("text", "file", "image"):
                    await self.send_message(
                        session_id=session_id,
                        sender="customer",
                        content=content,
                        msg_type=msg_type,
                        customer_id=customer_id,
                        language=language,
                        metadata=msg_data.get("metadata"),
                    )
                elif msg_type == "agent_chat":
                    await self.send_message(
                        session_id=session_id,
                        sender="agent",
                        content=content,
                        msg_type="text",
                        agent_id=info.get("agent_id"),
                        metadata=msg_data.get("metadata"),
                    )
        except WebSocketDisconnect:
            logger.info(f"WS 客户断开: session={session_id}")
        except Exception as e:
            logger.warning(f"WS 客户异常: session={session_id}, e={e}")
        finally:
            await self.disconnect_customer(session_id)

    async def handle_agent_websocket(self, websocket, agent_id: str):
        """
        供 main.py @app.websocket("/ws/agent/{agent_id}") 调用。
        坐席工作台连接 → 认证 → 接收坐席消息并路由到对应客户。
        """
        await websocket.accept()
        logger.info(f"坐席 WS 已 accept: agent={agent_id}, url={websocket.url}")
        # 认证：从第一个消息取 agent_name / role
        try:
            first = await asyncio.wait_for(websocket.receive_text(), timeout=10)
            logger.info(f"坐席 WS 收到首个消息: agent={agent_id}, first={first[:200]}")
            info = {}
            try:
                info = json.loads(first)
            except Exception:
                info = {}
            agent_name = info.get("agent_name", agent_id)
            role = info.get("role", "agent")
        except asyncio.TimeoutError:
            await websocket.close(code=1011, reason="Auth timeout")
            return

        await self.connect_agent(websocket, agent_id, agent_name=agent_name, role=role)

        try:
            while True:
                raw = await websocket.receive_text()
                msg_data = {}
                try:
                    msg_data = json.loads(raw)
                except Exception:
                    msg_data = {"content": raw, "type": "text"}

                msg_type = msg_data.get("type", "text")

                if msg_type == "ping":
                    await self._send_ws_json(websocket, {"type": "pong"})
                    continue

                if msg_type == "pong":
                    # 收到心跳回复，跳过正常处理
                    continue

                if msg_type == "auth":
                    logger.info(f"坐席 WS 认证成功: agent={agent_id}, msg_data={msg_data}")

                if msg_type == "send_message":
                    # 坐席通过 WS 主动发消息给客户
                    session_id = msg_data.get("session_id")
                    content = msg_data.get("content", "")
                    if session_id and content:
                        await self.send_message(
                            session_id=session_id,
                            sender="agent",
                            content=content,
                            msg_type="text",
                            agent_id=agent_id,
                            agent_name=agent_name,
                            metadata=msg_data.get("metadata"),
                        )

                elif msg_type == "set_status":
                    new_status = msg_data.get("status", "online")
                    await self.set_agent_status(agent_id, new_status)

                elif msg_type == "release_session":
                    session_id = msg_data.get("session_id")
                    if session_id:
                        await self.release_session(session_id)

                elif msg_type == "assign_session":
                    session_id = msg_data.get("session_id")
                    if session_id:
                        await self.assign_session_to_agent(session_id, agent_id)

        except WebSocketDisconnect as e:
            logger.info(f"WS 坐席断开: agent={agent_id}, code={e.code}, reason={e.reason if hasattr(e,'reason') else ''}")
        except Exception as e:
            logger.warning(f"WS 坐席异常: agent={agent_id}, e={e}")
        finally:
            await self.disconnect_agent(agent_id)


# 全局单例
realtime_server = RealtimeMessageServer()
