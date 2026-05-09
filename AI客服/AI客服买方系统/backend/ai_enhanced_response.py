# -*- coding: utf-8 -*-
"""
增强版 AI 响应引擎 - 融合 cross-border-ecommerce-chatbot.md 源文件

整合模块:
  - ai_intelligence: 意图分类 / 情绪检测 / RRF / 升级规则
  - RAG: 混合检索 (向量+关键词+图谱)
  - Neo4j 知识图谱: 商品-品牌-政策关系网络
  - DeepSeek LLM: 生成拟人化回复

使用方式:
  from ai_enhanced_response import EnhancedAIResponder
  responder = EnhancedAIResponder(neo4j_conn, deepseek_func)
  reply, lang_switch, metadata = responder.generate(user_message, customer_info, history, language)
"""

import re
import logging
from typing import Optional, Callable, Any
from dataclasses import dataclass, field

from ai_intelligence import (
    classify_intent,
    detect_emotion_enhanced,
    build_smart_context,
    check_escalation,
    KnowledgeBaseRetriever,
    SemanticDeduplicator,
    rrf_fusion,
    generate_hypothetical_answer,
    detect_language_simple,
)

logger = logging.getLogger(__name__)

# ============================================================
# 9 类意图 → 回复风格映射
# ============================================================

RESPONSE_STYLES = {
    "product_inquiry": {
        "zh": {
            "format": "规格列表 + 操作指引",
            "example": "商品规格：材质：XX；尺寸：XX；颜色：XX。建议您查看商品详情页获取完整信息。",
            "tone": "专业、详细、数据化",
        },
        "en": {
            "format": "spec list + guidance",
            "example": "Product specs: Material: XX; Size: XX; Color: XX. Check the product page for full details.",
            "tone": "Professional, detailed, data-driven",
        },
    },
    "logistics": {
        "zh": {
            "format": "实时状态 + 时间节点",
            "example": "您的包裹正在派送中，预计今天18:00前送达。",
            "tone": "清晰、准确、时间敏感",
        },
        "en": {
            "format": "real-time status + timeline",
            "example": "Your parcel is out for delivery, expected by 6 PM today.",
            "tone": "Clear, accurate, time-sensitive",
        },
    },
    "payment": {
        "zh": {
            "format": "操作步骤 + 金额说明",
            "example": "退款金额为¥XX，预计1-3个工作日到账。",
            "tone": "清晰、简洁、金额精确",
        },
        "en": {
            "format": "steps + amount details",
            "example": "Refund amount: $XX, expected in 1-3 business days.",
            "tone": "Clear, concise, precise",
        },
    },
    "refund_return": {
        "zh": {
            "format": "流程步骤 + 时间节点",
            "example": "退货流程：1. 申请退款；2. 等待审核；3. 寄回商品；4. 退款到账。",
            "tone": "耐心、流程化、温暖引导",
        },
        "en": {
            "format": "step-by-step process + timeline",
            "example": "Return process: 1. Apply for return; 2. Wait for approval; 3. Ship back; 4. Refund issued.",
            "tone": "Patient, structured, warm guidance",
        },
    },
    "policy": {
        "zh": {
            "format": "规定引用 + 具体条款",
            "example": "根据平台政策第XX条规定，关于进口限制...如需了解更多，请查看帮助中心。",
            "tone": "权威、引用明确、不可捏造",
        },
        "en": {
            "format": "policy citation + specific clause",
            "example": "Per platform policy section XX, regarding import restrictions... Visit Help Center for more.",
            "tone": "Authoritative, cite clearly, no fabrication",
        },
    },
    "account": {
        "zh": {
            "format": "解决步骤 + 操作指引",
            "example": "解决步骤：1. 点击「忘记密码」；2. 输入注册邮箱；3. 查收验证码；4. 重置密码。",
            "tone": "耐心、分步、安全提醒",
        },
        "en": {
            "format": "fix steps + guidance",
            "example": "Steps: 1. Click 'Forgot Password'; 2. Enter registered email; 3. Check verification code; 4. Reset password.",
            "tone": "Patient, step-by-step, security reminder",
        },
    },
    "complaint": {
        "zh": {
            "format": "同理倾听 + 道歉 + 解决方案",
            "example": "非常理解您的不满，我们深表歉意。以下是解决方案：XX。",
            "tone": "同理心优先、真诚道歉、给出方案",
        },
        "en": {
            "format": "empathy + apology + solution",
            "example": "We sincerely apologize for your experience. Here's what we can do: XX.",
            "tone": "Empathy first, sincere apology, solution-focused",
        },
    },
    "general": {
        "zh": {
            "format": "友好引导 + 推荐操作",
            "example": "您可能想了解：1) 订单物流；2) 退换货政策；3) 支付问题。请问是哪方面呢？",
            "tone": "友好、引导、主动",
        },
        "en": {
            "format": "friendly guidance + recommendations",
            "example": "You might want to know: 1) Order tracking; 2) Return policy; 3) Payment issues. Which one?",
            "tone": "Friendly, guiding, proactive",
        },
    },
}

# ============================================================
# 知识图谱查询模板
# ============================================================

GRAPH_QUERY_TEMPLATES = {
    "product_inquiry": """
已知客户想了解商品信息，商品为 {product_name}。
请从知识图谱中查找：
1. 该商品所属品牌及品牌相关政策
2. 该商品所属类目及类目相关政策（如进口限制）
3. 该类目下常见问题 FAQ 链接
4. 是否有同品牌商品的物流信息可参考

参考格式：
- 品牌：{brand_name}，品牌政策：{brand_policy}
- 类目：{category_name}，进口限制：{category_restrictions}
- 常见问题：{faq_links}
""",
    "logistics": """
客户询问物流信息：{logistics_query}
请从知识图谱中查找：
1. 该物流渠道的时效信息
2. 该目的地国家的清关要求
3. 是否有延迟或异常记录

参考格式：
- 预计时效：{estimated_days}天
- 清关要求：{customs_requirements}
- 近期状态：{recent_status}
""",
    "policy": """
客户询问政策：{policy_query}
请从知识图谱中查找相关政策节点：
1. 政策名称和版本
2. 政策适用地区
3. 政策具体条款

参考格式：
- 政策：{policy_name}（版本：{version}）
- 适用地区：{region}
- 条款：{clauses}
""",
}


@dataclass
class RAGContext:
    """RAG 检索结果"""
    retrieved_chunks: list[dict] = field(default_factory=list)
    graph_context: str = ""
    knowledge_summary: str = ""
    confidence: float = 0.0
    sources: list[str] = field(default_factory=list)


@dataclass
class EnhancedResponse:
    """增强回复结果"""
    reply: str
    language: str
    intent: str
    confidence: float
    emotion: str
    emotion_intensity: float
    rag_context: Optional[RAGContext] = None
    should_escalate: bool = False
    escalation_reason: str = ""
    auto_transfer: Optional[str] = None


# ============================================================
# 知识图谱查询器
# ============================================================

class GraphQueryEngine:
    """
    知识图谱查询引擎

    基于 Neo4j 的图谱查询
    支持商品-品牌-类目-政策关系网络
    """

    def __init__(self, neo4j_conn):
        self.conn = neo4j_conn
        self._cache = {}

    def query_by_intent(self, intent: str, user_message: str, product_name: str = None) -> str:
        """
        根据意图类型查询知识图谱

        Returns:
            图谱上下文字符串（用于注入到 Prompt）
        """
        cache_key = f"{intent}:{user_message[:30]}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        if not self.conn or not self.conn._neo4j_available:
            result = self._fallback_query(intent, user_message, product_name)
            self._cache[cache_key] = result
            return result

        try:
            result = self._neo4j_query(intent, user_message, product_name)
            self._cache[cache_key] = result
            return result
        except Exception as e:
            logger.warning(f"[GraphQuery] Neo4j 查询失败，回退到默认: {e}")
            fallback = self._fallback_query(intent, user_message, product_name)
            self._cache[cache_key] = fallback
            return fallback

    def _neo4j_query(self, intent: str, user_message: str, product_name: str = None) -> str:
        """Neo4j 图谱查询"""
        lines = []

        if intent == "product_inquiry" and product_name:
            try:
                with self.conn.driver.session() as session:
                    r = session.run("""
                        MATCH (p:Product {name: $name})-[:BELONGS_TO]->(c:Category)
                        OPTIONAL MATCH (c)-[:HAS_POLICY]->(pol:Policy)
                        OPTIONAL MATCH (p)-[:BRAND]->(b:Brand)
                        RETURN p.name AS product, c.name AS category, b.name AS brand,
                               pol.name AS policy, pol.restriction AS restriction
                        LIMIT 5
                    """, name=product_name)
                    records = list(r)
                    if records:
                        for rec in records:
                            rec_dict = dict(rec)
                            if rec_dict.get("category"):
                                lines.append(f"📦 类目：{rec_dict['category']}")
                            if rec_dict.get("brand"):
                                lines.append(f"🏷️ 品牌：{rec_dict['brand']}")
                            if rec_dict.get("policy"):
                                lines.append(f"📋 相关政策：{rec_dict['policy']}")
                            if rec_dict.get("restriction"):
                                lines.append(f"⚠️ 进口限制：{rec_dict['restriction']}")
            except Exception as e:
                logger.warning(f"[GraphQuery] 商品查询失败: {e}")

        if intent == "logistics":
            try:
                with self.conn.driver.session() as session:
                    regions = ["法国", "美国", "英国", "德国", "日本", "法国"]
                    for region in regions:
                        if region in user_message:
                            r = session.run("""
                                MATCH (pol:Policy)
                                WHERE pol.name CONTAINS $region
                                   OR pol.region CONTAINS $region
                                RETURN pol.name AS policy, pol.customs AS customs,
                                       pol.tax AS tax, pol.restriction AS restriction
                                LIMIT 3
                            """, region=region)
                            records = list(r)
                            for rec in records:
                                rec_dict = dict(rec)
                                if rec_dict.get("policy"):
                                    lines.append(f"🌍 {region}进口政策：{rec_dict['policy']}")
                                if rec_dict.get("customs"):
                                    lines.append(f"   清关要求：{rec_dict['customs']}")
                            break
            except Exception as e:
                logger.warning(f"[GraphQuery] 物流查询失败: {e}")

        if not lines:
            return ""
        return "\n".join(lines)

    def _fallback_query(self, intent: str, user_message: str, product_name: str = None) -> str:
        """降级查询：当无图谱时的默认返回"""
        if intent == "product_inquiry" and product_name:
            return f"📦 您咨询的商品：{product_name}\n请提供具体的商品名称或SKU，我可以帮您查询详细信息。"
        if intent == "logistics":
            regions = ["法国", "美国", "英国", "德国", "日本"]
            for region in regions:
                if region in user_message:
                    return f"🌍 寄往{region}的物流信息：\n请提供订单号，我可以帮您查询实时物流状态。"
        if intent == "policy":
            return "📋 相关政策信息建议您访问平台帮助中心查看完整政策条款。"
        return ""


# ============================================================
# RAG 检索引擎
# ============================================================

class EnhancedRAGEngine:
    """
    增强版 RAG 检索引擎

    支持:
    - 多路召回（商品库 + 政策库 + FAQ）
    - HyDE 查询增强
    - RRF 融合
    - 语义去重
    """

    def __init__(self):
        self.retriever = KnowledgeBaseRetriever()
        self.dedup = SemanticDeduplicator(threshold=0.85)

    def retrieve(self, query: str, intent: str, routed_kb: str,
                 hyde_func: Callable = None, limit: int = 5) -> RAGContext:
        """
        执行 RAG 检索

        Args:
            query: 用户查询
            intent: 意图类型
            routed_kb: 路由知识库
            hyde_func: HyDE 生成函数（传入 LLM 调用函数）
            limit: 返回数量

        Returns:
            RAGContext: 检索结果上下文
        """
        chunks = []
        sources = []
        confidence = 0.5

        kb_map = {
            "商品知识库": ["product", "faq"],
            "物流知识库": ["logistics", "faq"],
            "支付库": ["payment", "faq"],
            "退换货政策库": ["refund", "policy", "faq"],
            "政策库": ["policy", "faq"],
            "账户帮助": ["account", "faq"],
            "投诉流程库": ["complaint", "faq"],
            "全量检索": ["product", "logistics", "payment", "refund", "policy", "faq"],
        }

        target_kbs = kb_map.get(routed_kb, ["faq"])

        if hyde_func and len(query) > 5:
            try:
                hypothetical = generate_hypothetical_answer(query, hyde_func)
                hyde_query = f"{query} {hypothetical[:100]}"
            except Exception:
                hyde_query = query
        else:
            hyde_query = query

        all_results = []
        for kb in target_kbs:
            results = self.retriever.search(hyde_query, kb, limit=limit, use_vector=False)
            if results:
                all_results.append(results)

        fused_results = rrf_fusion(all_results) if all_results else []
        dedup_results = self.dedup.deduplicate(fused_results)

        for item in dedup_results[:limit]:
            chunks.append(item.get("text", ""))
            src = item.get("source", "知识库")
            if src not in sources:
                sources.append(src)

        if dedup_results:
            confidence = min(0.4 + len(dedup_results) * 0.08, 0.95)

        knowledge_summary = "\n".join(f"• {c[:150]}" for c in chunks[:3]) if chunks else ""

        return RAGContext(
            retrieved_chunks=chunks,
            knowledge_summary=knowledge_summary,
            confidence=confidence,
            sources=sources,
        )


# ============================================================
# 增强版 AI 响应器
# ============================================================

class EnhancedAIResponder:
    """
    增强版 AI 响应器

    融合流程:
      用户消息 → 意图分类 → 情绪检测 → RAG检索 → 图谱扩展 → LLM生成 → 拟人化结尾

    特点:
      - 8 类意图精准路由
      - 增强情绪响应（愤怒/悲伤/焦虑/开心）
      - RAG 知识检索增强
      - 知识图谱关系注入
      - 升级规则自动触发
      - 9 种语言支持
    """

    def __init__(self, neo4j_conn, llm_call_func: Callable):
        """
        Args:
            neo4j_conn: Neo4j 连接对象
            llm_call_func: LLM 调用函数，签名为 (messages, temperature, max_tokens) -> str
        """
        self.graph_engine = GraphQueryEngine(neo4j_conn)
        self.rag_engine = EnhancedRAGEngine()
        self.llm_call = llm_call_func
        self._lang_names = {
            "zh": "中文", "en": "English", "ar": "العربية", "ru": "Русский",
            "th": "ภาษาไทย", "vi": "Tiếng Việt", "id": "Bahasa Indonesia",
            "ms": "Bahasa Melayu", "tl": "Filipino"
        }
        self._tails = {
            "zh": "我在呢~有需要随时叫我~",
            "en": "I'm right here — ping me anytime!",
            "ar": "أنا هنا، لا تتردد في السؤال في أي وقت.",
            "ru": "Я на связи — обращайтесь в любое время!",
            "th": "มีอะไรสอบถามเพิ่มเติมได้เลยนะค่ะ/ครับ",
            "vi": "Tôi ở đây rồi — liên hệ bất cứ lúc nào nhé!",
            "id": "Saya siap membantu kapan saja, jangan ragu ya!",
            "ms": "Saya sedia membantu bila-bila masa, jangan segan bertanya ya!",
            "tl": "Nandito lang ako — makikipag-chat ka paano man, huwag mahiya!",
        }
        self._dears = {
            "zh": "亲爱的", "en": "Dear", "ar": "عزيزي", "ru": "Дорогой",
            "th": "สวัสดีค่ะ/ครับ", "vi": "Kính chào quý khách",
            "id": "Hai, selamat datang", "ms": "Hai, pelanggan tersayang",
            "tl": "Mahal na customer"
        }
        self._fallback_replies = {
            "zh": "亲爱的，我在呢~刚才网络有点忙，你可以再说一下问题，我帮你看看。",
            "en": "Dear, I'm here! The line was busy -- could you say that again?",
            "ar": "عزيزي، أنا هنا! الشبكة مشغولة قليلاً، هل يمكنك المحاولة مرة أخرى؟",
            "ru": "Дорогой, я здесь! Сеть немного занята, попробуйте ещё раз.",
            "th": "สวัสดีค่ะ มีอะไรสอบถามเพิ่มเติมได้เลยนะค่ะ/ครับ",
            "vi": "Kính chào quý khách, tôi ở đây rồi! Mạng hơi bận, bạn thử lại nhé.",
            "id": "Hai, saya di sini! Jaringan agak sibuk, coba lagi ya!",
            "ms": "Hai, saya sida di sini! Rangkaian agak sibuk, cuba lagi ya!",
            "tl": "Mahal na customer, nandito lang ako! Medyo busy ang linya, subukan mo ulit!",
        }

    def generate(
        self,
        user_message: str,
        customer_info: dict,
        conversation_history: list[dict],
        language: str = "zh"
    ) -> EnhancedResponse:
        """
        生成增强版 AI 回复

        Returns:
            EnhancedResponse: 包含回复、元数据和 RAG 上下文的完整响应
        """
        user_message = (user_message or "").strip()
        if not user_message:
            return EnhancedResponse(
                reply=f"{self._dears.get(language, '亲爱的')}，我在呢~请问有什么可以帮您？",
                language=language, intent="general", confidence=1.0,
                emotion="neutral", emotion_intensity=0.3
            )

        # 1. 语言切换检测
        lang_switch = self._detect_lang_switch(user_message)
        if lang_switch:
            confirm = self._get_lang_switch_msg(lang_switch)
            return EnhancedResponse(
                reply=confirm, language=lang_switch, intent="general",
                confidence=1.0, emotion="neutral", emotion_intensity=0.3
            )

        # 2. 自动语言检测
        detected_lang = detect_language_simple(user_message)
        if detected_lang != language and detected_lang in self._lang_names:
            confirm = self._get_auto_lang_switch_msg(detected_lang)
            return EnhancedResponse(
                reply=confirm, language=detected_lang, intent="general",
                confidence=0.9, emotion="neutral", emotion_intensity=0.3
            )

        # 3. 转人工关键词检测
        # 只匹配明确要求人工客服的短语，不包含意图关键词（如"投诉"、"退款"）
        transfer_kw = [
            # 中文明确人工请求
            "转人工", "人工客服", "转人工客服", "转接人工", "人工介入",
            "找人工", "真人客服", "人工在线", "人工服务",
            # 英文明确人工请求
            "transfer to human", "live agent", "speak to human", "talk to human",
            "real person", "human support", "agent please",
            # 极端负面情绪 + 请求（需要人工）
            "找你们老板", "要投诉你们", "曝光你们",
        ]
        if any(kw.lower() in user_message.lower() for kw in transfer_kw):
            return EnhancedResponse(
                reply="好的，正在为您转接人工客服，请稍候...",
                language=language, intent="general", confidence=1.0,
                emotion="neutral", emotion_intensity=0.3, auto_transfer="human"
            )

        # 4. 无订单时的订单类查询
        # 仅当消息明确在询问"我的订单状态/订单号"时触发，不拦截其他意图
        orders = (customer_info or {}).get("orders") or []
        # 判断是否在询问"我的订单"（需要具体订单号/询问特定订单的状态）
        order_status_patterns = ["我的订单", "我的快递", "订单号", "单号", "order number", "my order"]
        is_explicit_order_query = any(p in user_message for p in order_status_patterns)
        if is_explicit_order_query and not orders:
            dear = self._dears.get(language, "亲爱的")
            tail = self._tails.get(language, self._tails["zh"])
            no_orders = {
                "zh": f"{dear}，档案里暂无订单记录，建议您提供订单号我来帮查。",
                "en": f"{dear}, no orders in your profile. Please provide the order number.",
            }
            reply = f"{no_orders.get(language, no_orders['zh'])}\n\n{tail}"
            return EnhancedResponse(
                reply=reply, language=language, intent="general",
                confidence=1.0, emotion="neutral", emotion_intensity=0.3
            )

        # 5. 意图分类（必须在无订单检查之后执行，以获得正确意图）
        intent_result = classify_intent(user_message, language)

        # 6. 情绪检测
        emotion, emotion_intensity = detect_emotion_enhanced(user_message, language)

        # 7. RAG 检索
        rag_context = self.rag_engine.retrieve(
            query=user_message,
            intent=intent_result.intent,
            routed_kb=intent_result.routed_knowledge_base,
            hyde_func=self.llm_call,
            limit=3
        )

        # 8. 图谱查询
        product_name = self._extract_product_name(user_message)
        graph_context = self.graph_engine.query_by_intent(
            intent=intent_result.intent,
            user_message=user_message,
            product_name=product_name
        )

        # 9. 构建客户档案摘要
        cust = customer_info or {}
        orders = cust.get("orders") or []
        profile_summary = (
            f"客户等级：{cust.get('customer', {}).get('level', '普通')}\n"
            f"累计订单：{len(orders)}单\n"
            f"客户地区：{cust.get('customer', {}).get('region', '未知')}"
        )

        # 10. 构建对话历史
        history_text = self._build_history_text(conversation_history, language)

        # 11. 构建升级检查上下文
        turn_count = len([m for m in conversation_history if m.get("role") == "user"])
        escalation_ctx = {
            "user_message": user_message,
            "intent": intent_result.intent,
            "confidence": intent_result.confidence,
            "turn_count": turn_count,
            "emotion": emotion,
        }
        escalation = check_escalation(escalation_ctx)
        should_escalate = escalation is not None

        # 12. 构建增强 System Prompt
        system_prompt = self._build_enhanced_system_prompt(
            user_message=user_message,
            language=language,
            intent=intent_result,
            emotion=emotion,
            emotion_intensity=emotion_intensity,
            profile_summary=profile_summary,
            history_text=history_text,
            rag_context=rag_context,
            graph_context=graph_context,
            turn_count=turn_count,
        )

        # 13. 调用 LLM 生成回复
        messages = [{"role": "system", "content": system_prompt}]
        for h in conversation_history[-10:]:
            messages.append(h)
        messages.append({"role": "user", "content": user_message})

        ai_reply = self.llm_call(messages, temperature=0.65, max_tokens=400)

        if not ai_reply:
            return EnhancedResponse(
                reply=self._fallback_replies.get(language, self._fallback_replies["zh"]),
                language=language, intent=intent_result.intent,
                confidence=0.3, emotion=emotion, emotion_intensity=emotion_intensity,
                rag_context=rag_context
            )

        # 14. 确保拟人化结尾存在
        tail = self._tails.get(language, self._tails["zh"])
        ai_reply = self._ensure_tail(ai_reply, tail, language)

        return EnhancedResponse(
            reply=ai_reply,
            language=language,
            intent=intent_result.intent,
            confidence=rag_context.confidence,
            emotion=emotion,
            emotion_intensity=emotion_intensity,
            rag_context=rag_context,
            should_escalate=should_escalate,
            escalation_reason=escalation.get("ticket_type", "") if escalation else "",
        )

    def _detect_lang_switch(self, msg: str) -> Optional[str]:
        patterns = {
            "zh": ["说中文", "用中文", "切换中文", "换中文", "讲中文", "中文回复"],
            "en": ["speak english", "switch to english", "say in english", "说英语"],
            "ar": ["العربية", "切换阿拉伯", "阿拉伯语", "arabic"],
            "ru": ["по-русски", "切换俄语", "на русском", "russian"],
            "th": ["ภาษาไทย", "พูดไทย", "切换泰语", "thai"],
            "vi": ["tiếng việt", "nói tiếng việt", "切换越南语", "vietnamese"],
            "id": ["bahasa indonesia", "切换印尼语", "indonesian"],
            "ms": ["bahasa melayu", "切换马来语", "malay"],
            "tl": ["filipino", "切换菲律宾语", "in filipino", "tagalog"],
        }
        msg_lower = msg.lower()
        for lang, pats in patterns.items():
            for p in pats:
                if p.lower() in msg_lower:
                    return lang
        return None

    def _get_lang_switch_msg(self, lang: str) -> str:
        msgs = {
            "zh": "好的，已切换到中文回复。",
            "en": "Switched to English. What can I help you with?",
            "ar": "تم التحويل إلى اللغة العربية.",
            "ru": "Переключено на русский язык.",
            "th": "สลับเป็นภาษาไทยแล้วค่ะ/ครับ",
            "vi": "Đã chuyển sang Tiếng Việt.",
            "id": "Sudah beralih ke Bahasa Indonesia.",
            "ms": "Telah bertukar ke Bahasa Melayu.",
            "tl": "Na-switch na sa Filipino.",
        }
        return msgs.get(lang, f"已切换到{self._lang_names.get(lang, lang)}回复。")

    def _get_auto_lang_switch_msg(self, lang: str) -> str:
        msgs = {
            "zh": "好的，已自动切换到中文回复。",
            "en": "Auto-switched to English.",
        }
        return msgs.get(lang, f"Auto-switched to {self._lang_names.get(lang, lang)}.")

    def _extract_product_name(self, msg: str) -> Optional[str]:
        """从消息中提取商品名称"""
        patterns = [
            r"(?:这个|那款|这款|那件|这件|请问)?([\u4e00-\u9fffA-Za-z0-9\s]{2,20})(?:可以|能寄|能买|尺寸|颜色|规格|多少钱)",
            r"(?:请问|想问一下)(?:这个|那款|这款)([\u4e00-\u9fffA-Za-z0-9\s]{2,15})(?:呢|吗|怎么样)",
        ]
        for p in patterns:
            m = re.search(p, msg)
            if m:
                return m.group(1).strip()
        return None

    def _build_history_text(self, history: list[dict], language: str) -> str:
        if not history:
            return "（首次对话）"
        role_map_zh = {"user": "你", "assistant": "AI"}
        role_map_en = {"user": "You", "assistant": "AI"}
        role_map = role_map_zh if language == "zh" else role_map_en
        role_map_default = role_map_zh

        lines = []
        for m in history[-8:]:
            role = role_map.get(m.get("role", ""), role_map_default.get(m.get("role", ""), m.get("role", "")))
            content = (m.get("content") or "")[:100]
            lines.append(f"  {role}：{content}")
        return "\n".join(lines)

    def _build_enhanced_system_prompt(
        self,
        user_message: str,
        language: str,
        intent,
        emotion: str,
        emotion_intensity: float,
        profile_summary: str,
        history_text: str,
        rag_context: RAGContext,
        graph_context: str,
        turn_count: int,
    ) -> str:
        """构建增强版 System Prompt"""
        lang_display = self._lang_names.get(language, "中文")
        style = RESPONSE_STYLES.get(intent.intent, RESPONSE_STYLES["general"]).get(
            language, RESPONSE_STYLES["general"]["zh"]
        )

        emotion_guide = self._get_emotion_guide(emotion, emotion_intensity, language)

        # RAG 知识注入
        rag_section = ""
        if rag_context.knowledge_summary:
            rag_section = f"\n【相关知识】\n{rag_context.knowledge_summary}\n"

        # 图谱注入
        graph_section = ""
        if graph_context:
            graph_section = f"\n【知识图谱补充】\n{graph_context}\n"

        tail = self._tails.get(language, self._tails["zh"])

        prompt = f"""【角色】你是金牌AI客服，回复要干练、先答后暖。

【意图分类】本轮识别为：{intent.intent}（置信度：{intent.confidence:.0%}）
【回复风格】{style['tone']} — {style['format']}
{rag_section}{graph_section}

【情绪响应】{emotion_guide}

【必须遵守 — 违反者将被投诉】
1) 先直接回答客户问题：给事实/步骤/数据；不铺垫、不空泛共情。
2) 回答完立即追加1句拟人化结尾语，格式为：「{tail}」
   ← 这一句必须出现，不能省略！
3) 全程用 {lang_display} 回复，禁止混写其他语言。
4) 字数：中文80-120字，英文50-80词，其他语言同短。
5) 拟人化结尾语必须放在回复最后一行，前面加一个空行隔开。
6) 若引用知识库内容，融入回答自然表述，不要说"根据知识库"。

【铁律】禁止捏造任何订单号/物流单号/发货时间。若档案中无订单，对订单类询问必须回复：「档案里暂无订单记录，建议您提供订单号我来帮查」。

【客户档案摘要】
{profile_summary}

【对话历史】
{history_text}

【客户消息】
「{user_message}」

请严格按以下格式回复：
[直接回答部分]

{tail}"""

        return prompt

    def _get_emotion_guide(self, emotion: str, intensity: float, language: str) -> str:
        """获取情绪响应指南"""
        guides = {
            "angry": {
                "zh": "检测到愤怒情绪（强度：{intensity:.0%}）：先一句真诚道歉+解决方案要点，再一句俏皮收尾；禁止长篇说教。",
                "en": "Anger detected (intensity: {intensity:.0%}): One sincere apology + fix first, then one warm line. No lectures.",
            },
            "sad": {
                "zh": "检测到悲伤情绪（强度：{intensity:.0%}）：先给明确帮助或下一步，再温柔一句；别急着推销。",
                "en": "Sadness detected (intensity: {intensity:.0%}): Give clear help or next steps first, then one gentle line. No sales pitch.",
            },
            "anxious": {
                "zh": "检测到焦虑情绪（强度：{intensity:.0%}）：先给答案/时间节点/操作步骤，再安抚一句；短句为主。",
                "en": "Anxiety detected (intensity: {intensity:.0%}): Give answer/steps first, then one reassuring line. Keep it short.",
            },
            "happy": {
                "zh": "检测到开心情绪（强度：{intensity:.0%}）：先回应对方说的点，再活泼一句；可简短推荐但要有理由。",
                "en": "Happiness detected (intensity: {intensity:.0%}): Acknowledge their point, then one lively line.",
            },
            "neutral": {
                "zh": "中性情绪：先答问题，再一句拟人化；不堆套话。",
                "en": "Neutral tone: Answer the question first, then one human-like closing. No fluff.",
            },
        }
        guide = guides.get(emotion, guides["neutral"]).get(
            language, guides[emotion]["zh"]
        )
        return guide.format(intensity=intensity)

    def _ensure_tail(self, reply: str, tail: str, language: str) -> str:
        """确保回复末尾有拟人化结尾语"""
        tail_patterns = [
            "i'm right here", "ping me anytime", "ask me anything",
            "لا تتردد", "в любое время", "มีอะไรสอบถาม",
            "lien he", "bất cứ lúc nào", "bisa saya bantu",
            "sedia membantu", "makikipag-chat", "随时叫我",
            "我在呢", "nandito lang ako"
        ]
        has_tail = any(p in reply.lower() for p in tail_patterns)
        if not has_tail:
            return reply.strip() + "\n\n" + tail
        return reply


# ============================================================
# 导出
# ============================================================

__all__ = [
    "EnhancedAIResponder",
    "EnhancedRAGEngine",
    "GraphQueryEngine",
    "RAGContext",
    "EnhancedResponse",
    "RESPONSE_STYLES",
    "GRAPH_QUERY_TEMPLATES",
]
