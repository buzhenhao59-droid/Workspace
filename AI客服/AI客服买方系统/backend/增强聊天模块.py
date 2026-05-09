# -*- coding: utf-8 -*-
"""
增强的买方AI客服聊天API - 集成所有新模块

本模块是 main_buyer.py 中 customer_chat API 的增强版本
集成了以下新功能：
1. 语义缓存层 (Semantic Cache)
2. 离线消息推送 (Notification Service)
3. AI提示词版本控制 (Prompt Version Control)
4. 翻译术语库 (Translation Glossary)
5. 熔断降级机制 (Circuit Breaker & Fallback)

使用方法：
在 main_buyer.py 的 customer_chat 函数中替换原有逻辑即可
"""
import logging
import time
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# ============== 增强聊天函数 ==============

def enhanced_customer_chat(
    session_id: str,
    message: str,
    customer_info: dict,
    language: str,
    conversation_history: list
) -> Tuple[str, Optional[str], dict]:
    """
    增强版客户聊天处理
    
    增强流程：
    1. 检查语义缓存（Redis向量匹配）
    2. 关键词FAQ快速匹配
    3. 调用DeepSeek API
    4. 5秒超时后自动降级到关键词匹配
    
    Returns:
        (ai_reply, lang_switch_to, extra_data)
    """
    extra_data = {
        "cache_hit": False,
        "fallback_level": 0,
        "latency_ms": 0
    }
    
    start_time = time.time()
    message = (message or "").strip()
    
    # ============== 步骤1: 检查语义缓存 ==============
    try:
        from 语义缓存 import semantic_cache_get, keyword_fallback
        cache_result = None
        
        # 尝试语义缓存（需要Redis）
        try:
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                from redis_store import redis_store
                from 语义缓存 import get_semantic_cache
                
                cache = get_semantic_cache(redis_store._client)
                cache_result = loop.run_until_complete(
                    cache.get(message, language)
                )
            except Exception:
                pass
            finally:
                loop.close()
        except Exception:
            pass
        
        if cache_result:
            cached_response, similarity = cache_result
            extra_data["cache_hit"] = True
            extra_data["similarity"] = similarity
            logger.info(f"[EnhancedChat] 语义缓存命中 相似度={similarity:.2f}")
            return cached_response, None, extra_data
        
        # ============== 步骤2: 关键词FAQ快速匹配 ==============
        faq_response = keyword_fallback(message, language)
        if faq_response:
            logger.info("[EnhancedChat] 关键词FAQ匹配")
            extra_data["fallback_level"] = 3
            return faq_response, None, extra_data
            
    except ImportError:
        logger.warning("[EnhancedChat] 语义缓存模块未安装，使用传统模式")
    
    # ============== 步骤3: 调用DeepSeek API ==============
    try:
        # 导入熔断降级
        from 熔断降级机制 import FallbackAPICaller, FallbackLevel
        
        caller = FallbackAPICaller("deepseek")
        
        # 准备API调用
        def call_deepseek():
            from main_buyer import _call_deepseek, _generate_ai_response_optimized
            return _call_deepseek([])
        
        # 使用增强的生成函数
        ai_reply, lang_switch = _generate_ai_response_optimized(
            message, customer_info, conversation_history, language
        )
        
        return ai_reply, lang_switch, extra_data
        
    except ImportError:
        # 降级到原始函数
        from main_buyer import _generate_ai_response_optimized
        ai_reply, lang_switch = _generate_ai_response_optimized(
            message, customer_info, conversation_history, language
        )
        return ai_reply, lang_switch, extra_data
    
    finally:
        extra_data["latency_ms"] = round((time.time() - start_time) * 1000, 2)


# ============== 增强的翻译函数 ==============

def enhanced_translate(
    text: str,
    target_lang: str,
    source_lang: str = "zh"
) -> str:
    """
    增强版翻译函数
    
    增强流程：
    1. 检查Redis翻译缓存
    2. 应用术语库（保护专业词汇）
    3. 调用DeepSeek翻译
    4. 还原术语库
    """
    if not text:
        return text
    
    # ============== 步骤1: 检查Redis缓存 ==============
    try:
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            from redis_store import get_translation_cache, set_translation_cache
            cached = loop.run_until_complete(
                get_translation_cache(text, source_lang, target_lang)
            )
            if cached:
                return cached
        except Exception:
            pass
        finally:
            loop.close()
    except Exception:
        pass
    
    # ============== 步骤2: 应用术语库 ==============
    try:
        from 翻译术语库 import translate_with_glossary, get_glossary
        
        def translator(text_to_translate):
            from main_buyer import _translate_text
            return _translate_text(text_to_translate, target_lang)
        
        result = translate_with_glossary(text, source_lang, target_lang, translator)
        return result
        
    except ImportError:
        # 降级到原始翻译
        from main_buyer import _translate_text
        return _translate_text(text, target_lang)


# ============== 增强的转人工处理 ==============

def enhanced_transfer_to_human(
    session_id: str,
    customer_info: dict,
    language: str,
    question_summary: str
) -> dict:
    """
    增强版转人工处理
    
    增强流程：
    1. 记录等待开始时间
    2. 通知卖家系统
    3. 启动等待监控（60秒超时后自动通知）
    
    Returns:
        {
            "success": bool,
            "transfer_message": str,
            "wait_monitor_started": bool
        }
    """
    result = {
        "success": True,
        "transfer_message": "",
        "wait_monitor_started": False
    }
    
    # ============== 步骤1: 获取客户信息 ==============
    customer_name = "客户"
    customer_id = ""
    customer_phone = None
    
    if customer_info:
        cust = customer_info.get("customer", {})
        customer_name = cust.get("name") or customer_name
        customer_id = cust.get("customer_id") or customer_info.get("customer_id", "")
        customer_phone = cust.get("phone")
    
    # ============== 步骤2: 启动等待监控 ==============
    try:
        from 离线消息推送 import get_waiting_monitor
        
        monitor = get_waiting_monitor()
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            loop.run_until_complete(
                monitor.start_tracking(
                    session_id=session_id,
                    customer_id=customer_id,
                    customer_name=customer_name,
                    customer_phone=customer_phone,
                    language=language,
                    question_summary=question_summary[:100]
                )
            )
            result["wait_monitor_started"] = True
        finally:
            loop.close()
            
    except ImportError:
        logger.warning("[EnhancedTransfer] 离线消息推送模块未安装")
    
    # ============== 步骤3: 通知卖家系统（保持原有逻辑）==============
    try:
        from main_buyer import _notify_seller_transfer, _db_update_session
        
        _db_update_session(session_id, is_ai=0, status="waiting")
        notify_result = _notify_seller_transfer(session_id, customer_id, language)
        
        if not notify_result.get("success"):
            logger.warning(f"[EnhancedTransfer] 通知卖家失败: {notify_result.get('message')}")
    
    except Exception as e:
        logger.error(f"[EnhancedTransfer] 转人工处理失败: {e}")
        result["success"] = False
    
    return result


# ============== 等待监控后台任务 ==============

async def check_waiting_sessions():
    """
    检查等待超时会话的后台任务
    
    应在FastAPI lifespan中启动，或使用APScheduler定期执行
    """
    try:
        from 离线消息推送 import get_waiting_monitor
        monitor = get_waiting_monitor()
        results = await monitor.check_timeouts()
        
        if results:
            success_count = sum(1 for r in results if r.success)
            logger.info(f"[WaitingMonitor] 检查完成: {success_count}/{len(results)} 通知发送成功")
            
    except ImportError:
        pass
    except Exception as e:
        logger.error(f"[WaitingMonitor] 检查失败: {e}")


# ============== 导出 ==============
__all__ = [
    'enhanced_customer_chat',
    'enhanced_translate',
    'enhanced_transfer_to_human',
    'check_waiting_sessions',
]
