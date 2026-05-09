# -*- coding: utf-8 -*-
"""
AI 智能增强模块 - 融合 cross-border-ecommerce-chatbot.md 源文件

核心功能:
  1. 意图分类器 (8 类)  - 精准路由知识库
  2. 混合检索引擎       - 向量 + 关键词 + 知识图谱
  3. 查询意图增强 (HyDE) - 生成假设回答向量检索
  4. 语义去重          - RRF 融合后去重
  5. 情绪检测增强版      - 焦虑/愤怒/悲伤/开心 + 9种语言

基于源文件架构:
  - 技术框架: DeepSeek-V3 / BGE-m3 向量
  - 检索流程: 意图分类 → 查询增强 → 三路召回 → RRF → 精排 → 图谱注入 → LLM
  - 8 类意图: product_inquiry / logistics / payment / refund_return / policy / account / complaint / general
"""

import re
import time
import hashlib
import logging
from typing import Optional, Any
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ============================================================
# 1. 意图分类器 (8 类)
# ============================================================

INTENT_PATTERNS = {
    "product_inquiry": {
        "zh": [
            "尺寸", "颜色", "材质", "规格", "发货", "库存", "款式", "型号",
            "有没有", "可以买吗", "哪款", "哪个颜色", "大小", "手感", "质量",
            "尺码", "面料", "做工", "好不好", "怎么样", "实物", "图片",
            "product", "size", "color", "material", "spec", "stock", "inch"
        ],
        "en": [
            "size", "color", "material", "spec", "shipping", "stock",
            "inch", "cm", "available", "in stock", "out of stock",
            "what model", "which one", "does it come in"
        ],
        "ar": [
            "الحجم", "اللون", "المادة", "المواصفات", "الشحن", "المخزون",
            "متوفر", "غير متوفر", "أبعاد"
        ],
        "ru": [
            "размер", "цвет", "материал", "характеристики", "наличие",
            "товар", "модель", "доставка"
        ],
        "th": [
            "ขนาด", "สี", "วัสดุ", "สเปค", "สต็อก", "มีไหม", "สินค้า"
        ],
    },

    "logistics": {
        "zh": [
            "物流", "快递", "到哪了", "几天到", "什么时候到", "单号",
            "运单", "发货", "已发货", "派送", "签收", "追踪", "运输",
            "tracking", "delivery", "shipped", "arrive", "express"
        ],
        "en": [
            "tracking", "delivery", "shipped", "arrive", "express",
            "where is my order", "when will it arrive", "shipping status",
            "courier", "parcel", "package"
        ],
        "ar": [
            "الشحن", "التوصيل", "متابعة", "تاريخ الوصول", "المراقبة",
            "الطرد", "البريد السريع"
        ],
        "ru": [
            "доставка", "отслеживание", "посылка", "курьер",
            "прибудет", "отправлено", "логистика"
        ],
        "th": [
            "การจัดส่ง", "ติดตาม", "พัสดุ", "ถึงเมื่อไหร่", "ขนส่ง"
        ],
    },

    "payment": {
        "zh": [
            "支付", "付款", "到账", "汇率", "货币", "折扣", "优惠码",
            "优惠券", "积分", "红包", "满减", "活动价", "分期",
            "pay", "payment", "discount", "coupon", "price", "cost"
        ],
        "en": [
            "pay", "payment", "discount", "coupon", "price", "cost",
            "refund", "reimbursement", "currency", "exchange rate",
            "installment", "promo code"
        ],
        "ar": [
            "الدفع", "السعر", "الخصم", "القسيمة", "العملة", "السداد"
        ],
        "ru": [
            "оплата", "цена", "скидка", "купон", "валюта", "платёж"
        ],
        "th": [
            "ชำระเงิน", "ราคา", "ส่วนลด", "คูปอง", "เงิน"
        ],
    },

    "refund_return": {
        "zh": [
            "退货", "换货", "退款", "拒收", "退货退款", "售后",
            "退回", "不满意", "七天无理由", "退货流程", "拒收",
            "return", "refund", "exchange", "replace", "not satisfied"
        ],
        "en": [
            "return", "refund", "exchange", "replace", "not satisfied",
            "defective", "damaged", "wrong item", "money back",
            "return policy", "how to return"
        ],
        "ar": [
            "الإرجاع", "استرداد", "الاستبدال", "استرجاع", "عدم الرضا"
        ],
        "ru": [
            "возврат", "обмен", "деньги назад", "недоволен",
            "брак", "дефект", "не подошло"
        ],
        "th": [
            "คืนสินค้า", "เงินคืน", "เปลี่ยนสินค้า", "ไม่พอใจ"
        ],
    },

    "policy": {
        "zh": [
            "违禁品", "海关", "限制", "政策", "规定", "可以寄吗",
            "不让寄", "申报", "税收", "免税", "进口限制", "出口",
            "prohibited", "customs", "policy", "restriction", "declare"
        ],
        "en": [
            "prohibited", "customs", "policy", "restriction", "declare",
            "import", "export", "tax", "duty", "forbidden items",
            "can i ship"
        ],
        "ar": [
            "محظور", "الجمارك", "السياسة", "القيود", "إعلان",
            "ضريبة", "استيراد", "تصدير"
        ],
        "ru": [
            "запрещено", "таможня", "политика", "ограничение",
            "декларация", "налог", "ввоз", "вывоз"
        ],
        "th": [
            "ห้าม", "ศุลกากร", "นโยบาย", "ข้อจำกัด", "ภาษี"
        ],
    },

    "account": {
        "zh": [
            "账户", "登录", "密码", "封号", "账号", "注册", "认证",
            "实名", "验证", "找回密码", "无法登录", "账户异常",
            "account", "login", "password", "register", "verify"
        ],
        "en": [
            "account", "login", "password", "register", "verify",
            "sign in", "sign up", "locked", "suspended", "2fa",
            "authentication", "identity"
        ],
        "ar": [
            "الحساب", "تسجيل الدخول", "كلمة المرور", "التسجيل",
            "التحقق", "الهوية"
        ],
        "ru": [
            "аккаунт", "вход", "пароль", "регистрация", "верификация",
            "заблокирован", "идентификация"
        ],
        "th": [
            "บัญชี", "เข้าสู่ระบบ", "รหัสผ่าน", "ลงทะเบียน"
        ],
    },

    "complaint": {
        "zh": [
            "投诉", "差评", "态度", "不满意", "欺骗", "虚假宣传",
            "坑", "骗子", "退货理由", "举报", "曝光", "坑人",
            "complaint", "bad review", "scam", "fraud", "false advertising"
        ],
        "en": [
            "complaint", "bad review", "scam", "fraud", "false advertising",
            "poor service", "terrible", "awful", "cheated", "report",
            "negative feedback"
        ],
        "ar": [
            "شكوى", "مراجعة سيئة", "احتيال", "إعلان كاذب",
            "خدمة سيئة", "بلاغ"
        ],
        "ru": [
            "жалоба", "плохой отзыв", "мошенничество", "ложная реклама",
            "ужасный сервис"
        ],
        "th": [
            "ร้องเรียน", "รีวิวแย่", "หลอกลวง", "โกง"
        ],
    },

    "general": {
        "zh": [
            "你好", "hi", "hello", "在吗", "请问", "咨询", "帮忙",
            "怎么用", "help", "who are you", "what is this"
        ],
        "en": [
            "hello", "hi", "hey", "help", "how", "what", "who",
            "what is this", "can you help"
        ],
        "ar": [
            "مرحبا", "اهلا", "مساعدة", "من انت", "ماذا"
        ],
        "ru": [
            "привет", "здравствуйте", "помощь", "кто ты", "что"
        ],
        "th": [
            "สวัสดี", "ช่วย", "ช่วยเหลือ", "ใคร", "อะไร"
        ],
    },
}


@dataclass
class IntentResult:
    intent: str
    confidence: float
    matched_keywords: list[str] = field(default_factory=list)
    routed_knowledge_base: str = ""
    response_style: str = "neutral"


def detect_language_simple(text: str) -> str:
    """简单语言检测"""
    text = text.lower()
    if re.search(r'[\u4e00-\u9fff]', text):
        return "zh"
    if re.search(r'[\u0600-\u06ff]', text):
        return "ar"
    if re.search(r'[\u0400-\u04ff]', text):
        return "ru"
    if re.search(r'[\u0e00-\u0e7f]', text):
        return "th"
    return "en"


def classify_intent(user_message: str, language: str = None) -> IntentResult:
    """
    8 类意图分类器

    路由知识库映射:
      product_inquiry    → 商品知识库
      logistics          → 物流知识库
      payment           → 支付库
      refund_return     → 退换货政策
      policy            → 政策库
      account           → 账户帮助
      complaint         → 投诉流程
      general           → 全量检索
    """
    if language is None:
        language = detect_language_simple(user_message)

    # 预处理：去掉标点，转小写（英文部分有效，中文不变）
    import re as _re
    clean = re.sub(r'[^\w\u4e00-\u9fff\s]', ' ', user_message)
    text_lower = clean.lower().strip()
    text_has = lambda kw: kw.lower() in text_lower or kw in user_message

    best_intent = "general"
    best_score = 0.0
    best_keywords = []

    # 意图权重：基础分 + boost
    # boost 让某些关键词有更高优先级
    intent_boost = {
        "refund_return": ["退款", "退货", "换货", "退钱", "退", "return", "refund"],
        "complaint": ["投诉", "差评", "不满", "坑", "complaint", "terrible", "退款", "退货"],
        "logistics": ["物流", "快递", "到哪", "几天", "tracking", "delivery", "arrive", "派送"],
        "account": ["封号", "被盗", "密码", "登录不了", "无法登录"],
    }

    # 增强的关键词模式（中文更丰富）
    enhanced_patterns = {
        "product_inquiry": {
            "zh": ["尺寸", "颜色", "材质", "规格", "发货", "库存", "款式", "型号", "有没有",
                   "哪款", "哪个颜色", "大小", "手感", "好不好", "怎么样", "实物", "图片",
                   "尺码", "面料", "做工", "商品", "产品", "这个", "那款", "这款", "那个", "这个"],
            "en": ["size", "color", "material", "spec", "shipping", "stock", "inch", "cm",
                   "available", "what model", "which one"],
        },
        "logistics": {
            "zh": ["物流", "快递", "到哪", "几天", "到哪了", "什么时候到", "单号", "运单",
                   "发货", "已发货", "派送", "签收", "追踪", "运输", "快递员", "包裹",
                   "取件", "投递", "时效", "清关", "海关"],
            "en": ["tracking", "delivery", "shipped", "arrive", "express", "courier",
                   "parcel", "package", "where is my order", "when will it arrive"],
        },
        "payment": {
            "zh": ["支付", "付款", "到账", "汇率", "货币", "折扣", "优惠码", "优惠券",
                   "积分", "红包", "满减", "活动价", "分期", "价格", "多少钱", "贵不贵"],
            "en": ["pay", "payment", "discount", "coupon", "price", "cost", "refund",
                   "currency", "exchange rate", "installment", "promo code"],
        },
        "refund_return": {
            "zh": ["退货", "换货", "退款", "拒收", "退货退款", "七天无理由", "退货流程",
                   "不满意", "不喜欢", "退回去", "收到退货", "退款到账"],
            "en": ["return", "refund", "exchange", "replace", "not satisfied", "defective",
                   "damaged", "wrong item", "money back", "return policy"],
        },
        "policy": {
            "zh": ["违禁", "海关", "限制", "政策", "规定", "可以寄吗", "不让寄",
                   "申报", "税收", "免税", "进口", "出口", "限制"],
            "en": ["prohibited", "customs", "policy", "restriction", "declare",
                   "import", "export", "tax", "duty", "forbidden"],
        },
        "account": {
            "zh": ["账户", "登录", "密码", "封号", "账号", "注册", "认证", "实名",
                   "验证", "找回密码", "无法登录", "账户异常", "被盗"],
            "en": ["account", "login", "password", "register", "verify", "locked",
                   "suspended", "2fa", "authentication"],
        },
        "complaint": {
            "zh": ["投诉", "差评", "态度", "不满意", "欺骗", "虚假宣传", "坑", "骗子",
                   "举报", "曝光", "太差", "太烂", "垃圾", "糟糕", "恶劣", "坑人"],
            "en": ["complaint", "bad review", "scam", "fraud", "false advertising",
                   "poor service", "terrible", "awful", "cheated", "negative feedback"],
        },
        "general": {
            "zh": ["你好", "hi", "hello", "在吗", "请问", "咨询", "帮忙", "怎么用", "help"],
            "en": ["hello", "hi", "hey", "help", "how", "what", "who", "can you help"],
        },
    }

    for intent, patterns in enhanced_patterns.items():
        lang_patterns = patterns.get(language, patterns.get("zh", []))
        matched = [p for p in lang_patterns if text_has(p)]
        base_score = len(matched)

        boost = 0.0
        if intent in intent_boost:
            for kw in intent_boost[intent]:
                if text_has(kw):
                    boost += 2.0

        total_score = base_score + boost

        if total_score > best_score:
            best_score = total_score
            best_intent = intent
            best_keywords = matched

    kb_mapping = {
        "product_inquiry": "商品知识库",
        "logistics": "物流知识库",
        "payment": "支付库",
        "refund_return": "退换货政策库",
        "policy": "政策库",
        "account": "账户帮助",
        "complaint": "投诉流程库",
        "general": "全量检索",
    }

    style_mapping = {
        "refund_return": "detailed",
        "complaint": "empathetic",
        "account": "step_by_step",
        "policy": "precise",
        "general": "friendly",
    }

    confidence = min(best_score / 3.0, 1.0) if best_score > 0 else 0.3

    return IntentResult(
        intent=best_intent,
        confidence=confidence,
        matched_keywords=best_keywords,
        routed_knowledge_base=kb_mapping.get(best_intent, "全量检索"),
        response_style=style_mapping.get(best_intent, "neutral"),
    )


# ============================================================
# 2. 增强版情绪检测（融合源文件情绪分类）
# ============================================================

EMOTION_KEYWORDS = {
    "angry": {
        "zh": ["生气", "愤怒", "投诉", "退款", "退货", "垃圾", "烂透了", "太差",
               "坑", "骗子", "欺骗", "虚假", "非常不满", "非常生气", "要投诉",
               "退款退货", "垃圾商品", "烂死了", "怒", "气愤"],
        "en": ["angry", "furious", "refund", "return", "terrible", "awful",
               "worst", "scam", "cheated", "hate", "complaint", "rip off",
               "complete garbage", "extremely disappointed"],
        "ar": ["غاضب", "غضب", "استرداد", "إرجاع", "سيء جداً", "احتيال"],
        "ru": ["злой", "гнев", "возврат", "ужасный", "мошенничество"],
        "th": ["โกรธ", "หงุดหงิด", "ไม่พอใจมาก", "หลอกลวง", "แย่มาก"],
    },
    "sad": {
        "zh": ["难过", "伤心", "沮丧", "郁闷", "失望", "不开心", "郁闷",
               "心塞", "失落", "绝望", "没有希望", "好难", "怎么办"],
        "en": ["sad", "disappointed", "upset", "depressed", "unhappy", "hopeless",
               "what should i do", "feeling down", "frustrated"],
        "ar": ["حزين", "مخيب", "محبط", "مكتئب"],
        "ru": ["грустный", "разочарован", "подавлен", "несчастный"],
        "th": ["เศร้า", "ผิดหวัง", "ท้อแท้", "สิ้นหวัง"],
    },
    "anxious": {
        "zh": ["着急", "焦虑", "担心", "急", "很急", "慌", "怎么办",
               "快", "来不及", "超时", "来不及了", "很担心", "焦虑",
               "等不及", "多久", "多久能到", "急死了", "催"],
        "en": ["anxious", "worried", "urgent", "hurry", "when", "how long",
               "still waiting", "took too long", "impatient", " ASAP",
               "as soon as possible", "can't wait"],
        "ar": ["قلق", "عاجل", "مستعجل", "متى", "كم يستغرق"],
        "ru": ["тревожно", "срочно", "волнуюсь", "когда", "скорее"],
        "th": ["กังวล", "รีบ", "ด่วน", "เร็วๆ", "รอไม่ไหว"],
    },
    "happy": {
        "zh": ["谢谢", "好", "棒", "喜欢", "满意", "太好了", "开心",
               "非常满意", "good", "great", "perfect", "爱了", "好喜欢"],
        "en": ["thank", "thanks", "great", "perfect", "excellent", "love it",
               "amazing", "wonderful", "awesome", "best"],
        "ar": ["شكرا", "ممتاز", "رائع", "حب", "سعيد"],
        "ru": ["спасибо", "отлично", "прекрасно", "доволен", "люблю"],
        "th": ["ขอบคุณ", "ดีมาก", "ยอดเยี่ยม", "ชอบ", "มีความสุข"],
    },
}


def detect_emotion_enhanced(message: str, language: str = None) -> tuple[str, float]:
    """
    增强版情绪检测

    Returns:
        (emotion, intensity) - emotion: angry/sad/anxious/happy/neutral
                               intensity: 0.0-1.0
    """
    if language is None:
        language = detect_language_simple(message)

    text_lower = message.lower()
    emotion_scores = {}

    for emotion, keywords_dict in EMOTION_KEYWORDS.items():
        keywords = keywords_dict.get(language, keywords_dict.get("zh", []))
        matched = [kw for kw in keywords if kw.lower() in text_lower]
        score = len(matched)
        if matched:
            intensity = min(0.5 + score * 0.15, 1.0)
            emotion_scores[emotion] = (score, intensity)

    if emotion_scores:
        best = max(emotion_scores.items(), key=lambda x: x[1][0])
        return best[0], best[1][1]

    return "neutral", 0.3


# ============================================================
# 3. 查询意图增强 (HyDE - Hypothetical Document Embeddings)
# ============================================================

HYDE_INSTRUCTION = """你是一个专业的跨境电商客服问答助手。请根据买家的问题，生成一个假设的最佳回答。

要求：
1. 回答要专业、准确、简洁
2. 包含具体的数据、步骤或事实
3. 如果是问物流，给出预计时间范围
4. 如果是问商品，给出具体规格参数
5. 如果是问政策，引用具体政策条款
6. 只输出假设回答内容，禁止任何解释或前缀

买家问题：{user_message}

假设最佳回答："""


def generate_hypothetical_answer(user_message: str, call_llm_func, language: str = "zh") -> str:
    """
    生成假设回答（HyDE 核心）

    这个假设回答会被用于：
    1. 向量检索（找到与假设回答语义最接近的知识库内容）
    2. 与真实用户问题一起做混合检索
    """
    try:
        prompt = HYDE_INSTRUCTION.format(user_message=user_message)
        result = call_llm_func(
            [{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=200
        )
        return result if result else user_message
    except Exception as e:
        logger.warning(f"[HyDE] 生成假设回答失败: {e}")
        return user_message


# ============================================================
# 4. 语义去重 (SimHash / MinHash 简化版)
# ============================================================

class SemanticDeduplicator:
    """
    简化版语义去重器

    使用 n-gram fingerprint + Jaccard 相似度
    适用于知识库检索结果去重
    """

    def __init__(self, threshold: float = 0.85):
        self.threshold = threshold
        self._cache = {}

    def _ngram_fingerprint(self, text: str, n: int = 3) -> set:
        """生成 n-gram 指纹"""
        text = re.sub(r'\s+', '', text.lower())
        if len(text) < n:
            return {text}
        return {text[i:i+n] for i in range(len(text) - n + 1)}

    def _jaccard(self, set1: set, set2: set) -> float:
        """计算 Jaccard 相似度"""
        if not set1 or not set2:
            return 0.0
        intersection = len(set1 & set2)
        union = len(set1 | set2)
        return intersection / union if union > 0 else 0.0

    def is_duplicate(self, text1: str, text2: str) -> bool:
        """判断两个文本是否语义重复"""
        key = hashlib.md5((text1[:100] + text2[:100]).encode()).hexdigest()
        if key in self._cache:
            return self._cache[key]

        fp1 = self._ngram_fingerprint(text1)
        fp2 = self._ngram_fingerprint(text2)
        similarity = self._jaccard(fp1, fp2)

        result = similarity >= self.threshold
        self._cache[key] = result
        return result

    def deduplicate(self, items: list[dict]) -> list[dict]:
        """
        对检索结果去重

        Args:
            items: [{"text": "...", "score": 0.95, "source": "..."}]

        Returns:
            去重后的列表，保留最高分
        """
        if not items:
            return []

        unique = []
        for item in items:
            text = item.get("text", "")
            is_dup = False
            for existing in unique:
                if self.is_duplicate(text, existing.get("text", "")):
                    is_dup = True
                    if item.get("score", 0) > existing.get("score", 0):
                        existing["score"] = item["score"]
                        existing["source"] = item.get("source", "")
                    break
            if not is_dup:
                unique.append(item.copy())

        return unique

    def clear_cache(self):
        """清空缓存"""
        self._cache.clear()


# ============================================================
# 5. RRF 融合 (Reciprocal Rank Fusion)
# ============================================================

def rrf_fusion(ranked_lists: list[list[dict]], k: int = 60) -> list[dict]:
    """
    倒数排名融合 (RRF)

    将多路检索结果融合为统一排序

    Args:
        ranked_lists: 多路检索结果列表，每路是按相关性排序的 dict 列表
                     dict 必须包含 "text" 字段用于去重识别
        k: RRF 参数，默认 60

    Returns:
        融合后的统一排序列表
    """
    if not ranked_lists:
        return []
    if len(ranked_lists) == 1:
        return ranked_lists[0]

    score_map = {}
    source_map = {}

    for rank_list in ranked_lists:
        for rank, item in enumerate(rank_list):
            key = hashlib.md5(item.get("text", str(item)).encode()).hexdigest()
            rrf_score = 1.0 / (k + rank + 1)
            score_map[key] = score_map.get(key, 0.0) + rrf_score
            if key not in source_map:
                source_map[key] = item.copy()

    sorted_keys = sorted(score_map.keys(), key=lambda k: score_map[k], reverse=True)
    result = []
    for key in sorted_keys:
        item = source_map[key]
        item["rrf_score"] = round(score_map[key], 4)
        result.append(item)

    return result


# ============================================================
# 6. 知识库检索接口 (抽象接口，集成时需实现)
# ============================================================

class KnowledgeBaseRetriever:
    """
    知识库检索器接口

    需要集成的知识库:
    - 商品知识库 (product_chunks)
    - 物流知识库 (logistics_faq)
    - 支付知识库 (payment_faq)
    - 退换货政策库 (refund_policy)
    - 政策库 (policy_documents)
    - FAQ 知识库 (kb_articles)

    集成方式:
    1. 如果有 pgvector: 使用向量检索 + 关键词检索
    2. 如果有 Neo4j: 使用图谱关系扩展
    3. 简化模式: 使用关键词+TF-IDF 匹配
    """

    def __init__(self):
        self.dedup = SemanticDeduplicator(threshold=0.85)
        self._vector_available = False
        self._neo4j_available = False

    def search(self, query: str, kb_type: str, limit: int = 5,
               use_vector: bool = True) -> list[dict]:
        """
        检索知识库

        Args:
            query: 用户查询
            kb_type: 知识库类型 (product/logistics/payment/refund/policy/faq)
            limit: 返回数量上限
            use_vector: 是否使用向量检索

        Returns:
            [{"text": "...", "score": 0.95, "source": "商品库", "type": "..."}]
        """
        results = []

        if use_vector and self._vector_available:
            results = self._vector_search(query, kb_type, limit)
        else:
            results = self._keyword_search(query, kb_type, limit)

        return results[:limit]

    def _vector_search(self, query: str, kb_type: str, limit: int) -> list[dict]:
        """
        向量检索（需要 pgvector 支持）

        集成说明:
        - 使用 BGE-m3 生成 query_embedding (1024维)
        - 使用 HNSW 索引加速检索
        - 结合关键词过滤 (metadata filtering)
        """
        logger.debug(f"[Retriever] 向量检索 (kb={kb_type}, query={query[:30]}...)")
        return []

    def _keyword_search(self, query: str, kb_type: str, limit: int) -> list[dict]:
        """
        关键词检索（TF-IDF 简化版）

        适用于无向量数据库时的降级方案
        """
        logger.debug(f"[Retriever] 关键词检索 (kb={kb_type}, query={query[:30]}...)")
        return []

    def hybrid_search(self, query: str, kb_types: list[str] = None,
                      limit_per_kb: int = 5) -> list[dict]:
        """
        混合检索

        1. 在指定知识库中并行检索
        2. RRF 融合
        3. 语义去重
        """
        if kb_types is None:
            kb_types = ["faq"]

        ranked_lists = []
        for kb_type in kb_types:
            results = self.search(query, kb_type, limit=limit_per_kb, use_vector=False)
            if results:
                ranked_lists.append(results)

        fused = rrf_fusion(ranked_lists)
        deduplicated = self.dedup.deduplicate(fused)
        return deduplicated


# ============================================================
# 7. 升级规则引擎
# ============================================================

ESCALATION_RULES = [
    {
        "id": "human_request",
        "trigger": lambda ctx: any(kw in ctx.get("user_message", "").lower()
                                   for kw in ["转人工", "人工客服", "真人", "live agent",
                                              "human", "投诉", "complaint", "refund", "退款"]),
        "ticket_type": "人工介入",
        "priority": "high",
    },
    {
        "id": "complaint",
        "trigger": lambda ctx: ctx.get("intent") == "complaint",
        "ticket_type": "投诉处理",
        "priority": "high",
    },
    {
        "id": "fund_loss",
        "trigger": lambda ctx: any(kw in ctx.get("user_message", "").lower()
                                   for kw in ["封号", "资金损失", "账号被盗",
                                              "account hacked", "money stolen"]),
        "ticket_type": "资金安全",
        "priority": "critical",
    },
    {
        "id": "prohibited_policy",
        "trigger": lambda ctx: ctx.get("intent") == "policy" and ctx.get("confidence", 0) < 0.5,
        "ticket_type": "政策咨询",
        "priority": "medium",
    },
    {
        "id": "unresolved_3turns",
        "trigger": lambda ctx: ctx.get("turn_count", 0) >= 3 and ctx.get("resolved", False) is False,
        "ticket_type": "升级咨询",
        "priority": "medium",
    },
]


def check_escalation(context: dict) -> Optional[dict]:
    """
    检查是否需要升级工单

    Args:
        context: {"user_message": "...", "intent": "...", "confidence": 0.8,
                  "turn_count": 2, "resolved": False, "emotion": "angry"}

    Returns:
        {"should_escalate": True, "ticket_type": "...", "priority": "high"}
        或 None
    """
    for rule in ESCALATION_RULES:
        try:
            if rule["trigger"](context):
                return {
                    "should_escalate": True,
                    "ticket_type": rule["ticket_type"],
                    "priority": rule["priority"],
                }
        except Exception:
            continue
    return None


# ============================================================
# 8. 智能上下文构建器
# ============================================================

def build_smart_context(
    user_message: str,
    conversation_history: list[dict],
    customer_info: dict,
    language: str = "zh"
) -> dict:
    """
    构建智能上下文

    整合意图分类、情绪检测、知识检索结果
    """
    intent_result = classify_intent(user_message, language)
    emotion, intensity = detect_emotion_enhanced(user_message, language)

    context = {
        "user_message": user_message,
        "language": language,
        "intent": intent_result.intent,
        "intent_confidence": intent_result.confidence,
        "intent_matched_keywords": intent_result.matched_keywords,
        "routed_kb": intent_result.routed_knowledge_base,
        "response_style": intent_result.response_style,
        "emotion": emotion,
        "emotion_intensity": intensity,
        "customer": customer_info,
        "turn_count": len([m for m in conversation_history if m.get("role") == "user"]),
    }

    return context


# ============================================================
# 导出
# ============================================================

__all__ = [
    "IntentResult",
    "classify_intent",
    "detect_language_simple",
    "detect_emotion_enhanced",
    "generate_hypothetical_answer",
    "SemanticDeduplicator",
    "rrf_fusion",
    "KnowledgeBaseRetriever",
    "check_escalation",
    "build_smart_context",
    "INTENT_PATTERNS",
    "EMOTION_KEYWORDS",
    "ESCALATION_RULES",
]
