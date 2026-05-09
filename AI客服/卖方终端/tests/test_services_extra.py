# -*- coding: utf-8 -*-
"""
卖方 services.py 补充单元测试
覆盖：_safe_float / _build_product_context / build_upgraded_system_prompt
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import types
_mock_cfg = types.ModuleType("config")
for k, v in {
    "DEEPSEEK_API_KEY": "test-key",
    "DEEPSEEK_API_URL": "https://api.deepseek.com/v1/chat/completions",
    "GRAPHRAG_API_URL": "http://localhost:5050/query",
}.items():
    setattr(_mock_cfg, k, v)
sys.modules["config"] = _mock_cfg

import unittest.mock as mock

with mock.patch("requests.post", mock.MagicMock()):
    from services import (
        _safe_float,
        _order_items_text,
        build_upgraded_system_prompt,
        SUPPORTED_LANGUAGES,
        LANGUAGE_NAMES,
        LANGUAGE_SWITCH_MESSAGES,
    )


class TestSafeFloat:
    """_safe_float 边界值测试"""

    def test_valid_numbers(self):
        assert _safe_float(123) == 123.0
        assert _safe_float(0) == 0.0
        assert _safe_float(-5) == -5.0
        assert _safe_float(3.14) == 3.14

    def test_string_numbers(self):
        assert _safe_float("123") == 123.0
        assert _safe_float("3.14") == 3.14
        assert _safe_float("-10.5") == -10.5

    def test_invalid_input_defaults(self):
        assert _safe_float("not a number") == 0.0
        assert _safe_float(None) == 0.0
        assert _safe_float("") == 0.0

    def test_custom_default(self):
        assert _safe_float("invalid", default=99.9) == 99.9
        assert _safe_float(None, default=42.0) == 42.0

    def test_edge_cases(self):
        assert _safe_float(float("inf")) == float("inf")
        assert _safe_float(float("-inf")) == float("-inf")


class TestOrderItemsText:
    """订单商品文本构建测试"""

    def test_empty_order(self):
        result = _order_items_text({})
        assert isinstance(result, str)

    def test_single_item(self):
        order = {
            "items": [
                {"name": "测试商品", "quantity": 2, "price": 99.9}
            ]
        }
        result = _order_items_text(order)
        assert "测试商品" in result
        assert "2" in result

    def test_multiple_items(self):
        order = {
            "items": [
                {"name": "商品A", "quantity": 1, "price": 50},
                {"name": "商品B", "quantity": 3, "price": 30},
            ]
        }
        result = _order_items_text(order)
        assert "商品A" in result
        assert "商品B" in result

    def test_missing_fields(self):
        order = {"items": [{"name": "仅有名字"}]}
        result = _order_items_text(order)
        assert "仅有名字" in result


class TestBuildUpgradedSystemPrompt:
    """系统提示词构建测试"""

    def test_prompt_contains_customer_info(self):
        customer_info = {
            "customer": {"name": "测试客户", "level": "VIP", "customer_id": "c123"},
            "orders": [],
            "skus": [],
            "communications": [],
        }
        prompt = build_upgraded_system_prompt(customer_info, [])
        assert isinstance(prompt, str)
        assert len(prompt) > 0

    def test_prompt_contains_instructions(self):
        customer_info = {"customer": {}, "orders": [], "skus": [], "communications": []}
        prompt = build_upgraded_system_prompt(customer_info, [], "zh")
        assert "先直接回答" in prompt or "直接回答" in prompt

    def test_prompt_language_consistency(self):
        customer_info = {"customer": {}, "orders": [], "skus": [], "communications": []}
        prompt_en = build_upgraded_system_prompt(customer_info, [], "en")
        assert "English" in prompt_en or "english" in prompt_en.lower()

    def test_empty_customer_info_no_crash(self):
        prompt = build_upgraded_system_prompt({}, [], "zh")
        assert isinstance(prompt, str)
        assert len(prompt) > 0

    def test_conversation_history_included(self):
        customer_info = {"customer": {}, "orders": [], "skus": [], "communications": []}
        history = [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "您好"}
        ]
        prompt = build_upgraded_system_prompt(customer_info, history, "zh")
        assert "你好" in prompt
        assert "您好" in prompt


class TestServiceConstants:
    """服务常量测试"""

    def test_supported_languages(self):
        assert "zh" in SUPPORTED_LANGUAGES
        assert "en" in SUPPORTED_LANGUAGES
        assert "ar" in SUPPORTED_LANGUAGES
        assert "ru" in SUPPORTED_LANGUAGES

    def test_language_names_all_languages(self):
        for lang in SUPPORTED_LANGUAGES:
            assert lang in LANGUAGE_NAMES
            assert isinstance(LANGUAGE_NAMES[lang], str)
            assert len(LANGUAGE_NAMES[lang]) > 0

    def test_language_switch_messages(self):
        for lang in SUPPORTED_LANGUAGES:
            assert lang in LANGUAGE_SWITCH_MESSAGES
            assert isinstance(LANGUAGE_SWITCH_MESSAGES[lang], str)

    def test_language_names_count_matches(self):
        assert len(LANGUAGE_NAMES) >= len(SUPPORTED_LANGUAGES)
        assert len(LANGUAGE_SWITCH_MESSAGES) >= len(SUPPORTED_LANGUAGES)


class TestServiceIntegration:
    """服务集成测试"""

    def test_services_importable(self):
        """确保所有核心服务都能导入"""
        from services import (
            CircuitBreaker,
            query_graphrag,
            detect_emotion_advanced,
            detect_language,
            build_upgraded_system_prompt,
            SUPPORTED_LANGUAGES,
            LANGUAGE_NAMES,
            LANGUAGE_SWITCH_MESSAGES,
        )
        assert CircuitBreaker is not None
        assert isinstance(SUPPORTED_LANGUAGES, list)
