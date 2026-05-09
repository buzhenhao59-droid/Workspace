# -*- coding: utf-8 -*-
"""
翻译术语库 (Translation Glossary)

功能：
- 在翻译前对"政策关键词"进行强制保留
- 防止通用翻译API将专业词汇翻译错误
- 支持多语言术语对照
- 术语库可热更新

原理：
1. 翻译前，先匹配术语库中的关键词
2. 将匹配到的原文标记为特殊占位符
3. 调用翻译API
4. 将占位符还原为原始术语

配置项（.env）：
- GLOSSARY_ENABLED=1
- GLOSSARY_FILE=translation_glossary.yaml

使用方法：
- 在翻译前调用 apply_glossary(text, target_lang)
- 在翻译后调用 restore_glossary(text, target_lang)
"""
import json
import logging
import os
import re
import hashlib
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)

# ============== 配置 ==============
GLOSSARY_ENABLED = os.getenv("GLOSSARY_ENABLED", "1") == "1"
GLOSSARY_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "ruitalk_config")
GLOSSARY_FILE = os.getenv("GLOSSARY_FILE", "translation_glossary.yaml")


# ============== 数据结构 ==============
@dataclass
class GlossaryEntry:
    """术语库条目"""
    id: str
    source_term: str           # 源语言术语
    translations: Dict[str, str]  # target_lang -> 翻译
    category: str = "general"   # 分类：policy/payment/shipping/product/general
    notes: str = ""             # 备注
    case_sensitive: bool = False  # 是否区分大小写
    enabled: bool = True
    created_at: str = ""
    
    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()


@dataclass
class Glossary:
    """术语库"""
    entries: Dict[str, GlossaryEntry] = field(default_factory=dict)
    version: str = "1.0.0"
    updated_at: str = ""
    
    def __post_init__(self):
        if not self.updated_at:
            self.updated_at = datetime.now().isoformat()


# ============== 默认术语库 ==============
def _get_default_glossary() -> dict:
    """获取默认术语库"""
    return {
        "version": "1.0.0",
        "updated_at": datetime.now().isoformat(),
        
        # 政策相关术语
        "policy": [
            {
                "id": "policy_001",
                "source_term": "退货政策",
                "translations": {
                    "en": "Return Policy",
                    "ar": "سياسة الإرجاع",
                    "ru": "Политика возврата",
                    "th": "นโยบายการคืนสินค้า",
                    "vi": "Chính sách đổi trả",
                    "id": "Kebijakan Pengembalian",
                    "ms": "Dasar Pemulangan",
                    "tl": "Patakaran sa Pagbabalik"
                },
                "category": "policy",
                "notes": "退货相关政策",
                "case_sensitive": False
            },
            {
                "id": "policy_002",
                "source_term": "退款政策",
                "translations": {
                    "en": "Refund Policy",
                    "ar": "سياسة الاسترداد",
                    "ru": "Политика возврата средств",
                    "th": "นโยบายคืนเงิน",
                    "vi": "Chính sách hoàn tiền",
                    "id": "Kebijakan Pengembalian Dana",
                    "ms": "Dasar Bayaran Balik",
                    "tl": "Patakaran sa Refund"
                },
                "category": "policy",
                "notes": "退款相关政策",
                "case_sensitive": False
            },
            {
                "id": "policy_003",
                "source_term": "七天无理由退货",
                "translations": {
                    "en": "7-Day No-Reason Return",
                    "ar": "إرجاع بدون سبب خلال 7 أيام",
                    "ru": "Возврат без причины в течение 7 дней",
                    "th": "คืนสินค้าไม่มีเงื่อนไข 7 วัน",
                    "vi": "Đổi trả không cần lý do trong 7 ngày",
                    "id": "Pengembalian Tanpa Alasan dalam 7 Hari",
                    "ms": "Pemulangan Tanpa Alasan 7 Hari",
                    "tl": "Pagbabalik walang Dahilan sa loob ng 7 Araw"
                },
                "category": "policy",
                "notes": "七天无理由退货服务",
                "case_sensitive": False
            },
            {
                "id": "policy_004",
                "source_term": "售后服务",
                "translations": {
                    "en": "After-Sales Service",
                    "ar": "خدمة ما بعد البيع",
                    "ru": "Послепродажное обслуживание",
                    "th": "บริการหลังการขาย",
                    "vi": "Dịch vụ sau bán hàng",
                    "id": "Layanan Purna Jual",
                    "ms": "Servis Selepas Jual",
                    "tl": "Serbisyo Pagkatapos ng Pagbebenta"
                },
                "category": "policy",
                "notes": "售后服务相关",
                "case_sensitive": False
            },
            {
                "id": "policy_005",
                "source_term": "质量保证",
                "translations": {
                    "en": "Quality Guarantee",
                    "ar": "ضمان الجودة",
                    "ru": "Гарантия качества",
                    "th": "รับประกันคุณภาพ",
                    "vi": "Bảo hành chất lượng",
                    "id": "Jaminan Kualitas",
                    "ms": "Jaminan Kualiti",
                    "tl": "Garantiya ng Kalidad"
                },
                "category": "policy",
                "notes": "质量保证条款",
                "case_sensitive": False
            },
        ],
        
        # 支付相关术语
        "payment": [
            {
                "id": "payment_001",
                "source_term": "支付宝",
                "translations": {
                    "en": "Alipay",
                    "ar": "علي بابا باي",
                    "ru": "Alipay",
                    "th": "อลิเพย์",
                    "vi": "Alipay",
                    "id": "Alipay",
                    "ms": "Alipay",
                    "tl": "Alipay"
                },
                "category": "payment",
                "notes": "支付宝支付",
                "case_sensitive": False
            },
            {
                "id": "payment_002",
                "source_term": "微信支付",
                "translations": {
                    "en": "WeChat Pay",
                    "ar": "وي تشات باي",
                    "ru": "WeChat Pay",
                    "th": "วีแชทเพย์",
                    "vi": "WeChat Pay",
                    "id": "WeChat Pay",
                    "ms": "WeChat Pay",
                    "tl": "WeChat Pay"
                },
                "category": "payment",
                "notes": "微信支付",
                "case_sensitive": False
            },
            {
                "id": "payment_003",
                "source_term": "货到付款",
                "translations": {
                    "en": "Cash on Delivery (COD)",
                    "ar": "الدفع عند الاستلام",
                    "ru": "Оплата при получении",
                    "th": "ชำระเงินปลายทาง",
                    "vi": "Thanh toán khi nhận hàng (COD)",
                    "id": "Bayar di Tempat (COD)",
                    "ms": "Bayar semasa Penghantaran",
                    "tl": "Bayad sa Pagtanggap (COD)"
                },
                "category": "payment",
                "notes": "货到付款",
                "case_sensitive": False
            },
            {
                "id": "payment_004",
                "source_term": "七天退款到账",
                "translations": {
                    "en": "7-Day Refund to Account",
                    "ar": "استرداد خلال 7 أيام",
                    "ru": "Возврат средств в течение 7 дней",
                    "th": "คืนเงินภายใน 7 วัน",
                    "vi": "Hoàn tiền trong 7 ngày",
                    "id": "Pengembalian Dana dalam 7 Hari",
                    "ms": "Bayaran Balik dalam 7 Hari",
                    "tl": "Refund sa loob ng 7 Araw"
                },
                "category": "payment",
                "notes": "退款到账时间",
                "case_sensitive": False
            },
        ],
        
        # 物流相关术语
        "shipping": [
            {
                "id": "shipping_001",
                "source_term": "七天无理由包邮",
                "translations": {
                    "en": "7-Day Free Return Shipping",
                    "ar": "شحن مجاني للإرجاع خلال 7 أيام",
                    "ru": "Бесплатная доставка при возврате в течение 7 дней",
                    "th": "ส่งคืนฟรี 7 วัน",
                    "vi": "Miễn phí vận chuyển khi đổi trả trong 7 ngày",
                    "id": "Gratis Ongkos Kirim Pengembalian 7 Hari",
                    "ms": "Penghantaran Percuma Pulangan 7 Hari",
                    "tl": "Libreng Pagbabalik sa loob ng 7 Araw"
                },
                "category": "shipping",
                "notes": "七天无理由退货且包邮",
                "case_sensitive": False
            },
            {
                "id": "shipping_002",
                "source_term": "顺丰速运",
                "translations": {
                    "en": "SF Express",
                    "ar": "إس إف إكسبريس",
                    "ru": "SF Express",
                    "th": "เอสเอฟ เอ็กซ์เพรส",
                    "vi": "SF Express",
                    "id": "SF Express",
                    "ms": "SF Express",
                    "tl": "SF Express"
                },
                "category": "shipping",
                "notes": "顺丰快递",
                "case_sensitive": False
            },
            {
                "id": "shipping_003",
                "source_term": "物流单号",
                "translations": {
                    "en": "Tracking Number",
                    "ar": "رقم التتبع",
                    "ru": "Номер отслеживания",
                    "th": "หมายเลขติดตามพัสดุ",
                    "vi": "Mã vận đơn",
                    "id": "Nomor Pelacakan",
                    "ms": "Nombor Pengesanan",
                    "tl": "Numero ng Pagsubaybay"
                },
                "category": "shipping",
                "notes": "物流单号",
                "case_sensitive": False
            },
            {
                "id": "shipping_004",
                "source_term": "已发货",
                "translations": {
                    "en": "Shipped",
                    "ar": "تم الشحن",
                    "ru": "Отправлено",
                    "th": "จัดส่งแล้ว",
                    "vi": "Đã gửi hàng",
                    "id": "Sudah Dikirim",
                    "ms": "Telah Dihantar",
                    "tl": "Naipadala na"
                },
                "category": "shipping",
                "notes": "订单状态-已发货",
                "case_sensitive": False
            },
            {
                "id": "shipping_005",
                "source_term": "配送中",
                "translations": {
                    "en": "In Transit",
                    "ar": "قيد التوصيل",
                    "ru": "В пути",
                    "th": "กำลังจัดส่ง",
                    "vi": "Đang vận chuyển",
                    "id": "Dalam Perjalanan",
                    "ms": "Dalam Penghantaran",
                    "tl": "Nasa Daan na"
                },
                "category": "shipping",
                "notes": "配送中",
                "case_sensitive": False
            },
        ],
        
        # 商品相关术语
        "product": [
            {
                "id": "product_001",
                "source_term": "正品保证",
                "translations": {
                    "en": "Authenticity Guaranteed",
                    "ar": "ضمان الأصالة",
                    "ru": "Гарантия подлинности",
                    "th": "รับประกันของแท้",
                    "vi": "Đảm bảo chính hãng",
                    "id": "Jaminan Original",
                    "ms": "Jaminan Original",
                    "tl": "Garantiyang Authenticity"
                },
                "category": "product",
                "notes": "正品保证",
                "case_sensitive": False
            },
            {
                "id": "product_002",
                "source_term": "原产地",
                "translations": {
                    "en": "Country of Origin",
                    "ar": "بلد المنشأ",
                    "ru": "Страна происхождения",
                    "th": "ประเทศต้นทาง",
                    "vi": "Xuất xứ",
                    "id": "Negara Asal",
                    "ms": "Negeri Asal",
                    "tl": "Bansang Pinagmulan"
                },
                "category": "product",
                "notes": "原产地证明",
                "case_sensitive": False
            },
        ]
    }


# ============== 术语库管理器 ==============
class TranslationGlossary:
    """
    翻译术语库管理器
    
    职责：
    - 加载和管理术语库
    - 提供术语匹配和替换
    - 支持术语的热更新
    """
    
    # 占位符格式
    PLACEHOLDER_PREFIX = "【术语:"
    PLACEHOLDER_SUFFIX = "】"
    
    def __init__(self, glossary_file: str = None):
        self.glossary_file = glossary_file or os.path.join(GLOSSARY_DIR, GLOSSARY_FILE)
        self._glossary: Glossary = Glossary()
        self._entry_cache: List[Tuple[str, str, str, bool]] = []  # (term, placeholder, target, case)
        self._pattern_cache: Optional[re.Pattern] = None
        self._load_glossary()
    
    def _load_glossary(self):
        """加载术语库"""
        # 确保目录存在
        os.makedirs(os.path.dirname(self.glossary_file), exist_ok=True)
        
        # 检查文件是否存在
        if not os.path.exists(self.glossary_file):
            # 创建默认术语库
            self._save_glossary(_get_default_glossary())
            logger.info(f"[Glossary] 创建默认术语库: {self.glossary_file}")
        
        # 加载术语库
        try:
            import yaml
            with open(self.glossary_file, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
        except ImportError:
            # 没有yaml，使用json
            json_file = self.glossary_file.replace('.yaml', '.json')
            if os.path.exists(json_file):
                with open(json_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            else:
                data = _get_default_glossary()
        except Exception as e:
            logger.error(f"[Glossary] 加载术语库失败: {e}")
            data = _get_default_glossary()
        
        # 解析术语库
        self._glossary.version = data.get("version", "1.0.0")
        self._glossary.updated_at = data.get("updated_at", datetime.now().isoformat())
        
        # 构建术语列表
        self._entry_cache = []
        for category, entries in data.items():
            if category in ("version", "updated_at"):
                continue
            if isinstance(entries, list):
                for entry_data in entries:
                    if not entry_data.get("enabled", True):
                        continue
                    entry = GlossaryEntry(**entry_data)
                    self._glossary.entries[entry.id] = entry
                    
                    # 构建替换映射
                    for target_lang, translation in entry.translations.items():
                        placeholder = f"{self.PLACEHOLDER_PREFIX}{entry.id}:{target_lang}{self.PLACEHOLDER_SUFFIX}"
                        self._entry_cache.append((
                            entry.source_term,
                            placeholder,
                            translation,
                            entry.case_sensitive
                        ))
        
        # 按长度排序（长词优先匹配）
        self._entry_cache.sort(key=lambda x: len(x[0]), reverse=True)
        
        # 更新模式缓存
        self._update_pattern()
        
        logger.info(f"[Glossary] 已加载术语库 v{self._glossary.version}，共{len(self._entry_cache)}条术语")
    
    def _save_glossary(self, data: dict):
        """保存术语库"""
        try:
            import yaml
            with open(self.glossary_file, 'w', encoding='utf-8') as f:
                yaml.dump(data, f, allow_unicode=True, default_flow_style=False)
        except ImportError:
            json_file = self.glossary_file.replace('.yaml', '.json')
            with open(json_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"[Glossary] 保存术语库失败: {e}")
    
    def _update_pattern(self):
        """更新正则表达式模式缓存"""
        patterns = []
        for term, _, _, case_sensitive in self._entry_cache:
            # 转义特殊字符
            escaped = re.escape(term)
            patterns.append(escaped)
        
        if patterns:
            pattern_str = "|".join(patterns)
            flags = 0 if patterns and self._entry_cache[0][3] else re.IGNORECASE
            self._pattern_cache = re.compile(pattern_str, flags)
        else:
            self._pattern_cache = None
    
    def apply_glossary(self, text: str, source_lang: str = "zh") -> Tuple[str, List[Tuple[str, str]]]:
        """
        应用术语库：将原文中的术语替换为占位符
        
        Args:
            text: 原文
            source_lang: 源语言（目前主要针对中文）
            
        Returns:
            (替换后的文本, [(原始术语, 占位符)] 替换记录)
        """
        if not GLOSSARY_ENABLED or not text or not self._pattern_cache:
            return text, []
        
        replacements = []
        
        def replacer(match):
            matched_text = match.group(0)
            # 找到对应的占位符
            for term, placeholder, _, case_sensitive in self._entry_cache:
                if (case_sensitive and term == matched_text) or (not case_sensitive and term.lower() == matched_text.lower()):
                    replacements.append((matched_text, placeholder))
                    return placeholder
            return matched_text
        
        result = self._pattern_cache.sub(replacer, text)
        return result, replacements
    
    def restore_glossary(self, text: str, target_lang: str) -> str:
        """
        还原术语库：将占位符替换为目标语言的术语
        
        Args:
            text: 翻译后的文本
            target_lang: 目标语言
            
        Returns:
            还原后的文本
        """
        if not GLOSSARY_ENABLED or not text:
            return text
        
        # 查找所有占位符
        placeholder_pattern = re.compile(
            rf'{re.escape(self.PLACEHOLDER_PREFIX)}([^:]+):{target_lang}{re.escape(self.PLACEHOLDER_SUFFIX)}'
        )
        
        def restore(match):
            entry_id = match.group(1)
            entry = self._glossary.entries.get(entry_id)
            if entry and entry.translations.get(target_lang):
                return entry.translations[target_lang]
            return match.group(0)
        
        result = placeholder_pattern.sub(restore, text)
        return result
    
    def translate_with_glossary(
        self,
        text: str,
        source_lang: str = "zh",
        target_lang: str = "en",
        translator_func=None
    ) -> str:
        """
        带术语库的翻译流程
        
        Args:
            text: 原文
            source_lang: 源语言
            target_lang: 目标语言
            translator_func: 翻译函数 (text: str) -> str
            
        Returns:
            翻译后的文本
        """
        if not text:
            return text
        
        # 1. 应用术语库（替换术语为占位符）
        text_with_placeholders, _ = self.apply_glossary(text, source_lang)
        
        # 2. 调用翻译API
        if translator_func:
            translated = translator_func(text_with_placeholders)
        else:
            translated = text_with_placeholders
        
        # 3. 还原术语库
        result = self.restore_glossary(translated, target_lang)
        
        return result
    
    def add_entry(self, entry: GlossaryEntry) -> bool:
        """添加术语条目"""
        try:
            # 更新内存
            self._glossary.entries[entry.id] = entry
            
            # 更新缓存
            for target_lang, translation in entry.translations.items():
                placeholder = f"{self.PLACEHOLDER_PREFIX}{entry.id}:{target_lang}{self.PLACEHOLDER_SUFFIX}"
                self._entry_cache.append((
                    entry.source_term,
                    placeholder,
                    translation,
                    entry.case_sensitive
                ))
            
            # 按长度排序
            self._entry_cache.sort(key=lambda x: len(x[0]), reverse=True)
            self._update_pattern()
            
            # 持久化
            self._save_glossary(self._export_glossary())
            
            logger.info(f"[Glossary] 添加术语: {entry.source_term} -> {entry.id}")
            return True
        except Exception as e:
            logger.error(f"[Glossary] 添加术语失败: {e}")
            return False
    
    def remove_entry(self, entry_id: str) -> bool:
        """删除术语条目"""
        if entry_id not in self._glossary.entries:
            return False
        
        # 从内存删除
        del self._glossary.entries[entry_id]
        
        # 重建缓存
        self._entry_cache = []
        for entry in self._glossary.entries.values():
            for target_lang, translation in entry.translations.items():
                placeholder = f"{self.PLACEHOLDER_PREFIX}{entry.id}:{target_lang}{self.PLACEHOLDER_SUFFIX}"
                self._entry_cache.append((
                    entry.source_term,
                    placeholder,
                    translation,
                    entry.case_sensitive
                ))
        
        self._entry_cache.sort(key=lambda x: len(x[0]), reverse=True)
        self._update_pattern()
        
        # 持久化
        self._save_glossary(self._export_glossary())
        
        logger.info(f"[Glossary] 删除术语: {entry_id}")
        return True
    
    def _export_glossary(self) -> dict:
        """导出术语库为dict"""
        data = {
            "version": self._glossary.version,
            "updated_at": datetime.now().isoformat()
        }
        
        # 按分类组织
        categories = {}
        for entry in self._glossary.entries.values():
            cat = entry.category
            if cat not in categories:
                categories[cat] = []
            categories[cat].append({
                "id": entry.id,
                "source_term": entry.source_term,
                "translations": entry.translations,
                "category": entry.category,
                "notes": entry.notes,
                "case_sensitive": entry.case_sensitive,
                "enabled": entry.enabled,
                "created_at": entry.created_at
            })
        
        data.update(categories)
        return data
    
    def reload(self):
        """重新加载术语库"""
        self._glossary = Glossary()
        self._entry_cache = []
        self._pattern_cache = None
        self._load_glossary()
    
    def get_stats(self) -> Dict[str, Any]:
        """获取术语库统计"""
        categories = {}
        for entry in self._glossary.entries.values():
            cat = entry.category
            categories[cat] = categories.get(cat, 0) + 1
        
        return {
            "enabled": GLOSSARY_ENABLED,
            "version": self._glossary.version,
            "total_entries": len(self._glossary.entries),
            "categories": categories
        }


# ============== 全局实例 ==============
_glossary: Optional[TranslationGlossary] = None


def get_glossary() -> TranslationGlossary:
    """获取术语库实例"""
    global _glossary
    if _glossary is None:
        _glossary = TranslationGlossary()
    return _glossary


def apply_glossary(text: str, source_lang: str = "zh") -> Tuple[str, List[Tuple[str, str]]]:
    """快捷函数：应用术语库"""
    return get_glossary().apply_glossary(text, source_lang)


def restore_glossary(text: str, target_lang: str) -> str:
    """快捷函数：还原术语库"""
    return get_glossary().restore_glossary(text, target_lang)


def translate_with_glossary(text: str, source_lang: str, target_lang: str, translator_func=None) -> str:
    """快捷函数：带术语库的翻译"""
    return get_glossary().translate_with_glossary(text, source_lang, target_lang, translator_func)


# ============== 导出 ==============
__all__ = [
    'GlossaryEntry',
    'Glossary',
    'TranslationGlossary',
    'get_glossary',
    'apply_glossary',
    'restore_glossary',
    'translate_with_glossary',
]
