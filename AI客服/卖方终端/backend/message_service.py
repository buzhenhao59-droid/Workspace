# -*- coding: utf-8 -*-
"""
消息服务 - 消息存储、查询、翻译的统一抽象层
将 realtime_server 的实时推送与 db.py 的 SQLite 持久化连接起来。
"""
import json
import logging
import threading
import time
import uuid
from collections import defaultdict
from datetime import datetime
from typing import Optional, List, Dict, Any

from services import translate_text, detect_language

logger = logging.getLogger(__name__)

# 全局消息去重缓存
# 结构: { session_id: { client_message_id: received_at } }
_dedup_cache: Dict[str, Dict[str, float]] = defaultdict(dict)
_dedup_cache_lock = threading.Lock()
_DEDUP_TTL_SECONDS = 120  # 2分钟内相同 client_message_id 视为重复


def _clean_dedup_cache():
    """清理过期的去重缓存（每 60 秒调用一次）"""
    now = time.time()
    expired_sessions = []
    for sid, cache in _dedup_cache.items():
        expired_keys = [mid for mid, t in cache.items() if now - t > _DEDUP_TTL_SECONDS]
        for mid in expired_keys:
            del cache[mid]
        if not cache:
            expired_sessions.append(sid)
    for sid in expired_sessions:
        _dedup_cache.pop(sid, None)


def _is_duplicate_message(session_id: str, client_message_id: str) -> bool:
    """
    检查消息是否重复。
    返回 True 表示重复（应忽略）；False 表示新消息。
    线程安全。
    """
    if not client_message_id:
        return False
    with _dedup_cache_lock:
        cache = _dedup_cache.get(session_id, {})
        if client_message_id in cache:
            # 已存在，忽略重复
            return True
        _dedup_cache[session_id][client_message_id] = time.time()
        return False


# 启动后台清理线程
_clean_thread_running = True


def _start_dedup_cleaner():
    global _clean_thread_running

    def cleaner():
        while _clean_thread_running:
            time.sleep(60)
            _clean_dedup_cache()

    t = threading.Thread(target=cleaner, daemon=True)
    t.start()


_start_dedup_cleaner()


class MessageService:
    """
    消息服务 - 封装消息的存取、翻译、格式化逻辑。

    职责：
    1. 消息持久化 - 写入 SQLite（复用 db.py）
    2. 消息格式化 - 给客户/坐席看各自的格式（翻译/转义）
    3. 消息查询 - 支持分页、增量拉取（last_id 游标）
    4. 未读计数 - 每个会话的未读消息数
    5. 实时通知 - 触发 realtime_server 推送消息
    """

    def __init__(self):
        self._unread_cache: Dict[str, int] = {}

    def _get_db(self):
        """延迟导入 db 模块，避免循环依赖"""
        from db import add_message as db_add_message, get_messages as db_get_messages
        from db import get_session as db_get_session
        return db_add_message, db_get_messages, db_get_session

    def _persist_message(
        self,
        session_id: str,
        role: str,
        content: str,
        agent_id: str = "",
        is_ai: bool = True
    ) -> dict:
        """
        持久化消息到 SQLite。
        role: 'user' | 'assistant' | 'agent' | 'system'
        """
        from db import add_message
        add_message(session_id, role, content)

        # 更新会话状态
        from db import update_session
        is_ai_flag = 1 if is_ai else 0
        update_session(session_id, is_ai=is_ai_flag, status="active")

        return {
            "session_id": session_id,
            "role": role,
            "content": content,
            "agent_id": agent_id,
            "is_ai": is_ai,
            "saved_at": datetime.now().isoformat()
        }

    # ==================== 客户发消息（人工模式） ====================

    def customer_send_message(
        self,
        session_id: str,
        content: str,
        customer_id: str = "",
        customer_lang: str = "zh",
        client_message_id: str = ""
    ) -> dict:
        """
        客户发送消息（转人工后）流程：
        1. 检测重复消息（client_message_id + 2min TTL）
        2. 检测是否媒体消息
        3. 非中文翻译成中文给坐席看
        4. 持久化消息（原始语言）
        5. 触发 realtime_server 推送给坐席
        """
        # ---- 去重检查 ----
        if _is_duplicate_message(session_id, client_message_id):
            logger.info(f"[去重] 忽略重复消息: session={session_id}, client_id={client_message_id}")
            return {
                "success": False,
                "reason": "duplicate",
                "payload": None,
                "translated_zh": None
            }
        # 检测是否媒体消息
        is_media = content.startswith("{") and "type" in content
        translated_zh = None

        # 文本消息翻译
        if not is_media and customer_lang != "zh" and content.strip():
            try:
                translated_zh = translate_text(content, "zh")
                # 存储结构：原始语言 + 中文翻译
                db_content = json.dumps({
                    "original": content,
                    "translated_zh": translated_zh
                }, ensure_ascii=False)
            except Exception:
                db_content = content
        else:
            db_content = content

        # 持久化
        self._persist_message(session_id, "user", db_content, is_ai=False)

        # 构造推送数据
        payload = {
            "type": "new_message",
            "data": {
                "id": str(uuid.uuid4()),
                "session_id": session_id,
                "from_type": "customer",
                "from_id": customer_id,
                "content": content,
                "translated_zh": translated_zh,
                "customer_language": customer_lang,
                "is_media": is_media,
                "created_at": datetime.now().isoformat(),
            }
        }

        # 触发实时推送（realtime_server 会处理）
        return {
            "success": True,
            "payload": payload,
            "translated_zh": translated_zh
        }

    # ==================== 坐席发消息 ====================

    def agent_send_message(
        self,
        session_id: str,
        content: str,
        agent_id: str = "",
        agent_name: str = "客服",
        target_lang: str = "zh",
        client_message_id: str = ""
    ) -> dict:
        """
        坐席发送消息给客户流程：
        1. 检测重复消息（防止坐席端网络重传）
        2. 持久化消息
        3. 按客户语言翻译
        4. 触发 realtime_server 推送给客户
        """
        # ---- 去重检查 ----
        if _is_duplicate_message(f"agent_{session_id}", client_message_id):
            logger.info(f"[去重] 忽略重复坐席消息: session={session_id}, client_id={client_message_id}")
            return {
                "success": False,
                "reason": "duplicate",
                "payload": None,
                "translated": None,
                "customer_language": target_lang
            }
        # 获取会话语言
        from db import get_session
        session = get_session(session_id)
        customer_lang = session.get("language", "zh") if session else "zh"

        # 翻译消息
        translated = content
        if customer_lang != "zh" and content.strip():
            try:
                translated = translate_text(content, customer_lang)
            except Exception:
                translated = content  # 翻译失败用原文

        # 持久化（坐席消息存中文原文）
        self._persist_message(session_id, "seller", content, agent_id=agent_id, is_ai=False)

        # 构造推送数据
        payload = {
            "type": "new_message",
            "data": {
                "id": str(uuid.uuid4()),
                "session_id": session_id,
                "from_type": "agent",
                "from_id": agent_id,
                "from_name": agent_name,
                "content": translated,  # 推给客户的语言版本
                "original_content": content,  # 坐席输入的原文
                "customer_language": customer_lang,
                "created_at": datetime.now().isoformat(),
            }
        }

        return {
            "success": True,
            "payload": payload,
            "translated": translated,
            "customer_language": customer_lang
        }

    # ==================== AI 消息 ====================

    def ai_send_message(
        self,
        session_id: str,
        content: str,
        customer_id: str = "",
        target_lang: str = "zh"
    ) -> dict:
        """
        AI 客服发送消息（复用现有 AI 流程的消息推送部分）。
        返回推送 payload，由调用方决定是否推送。
        """
        return {
            "type": "new_message",
            "data": {
                "id": str(uuid.uuid4()),
                "session_id": session_id,
                "from_type": "ai",
                "from_id": "ai_assistant",
                "content": content,
                "customer_language": target_lang,
                "created_at": datetime.now().isoformat(),
            }
        }

    # ==================== 消息查询 ====================

    def get_messages_for_customer(
        self,
        session_id: str,
        after_id: str = "",
        limit: int = 50
    ) -> List[dict]:
        """
        获取消息列表（客户视角）。
        - 坐席消息按客户语言返回
        - AI 消息直接返回
        - 支持增量拉取（after_id 游标）
        """
        from db import get_messages, get_session

        session = get_session(session_id)
        if not session:
            return []

        customer_lang = session.get("language", "zh")
        all_messages = get_messages(session_id)

        # 增量拉取
        if after_id:
            found = False
            filtered = []
            for msg in all_messages:
                if msg["id"] == after_id or found:
                    found = True
                    filtered.append(msg)
            all_messages = filtered

        # 限制条数
        all_messages = all_messages[-limit:]

        result = []
        for msg in all_messages:
            role = msg.get("role", "")
            content = msg.get("content", "")

            # 解析翻译内容
            if role == "seller":
                try:
                    parsed = json.loads(content)
                    display = parsed.get("translated", parsed.get("original", content))
                except (json.JSONDecodeError, TypeError):
                    display = content
            else:
                display = content

            result.append({
                "id": msg.get("id", ""),
                "role": role,
                "content": display,
                "created_at": msg.get("created_at", ""),
            })

        return result

    def get_messages_for_agent(
        self,
        session_id: str,
        after_id: str = "",
        limit: int = 50
    ) -> List[dict]:
        """
        获取消息列表（坐席视角）。
        - 客户消息统一显示中文翻译
        - 坐席消息显示原文
        """
        from db import get_messages, get_session

        session = get_session(session_id)
        if not session:
            return []

        all_messages = get_messages(session_id)

        # 增量拉取
        if after_id:
            found = False
            filtered = []
            for msg in all_messages:
                if msg["id"] == after_id or found:
                    found = True
                    filtered.append(msg)
            all_messages = filtered

        all_messages = all_messages[-limit:]

        result = []
        for msg in all_messages:
            role = msg.get("role", "")
            content = msg.get("content", "")

            if role == "user":
                try:
                    parsed = json.loads(content)
                    display = parsed.get("translated_zh", parsed.get("original", content))
                except (json.JSONDecodeError, TypeError):
                    display = content
            else:
                display = content

            result.append({
                "id": msg.get("id", ""),
                "role": role,
                "content": display,
                "original_content": content,
                "created_at": msg.get("created_at", ""),
            })

        return result

    def get_conversation_history_for_ai(
        self,
        session_id: str,
        limit: int = 20,
        ai_mode_since: str = ""
    ) -> List[dict]:
        """
        获取对话历史（给 AI 看，仅限 AI 模式下的消息）。

        ai_mode_since: ISO 时间字符串，只返回 created_at >= 此时间的消息。
        用于在转人工后再切回 AI 时，只给 AI 喂 AI 模式的历史，避免人工坐席的话混入 AI 上下文。
        如果 ai_mode_since 为空，则取最近 limit 条（兼容旧调用）。
        """
        from db import get_messages

        all_messages = get_messages(session_id)

        # 过滤：只取 ai_mode_since 之后的 AI 模式消息
        if ai_mode_since:
            ai_messages = []
            for msg in all_messages:
                created = msg.get("created_at", "")
                # 跳过人工作为"用户"发出的消息（role=seller 是人工回复）
                role = msg.get("role", "")
                # 只取 AI 视角有意义的消息：user(客户)、assistant/ai(AI回复)、system(系统)
                # 排除 role=seller（人工坐席回复）
                if role == "seller":
                    continue
                if created >= ai_mode_since:
                    ai_messages.append(msg)
            all_messages = ai_messages[-limit:]

        result = []
        for msg in all_messages:
            role = msg.get("role", "")
            content = msg.get("content", "")

            # 坐席消息给 AI 看原始内容（不含 JSON 包装）
            if role == "seller":
                try:
                    parsed = json.loads(content)
                    display = parsed.get("original", content)
                except (json.JSONDecodeError, TypeError):
                    display = content
                role = "assistant"  # 统一映射给 AI
            elif role == "user":
                # 客户消息取原文
                try:
                    parsed = json.loads(content)
                    display = parsed.get("original", content)
                except (json.JSONDecodeError, TypeError):
                    display = content

            result.append({
                "role": role,
                "content": display,
            })

        return result

    # ==================== 未读与状态 ====================

    def mark_as_read(self, session_id: str, agent_id: str = ""):
        """标记会话已读"""
        key = f"{session_id}:{agent_id}"
        self._unread_cache[key] = 0

    def get_unread_count(self, session_id: str) -> int:
        """获取会话未读消息数"""
        return self._unread_cache.get(session_id, 0)

    # ==================== 统计 ====================

    def get_session_stats(self, session_id: str) -> dict:
        """获取会话统计信息"""
        from db import get_messages

        all_messages = get_messages(session_id)
        user_count = sum(1 for m in all_messages if m.get("role") == "user")
        agent_count = sum(1 for m in all_messages if m.get("role") == "seller")
        ai_count = sum(1 for m in all_messages if m.get("role") in ("assistant", "ai"))

        return {
            "session_id": session_id,
            "total_messages": len(all_messages),
            "customer_messages": user_count,
            "agent_messages": agent_count,
            "ai_messages": ai_count,
        }


# 全局单例
message_service = MessageService()
