# -*- coding: utf-8 -*-
"""
AI客服上下文管理 - 滑动窗口模式
优化 Token 消耗，提升响应速度

核心特性：
- 滑动摘要：保留最近 10 轮对话的核心摘要
- 原始对话：保留最近 3 轮的完整对话
- Token 预算控制：动态调整上下文长度
- 内存管理：自动清理过期会话

使用方法：
    from conversation_memory import ConversationMemory, get_optimized_context
    
    memory = ConversationMemory()
    context = memory.get_context_for_ai(session_id)
    
    # 或者使用便捷函数
    context = get_optimized_context(session_id, max_tokens=2000)
"""

import time
import json
import logging
from typing import Dict, List, Any, Optional, Tuple
from collections import OrderedDict
from threading import Lock

logger = logging.getLogger(__name__)


class ConversationWindow:
    """
    单个会话的滑动窗口
    维护最近 N 轮对话
    """
    
    def __init__(
        self,
        session_id: str,
        summary_rounds: int = 10,
        raw_rounds: int = 3,
        max_tokens: int = 2000
    ):
        self.session_id = session_id
        self.summary_rounds = summary_rounds  # 摘要保留轮数
        self.raw_rounds = raw_rounds          # 原始对话保留轮数
        self.max_tokens = max_tokens           # 最大 Token 数
        
        # 对话历史（按时间顺序）
        self.messages: List[Dict[str, Any]] = []
        
        # 摘要历史
        self.summaries: List[Dict[str, Any]] = []
        
        # 创建时间
        self.created_at = time.time()
        self.last_access = time.time()
    
    def add_message(self, role: str, content: str, metadata: Dict = None) -> None:
        """
        添加消息到对话窗口
        
        Args:
            role: 角色（customer / assistant）
            content: 消息内容
            metadata: 额外元数据
        """
        message = {
            "role": role,
            "content": content,
            "timestamp": time.time(),
            "metadata": metadata or {}
        }
        
        self.messages.append(message)
        self.last_access = time.time()
        
        # 如果原始消息超过限制，生成摘要
        if len(self.messages) > self.raw_rounds * 2:
            self._generate_summary()
    
    def _generate_summary(self) -> None:
        """生成对话摘要"""
        if len(self.messages) < 4:
            return
        
        # 取最近几个完整轮次
        recent_messages = self.messages[-self.raw_rounds * 2:]
        
        # 生成摘要
        summary = self._create_summary_text(recent_messages)
        
        self.summaries.append({
            "summary": summary,
            "message_count": len(self.messages) - len(recent_messages),
            "timestamp": time.time()
        })
        
        # 保留最近的摘要
        if len(self.summaries) > self.summary_rounds:
            self.summaries = self.summaries[-self.summary_rounds:]
        
        # 保留最近的原始对话
        self.messages = self.messages[-self.raw_rounds * 2:]
    
    def _create_summary_text(self, messages: List[Dict]) -> str:
        """
        创建摘要文本
        
        简单实现：提取关键信息
        实际生产环境可以调用 AI 生成更好的摘要
        """
        customer_msgs = [m for m in messages if m["role"] == "customer"]
        assistant_msgs = [m for m in messages if m["role"] == "assistant"]
        
        topics = []
        intents = []
        
        for msg in customer_msgs:
            content = msg["content"].lower()
            # 简单的主题识别
            if any(word in content for word in ["order", "订单", "买"]):
                topics.append("订单咨询")
            if any(word in content for word in ["refund", "退款", "退货"]):
                topics.append("退款退货")
            if any(word in content for word in ["product", "产品", "商品"]):
                topics.append("产品咨询")
            if any(word in content for word in ["shipping", "物流", "快递"]):
                topics.append("物流咨询")
            
            # 意图识别
            if any(word in content for word in ["when", "什么时候", "多久"]):
                intents.append("时间询问")
            if any(word in content for word in ["how", "怎么", "如何"]):
                intents.append("方法咨询")
        
        topic_str = "、".join(set(topics)) if topics else "一般咨询"
        intent_str = "、".join(set(intents)) if intents else "其他"
        
        return f"[摘要] 主题：{topic_str}，意图：{intent_str}，客户消息{len(customer_msgs)}条，助手回复{len(assistant_msgs)}条"
    
    def get_context(self, max_tokens: int = None) -> List[Dict]:
        """
        获取 AI 上下文
        
        Args:
            max_tokens: 最大 Token 数（预留，实际按字符估算）
            
        Returns:
            格式化的对话列表
        """
        if max_tokens is None:
            max_tokens = self.max_tokens
        
        context = []
        
        # 添加摘要
        for summary in self.summaries[-3:]:  # 最多3个摘要
            context.append({
                "role": "system",
                "content": summary["summary"]
            })
        
        # 添加原始对话
        for msg in self.messages[-self.raw_rounds * 2:]:
            context.append({
                "role": msg["role"],
                "content": msg["content"]
            })
        
        # 截断以控制长度
        return self._truncate_context(context, max_tokens)
    
    def _truncate_context(self, context: List[Dict], max_tokens: int) -> List[Dict]:
        """截断上下文以控制长度"""
        # 估算：1 token ≈ 2 字符
        char_limit = max_tokens * 2
        
        total_chars = sum(len(msg.get("content", "")) for msg in context)
        
        if total_chars <= char_limit:
            return context
        
        # 从后向前截断
        truncated = []
        current_chars = 0
        
        for msg in reversed(context):
            msg_len = len(msg.get("content", ""))
            if current_chars + msg_len <= char_limit:
                truncated.insert(0, msg)
                current_chars += msg_len
            else:
                break
        
        # 确保至少有原始对话
        raw_msgs = [msg for msg in context if msg.get("role") in ("customer", "assistant")]
        if not any(msg in truncated for msg in raw_msgs[-2:]):
            truncated.extend(raw_msgs[-2:])
        
        return truncated
    
    def get_stats(self) -> Dict:
        """获取会话统计"""
        return {
            "session_id": self.session_id,
            "total_messages": len(self.messages),
            "total_summaries": len(self.summaries),
            "estimated_tokens": self._estimate_tokens(),
            "last_access": self.last_access,
            "age_seconds": time.time() - self.created_at
        }
    
    def _estimate_tokens(self) -> int:
        """估算 Token 数"""
        total_chars = 0
        for summary in self.summaries:
            total_chars += len(summary.get("summary", ""))
        for msg in self.messages:
            total_chars += len(msg.get("content", ""))
        return total_chars // 2


class ConversationMemory:
    """
    对话内存管理器
    管理所有会话的滑动窗口
    """
    
    def __init__(
        self,
        max_sessions: int = 10000,
        session_ttl: int = 3600,
        summary_rounds: int = 10,
        raw_rounds: int = 3,
        max_tokens: int = 2000
    ):
        """
        Args:
            max_sessions: 最大会话数
            session_ttl: 会话 TTL（秒）
            summary_rounds: 摘要保留轮数
            raw_rounds: 原始对话保留轮数
            max_tokens: 最大 Token 数
        """
        self.max_sessions = max_sessions
        self.session_ttl = session_ttl
        self.summary_rounds = summary_rounds
        self.raw_rounds = raw_rounds
        self.max_tokens = max_tokens
        
        self._sessions: Dict[str, ConversationWindow] = {}
        self._lock = Lock()
        
        # 访问统计
        self._access_count = 0
        self._cache_hits = 0
    
    def get_or_create(self, session_id: str) -> ConversationWindow:
        """
        获取或创建会话窗口
        """
        with self._lock:
            if session_id in self._sessions:
                self._sessions[session_id].last_access = time.time()
                self._cache_hits += 1
                return self._sessions[session_id]
            
            # 检查是否需要清理过期会话
            if len(self._sessions) >= self.max_sessions:
                self._cleanup_expired()
            
            window = ConversationWindow(
                session_id=session_id,
                summary_rounds=self.summary_rounds,
                raw_rounds=self.raw_rounds,
                max_tokens=self.max_tokens
            )
            self._sessions[session_id] = window
            return window
    
    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: Dict = None
    ) -> None:
        """
        添加消息
        """
        window = self.get_or_create(session_id)
        window.add_message(role, content, metadata)
    
    def get_context(self, session_id: str, max_tokens: int = None) -> List[Dict]:
        """
        获取 AI 上下文
        """
        self._access_count += 1
        
        window = self._sessions.get(session_id)
        if not window:
            return []
        
        return window.get_context(max_tokens or self.max_tokens)
    
    def _cleanup_expired(self) -> None:
        """清理过期会话"""
        current_time = time.time()
        expired = []
        
        for session_id, window in self._sessions.items():
            if current_time - window.last_access > self.session_ttl:
                expired.append(session_id)
        
        for session_id in expired[:len(expired) // 2]:  # 清理一半过期会话
            del self._sessions[session_id]
        
        if expired:
            logger.debug(f"Cleaned up {len(expired)} expired sessions")
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        total_messages = sum(len(w.messages) for w in self._sessions.values())
        total_summaries = sum(len(w.summaries) for w in self._sessions.values())
        
        return {
            "active_sessions": len(self._sessions),
            "total_messages": total_messages,
            "total_summaries": total_summaries,
            "access_count": self._access_count,
            "cache_hits": self._cache_hits,
            "cache_hit_rate": self._cache_hits / max(1, self._access_count)
        }
    
    def clear_session(self, session_id: str) -> bool:
        """清除单个会话"""
        with self._lock:
            if session_id in self._sessions:
                del self._sessions[session_id]
                return True
            return False


# 全局实例
_memory: Optional[ConversationMemory] = None


def get_memory() -> ConversationMemory:
    """获取全局内存实例"""
    global _memory
    if _memory is None:
        _memory = ConversationMemory()
    return _memory


def add_message(
    session_id: str,
    role: str,
    content: str,
    metadata: Dict = None
) -> None:
    """添加消息到会话"""
    get_memory().add_message(session_id, role, content, metadata)


def get_context_for_ai(
    session_id: str,
    max_tokens: int = 2000
) -> List[Dict]:
    """获取 AI 上下文"""
    return get_memory().get_context(session_id, max_tokens)


def get_optimized_context(
    session_id: str,
    max_tokens: int = 2000
) -> str:
    """
    获取优化的上下文字符串
    用于直接拼接到 Prompt
    """
    context = get_context_for_ai(session_id, max_tokens)
    
    # 格式化为字符串
    formatted = []
    for msg in context:
        role = msg.get("role", "system")
        content = msg.get("content", "")
        if role == "system":
            formatted.append(f"[背景] {content}")
        elif role == "customer":
            formatted.append(f"[客户] {content}")
        elif role == "assistant":
            formatted.append(f"[助手] {content}")
        else:
            formatted.append(content)
    
    return "\n".join(formatted)


def clear_session(session_id: str) -> bool:
    """清除会话"""
    return get_memory().clear_session(session_id)


def get_memory_stats() -> Dict:
    """获取内存统计"""
    return get_memory().get_stats()
