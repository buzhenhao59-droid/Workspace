# -*- coding: utf-8 -*-
"""
业务服务层 - 包含 GraphRAG、DeepSeek、AI 回复生成等逻辑
客服风格：先直接回答客户问题（事实/步骤/数据），再附一句简短拟人化收尾；
       避免长篇「心理洞察」「产品解读」分段堆砌。
"""
import json
import logging
import re
import requests
import threading
import time
from typing import Optional
from config import DEEPSEEK_API_KEY, DEEPSEEK_API_URL, GRAPHRAG_API_URL

logger = logging.getLogger(__name__)


# ============== DeepSeek 熔断器 ==============
# 解决 API 宕机时持续调用导致级联失败的问题

class CircuitBreaker:
    """
    熔断器：保护外部 API 调用，防止级联故障。

    状态流转：
      CLOSED（正常）→ 连续失败达到阈值 → OPEN（熔断）
      OPEN（熔断中）→ 冷却时间到 → HALF_OPEN（半开，允许一次探测）
      HALF_OPEN → 成功 → CLOSED；失败 → OPEN

    熔断期间直接返回 fallback，节省资源。
    """
    CLOSED, OPEN, HALF_OPEN = "closed", "open", "half_open"

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        expected_exception: type = Exception
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception

        self._state = self.CLOSED
        self._failure_count = 0
        self._last_failure_time: float = 0
        self._lock = threading.RLock()

    @property
    def state(self) -> str:
        with self._lock:
            if self._state == self.OPEN:
                if time.time() - self._last_failure_time >= self.recovery_timeout:
                    self._state = self.HALF_OPEN
                    logger.info(f"[CircuitBreaker] {self.name} 从 OPEN 进入 HALF_OPEN（冷却结束）")
            return self._state

    def is_available(self) -> bool:
        """当前是否允许发起调用"""
        return self.state != self.OPEN

    def record_success(self):
        """记录一次成功调用"""
        with self._lock:
            if self._state == self.HALF_OPEN:
                self._state = self.CLOSED
                self._failure_count = 0
                logger.info(f"[CircuitBreaker] {self.name} 从 HALF_OPEN 恢复到 CLOSED")
            elif self._state == self.CLOSED:
                self._failure_count = 0

    def record_failure(self):
        """记录一次失败调用"""
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()
            if self._state == self.HALF_OPEN:
                self._state = self.OPEN
                logger.warning(f"[CircuitBreaker] {self.name} HALF_OPEN 探测失败，重新进入 OPEN")
            elif self._state == self.CLOSED and self._failure_count >= self.failure_threshold:
                self._state = self.OPEN
                logger.warning(f"[CircuitBreaker] {self.name} 连续 {self._failure_count} 次失败，熔断 OPEN（{self.recovery_timeout}s 后尝试恢复）")

    def get_status(self) -> dict:
        """获取熔断器状态（用于监控）"""
        with self._lock:
            return {
                "name": self.name,
                "state": self.state,
                "failure_count": self._failure_count,
                "failure_threshold": self.failure_threshold,
                "last_failure_seconds_ago": round(time.time() - self._last_failure_time, 1) if self._last_failure_time else None,
                "recovery_timeout": self.recovery_timeout,
            }


# 全局熔断器（单例）
_deepseek_circuit = CircuitBreaker(
    name="deepseek_api",
    failure_threshold=5,   # 连续 5 次失败后熔断
    recovery_timeout=30.0  # 30 秒后尝试探测
)

# Neo4j 熔断器（连续失败后快速降级到 SQLite）
_neo4j_circuit = CircuitBreaker(
    name="neo4j_db",
    failure_threshold=3,   # Neo4j 宕机时更快降级
    recovery_timeout=60.0  # 60 秒后探测
)

# GraphRAG 熔断器
_graphrag_circuit = CircuitBreaker(
    name="graphrag_api",
    failure_threshold=3,   # 连续 3 次失败后熔断
    recovery_timeout=30.0  # 30 秒后探测
)


def query_graphrag(customer_id: str):
    """
    调用 GraphRAG API 获取客户信息（带熔断保护）。
    熔断期间直接返回 None，快速降级。
    """
    if not GRAPHRAG_API_URL:
        return None

    # 熔断器检查
    if not _graphrag_circuit.is_available():
        logger.debug("[CircuitBreaker] GraphRAG 熔断中，跳过请求")
        return None

    try:
        response = requests.post(
            GRAPHRAG_API_URL,
            json={"query": f"客户 {customer_id} 的完整档案"},
            timeout=5
        )
        if response.status_code == 200:
            _graphrag_circuit.record_success()
            data = response.json()
            logger.info(f"GraphRAG 返回数据成功: {customer_id}")
            return {
                "orders": data.get("orders", []),
                "skus": data.get("skus", []),
                "emotions": data.get("emotions", [])
            }
        else:
            _graphrag_circuit.record_failure()
            logger.warning(f"GraphRAG 返回错误状态: {response.status_code}")
    except requests.exceptions.Timeout:
        _graphrag_circuit.record_failure()
        logger.warning("GraphRAG 请求超时")
    except Exception as e:
        _graphrag_circuit.record_failure()
        logger.warning(f"GraphRAG 调用失败: {e}")
    return None


def _safe_float(val, default=0.0):
    """安全转 float，避免订单金额异常导致整段逻辑崩溃"""
    try:
        if val is None or val == "":
            return default
        return float(val)
    except (TypeError, ValueError):
        return default


def call_deepseek_api(messages: list, temperature: float = 0.7, max_tokens: int = 1000):
    """
    调用 DeepSeek API 生成回复。
    内置熔断器保护：连续失败 5 次后熔断 30 秒，期间直接返回 None。
    成功返回文本；失败返回 None。
    """
    if not DEEPSEEK_API_KEY:
        logger.error("DeepSeek API Key 未配置")
        return None

    # ---- 熔断器检查 ----
    if not _deepseek_circuit.is_available():
        logger.warning("[CircuitBreaker] DeepSeek API 熔断中，跳过请求")
        return None

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}"
    }

    payload = {
        "model": "deepseek-chat",
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    # 熔断状态下的探测请求（HOLD_OPEN）正常尝试
    timeouts = (15, 60)
    for attempt, timeout in enumerate(timeouts):
        try:
            response = requests.post(
                DEEPSEEK_API_URL,
                headers=headers,
                json=payload,
                timeout=timeout
            )
            if response.status_code == 200:
                data = response.json()
                choices = data.get("choices") or []
                if not choices:
                    logger.error("DeepSeek API 返回无 choices")
                    _deepseek_circuit.record_failure()
                    return None
                msg = choices[0].get("message") or {}
                content = (msg.get("content") or "").strip()
                _deepseek_circuit.record_success()
                return content if content else None
            logger.error(f"DeepSeek API 错误: {response.status_code} - {response.text[:500]}")
            _deepseek_circuit.record_failure()
        except requests.exceptions.Timeout as e:
            logger.warning(f"DeepSeek API 超时 (attempt {attempt + 1}, timeout={timeout}s): {e}")
            _deepseek_circuit.record_failure()
        except Exception as e:
            logger.error(f"DeepSeek API 调用失败: {e}")
            _deepseek_circuit.record_failure()
        if attempt < len(timeouts) - 1:
            continue
    return None


# ============== 金牌客服（干练：先答后暖） ==============

LEAN_CUSTOMER_PROMPT_TEMPLATE = """【角色】你是「金牌客服」助手，回复要干练、先答后暖。

【必须遵守】
1) 先直接回答客户「当前这句话」在问什么：给事实、步骤、数据或明确结论；不要铺垫、不要空泛共情、不要长篇产品故事。
2) 核心回答说完后，再单独用 1 句简短、俏皮或温暖的拟人化收尾（不要编号、不要用【心理洞察】【产品解读】【情感共鸣】等小节标题）。
3) 全文：中文约 80–120 字；英文约 50–80 词；阿拉伯语/俄语/泰语/越南语/印尼语/菲律宾语同样保持短。
4) 客户问订单号/订单/购买记录/物流售后入口等：只给订单信息与下一步操作，禁止讲无关产品故事或设计感。
5) 仅在客户明确要「推荐/选型/对比」时再推荐；若推荐需 1 句理由；若档案里有更合适的商品可写「更推荐…因为…」。
6) 称呼用「你」或「亲爱的」，不要在正文里写客户真实姓名。
7) 全段只用{lang_name}一种语言，禁止中英阿俄混写。

【铁律：禁止捏造数据】
- 严禁凭空捏造任何订单号、物流单号（即使是「SF123456789」类示例形式也禁止出现）、发货时间、收货地址。
- 若档案中无订单/商品数据，对订单类询问必须统一回复：「档案里暂无订单记录，建议您提供订单号我来帮查」。
- 严禁编造「已发货」「待发货」「物流单号已生成」等未确认状态。
- 如不确定，直接说「需要您提供更多信息」。

【客户档案】
{customer_context}

【对话历史】
{conversation_context}

【产品知识库摘要】
{product_context}

【客户原话】
「{user_message}」

请按：先直接答完 → 再一句拟人化收尾。"""


UPGRADED_AI_RULES = {
    'zh': {
        'lang_name': '中文',
        'dear': '亲爱的',
        'no_orders': '{dear}，档案里暂时没有订单记录。若在其他渠道下单，把订单号发我帮你核对。',
        'no_data_fallback': '{dear}，档案里暂时没有相关信息，麻烦提供一下订单号或具体问题，我帮你查一下～',
    },
    'en': {
        'lang_name': 'English',
        'dear': 'Dear',
        'no_orders': "{dear}, no orders in your profile yet. If you bought elsewhere, send the order ID and I'll check.",
        'no_data_fallback': "{dear}, I don't have that info on hand. Could you share the order ID or more details so I can look it up?",
    },
    'ar': {
        'lang_name': 'العربية',
        'dear': 'عزيزي',
        'no_orders': 'عزيزي، لا توجد طلبات في ملفك بعد. إذا اشتريت من مكان آخر، أرسل رقم الطلب وسأساعدك.',
        'no_data_fallback': 'عزيزي، لا تتوفر لدي تلك المعلومات. هل يمكنك مشاركة رقم الطلب أو المزيد من التفاصيل؟',
    },
    'ru': {
        'lang_name': 'Русский',
        'dear': 'Дорогой',
        'no_orders': 'Дорогой, в профиле пока нет заказов. Если покупали в другом месте, пришлите номер — проверю.',
        'no_data_fallback': 'Дорогой, у меня нет этих данных. Пришлите номер заказа или подробности — проверю.',
    },
    'th': {
        'lang_name': 'ภาษาไทย',
        'dear': 'สวัสดีค่ะ/ครับ',
        'no_orders': 'ไม่พบรายการสั่งซื้อในข้อมูลของคุณค่ะ หากสั่งซื้อจากช่องทางอื่น กรุณาแจ้งหมายเลขคำสั่งซื้อด้วยนะคะ/ครับ',
        'no_data_fallback': 'ข้อมูลนี้ยังไม่มีในระบบค่ะ ช่วยบอกหมายเลขคำสั่งซื้อหรือรายละเอียดเพิ่มเติมได้เลยนะคะ/ครับ จะตรวจสอบให้ทันทีเลยค่ะ/ครับ',
    },
    'vi': {
        'lang_name': 'Tiếng Việt',
        'dear': 'Kính chào quý khách',
        'no_orders': 'Hiện chưa có đơn hàng nào trong hồ sơ của bạn. Nếu đã đặt ở nơi khác, hãy gửi mã đơn hàng để tôi kiểm tra giúp nhé.',
        'no_data_fallback': 'Hiện tôi chưa có thông tin này trong hệ thống. Bạn cung cấp mã đơn hàng hoặc chi tiết thêm để tôi kiểm tra ngay nhé.',
    },
    'id': {
        'lang_name': 'Bahasa Indonesia',
        'dear': 'Hai, selamat datang',
        'no_orders': 'Saat ini belum ada pesanan di profil kamu. Kalau beli di tempat lain, coba kirim nomor pesanan — saya bantu cek ya.',
        'no_data_fallback': 'Saya belum punya info ini di sistem. Boleh kasih nomor pesanan atau detailnya supaya saya bisa cek langsung?',
    },
    'ms': {
        'lang_name': 'Bahasa Melayu',
        'dear': 'Hai, pelanggan tersayang',
        'no_orders': 'Buat masa ini belum ada pesanan dalam profil anda. Jika beli di tempat lain, sila berikan nombor pesanan — saya akan semak.',
        'no_data_fallback': 'Saya belum ada maklumat ini dalam sistem. Boleh berikan nombor pesanan atau butiran lanjut supaya saya boleh semak dengan segera?',
    },
    'tl': {
        'lang_name': 'Filipino',
        'dear': 'Mahal na customer',
        'no_orders': 'Wala pang order sa profile mo. Kung nag-order ka sa ibang paraan, padala mo ang order number — aalagan kita yan.',
        'no_data_fallback': 'Wala pa akong available na info para dito. Pwede mo bang ibigay ang order number o dagdag na details para masuri ko agad?',
    },
}


# 规则类直答后的统一「拟人化尾巴」
SERVICE_DIRECT_TEMPLATES = {
    'zh': {
        'tail': '我在呢，有需要再叫我～',
        'no_orders': '{dear}，档案里暂时没有订单记录。若在其他渠道下单，把订单号发我帮你核对。',
        'orders_block': '{dear}，查到 {count} 笔订单：\n{lines}\n要查物流或售后，告诉我具体订单号即可。',
        'order_line': '· {order_id} ｜{date}｜¥{total}｜{status}｜{items}',
        'no_products': '{dear}，档案里还没有购买记录。',
        'products_block': '{dear}，你买过的商品：{items}。',
        'recommend_block': '{dear}，结合你的购买偏好，推荐：{items}。理由：{reason}。',
        'recommend_fallback': '{dear}，可以先说说用途和预算，我帮你缩小范围；店里常出数码配件、手机支架等。',
        'no_emotions': '{dear}，暂时没有沟通/情绪类记录。',
        'emotions_block': '{dear}，近期沟通记录：{lines}。',
        'emotion_line': '{date} {etype} · {channel}',
    },
    'en': {
        'tail': "I'm here—ping me anytime.",
        'no_orders': "{dear}, no orders in your profile yet. If you bought elsewhere, send the order ID and I'll check.",
        'orders_block': '{dear}, found {count} order(s):\n{lines}\nFor tracking or after-sales, tell me the order ID.',
        'order_line': '· {order_id} | {date} | ¥{total} | {status} | {items}',
        'no_products': '{dear}, no purchase history yet.',
        'products_block': '{dear}, items you bought: {items}.',
        'recommend_block': '{dear}, based on your profile: {items}. Why: {reason}.',
        'recommend_fallback': "{dear}, tell me use case + budget and I'll narrow it down; we often sell accessories and stands.",
        'no_emotions': '{dear}, no communication/emotion records.',
        'emotions_block': '{dear}, recent notes: {lines}.',
        'emotion_line': '{date} {etype} · {channel}',
    },
    'ar': {
        'tail': 'أنا هنا إذا احتجتِ أي شيء.',
        'no_orders': '{dear}، لا توجد طلبات في الملف. إن اشتريت من قناة أخرى، أرسل رقم الطلب.',
        'orders_block': '{dear}، يوجد {count} طلب(ات):\n{lines}\nللتتبع أو ما بعد البيع، أرسل رقم الطلب.',
        'order_line': '· {order_id} | {date} | ¥{total} | {status} | {items}',
        'no_products': '{dear}، لا يوجد سجل مشتريات.',
        'products_block': '{dear}، مشترياتك: {items}.',
        'recommend_block': '{dear}، اقتراح: {items}. السبب: {reason}.',
        'recommend_fallback': '{dear}، اذكري الاستخدام والميزانية لأختصر الخيارات.',
        'no_emotions': '{dear}، لا سجلات تواصل.',
        'emotions_block': '{dear}، آخر الملاحظات: {lines}.',
        'emotion_line': '{date} {etype} · {channel}',
    },
    'ru': {
        'tail': 'Я на связи — напиши, если что.',
        'no_orders': '{dear}, в профиле заказов нет. Если покупали в другом месте — пришлите номер заказа.',
        'orders_block': '{dear}, найдено заказов: {count}\n{lines}\nДля отслеживания или сервиса — напишите номер заказа.',
        'order_line': '· {order_id} | {date} | ¥{total} | {status} | {items}',
        'no_products': '{dear}, покупок в профиле пока нет.',
        'products_block': '{dear}, что приобретали: {items}.',
        'recommend_block': '{dear}, по профилю логично: {items}. Потому что: {reason}.',
        'recommend_fallback': '{dear}, опиши задачу и бюджет — сузим выбор; часто берут аксессуары и подставки.',
        'no_emotions': '{dear}, записей общения нет.',
        'emotions_block': '{dear}, последние записи: {lines}.',
        'emotion_line': '{date} {etype} · {channel}',
    },
    'th': {
        'tail': 'มีอะไรสอบถามเพิ่มเติมได้เลยนะคะ/ครับ',
        'no_orders': '{dear}，ไม่พบรายการสั่งซื้อในข้อมูลของคุณค่ะ หากสั่งซื้อจากช่องทางอื่น กรุณาแจ้งหมายเลขคำสั่งซื้อด้วยนะคะ/ครับ',
        'orders_block': '{dear}，พบ {count} รายการ:\n{lines}\nหากต้องการติดตามพัสดุหรือบริการหลังการขาย แจ้งหมายเลขคำสั่งซื้อได้เลยค่ะ/ครับ',
        'order_line': '· {order_id} | {date} | ¥{total} | {status} | {items}',
        'no_products': '{dear}，ยังไม่มีประวัติการซื้อค่ะ/ครับ',
        'products_block': '{dear}，สินค้าที่เคยซื้อ: {items}.',
        'recommend_block': '{dear}，แนะนำตามประวัติ: {items}. เหตุผล: {reason}.',
        'recommend_fallback': '{dear}，บอกวัตถุประสงค์การใช้และงบประมาณมาได้เลยนะค่ะ/ครับ จะช่วยแนะนำให้ค่ะ/ครับ',
        'no_emotions': '{dear}，ยังไม่มีบันทึกการสื่อสารค่ะ/ครับ',
        'emotions_block': '{dear}，บันทึกล่าสุด: {lines}.',
        'emotion_line': '{date} {etype} · {channel}',
    },
    'vi': {
        'tail': 'Có gì thêm cứ hỏi nhé.',
        'no_orders': '{dear}，hiện chưa có đơn hàng nào trong hồ sơ của bạn. Nếu đã đặt ở nơi khác, hãy gửi mã đơn hàng để tôi kiểm tra giúp nhé.',
        'orders_block': '{dear}，tìm thấy {count} đơn hàng:\n{lines}\nĐể theo dõi hoặc bảo hành, hãy gửi mã đơn nhé.',
        'order_line': '· {order_id} | {date} | ¥{total} | {status} | {items}',
        'no_products': '{dear}，chưa có lịch sử mua hàng.',
        'products_block': '{dear}，sản phẩm đã mua: {items}.',
        'recommend_block': '{dear}，theo hồ sơ: {items}. Lý do: {reason}.',
        'recommend_fallback': '{dear}，kể cho tôi mục đích sử dụng và ngân sách nhé, tôi sẽ gợi ý phù hợp.',
        'no_emotions': '{dear}，chưa có ghi chú giao tiếp.',
        'emotions_block': '{dear}，ghi chú gần nhất: {lines}.',
        'emotion_line': '{date} {etype} · {channel}',
    },
    'id': {
        'tail': 'Ada yang lain bisa saya bantu?',
        'no_orders': '{dear}，saat ini belum ada pesanan di profil kamu. Kalau beli di tempat lain, coba kirim nomor pesanan — saya bantu cek ya.',
        'orders_block': '{dear}，ditemukan {count} pesanan:\n{lines}\nUntuk lacak atau after-sales, kasih tau nomor pesanan ya.',
        'order_line': '· {order_id} | {date} | ¥{total} | {status} | {items}',
        'no_products': '{dear}，belum ada riwayat pembelian.',
        'products_block': '{dear}，barang yang pernah dibeli: {items}.',
        'recommend_block': '{dear}，berdasarkan profil kamu: {items}. Alasan: {reason}.',
        'recommend_fallback': '{dear}，ceritain use case + budget ya, saya bantu carikan yang cocok.',
        'no_emotions': '{dear}，belum ada catatan komunikasi.',
        'emotions_block': '{dear}，catatan terbaru: {lines}.',
        'emotion_line': '{date} {etype} · {channel}',
    },
    'ms': {
        'tail': 'Ada apa-apa lagi, jangan segan bertanya ya.',
        'no_orders': '{dear}，buat masa ini belum ada pesanan dalam profil anda. Jika beli di tempat lain, sila berikan nombor pesanan — saya akan semak.',
        'orders_block': '{dear}，ditemui {count} pesanan:\n{lines}\nUntuk jejak atau servis lepas jual, sila berikan nombor pesanan ya.',
        'order_line': '· {order_id} | {date} | ¥{total} | {status} | {items}',
        'no_products': '{dear}，belum ada rekod pembelian.',
        'products_block': '{dear}，barang yang pernah dibeli: {items}.',
        'recommend_block': '{dear}，berdasarkan profil anda: {items}. Sewajarnya: {reason}.',
        'recommend_fallback': '{dear}，beritahu saya fungsi penggunaan dan bajet ya, saya cadangkan yang sesuai.',
        'no_emotions': '{dear}，belum ada rekod komunikasi.',
        'emotions_block': '{dear}，rekod terkini: {lines}.',
        'emotion_line': '{date} {etype} · {channel}',
    },
    'tl': {
        'tail': 'May iba pa ba kailangan mo? Nandito lang ako.',
        'no_orders': '{dear}，wala pang order sa profile mo. Kung nag-order ka sa ibang paraan, padala mo ang order number — aalagan kita yan.',
        'orders_block': '{dear}，may {count} order(s):\n{lines}\nPara sa tracking o after-sales, sabihin mo lang ang order number.',
        'order_line': '· {order_id} | {date} | ¥{total} | {status} | {items}',
        'no_products': '{dear}，wala pang purchase history.',
        'products_block': '{dear}，items na binili mo: {items}.',
        'recommend_block': '{dear}，base sa profile mo: {items}. Dahilan: {reason}.',
        'recommend_fallback': '{dear}，sabihin mo lang ang gamit at budget, aalagan kita maghanap.',
        'no_emotions': '{dear}，wala pang communication record.',
        'emotions_block': '{dear}，recent notes: {lines}.',
        'emotion_line': '{date} {etype} · {channel}',
    },
}


def _order_items_text(o: dict) -> str:
    """从订单里取出商品名列表（兼容 items / products）。"""
    items = o.get('items')
    if isinstance(items, list) and items:
        return '、'.join(str(x) for x in items[:6])
    names = []
    for p in (o.get('products') or [])[:6]:
        if isinstance(p, dict):
            n = p.get('name') or ''
            if n:
                names.append(n)
        elif p:
            names.append(str(p))
    return '、'.join(names) if names else '-'


def _try_direct_context_reply(user_message: str, customer_info: dict, language: str) -> Optional[str]:
    """
    订单/商品/推荐/沟通记录等可结构化回答时，直接基于档案短答 + 拟人化尾巴，避免模型写长文跑题。
    """
    msg = (user_message or '').strip()
    if not msg:
        return None
    msg_lower = msg.lower()
    lang = language if language in SERVICE_DIRECT_TEMPLATES else 'zh'
    t = SERVICE_DIRECT_TEMPLATES[lang]
    dear = UPGRADED_AI_RULES.get(lang, UPGRADED_AI_RULES['zh'])['dear']
    tail = t['tail']

    def _with_tail(body: str) -> Optional[str]:
        body = (body or '').strip()
        if not body:
            return None
        return f"{body}\n\n{tail}"

    orders = customer_info.get('orders') or []
    skus = customer_info.get('skus') or []
    emotions = customer_info.get('emotions') or []

    # 注意：英文不要用裸关键词 "order"，否则会误匹配 border/disorder 等
    order_keywords_zh = [
        '订单', '订单号', '单号', '购买记录', '购买历史', '消费记录', '有什么订单', '我的订单',
    ]
    order_keywords_other = [
        'commande', 'pedido', 'purchase history', 'order number', 'order id', 'order no',
        'номер заказа', 'طلب', 'رقم الطلب',
    ]
    product_keywords_zh = ['商品', '产品', '买过', '买过什么', '买了什么', '购买过', 'sku']
    product_keywords_other = ['achat', 'compra', 'покупка', 'what did i buy', 'what have i bought', 'purchased']
    recommend_keywords = [
        '推荐', 'recommend', 'recommendation', 'suggest', 'suggestion', '哪款', '选哪个', '有什么好的',
        '给我推荐', '帮我选', '哪个好',
    ]
    emotion_keywords = [
        'emotion', '情绪', '沟通', '反馈', '投诉', '表扬', 'communication', 'связь', 'سجل',
    ]

    def _has(kws):
        return any((kw in msg) or (kw.lower() in msg_lower) for kw in kws)

    def _has_order_intent() -> bool:
        if any(kw in msg for kw in order_keywords_zh):
            return True
        if _has(order_keywords_other):
            return True
        if re.search(r'(?i)\borders?\b', msg):
            return True
        if re.search(r'(?i)order\s*(number|id|no\.?|#)', msg):
            return True
        if re.search(r'(?i)my\s+orders?\b', msg):
            return True
        if re.search(r'(?i)\bзаказ(а|ов|у|е|ом)?\b', msg):
            return True
        return False

    def _has_product_intent() -> bool:
        if any(kw in msg for kw in product_keywords_zh):
            return True
        if _has(product_keywords_other):
            return True
        if re.search(r'(?i)\bproducts?\b', msg):
            return True
        if re.search(r'(?i)\b(sku|skus)\b', msg):
            return True
        if re.search(r'(?i)\b(bought|purchase[sd]?)\b', msg):
            return True
        return False

    if _has_order_intent():
        if not orders:
            return _with_tail(t['no_orders'].format(dear=dear))
        lines = []
        for o in orders[:10]:
            oid = o.get('order_id') or o.get('id') or '-'
            date_val = o.get('date') or o.get('created_at') or o.get('order_date') or '-'
            total_val = _safe_float(o.get('total') if o.get('total') is not None else o.get('amount', 0))
            status_val = o.get('status') if o.get('status') not in (None, '') else '-'
            items_str = _order_items_text(o)
            disp_total = int(total_val) if total_val == int(total_val) else round(total_val, 2)
            lines.append(t['order_line'].format(
                order_id=oid, date=date_val, total=disp_total, status=status_val, items=items_str
            ))
        block = t['orders_block'].format(dear=dear, count=len(orders), lines='\n'.join(lines))
        return _with_tail(block)

    if _has(recommend_keywords):
        if skus:
            top = skus[:3]
            names = [p.get('name') or '-' for p in top]
            items_str = '、'.join(names)
            cat = next((p.get('category') for p in skus if p.get('category')), '')
            if lang == 'zh':
                reason = f"和你常买的「{cat}」更匹配" if cat else '和你历史购买偏好更接近'
            elif lang == 'en':
                reason = f'matches your usual “{cat}” picks' if cat else 'fits your past purchases'
            elif lang == 'ar':
                reason = f"يتوافق مع تفضيلاتك في «{cat}»" if cat else 'قريب من مشترياتك السابقة'
            else:
                reason = f"ближе к твоим покупкам в категории «{cat}»" if cat else 'ближе к твоим прошлым покупкам'
            return _with_tail(t['recommend_block'].format(dear=dear, items=items_str, reason=reason))
        return _with_tail(t['recommend_fallback'].format(dear=dear))

    if _has_product_intent():
        if not skus:
            return _with_tail(t['no_products'].format(dear=dear))
        items = []
        seen = set()
        for p in skus[:15]:
            n = p.get('name', '')
            c = p.get('category', '')
            if n and n not in seen:
                seen.add(n)
                items.append(f"{n}（{c}）" if c else n)
        return _with_tail(t['products_block'].format(dear=dear, items='、'.join(items)))

    if _has(emotion_keywords):
        if not emotions:
            return _with_tail(t['no_emotions'].format(dear=dear))
        parts = []
        for e in emotions[:5]:
            parts.append(t['emotion_line'].format(
                date=e.get('date', '-'),
                etype=e.get('type', '-'),
                channel=e.get('channel', '-'),
            ))
        return _with_tail(t['emotions_block'].format(dear=dear, lines='；'.join(parts)))

    return None


def detect_emotion_advanced(user_message: str) -> str:
    """高级情绪检测"""
    msg = (user_message or '').lower().strip()

    angry_keywords = ['生气', '愤怒', '恼火', '发火', '烦', '讨厌', '垃圾', '差', '烂', '退货', '投诉', '不满', '再也不', '恨', '滚',
                      'shut up', 'angry', 'mad', 'hate', 'terrible', 'awful', 'worst', 'complaint', 'refund', 'return', 'annoyed', 'frustrated',
                      'плохо', 'ужасно', 'жалоба', 'злой', 'бесит']
    sad_keywords = ['难过', '伤心', '失望', '郁闷', '烦心', '累', '压力', '无奈', '心累',
                    'sad', 'unhappy', 'disappointed', 'depressed', 'tired', 'upset', 'frustrating',
                    'грустно', 'печально', 'разочарован']
    anxious_keywords = ['着急', '急', '焦虑', '担心', '害怕', '不安', '紧张', '什么时候', '多久',
                       'worried', 'anxious', 'when', 'how long', 'soon',
                       'волнуюсь', 'переживаю', 'скорее']
    happy_keywords = ['谢谢', '感谢', '好样的', '棒', '喜欢', '满意', '开心', '高兴', '不错', '很好', '优秀', '完美',
                      'good', 'great', 'excellent', 'amazing', 'wonderful', 'love', 'thank', 'thanks', 'perfect',
                      'спасибо', 'отлично', 'прекрасно', 'классно', 'доволен']
    curious_keywords = ['为什么', '怎么', '如何', '什么原理', 'why', 'how', 'what', '原理',
                        'почему', 'как', 'что']

    if any(kw in msg for kw in angry_keywords):
        return 'angry'
    if any(kw in msg for kw in sad_keywords):
        return 'sad'
    if any(kw in msg for kw in anxious_keywords):
        return 'anxious'
    if any(kw in msg for kw in happy_keywords):
        return 'happy'
    if any(kw in msg for kw in curious_keywords):
        return 'curious'
    return 'neutral'


def _build_product_context(skus: list) -> str:
    """构建产品知识库上下文"""
    if not skus:
        return (
            "（暂无购买/商品档案。注意：① 禁止凭空捏造任何订单号、物流单号或发货信息；"
            "② 客户询问订单时，若档案为空，统一回复：「档案里暂时没有订单记录，建议您提供订单号我来帮查」；"
            "③ 绝对不要编造「SF123456789」或类似物流单号，或「已发货/待发货」等未经确认的状态。）"
        )

    lines = ["【可供参考的产品知识库】"]
    seen = set()
    for p in skus[:10]:
        name = p.get('name', '')
        cat = p.get('category', '商品')
        price = p.get('price', 0)
        qty = p.get('quantity', 1)
        if name and name not in seen:
            seen.add(name)
            lines.append(f"  · {name}（{cat}，¥{price}，购买{qty}次）")
    return '\n'.join(lines)


def _build_conversation_context(history: list) -> str:
    """构建对话历史上下文"""
    if not history:
        return "（首次对话，无历史记录）"

    lines = []
    for msg in history[-6:]:
        role = msg.get('role', 'user')
        content = msg.get('content', '')[:100]
        if role == 'user':
            lines.append(f"  你：{content}")
        else:
            lines.append(f"  AI：{content[:80]}...")
    return '\n'.join(lines) if lines else "（首次对话，无历史记录）"


def _build_customer_context(customer_info: dict, language: str) -> str:
    """构建客户档案上下文"""
    customer = customer_info.get('customer', {})
    orders = customer_info.get('orders', [])
    skus = customer_info.get('skus', [])
    communications = customer_info.get('communications', [])

    name = customer.get('name') or customer.get('customer_id') or '未知'
    region = customer.get('region', '未知')
    level = customer.get('m_value') or customer.get('level', '普通客户')
    member_since = customer.get('member_since', '未知')

    order_count = len(orders)
    total_spent = sum(_safe_float(o.get('total', 0) or o.get('amount', 0)) for o in orders)

    recent_products = []
    seen = set()
    for o in orders[:3]:
        for p in o.get('products', [])[:2]:
            n = p.get('name', '')
            if n and n not in seen:
                seen.add(n)
                recent_products.append(n)
    recent_str = '、'.join(recent_products[:5]) if recent_products else '暂无购买'

    context = f"""客户昵称：{name}
会员等级：{level}
所在地区：{region}
注册时间：{member_since}
累计订单：{order_count}单，累计消费：¥{total_spent:.0f}
近期购买：{recent_str}"""

    if communications:
        context += f"\n沟通记录：{len(communications)}条"
    return context


EMOTION_GUIDANCE = {
    'angry': {
        'zh': "【语气】先一句真诚道歉+解决方案要点，再一句俏皮收尾；禁止长篇说教。",
        'en': "Tone: one line apology + fix, then one warm line. No lectures.",
        'ar': "النبرة: اعتذار قصير + حل، ثم سطر دافئ. بلا طول.",
        'ru': "Тон: извинение + суть решения, потом одно тёплое предложение. Без полотна."
    },
    'sad': {
        'zh': "【语气】先给明确帮助或下一步，再温柔一句；别急着推销。",
        'en': "Tone: clear help first, one gentle line. Don’t push sales.",
        'ar': "النبرة: مساعدة واضحة أولاً، ثم دفء بسيط.",
        'ru': "Тон: сначала конкретная помощь, потом одно тёплое слово."
    },
    'anxious': {
        'zh': "【语气】先给答案/时间节点/操作步骤，再安抚一句；短句为主。",
        'en': "Tone: answer/steps first, one reassuring line. Short sentences.",
        'ar': "النبرة: إجابة/خطوات أولاً، ثم طمأنة قصيرة.",
        'ru': "Тон: сначала ответ/шаги, потом короткое успокоение."
    },
    'happy': {
        'zh': "【语气】先回应对方说的点，再活泼一句；可简短推荐但要有理由。",
        'en': "Tone: acknowledge first, one lively line; optional brief rec with reason.",
        'ar': "النبرة: اعترف بالنقطة أولاً، ثم دفء حيوي قصير.",
        'ru': "Тон: сначала ответь по сути, потом одно живое предложение."
    },
    'curious': {
        'zh': "【语气】先给结论/要点，再补一句有趣补充；控制在短段落内。",
        'en': "Tone: conclusion first, one fun extra; keep it short.",
        'ar': "النبرة: الخلاصة أولاً، ثم إضافة ممتعة قصيرة.",
        'ru': "Тон: сначала суть, потом одно яркое дополнение — коротко."
    },
    'neutral': {
        'zh': "【语气】先答问题，再一句拟人化；不堆套话。",
        'en': "Tone: answer first, one human line. No filler.",
        'ar': "النبرة: أجب أولاً، ثم سطر دافئ. بلا حشو.",
        'ru': "Тон: сначала ответ, потом одно «живое» предложение. Без воды."
    }
}


def build_upgraded_system_prompt(customer_info: dict, conversation_history: list, language: str = "zh") -> str:
    """
    构建系统提示词：金牌客服「先直答、再一句拟人化」，并附带简短语气指引。
    """
    lang_rules = UPGRADED_AI_RULES.get(language, UPGRADED_AI_RULES['zh'])
    emotion = detect_emotion_advanced(conversation_history[-1]['content'] if conversation_history and conversation_history[-1].get('role') == 'user' else '')

    customer_context = _build_customer_context(customer_info, language)
    conversation_context = _build_conversation_context(conversation_history)
    product_context = _build_product_context(customer_info.get('skus', []))

    emotion_guidance = EMOTION_GUIDANCE.get(emotion, EMOTION_GUIDANCE['neutral']).get(language,
        EMOTION_GUIDANCE.get(emotion, EMOTION_GUIDANCE['neutral'])['zh'])

    prompt = LEAN_CUSTOMER_PROMPT_TEMPLATE.format(
        lang_name=lang_rules['lang_name'],
        customer_context=customer_context,
        conversation_context=conversation_context,
        product_context=product_context,
        user_message="{user_message}"
    )

    prompt += f"\n\n【语气提示】\n{emotion_guidance}"

    return prompt


def generate_customer_response(
    user_message: str,
    customer_info: dict,
    conversation_history: list,
    language: str = "zh",
    session_id: str = None
) -> str:
    """
    AI 客服回复：订单/商品/推荐等可结构化问题优先档案直答 + 拟人化尾巴；
    其余走模型，系统提示要求「先答客户问题 → 再一句拟人化」，并限制篇幅。

    新增功能：
    - 支持 session_id 参数，在语言切换时即时更新 Session 状态
    - 语种自动识别：检测客户切换语言后强制刷新后续回复的 Prompt 语种指令
    """
    user_message = (user_message or '').strip()
    if not user_message:
        lang_rules = UPGRADED_AI_RULES.get(language, UPGRADED_AI_RULES['zh'])
        return lang_rules.get('greeting', UPGRADED_AI_RULES['zh']['greeting'])

    lang_switch_patterns = {
        "zh": ["说中文", "用中文", "切换中文", "换中文", "中文回复", "请说中文", "我要说中文", "讲中文"],
        "en": ["speak english", "in english", "switch to english", "use english", "say in english", "talk in english", "english please", "说英语", "用英语", "切换英语", "换英语", "英语回复", "in english please"],
        "ar": ["العربية", " speaking arabic", "in arabic", "切换阿拉伯", "换阿拉伯", "阿拉伯语", "使用阿拉伯语"],
        "ru": ["по-русски", "на русском", "in russian", "切换俄语", "换俄语", "俄语回复", "说俄语"],
        "th": ["ภาษาไทย", "พูดไทย", "in thai", "switch to thai", "说泰语", "用泰语", "切换泰语", "泰语回复"],
        "vi": ["tiếng việt", "nói tiếng việt", "in vietnamese", "switch to vietnamese", "说越南语", "用越南语", "切换越南语"],
        "id": ["bahasa indonesia", "nanti bicara indonesia", "in indonesian", "switch to indonesian", "说印尼语", "用印尼语", "切换印尼语"],
        "ms": ["bahasa melayu", "nanti bicara melayu", "in malay", "switch to malay", "说马来语", "用马来语", "切换马来语"],
        "tl": ["filipino", "tagalog", "in filipino", "switch to filipino", "说菲律宾语", "用菲律宾语", "切换菲律宾语"],
    }

    user_lower = user_message.lower().strip()

    for lang_code, patterns in lang_switch_patterns.items():
        for pattern in patterns:
            if pattern in user_lower or pattern in user_message:
                # === 多语言优化：即时更新 Session 语种状态 ===
                if session_id:
                    try:
                        from session_mode import session_mode
                        session_mode.set_target_language(session_id, lang_code)
                    except Exception:
                        pass
                return f"__LANG_SWITCH__{lang_code}__LANG_SWITCH__"

    lang_rules = UPGRADED_AI_RULES.get(language, UPGRADED_AI_RULES['zh'])

    # =========================================================
    # 【关键修复】客户提到具体订单号/物流单号，但数据库无订单
    # → 直接返回「未找到」，禁止调用 DeepSeek（防止捏造）
    # =========================================================
    orders_in_db = customer_info.get('orders') or []
    user_lower = user_message.lower()
    # 检测客户是否在询问具体订单（提到了关键词+数字组合）
    order_keyword_patterns = [
        "订单", "order", "订单号", "ord-", "ord_", "单号",
        "快递", "物流", "运单", "tracking", "shipment",
        "退款", "退货", "refund", "return"
    ]
    has_order_keyword = any(kw in user_lower for kw in order_keyword_patterns)
    # 如果有订单关键词但数据库里没有订单记录 → 直接返回安全答案
    if has_order_keyword and not orders_in_db:
        dear = lang_rules.get('dear', '亲爱的')
        tail = lang_rules.get('tail', '有需要再叫我～')
        no_orders = lang_rules.get(
            'no_data_fallback',
            '{dear}，档案里暂无订单记录，建议您提供订单号我来帮查。'
        ).format(dear=dear)
        return f"{no_orders}\n\n{tail}"

    direct = _try_direct_context_reply(user_message, customer_info, language)
    if direct:
        return direct

    emotion = detect_emotion_advanced(user_message)

    customer_context = _build_customer_context(customer_info, language)
    conversation_context = _build_conversation_context(conversation_history)
    product_context = _build_product_context(customer_info.get('skus', []))
    emotion_guidance = EMOTION_GUIDANCE.get(emotion, EMOTION_GUIDANCE['neutral']).get(language,
        EMOTION_GUIDANCE.get(emotion, EMOTION_GUIDANCE['neutral'])['zh'])

    full_system = LEAN_CUSTOMER_PROMPT_TEMPLATE.format(
        lang_name=lang_rules['lang_name'],
        customer_context=customer_context,
        conversation_context=conversation_context,
        product_context=product_context,
        user_message=user_message
    )
    full_system += f"\n\n【语气提示】\n{emotion_guidance}"

    messages = [
        {"role": "system", "content": full_system}
    ]

    for msg in conversation_history[-20:]:
        messages.append(msg)
    messages.append({"role": "user", "content": user_message})

    ai_reply = call_deepseek_api(messages, temperature=0.65, max_tokens=450)
    # API 失败时用多语言友好兜底，绝不返回错误提示串（避免被翻译后仍显示「请稍后重试」）
    if ai_reply is None or not str(ai_reply).strip():
        fallback = {
            "zh": f"{lang_rules['dear']}，我在呢～刚才网络有点忙，你可以再说一下你的问题，我帮你看看。",
            "en": f"{lang_rules['dear']}, I'm here! The line was busy for a moment — could you say that again? I'll help right away.",
            "ar": f"{lang_rules['dear']}، أنا هنا! حدثت مشكلة بسيطة في الاتصال — هل يمكنك إعادة سؤالك؟",
            "ru": f"{lang_rules['dear']}, я на связи! Соединение подвисло — повторите, пожалуйста, вопрос, я помогу.",
        }
        return fallback.get(language, fallback["zh"])

    return ai_reply


def translate_text(text: str, target_lang: str, source_lang: str = "auto") -> str:
    """
    翻译文本 - 支持中文、英文、阿拉伯语、俄语。
    绝不抛错，失败时返回原文。
    已集成 Redis 缓存，重复翻译请求直接从缓存返回。
    """
    if not text or not str(text).strip():
        return text or ""
    text = str(text).strip()

    # === 性能优化：检查 Redis 翻译缓存 ===
    try:
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            from redis_store import get_translation_cache
            cached = loop.run_until_complete(
                get_translation_cache(text, source_lang, target_lang)
            )
            if cached:
                logger.debug(f"[Translation] 缓存命中: {source_lang} -> {target_lang}")
                return cached
        except Exception:
            pass
        finally:
            loop.close()
    except Exception:
        pass

    try:
        if not DEEPSEEK_API_KEY:
            logger.warning("翻译: API Key 未配置")
            return text

        def _has_enough_target_script(s: str, lang: str) -> bool:
            s = (s or "").strip()
            if not s:
                return False
            total = len(s)
            if lang == "ar":
                arabic_chars = sum(
                    1
                    for c in s
                    if ("\u0600" <= c <= "\u06ff") or ("\u0750" <= c <= "\u077f") or ("\u08a0" <= c <= "\u08ff")
                )
                return arabic_chars >= max(2, int(total * 0.25))
            if lang == "ru":
                russian_chars = sum(1 for c in s if "\u0400" <= c <= "\u04ff")
                return russian_chars >= max(2, int(total * 0.25))
            if lang == "zh":
                chinese_chars = sum(1 for c in s if "\u4e00" <= c <= "\u9fff")
                return chinese_chars >= max(1, int(total * 0.10))
            if lang == "en":
                latin_chars = sum(1 for c in s if ("A" <= c <= "Z") or ("a" <= c <= "z"))
                return latin_chars >= max(2, int(total * 0.20))
            return True

        lang_map = {
            "zh": "简体中文",
            "en": "英语",
            "ar": "阿拉伯语",
            "ru": "俄语"
        }
        target = lang_map.get(target_lang, "英语")

        system_content = f"""你是一个专业翻译引擎。你的任务是将用户输入准确翻译成{target}。

【强制要求】
1. 只输出翻译后的文本，不要添加任何解释、注释、报价或额外内容
2. 保持原文的语气、情感和风格
3. 确保输出完全是{target}，不能夹杂任何其他语言
4. 如果原文就是{target}，直接返回原文

直接输出翻译结果，不要使用引号包裹。"""

        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": text},
        ]
        result = call_deepseek_api(messages, temperature=0.1)
        if result is not None:
            result = str(result).strip()
        if result and _has_enough_target_script(result, target_lang):
            # === 性能优化：翻译成功后写入 Redis 缓存 ===
            try:
                import asyncio
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    from redis_store import set_translation_cache
                    loop.run_until_complete(
                        set_translation_cache(text, source_lang, target_lang, result)
                    )
                except Exception:
                    pass
                finally:
                    loop.close()
            except Exception:
                pass
            return result

        retry_system = f"""You are a professional translator. Translate to {target_lang} ONLY. Output ONLY the translation in {target}. No quotes."""
        retry_messages = [
            {"role": "system", "content": retry_system},
            {"role": "user", "content": text},
        ]
        retry = call_deepseek_api(retry_messages, temperature=0.0)
        if retry is not None:
            retry = str(retry).strip()
        if retry and _has_enough_target_script(retry, target_lang):
            # === 性能优化：翻译成功后写入 Redis 缓存 ===
            try:
                import asyncio
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    from redis_store import set_translation_cache
                    loop.run_until_complete(
                        set_translation_cache(text, source_lang, target_lang, retry)
                    )
                except Exception:
                    pass
                finally:
                    loop.close()
            except Exception:
                pass
            return retry
        return result if result else text
    except Exception as e:
        logger.warning(f"翻译异常 target_lang={target_lang}: {e}")
        return text


def detect_language(text: str) -> str:
    """
    语言检测 - 支持中文、英文、阿拉伯语、俄语
    """
    if not text:
        return "zh"

    # 统计各语言字符
    chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')

    # 阿拉伯语字符范围: \u0600-\u06ff, \u0750-\u077f, \u08a0-\u08ff
    arabic_chars = sum(1 for c in text if '\u0600' <= c <= '\u06ff' or '\u0750' <= c <= '\u077f' or '\u08a0' <= c <= '\u08ff')

    # 俄语字符范围: \u0400-\u04ff (西里尔字母)
    russian_chars = sum(1 for c in text if '\u0400' <= c <= '\u04ff')

    total_chars = len(text.strip())
    if total_chars == 0:
        return "zh"

    # 判断逻辑
    if chinese_chars > total_chars * 0.3:
        return "zh"
    elif arabic_chars > total_chars * 0.3:
        return "ar"
    elif russian_chars > total_chars * 0.3:
        return "ru"
    else:
        # 默认为英文
        return "en"


# 支持的语言列表
SUPPORTED_LANGUAGES = ["zh", "en", "ar", "ru", "th", "vi", "id", "ms", "tl"]

# 语言显示名称
LANGUAGE_NAMES = {
    "zh": "中文",
    "en": "英文",
    "ar": "阿拉伯语",
    "ru": "俄语",
    "th": "泰语",
    "vi": "越南语",
    "id": "印尼语",
    "ms": "马来语",
    "tl": "菲律宾语",
}

# 语言切换确认消息
LANGUAGE_SWITCH_MESSAGES = {
    "zh": "已切换到中文回复。",
    "en": "Switched to English.",
    "ar": "تم التحويل إلى اللغة العربية.",
    "ru": "Переключено на русский язык.",
    "th": "สลับเป็นภาษาไทยแล้วค่ะ/ครับ",
    "vi": "Đã chuyển sang Tiếng Việt.",
    "id": "Sudah beralih ke Bahasa Indonesia.",
    "ms": "Telah bertukar ke Bahasa Melayu.",
    "tl": "Na-switch na sa Filipino.",
}
