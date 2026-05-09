# -*- coding: utf-8 -*-
"""
AI提示词版本控制系统 (Prompt Version Control)

功能：
- 将AI System Prompt独立存储在配置文件或数据库中
- 支持版本管理和回滚
- 支持运行时动态修改，无需重启程序
- 可通过卖家后台"信息管理"模块直接修改

原理：
1. System Prompt存储在ai_prompts.yaml文件中
2. 每次修改生成新版本，自动备份旧版本
3. 支持语言别、情绪策略等独立配置
4. 运行时会加载最新版本并缓存在内存中

配置项（.env）：
- AI_PROMPTS_FILE=ai_prompts.yaml
- AI_PROMPT_CACHE_TTL=300 (5分钟刷新一次)

使用方法：
- 修改yaml文件后，AI会自动在TTL后使用新提示词
- 支持API调用刷新：POST /api/admin/ai-prompts/reload
"""
import json
import logging
import os
import time
import hashlib
import threading
from datetime import datetime
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)

# ============== 配置 ==============
AI_PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "ruitalk_config")
AI_PROMPTS_FILE = os.getenv("AI_PROMPTS_FILE", "ai_prompts.yaml")
AI_PROMPT_CACHE_TTL = int(os.getenv("AI_PROMPT_CACHE_TTL", "300"))  # 5分钟

# ============== 数据结构 ==============
class PromptType(str, Enum):
    """提示词类型"""
    SYSTEM = "system"           # 系统提示词
    WELCOME = "welcome"         # 欢迎语
    TRANSFER_HUMAN = "transfer" # 转人工提示
    FALLBACK = "fallback"       # 降级回复
    EMOTION_GUIDE = "emotion"   # 情绪引导
    TAIL = "tail"               # 拟人化结尾语


@dataclass
class PromptVersion:
    """提示词版本"""
    version: str
    content: str
    created_at: float
    created_by: str = "system"
    comment: str = ""
    
    @property
    def created_time(self) -> str:
        return datetime.fromtimestamp(self.created_at).strftime('%Y-%m-%d %H:%M:%S')


@dataclass
class PromptEntry:
    """提示词条目"""
    id: str
    type: str
    language: str
    content: str
    version: str
    created_at: float
    updated_at: float
    tags: List[str] = field(default_factory=list)
    
    @property
    def updated_time(self) -> str:
        return datetime.fromtimestamp(self.updated_at).strftime('%Y-%m-%d %H:%M:%S')


@dataclass
class EmotionStrategy:
    """情绪策略配置"""
    emotion: str  # angry, sad, anxious, happy, curious, neutral
    language: str
    guide: str
    priority: int = 1


@dataclass
class FewShotSample:
    """Few-Shot样本"""
    scenario: str
    emotion: str
    samples: Dict[str, str]  # language -> content


@dataclass
class EmotionStrategyRule:
    """情绪策略规则"""
    emotion: str
    language: str
    rules: list  # 策略列表


@dataclass
class ContextWindowConfig:
    """上下文窗口配置"""
    max_rounds: int = 10
    summary_max_length: int = 200


@dataclass
class PromptConfig:
    """提示词配置"""
    system: Dict[str, str]  # language -> content
    welcome: Dict[str, str]
    transfer: Dict[str, str]
    fallback: Dict[str, str]
    tails: Dict[str, Dict[str, str]]  # emotion -> language -> content
    emotion_guides: List[EmotionStrategy]
    few_shot_samples: List[FewShotSample] = field(default_factory=list)  # 新增
    emotion_strategies: Dict[str, Dict[str, list]] = field(default_factory=dict)  # 新增
    context_window: ContextWindowConfig = field(default_factory=ContextWindowConfig)  # 新增
    version: str
    updated_at: float
    
    @property
    def updated_time(self) -> str:
        return datetime.fromtimestamp(self.updated_at).strftime('%Y-%m-%d %H:%M:%S')


# ============== YAML格式的提示词存储 ==============
def _get_default_prompts() -> dict:
    """获取默认提示词配置"""
    return {
        "version": "1.0.0",
        "updated_at": datetime.now().isoformat(),
        "updated_by": "system",
        
        "system": {
            "zh": """【角色】你是金牌AI客服，回复要干练、先答后暖。

【必须遵守 — 违反者将被投诉】
1) 先直接回答客户问题：给事实/步骤/数据；不铺垫、不空泛共情。
2) 回答完立即追加1句拟人化结尾语，格式为：「我在呢~有需要随时叫我~」
3) 全程用中文回复，禁止混写其他语言。
4) 字数：中文80-120字，英文50-80词，其他语言同短。
5) 拟人化结尾语必须放在回复最后一行，前面加一个空行隔开。

【铁律】禁止捏造任何订单号/物流单号/发货时间。若档案中无订单，对订单类询问必须回复：「档案里暂无订单记录，建议您提供订单号我来帮查」。

【客户档案摘要】
{customer_profile}

【对话历史】
{conversation_history}

【客户消息】「{user_message}」

请严格按以下格式回复：
[直接回答部分]

{ai_tail}""",
            
            "en": """【Role】You are a premium customer service AI assistant. Reply concisely, then add a warm closing.

【Must Follow】
1) Answer directly with facts/steps/data. No fluff or excessive empathy.
2) End with ONE human-like closing line: "I'm here — ping me anytime."
3) Always reply in English only.
4) Length: 50-80 words.
5) The closing line must be the LAST line of your response.

【Iron Rule】Never fabricate order numbers, tracking numbers, or shipping times. If no order exists, reply: "No orders found. Please provide your order number."

【Customer Profile】
{customer_profile}

【Conversation History】
{conversation_history}

【Customer Message】「{user_message}」

Reply format:
[Direct answer]

I'm here — ping me anytime.""",
            
            "ar": """【الدور】أنت مساعد خدمة العملاء الذهبي. أجب بإيجاز ثم أضف إغلاقاً دافئاً.

【يجب اتباعه】
1) أجب مباشرة بالحقائق/الخطوات. لا مقدمات.
2) اختم بسطر واحد دافئ: "أنا هنا إذا احتجتِ أي شيء."
3) أجب بالعربية دائماً.
4) الطول: 50-80 كلمة.

【القاعدة الذهبية】لا تخترع أرقام الطلبات أو الشحن. إذا لم يكن هناك طلب: "لا توجد طلبات. يرجى تقديم رقم الطلب." """,
            
            "ru": """【Роль】Вы — премиум AI-ассистент. Отвечайте кратко, затем добавьте тёплое завершение.

【Обязательно】
1) Отвечайте фактами/шагами. Без воды.
2) Завершите одной тёплой фразой: "Я на связи — напиши, если что."
3) Всегда отвечайте на русском.
4) Объём: 50-80 слов."""
        },
        
        "welcome": {
            "zh": "您好，{name}！我是您的专属AI客服，请问有什么可以帮您？",
            "en": "Hello {name}! I'm your dedicated AI assistant. How can I help you today?",
            "ar": "مرحباً {name}! أنا المساعد الذكي الخاص بك. كيف يمكنني مساعدتك؟",
            "ru": "Привет, {name}! Я ваш персональный AI-ассистент. Чем могу помочь?",
            "th": "สวัสดีค่ะ/ครับ {name}! ผม/หนูคือผู้ช่วย AI ของคุณ มีอะไรให้ช่วยไหมคะ/ครับ?",
            "vi": "Xin chào {name}! Tôi là trợ lý AI của bạn. Tôi có thể giúp gì cho bạn?",
            "id": "Halo {name}! Saya asisten AI kamu. Ada yang bisa saya bantu?",
            "ms": "Hai {name}! Saya pembantu AI anda. Apa yang boleh saya bantu?",
            "tl": "Kumusta {name}! Ako ang AI assistant mo. Paano kita makakatulong?",
        },
        
        "transfer": {
            "zh": "好的，正在为您转接人工客服，请稍候...",
            "en": "Transferring you to a human agent, please wait...",
            "ar": "جارٍ تحويلك إلى موظف خدمة عملاء، يرجى الانتظار...",
            "ru": "Переключаю вас на оператора, пожалуйста, подождите...",
        },
        
        "fallback": {
            "zh": "亲爱的，我在呢~刚才网络有点忙，你可以再说一下问题，我帮你看看。",
            "en": "Dear, I'm here! The line was busy -- could you say that again?",
            "ar": "عزيزي، أنا هنا! الشبكة مشغولة قليلاً، هل يمكنك المحاولة مرة أخرى؟",
            "ru": "Дорогой, я здесь! Сеть немного занята, попробуйте ещё раз.",
        },
        
        "tails": {
            "neutral": {
                "zh": "我在呢~有需要随时叫我~",
                "en": "I'm here — ping me anytime!",
                "ar": "أنا هنا إذا احتجتِ أي شيء.",
                "ru": "Я на связи — напиши, если что.",
            },
            "angry": {
                "zh": "抱歉给您带来不便，我尽快帮您解决~",
                "en": "So sorry for the inconvenience — I'll fix this right away!",
            },
            "happy": {
                "zh": "太开心能帮到您啦~有问题随时来找我~",
                "en": "So happy I could help! Reach out anytime!",
            },
            "sad": {
                "zh": "别难过，我帮你一起想办法~",
                "en": "Don't worry — let's figure this out together!",
            },
        },
        
        "emotion_guides": [
            {"emotion": "angry", "language": "zh", "guide": "先一句真诚道歉+解决方案要点，再一句俏皮收尾；禁止长篇说教。", "priority": 5},
            {"emotion": "sad", "language": "zh", "guide": "先给明确帮助或下一步，再温柔一句；别急着推销。", "priority": 4},
            {"emotion": "anxious", "language": "zh", "guide": "先给答案/时间节点/操作步骤，再安抚一句；短句为主。", "priority": 5},
            {"emotion": "happy", "language": "zh", "guide": "先回应对方说的点，再活泼一句；可简短推荐但要有理由。", "priority": 2},
            {"emotion": "neutral", "language": "zh", "guide": "先答问题，再一句拟人化；不堆套话。", "priority": 1},
        ],
        
        "version_history": []
    }


# ============== 提示词配置管理器 ==============
class PromptConfigManager:
    """
    提示词配置管理器
    
    职责：
    - 从YAML文件加载提示词配置
    - 缓存配置并定期刷新
    - 支持运行时热更新
    - 版本管理和回滚
    """
    
    def __init__(self, config_file: str = None):
        self.config_file = config_file or os.path.join(AI_PROMPTS_DIR, AI_PROMPTS_FILE)
        self._config: Optional[PromptConfig] = None
        self._last_load_time: float = 0
        self._lock = threading.RLock()
        self._version_history: List[Dict] = []
        
        # 确保目录存在
        os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
        
        # 初始化配置文件
        self._ensure_config_file()
    
    def _ensure_config_file(self):
        """确保配置文件存在"""
        if not os.path.exists(self.config_file):
            default_config = _get_default_prompts()
            self._save_to_file(default_config)
            logger.info(f"[PromptConfig] 创建默认提示词配置: {self.config_file}")
    
    def _load_from_file(self) -> dict:
        """从文件加载配置"""
        try:
            import yaml
            with open(self.config_file, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f) or {}
        except ImportError:
            # 没有yaml库，使用json
            json_file = self.config_file.replace('.yaml', '.json')
            if os.path.exists(json_file):
                with open(json_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            
            # 创建默认配置
            return _get_default_prompts()
        except Exception as e:
            logger.error(f"[PromptConfig] 加载配置文件失败: {e}")
            return _get_default_prompts()
    
    def _save_to_file(self, config: dict):
        """保存配置到文件"""
        try:
            import yaml
            with open(self.config_file, 'w', encoding='utf-8') as f:
                yaml.dump(config, f, allow_unicode=True, default_flow_style=False)
        except ImportError:
            # 没有yaml库，保存为json
            json_file = self.config_file.replace('.yaml', '.json')
            with open(json_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"[PromptConfig] 保存配置文件失败: {e}")
    
    def _parse_config(self, raw: dict) -> PromptConfig:
        """解析原始配置为PromptConfig"""
        # 解析 few_shot_samples
        few_shot_samples = []
        for item in raw.get("few_shot_samples", []):
            few_shot_samples.append(FewShotSample(
                scenario=item.get("scenario", ""),
                emotion=item.get("emotion", "neutral"),
                samples=item.get("samples", {})
            ))
        
        # 解析 emotion_strategies
        emotion_strategies = raw.get("emotion_strategies", {})
        
        # 解析 context_window
        cw_raw = raw.get("context_window", {})
        context_window = ContextWindowConfig(
            max_rounds=cw_raw.get("max_rounds", 10),
            summary_max_length=cw_raw.get("summary_max_length", 200)
        )
        
        return PromptConfig(
            system=raw.get("system", {}),
            welcome=raw.get("welcome", {}),
            transfer=raw.get("transfer", {}),
            fallback=raw.get("fallback", {}),
            tails=raw.get("tails", {}),
            emotion_guides=[
                EmotionStrategy(**eg) 
                for eg in raw.get("emotion_guides", [])
            ],
            few_shot_samples=few_shot_samples,
            emotion_strategies=emotion_strategies,
            context_window=context_window,
            version=raw.get("version", "1.0.0"),
            updated_at=datetime.fromisoformat(raw.get("updated_at", datetime.now().isoformat())).timestamp()
        )
    
    def load(self, force: bool = False) -> PromptConfig:
        """
        加载提示词配置
        
        Args:
            force: 是否强制重新加载
            
        Returns:
            PromptConfig对象
        """
        with self._lock:
            now = time.time()
            
            # 检查是否需要刷新
            if (not force and 
                self._config is not None and 
                now - self._last_load_time < AI_PROMPT_CACHE_TTL):
                return self._config
            
            # 重新加载
            raw = self._load_from_file()
            self._config = self._parse_config(raw)
            self._last_load_time = now
            
            logger.info(f"[PromptConfig] 已加载提示词配置 v{self._config.version}")
            return self._config
    
    def get_system_prompt(
        self, 
        language: str = "zh",
        customer_profile: str = "",
        conversation_history: str = "",
        user_message: str = "",
        ai_tail: str = ""
    ) -> str:
        """
        获取系统提示词
        
        支持模板变量替换：
        - {customer_profile}: 客户档案
        - {conversation_history}: 对话历史
        - {user_message}: 用户消息
        - {ai_tail}: 拟人化结尾语
        """
        config = self.load()
        
        template = config.system.get(language, config.system.get("zh", ""))
        
        # 替换变量
        content = template.format(
            customer_profile=customer_profile or "(暂无客户档案)",
            conversation_history=conversation_history or "(首次对话)",
            user_message=user_message or "",
            ai_tail=ai_tail or config.tails.get("neutral", {}).get(language, "我在呢~")
        )
        
        return content
    
    def get_welcome(self, language: str = "zh", name: str = "朋友") -> str:
        """获取欢迎语"""
        config = self.load()
        template = config.welcome.get(language, config.welcome.get("zh", ""))
        return template.format(name=name)
    
    def get_transfer_prompt(self, language: str = "zh") -> str:
        """获取转人工提示"""
        config = self.load()
        return config.transfer.get(language, config.transfer.get("zh", "好的，正在为您转接人工客服，请稍候..."))
    
    def get_fallback(self, language: str = "zh") -> str:
        """获取降级回复"""
        config = self.load()
        return config.fallback.get(language, config.fallback.get("zh", "服务繁忙，请稍后重试"))
    
    def get_tail(self, emotion: str = "neutral", language: str = "zh") -> str:
        """获取拟人化结尾语"""
        config = self.load()
        tails_for_emotion = config.tails.get(emotion, config.tails.get("neutral", {}))
        return tails_for_emotion.get(language, tails_for_emotion.get("zh", "我在呢~有需要随时叫我~"))
    
    def get_emotion_guide(self, emotion: str = "neutral", language: str = "zh") -> str:
        """获取情绪引导"""
        config = self.load()
        for guide in config.emotion_guides:
            if guide.emotion == emotion and guide.language == language:
                return guide.guide
        return ""
    
    def get_few_shot_samples(self, emotion: str = None, language: str = "zh") -> List[FewShotSample]:
        """获取Few-Shot样本"""
        config = self.load()
        samples = config.few_shot_samples
        if emotion:
            samples = [s for s in samples if s.emotion == emotion]
        return samples
    
    def get_few_shot_for_emotion(self, emotion: str, language: str = "zh") -> str:
        """获取指定情绪的Few-Shot示例文本"""
        samples = self.get_few_shot_samples(emotion=emotion, language=language)
        if not samples:
            return ""
        
        parts = []
        for sample in samples[:3]:  # 最多返回3个示例
            content = sample.samples.get(language, sample.samples.get("zh", ""))
            if content:
                parts.append(f"[{sample.scenario}] {content}")
        return "\n".join(parts)
    
    def get_emotion_strategy(self, emotion: str, language: str = "zh") -> list:
        """获取情绪策略规则"""
        config = self.load()
        strategies = config.emotion_strategies.get(emotion, {})
        return strategies.get(language, strategies.get("zh", []))
    
    def get_context_window_config(self) -> ContextWindowConfig:
        """获取上下文窗口配置"""
        config = self.load()
        return config.context_window
    
    def update_system_prompt(self, language: str, content: str, comment: str = "") -> bool:
        """
        更新系统提示词
        
        会自动备份旧版本并生成新版本号。
        """
        with self._lock:
            raw = self._load_from_file()
            
            # 备份旧版本
            old_content = raw.get("system", {}).get(language, "")
            if old_content:
                history = raw.get("version_history", [])
                history.append({
                    "type": "system",
                    "language": language,
                    "version": raw.get("version", "1.0.0"),
                    "content": old_content,
                    "backup_at": datetime.now().isoformat(),
                    "backup_by": "system"
                })
                raw["version_history"] = history[-10:]  # 保留最近10个版本
            
            # 更新内容
            if "system" not in raw:
                raw["system"] = {}
            raw["system"][language] = content
            raw["updated_at"] = datetime.now().isoformat()
            
            # 生成新版本号
            old_version = raw.get("version", "1.0.0")
            parts = old_version.split(".")
            parts[-1] = str(int(parts[-1]) + 1)
            raw["version"] = ".".join(parts)
            
            # 保存
            self._save_to_file(raw)
            
            # 强制刷新缓存
            self.load(force=True)
            
            logger.info(f"[PromptConfig] 已更新系统提示词 v{raw['version']} ({language})")
            return True
    
    def rollback(self, type: str, language: str = None, version: str = None) -> bool:
        """
        回滚到指定版本
        
        Args:
            type: 提示词类型
            language: 语言（可选）
            version: 版本号（可选，默认为上一个版本）
        """
        with self._lock:
            raw = self._load_from_file()
            history = raw.get("version_history", [])
            
            # 查找目标版本
            target = None
            for item in reversed(history):
                if item.get("type") == type:
                    if language is None or item.get("language") == language:
                        target = item
                        break
            
            if not target:
                logger.warning(f"[PromptConfig] 未找到可回滚的版本: {type}/{language}")
                return False
            
            # 执行回滚
            if type == "system":
                if "system" not in raw:
                    raw["system"] = {}
                raw["system"][target.get("language", "zh")] = target.get("content", "")
            
            raw["updated_at"] = datetime.now().isoformat()
            self._save_to_file(raw)
            self.load(force=True)
            
            logger.info(f"[PromptConfig] 已回滚到 v{target.get('version')} ({type})")
            return True
    
    def get_version_history(self, type: str = None, language: str = None, limit: int = 10) -> List[Dict]:
        """获取版本历史"""
        raw = self._load_from_file()
        history = raw.get("version_history", [])
        
        # 过滤
        if type:
            history = [h for h in history if h.get("type") == type]
        if language:
            history = [h for h in history if h.get("language") == language]
        
        return history[-limit:]
    
    def export_config(self) -> Dict[str, Any]:
        """导出完整配置"""
        return self._load_from_file()
    
    def import_config(self, config: Dict) -> bool:
        """导入配置"""
        try:
            self._save_to_file(config)
            self.load(force=True)
            logger.info(f"[PromptConfig] 已导入新配置 v{config.get('version', '?')}")
            return True
        except Exception as e:
            logger.error(f"[PromptConfig] 导入配置失败: {e}")
            return False


# ============== 全局实例 ==============
_prompt_manager: Optional[PromptConfigManager] = None


def get_prompt_manager() -> PromptConfigManager:
    """获取提示词管理器实例"""
    global _prompt_manager
    if _prompt_manager is None:
        _prompt_manager = PromptConfigManager()
    return _prompt_manager


def get_system_prompt(**kwargs) -> str:
    """快捷函数：获取系统提示词"""
    return get_prompt_manager().get_system_prompt(**kwargs)


def get_welcome_message(**kwargs) -> str:
    """快捷函数：获取欢迎语"""
    return get_prompt_manager().get_welcome(**kwargs)


def get_ai_tail(**kwargs) -> str:
    """快捷函数：获取拟人化结尾语"""
    return get_prompt_manager().get_tail(**kwargs)


def reload_prompts() -> bool:
    """快捷函数：强制刷新提示词"""
    get_prompt_manager().load(force=True)
    return True


# ============== 导出 ==============
__all__ = [
    'PromptConfig',
    'PromptEntry',
    'PromptVersion',
    'PromptType',
    'EmotionStrategy',
    'PromptConfigManager',
    'get_prompt_manager',
    'get_system_prompt',
    'get_welcome_message',
    'get_ai_tail',
    'reload_prompts',
]
