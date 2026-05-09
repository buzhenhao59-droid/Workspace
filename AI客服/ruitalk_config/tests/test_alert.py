# -*- coding: utf-8 -*-
"""
告警工具 pytest 测试
"""
import sys, os
from pathlib import Path

# 添加 tools 路径
_tools = Path(__file__).parent.parent / "tools"
sys.path.insert(0, str(_tools))
# mock .env.master 不存在的情况
os.environ.setdefault("DINGTALK_WEBHOOK", "")
os.environ.setdefault("FEISHU_WEBHOOK", "")
os.environ.setdefault("DINGTALK_SECRET", "")
os.environ.setdefault("SMTP_HOST", "")
os.environ.setdefault("ALERT_NOTIFY_EMAIL", "")
os.environ.setdefault("ALERT_LEVEL", "warning")

from alert import (
    AlertMessage, send, send_dingtalk, send_feishu,
    send_email, alert_error, alert_warning,
    LEVEL_PRIORITY, LEVEL_ICONS,
)


class TestAlertMessage:
    def test_dingtalk_format(self):
        msg = AlertMessage(level="error", title="测试告警", content="这是一条测试内容", source="Pytest")
        result = msg.to_dingtalk()
        assert result["msgtype"] == "markdown"
        assert "测试告警" in result["markdown"]["text"]
        assert "这是一条测试内容" in result["markdown"]["text"]

    def test_feishu_format(self):
        msg = AlertMessage(level="warning", title="飞书测试", content="飞书告警内容")
        result = msg.to_feishu()
        assert result["msg_type"] == "post"
        assert "飞书测试" in str(result["content"])

    def test_wecom_format(self):
        msg = AlertMessage(level="critical", title="企微测试", content="企微告警")
        result = msg.to_wecom()
        assert result["msgtype"] == "text"
        assert "企微测试" in result["text"]["content"]

    def test_email_format(self):
        msg = AlertMessage(level="info", title="邮件测试", content="邮件内容")
        subject, body = msg.to_email()
        assert "邮件测试" in subject
        assert "邮件内容" in body
        assert "<div" in body

    def test_extra_fields(self):
        msg = AlertMessage(level="error", title="带详情", content="内容",
                          extra={"server": "prod-01", "error_code": "E500"})
        dingtalk = msg.to_dingtalk()
        assert "server" in dingtalk["markdown"]["text"]
        assert "E500" in dingtalk["markdown"]["text"]

    def test_icon_mapping(self):
        assert LEVEL_ICONS["error"] == "🚨"
        assert LEVEL_ICONS["warning"] == "⚠️ "
        assert LEVEL_ICONS["info"] == "ℹ️ "

    def test_level_priority(self):
        assert LEVEL_PRIORITY["debug"] < LEVEL_PRIORITY["info"]
        assert LEVEL_PRIORITY["warning"] < LEVEL_PRIORITY["error"]
        assert LEVEL_PRIORITY["error"] < LEVEL_PRIORITY["critical"]


class TestAlertSend:
    def test_send_no_config_returns_false(self):
        """无任何配置时 send 应返回 False（不崩溃）"""
        msg = AlertMessage(level="error", title="无配置测试", content="不应发出")
        result = send(msg)
        # 无配置时应返回 False（没有成功发送的渠道）
        assert result == False

    def test_send_below_min_level_skipped(self):
        """级别低于阈值时跳过"""
        msg = AlertMessage(level="debug", title="不应发送", content="debug")
        result = send(msg, min_level="error")
        assert result == True  # 跳过不算失败，返回 True

    def test_alert_error_shortcut(self):
        """快捷函数不抛异常"""
        try:
            alert_error(title="测试错误", content="测试内容")
        except Exception as e:
            raise AssertionError(f"alert_error 抛出了异常: {e}")

    def test_alert_warning_shortcut(self):
        try:
            alert_warning(title="测试警告", content="测试内容")
        except Exception as e:
            raise AssertionError(f"alert_warning 抛出了异常: {e}")
