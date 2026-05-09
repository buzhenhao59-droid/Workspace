# -*- coding: utf-8 -*-
"""
卖方 services.py 单元测试
覆盖：CircuitBreaker 熔断器 / detect_emotion_advanced 情绪检测 / detect_language 语言检测
"""
import time
import pytest
import sys, os, importlib

# 避免真实加载 config（会有环境变量依赖）
backend_dir = os.path.join(os.path.dirname(__file__), "..", "backend")
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

# Mock config 模块（避免环境变量依赖）
import types
_config_module = types.ModuleType("config")
_config_module.DEEPSEEK_API_KEY = "test-key"
_config_module.DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
_config_module.GRAPHRAG_API_URL = "http://localhost:5050/query"
sys.modules["config"] = _config_module

# Mock requests（避免网络调用）
import unittest.mock as mock
with mock.patch("requests.post", mock.MagicMock()):
    # 重新导入以使用 mock
    import importlib
    import services as _svc_module
    importlib.reload(_svc_module)
    CircuitBreaker = _svc_module.CircuitBreaker
    detect_emotion_advanced = _svc_module.detect_emotion_advanced
    detect_language = _svc_module.detect_language


class TestCircuitBreaker:
    """CircuitBreaker 熔断器状态机测试"""

    def test_initial_state_is_closed(self):
        cb = CircuitBreaker("test", failure_threshold=3, recovery_timeout=10.0)
        assert cb.state == "closed"
        assert cb.is_available() is True
        assert cb._failure_count == 0

    def test_single_failure_does_not_open(self):
        cb = CircuitBreaker("test", failure_threshold=3, recovery_timeout=10.0)
        cb.record_failure()
        assert cb.state == "closed"
        assert cb.is_available() is True
        assert cb._failure_count == 1

    def test_threshold_failures_opens_circuit(self):
        cb = CircuitBreaker("test", failure_threshold=3, recovery_timeout=10.0)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "closed"
        cb.record_failure()  # 第3次，触发 OPEN
        assert cb.state == "open"
        assert cb.is_available() is False

    def test_open_circuit_blocks_requests(self):
        cb = CircuitBreaker("test", failure_threshold=2, recovery_timeout=30.0)
        cb.record_failure()
        cb.record_failure()
        assert cb.is_available() is False

    def test_recovery_timeout_transitions_to_half_open(self):
        cb = CircuitBreaker("test", failure_threshold=2, recovery_timeout=0.1)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "open"
        time.sleep(0.15)
        assert cb.state == "half_open"
        assert cb.is_available() is True

    def test_half_open_success_closes_circuit(self):
        cb = CircuitBreaker("test", failure_threshold=2, recovery_timeout=0.05)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "open"
        time.sleep(0.1)
        assert cb.state == "half_open"
        cb.record_success()
        assert cb.state == "closed"
        assert cb._failure_count == 0

    def test_half_open_failure_reopens_circuit(self):
        cb = CircuitBreaker("test", failure_threshold=2, recovery_timeout=0.05)
        cb.record_failure()
        cb.record_failure()
        time.sleep(0.1)
        assert cb.state == "half_open"
        cb.record_failure()
        assert cb.state == "open"

    def test_success_resets_failure_count_in_closed_state(self):
        cb = CircuitBreaker("test", failure_threshold=5, recovery_timeout=30.0)
        cb.record_failure()
        cb.record_failure()
        assert cb._failure_count == 2
        cb.record_success()
        assert cb._failure_count == 0

    def test_get_status_returns_correct_dict(self):
        cb = CircuitBreaker("test-service", failure_threshold=5, recovery_timeout=30.0)
        cb.record_failure()
        status = cb.get_status()
        assert status["name"] == "test-service"
        assert status["state"] == "closed"
        assert status["failure_count"] == 1
        assert status["failure_threshold"] == 5
        assert status["recovery_timeout"] == 30.0

    def test_concurrent_access_thread_safety(self):
        import threading
        cb = CircuitBreaker("test", failure_threshold=100, recovery_timeout=60.0)
        errors = []

        def hammer():
            try:
                for _ in range(100):
                    cb.record_failure()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=hammer) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert cb._failure_count == 500


class TestDetectEmotionAdvanced:
    """情绪检测算法测试"""

    def test_angry_keywords(self):
        assert detect_emotion_advanced("我非常生气，你们服务太差了") == "angry"
        assert detect_emotion_advanced("垃圾产品，烂透了") == "angry"
        assert detect_emotion_advanced("我要投诉你们") == "angry"
        assert detect_emotion_advanced("I am very angry, this is terrible") == "angry"
        assert detect_emotion_advanced("плохо, ужасно, жалоба") == "angry"

    def test_sad_keywords(self):
        assert detect_emotion_advanced("我很难过，非常失望") == "sad"
        assert detect_emotion_advanced("sad and disappointed") == "sad"
        assert detect_emotion_advanced("грустно и печально") == "sad"

    def test_anxious_keywords(self):
        assert detect_emotion_advanced("我很着急，什么时候能到") == "anxious"
        assert detect_emotion_advanced("I am worried, how long") == "anxious"
        assert detect_emotion_advanced("переживаю, скорее") == "anxious"

    def test_happy_keywords(self):
        assert detect_emotion_advanced("谢谢，服务很好！") == "happy"
        assert detect_emotion_advanced("good, great, thank you!") == "happy"
        assert detect_emotion_advanced("отлично, спасибо") == "happy"

    def test_curious_keywords(self):
        assert detect_emotion_advanced("为什么订单还没发货？") == "curious"
        assert detect_emotion_advanced("why and how does this work") == "curious"
        assert detect_emotion_advanced("почему и как") == "curious"

    def test_neutral_returns_for_normal_text(self):
        # "what" 和 "how" 会被 curious 关键词匹配
        assert detect_emotion_advanced("我的订单号是123456") == "neutral"
        assert detect_emotion_advanced("请问可以帮我查一下吗") == "neutral"
        assert detect_emotion_advanced("hello world today is fine") == "neutral"

    def test_curious_detection(self):
        # "what" 和 "how" 触发 curious
        assert detect_emotion_advanced("hello, what is the status") == "curious"
        assert detect_emotion_advanced("how can I check my order") == "curious"

    def test_empty_string_returns_neutral(self):
        assert detect_emotion_advanced("") == "neutral"
        assert detect_emotion_advanced(None) == "neutral"

    def test_priority_angry_over_sad(self):
        assert detect_emotion_advanced("生气又难过，退款投诉") == "angry"

    def test_priority_happy_over_neutral(self):
        assert detect_emotion_advanced("谢谢，请帮我查一下") == "happy"


class TestDetectLanguage:
    """语言检测算法测试"""

    def test_chinese_detection(self):
        assert detect_language("你好，请问有什么可以帮您") == "zh"
        assert detect_language("我的订单号是123456") == "zh"
        assert detect_language("今天天气不错") == "zh"

    def test_english_detection(self):
        assert detect_language("Hello, what is the status of my order") == "en"
        assert detect_language("thank you very much") == "en"
        assert detect_language("please help me check") == "en"

    def test_arabic_detection(self):
        assert detect_language("مرحبا كيف حالك") == "ar"
        assert detect_language("شكرا لك") == "ar"
        assert detect_language("أريد استرداد أموالي") == "ar"

    def test_russian_detection(self):
        assert detect_language("здравствуйте, как дела") == "ru"
        assert detect_language("спасибо большое") == "ru"
        assert detect_language("пожалуйста, помогите") == "ru"

    def test_mixed_language_prefers_majority(self):
        # 中文字符占比超过 30% 才判断为中文
        assert detect_language("你好hello世界world今天很好") == "zh"  # 中文字符多
        assert detect_language("hello world 中文") == "en"  # 中文字符少
        assert detect_language("中英混排EnglishABC") == "en"  # 中文字符仅2个，远低于30%

    def test_numbers_only_defaults_to_english(self):
        # 无中文字符时默认英文
        assert detect_language("123456789") == "en"
        assert detect_language("!!!...???") == "en"

    def test_threshold_30_percent(self):
        # 阈值 30%：中文少于 30% 则判断为英文
        assert detect_language("中EnglishABC") == "en"
        assert detect_language("中中中中中EnglishABC") == "zh"  # 5/14 > 30%
