# -*- coding: utf-8 -*-
"""
Ruitalk Buyer API E2E Test Suite
================================
测试买方 FastAPI 服务 (http://127.0.0.1:8001) 的所有 API 端点。
无需浏览器，直接调用 REST API。

使用方法：
  python tests/full_buyer_e2e_test.py

依赖：requests
  pip install requests
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Any

import requests

# ─── 配置 ───────────────────────────────────────────────────────────────
BUYER_BASE = "http://127.0.0.1:8001"

# ─── ANSI 颜色 ─────────────────────────────────────────────────────────
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

C_RESET = "\033[0m"
C_GREEN = "\033[92m"
C_RED = "\033[91m"
C_YELLOW = "\033[93m"
C_BLUE = "\033[94m"
C_BOLD = "\033[1m"
C_GRAY = "\033[90m"


def ok(s: str) -> str:
    return f"{C_GREEN}{s}{C_RESET}"


def fail(s: str) -> str:
    return f"{C_RED}{s}{C_RESET}"


def warn(s: str) -> str:
    return f"{C_YELLOW}{s}{C_RESET}"


def info(s: str) -> str:
    return f"{C_BLUE}{s}{C_RESET}"


def gray(s: str) -> str:
    return f"{C_GRAY}{s}{C_RESET}"


# ─── 测试结果 ─────────────────────────────────────────────────────────
@dataclass
class TestResult:
    name: str
    passed: bool
    duration_ms: float
    detail: str = ""
    error: str = ""

    def __str__(self) -> str:
        icon = ok("[PASS]") if self.passed else fail("[FAIL]")
        ms = f"{self.duration_ms:.0f}ms"
        line = f"  {icon} {self.name:<55} {gray(ms)}"
        if self.error:
            line += f"\n        {fail('ERROR:')} {self.error[:120]}"
        elif self.detail:
            line += f"\n        {gray(self.detail[:120])}"
        return line


class TestRunner:
    def __init__(self):
        self.results: list[TestResult] = []
        self.session_id: str | None = None
        self.start_time = time.time()
        self._phone_counter = 19900000000

    def new_phone(self) -> str:
        self._phone_counter += 1
        return str(self._phone_counter)

    def _get(self, path: str, params: dict | None = None, **kwargs) -> requests.Response:
        url = f"{BUYER_BASE}{path}"
        kwargs.setdefault("timeout", 15)
        return requests.get(url, params=params, **kwargs)

    def _post(self, path: str, data: dict | None = None, **kwargs) -> requests.Response:
        url = f"{BUYER_BASE}{path}"
        kwargs.setdefault("timeout", 30)
        return requests.post(url, json=data, **kwargs)

    def run(self, name: str, fn: Callable[[], Any], detail_fn: Callable[[], str] | None = None):
        start = time.time()
        try:
            fn()
            dur = (time.time() - start) * 1000
            detail = detail_fn() if detail_fn else ""
            self.results.append(TestResult(name, True, dur, detail, ""))
            print(f"  {ok('[PASS]')} {name:<55} {gray(f'{dur:.0f}ms')}")
        except Exception as e:
            dur = (time.time() - start) * 1000
            err_type = type(e).__name__
            err_msg = f"[{err_type}] {str(e)[:200]}"
            self.results.append(TestResult(name, False, dur, "", err_msg))
            print(f"  {fail('[FAIL]')} {name:<55} {gray(f'{dur:.0f}ms')}")
            print(f"        {fail('ERROR:')} {err_type}: {str(e)[:150]}")

    def section(self, title: str):
        print(f"\n{C_BOLD}{'─' * 70}{C_RESET}")
        print(f"{C_BOLD}  {title}{C_RESET}")
        print(f"{C_BOLD}{'─' * 70}{C_RESET}")

    def summary(self) -> dict:
        passed = sum(1 for r in self.results if r.passed)
        total = len(self.results)
        failed = total - passed
        dur = time.time() - self.start_time

        print(f"\n{C_BOLD}{'═' * 70}{C_RESET}")
        print(f"{C_BOLD}  测试汇总{C_RESET}")
        print(f"{C_BOLD}{'═' * 70}{C_RESET}")
        print(f"  总计:    {total} 个测试")
        if passed == total:
            print(f"  {ok('通过:')}  {passed} 个  (100.0%)")
        else:
            pct = passed / max(total, 1) * 100
            if failed > 0:
                print(f"  {ok('通过:')}  {passed} 个  ({pct:.1f}%)")
                print(f"  {fail('失败:')}  {failed} 个")
            else:
                print(f"  {ok('通过:')}  {passed} 个  ({pct:.1f}%)")
        print(f"  耗时:    {dur:.1f}s")
        print()

        if failed > 0:
            print(f"{C_BOLD}{'─' * 70}{C_RESET}")
            print(f"{C_BOLD}  失败详情{C_RESET}")
            for r in self.results:
                if not r.passed:
                    print(f"  {fail('[X]')} {r.name}")
                    print(f"      {fail(r.error[:100])}")
            print()

        pct = passed / max(total, 1) * 100
        if pct == 100:
            status = ok(f"全部通过 (100%)")
        elif pct >= 80:
            status = warn(f"良好 ({pct:.1f}%)")
        else:
            status = fail(f"需改进 ({pct:.1f}%)")

        print(f"  综合结果: {status}")
        print(f"{C_BOLD}{'═' * 70}{C_RESET}\n")

        return {
            "passed": passed,
            "failed": failed,
            "total": total,
            "duration_s": round(dur, 1),
            "pct": round(pct, 1),
        }


# ─── 测试套件 ─────────────────────────────────────────────────────────
def run_tests() -> dict:
    t = TestRunner()

    # ════════════════════════════════════════════════════════════════
    t.section("1. 健康检查")
    # ════════════════════════════════════════════════════════════════

    def test_health():
        r = t._get("/health")
        assert r.status_code == 200

    def test_ready():
        r = t._get("/ready")
        assert r.status_code == 200

    def test_status():
        r = t._get("/api/v1/status")
        assert r.status_code == 200
        body = r.json()
        assert "circuit_breaker" in body or "status" in body

    def test_health_no_auth():
        r = t._get("/health")
        assert r.status_code == 200

    t.run("GET /health → 200 OK", test_health)
    t.run("GET /ready → 200 OK", test_ready)
    t.run("GET /api/v1/status → 系统状态信息", test_status)
    t.run("健康端点无需认证", test_health_no_auth)

    # ════════════════════════════════════════════════════════════════
    t.section("2. 会话管理")
    # ════════════════════════════════════════════════════════════════

    def test_start_session():
        phone = t.new_phone()
        r = t._post("/api/v1/customer/start", {"phone": phone})
        assert r.status_code == 200
        body = r.json()
        assert body["success"], f"响应: {body}"
        assert len(body["session_id"]) > 10
        t.session_id = body["session_id"]
        assert "welcome_message" in body

    def test_start_session_welcome():
        phone = t.new_phone()
        r = t._post("/api/v1/customer/start", {"phone": phone})
        body = r.json()
        assert "welcome_message" in body
        assert len(body["welcome_message"]) > 0

    def test_get_messages():
        assert t.session_id is not None, "No session"
        r = t._get("/api/v1/customer/messages", params={"session_id": t.session_id})
        assert r.status_code == 200
        body = r.json()
        assert body["success"], f"响应: {body}"
        assert "messages" in body["data"]
        assert isinstance(body["data"]["messages"], list)

    def test_get_session_info():
        assert t.session_id is not None, "No session"
        r = t._get("/api/v1/customer/session", params={"session_id": t.session_id})
        assert r.status_code == 200
        body = r.json()
        assert body["success"]
        assert body["data"]["is_ai"] in (True, False)
        assert body["data"]["language"] is not None

    def test_logout():
        assert t.session_id is not None, "No session"
        r = t._post("/api/v1/customer/logout", {"session_id": t.session_id})
        assert r.status_code == 200
        body = r.json()
        assert body["success"]

    def test_invalid_session():
        r = t._get("/api/v1/customer/messages", params={"session_id": "invalid_sid"})
        body = r.json()
        assert not body["success"]

    t.run("POST /api/v1/customer/start → 创建会话成功", test_start_session)
    t.run("会话返回 welcome_message", test_start_session_welcome)
    t.run("GET /api/v1/customer/messages → 获取消息历史", test_get_messages)
    t.run("GET /api/v1/customer/session → 获取会话信息", test_get_session_info)
    t.run("POST /api/v1/customer/logout → 登出成功", test_logout)
    t.run("无效 session_id → 返回错误", test_invalid_session)

    # ════════════════════════════════════════════════════════════════
    t.section("3. AI 对话")
    # ════════════════════════════════════════════════════════════════

    ai_phone = t.new_phone()
    ai_sid = None

    def setup_ai_session():
        nonlocal ai_sid
        r = t._post("/api/v1/customer/start", {"phone": ai_phone})
        body = r.json()
        ai_sid = body["session_id"]
        return ai_sid

    def test_ai_chat_zh():
        sid = setup_ai_session()
        r = t._post("/api/v1/customer/chat", {"session_id": sid, "message": "你好，请问我的订单什么时候发货？"})
        assert r.status_code == 200
        body = r.json()
        assert body["success"], f"失败: {body}"
        assert len(body["response"]) > 0, f"回复为空: {body}"

    def test_ai_chat_returns_language():
        r = t._post("/api/v1/customer/chat", {"session_id": ai_sid, "message": "Hello"})
        body = r.json()
        assert "language" in body

    def test_ai_chat_en():
        r = t._post("/api/v1/customer/chat", {"session_id": ai_sid, "message": "Hello, when will my order ship?"})
        body = r.json()
        assert body["success"]

    def test_ai_chat_ar():
        r = t._post("/api/v1/customer/chat", {"session_id": ai_sid, "message": "مرحبا، متى سيتم شحن طلبي؟"})
        body = r.json()
        assert body["success"]

    def test_ai_chat_ru():
        r = t._post("/api/v1/customer/chat", {"session_id": ai_sid, "message": "Здравствуйте, когда будет отправлен мой заказ?"})
        body = r.json()
        assert body["success"]

    def test_ai_chat_th():
        r = t._post("/api/v1/customer/chat", {"session_id": ai_sid, "message": "สวัสดีค่ะ สินค้าจะจัดส่งเมื่อไหร่?"})
        body = r.json()
        assert body["success"]

    def test_ai_chat_vi():
        r = t._post("/api/v1/customer/chat", {"session_id": ai_sid, "message": "Xin chào, đơn hàng của tôi khi nào gửi?"})
        body = r.json()
        assert body["success"]

    def test_ai_chat_id():
        r = t._post("/api/v1/customer/chat", {"session_id": ai_sid, "message": "Halo, kapan pesanan saya dikirim?"})
        body = r.json()
        assert body["success"]

    def test_ai_multi_turn():
        for msg in ["你好", "我的订单号是 ORD-123456", "谢谢"]:
            r = t._post("/api/v1/customer/chat", {"session_id": ai_sid, "message": msg})
            body = r.json()
            assert body["success"], f"'{msg}' 失败: {body}"

    def test_ai_no_garbled():
        r = t._post("/api/v1/customer/chat", {"session_id": ai_sid, "message": "你好，请介绍一下你们的商品"})
        body = r.json()
        resp = body["response"]
        has_bad = "\ufffd" in resp or "\x00" in resp
        assert not has_bad, f"回复含乱码: {resp[:100]}"

    def test_ai_invalid_session():
        r = t._post("/api/v1/customer/chat", {"session_id": "invalid", "message": "Hello"})
        body = r.json()
        assert not body["success"]

    def test_ai_missing_message():
        r = t._post("/api/v1/customer/chat", {"session_id": ai_sid})
        body = r.json()
        assert r.status_code == 422 or not body["success"]

    t.run("POST /api/v1/customer/chat → 中文对话成功", test_ai_chat_zh)
    t.run("POST /api/v1/customer/chat → 返回 language 字段", test_ai_chat_returns_language)
    t.run("POST /api/v1/customer/chat → 英语对话成功", test_ai_chat_en)
    t.run("POST /api/v1/customer/chat → 阿拉伯语对话成功", test_ai_chat_ar)
    t.run("POST /api/v1/customer/chat → 俄语对话成功", test_ai_chat_ru)
    t.run("POST /api/v1/customer/chat → 泰语对话成功", test_ai_chat_th)
    t.run("POST /api/v1/customer/chat → 越南语对话成功", test_ai_chat_vi)
    t.run("POST /api/v1/customer/chat → 印尼语对话成功", test_ai_chat_id)
    t.run("POST /api/v1/customer/chat → 多轮对话正确", test_ai_multi_turn)
    t.run("POST /api/v1/customer/chat → AI 回复不含乱码", test_ai_no_garbled)
    t.run("POST /api/v1/customer/chat → 无效 session 返回错误", test_ai_invalid_session)
    t.run("POST /api/v1/customer/chat → 缺少 message 返回错误", test_ai_missing_message)

    # ════════════════════════════════════════════════════════════════
    t.section("4. 语言切换")
    # ════════════════════════════════════════════════════════════════

    lang_phone = t.new_phone()
    lang_sid = None

    def setup_lang_session():
        nonlocal lang_sid
        r = t._post("/api/v1/customer/start", {"phone": lang_phone})
        lang_sid = r.json()["session_id"]
        return lang_sid

    for lang_code, lang_name in [("zh", "中文"), ("en", "英语"), ("ar", "阿拉伯语"), ("ru", "俄语"), ("th", "泰语"), ("vi", "越南语")]:
        def make_lang_test(lc, ln):
            def inner():
                nonlocal lang_sid
                if lang_sid is None:
                    lang_sid = setup_lang_session()
                r = t._post("/api/v1/customer/change_language", {"session_id": lang_sid, "language": lc})
                assert r.status_code == 200
                body = r.json()
                assert body["success"], f"{lc} 切换失败: {body}"
            return inner
        t.run(f"语言切换 → {lang_name}({lang_code})", make_lang_test(lang_code, lang_name))

    def test_lang_context_preserved():
        nonlocal lang_sid
        lang_sid = setup_lang_session()
        t._post("/api/v1/customer/chat", {"session_id": lang_sid, "message": "你好"})
        t._post("/api/v1/customer/change_language", {"session_id": lang_sid, "language": "en"})
        r = t._post("/api/v1/customer/chat", {"session_id": lang_sid, "message": "Hello"})
        body = r.json()
        assert body["success"]

    t.run("语言切换后对话上下文保持", test_lang_context_preserved)

    # ════════════════════════════════════════════════════════════════
    t.section("5. 转人工")
    # ════════════════════════════════════════════════════════════════

    tf_phone = t.new_phone()
    tf_sid = None

    def setup_tf_session():
        nonlocal tf_sid
        r = t._post("/api/v1/customer/start", {"phone": tf_phone})
        tf_sid = r.json()["session_id"]
        return tf_sid

    def test_transfer_to_human():
        nonlocal tf_sid
        tf_sid = setup_tf_session()
        r = t._post(f"/api/v1/customer/transfer-to-human?session_id={tf_sid}")
        assert r.status_code == 200
        body = r.json()
        assert body["success"], f"转人工失败: {body}"

    def test_transfer_ai_false():
        r = t._get("/api/v1/customer/session", params={"session_id": tf_sid})
        body = r.json()
        assert body["data"]["is_ai"] is False, f"is_ai 应为 False: {body['data']}"

    def test_transfer_to_ai():
        r = t._post(f"/api/v1/customer/transfer-to-ai?session_id={tf_sid}")
        assert r.status_code == 200
        body = r.json()
        assert body["success"]

    def test_transfer_back_ai_true():
        r = t._get("/api/v1/customer/session", params={"session_id": tf_sid})
        body = r.json()
        assert body["data"]["is_ai"] is True, f"is_ai 应为 True: {body['data']}"

    def test_transfer_back_ai_works():
        r = t._post("/api/v1/customer/chat", {"session_id": tf_sid, "message": "你好"})
        body = r.json()
        assert body["success"]

    def test_transfer_invalid():
        r = t._post("/api/v1/customer/transfer-to-human?session_id=invalid")
        body = r.json()
        assert not body["success"]

    t.run("POST transfer-to-human → 转人工成功", test_transfer_to_human)
    t.run("转人工后会话 is_ai = false", test_transfer_ai_false)
    t.run("POST transfer-to-ai → 转回 AI 成功", test_transfer_to_ai)
    t.run("转回 AI 后 is_ai = true", test_transfer_back_ai_true)
    t.run("转回 AI 后 AI 对话正常响应", test_transfer_back_ai_works)
    t.run("无效 session 转人工返回错误", test_transfer_invalid)

    # ════════════════════════════════════════════════════════════════
    t.section("6. 翻译 API")
    # ════════════════════════════════════════════════════════════════

    for text, target, lang_name in [
        ("Hello world", "zh", "英译中"),
        ("مرحبا", "zh", "阿拉伯语译中"),
        ("Здравствуйте", "zh", "俄语译中"),
        ("สวัสดีค่ะ", "zh", "泰语译中"),
        ("Xin chào", "zh", "越南语译中"),
        ("Halo", "zh", "印尼语译中"),
        ("Bonjour", "zh", "法语译中"),
        ("你好", "en", "中译英"),
    ]:
        def make_trans_test(tx, tg):
            def inner():
                r = t._post("/api/v1/translate", {"text": tx, "target": tg})
                assert r.status_code == 200
                body = r.json()
                assert body["success"], f"翻译失败: {body}"
                assert len(body["translated"]) > 0, f"翻译结果为空: {body}"
            return inner
        t.run(f"翻译: {lang_name}", make_trans_test(text, target))

    def test_translate_missing_text():
        r = t._post("/api/v1/translate", {"target": "zh"})
        body = r.json()
        assert not body["success"]

    def test_translate_missing_target():
        r = t._post("/api/v1/translate", {"text": "Hello"})
        body = r.json()
        assert not body["success"]

    t.run("缺少 text 参数 → 返回错误", test_translate_missing_text)
    t.run("缺少 target 参数 → 返回错误", test_translate_missing_target)

    # ════════════════════════════════════════════════════════════════
    t.section("7. 客户档案")
    # ════════════════════════════════════════════════════════════════

    prof_phone = t.new_phone()
    prof_sid = None

    def setup_prof_session():
        nonlocal prof_sid
        r = t._post("/api/v1/customer/start", {"phone": prof_phone})
        prof_sid = r.json()["session_id"]
        return prof_sid

    def test_myinfo():
        nonlocal prof_sid
        prof_sid = setup_prof_session()
        r = t._post("/api/v1/customer/myinfo", {"session_id": prof_sid})
        assert r.status_code == 200
        body = r.json()
        assert body["success"], f"失败: {body}"
        assert body["data"]["customer"] is not None

    def test_myinfo_has_customer_id():
        r = t._post("/api/v1/customer/myinfo", {"session_id": prof_sid})
        body = r.json()
        assert body["data"]["customer"]["customer_id"] is not None

    def test_myinfo_correct_phone():
        r = t._post("/api/v1/customer/myinfo", {"session_id": prof_sid})
        body = r.json()
        assert body["data"]["customer"]["phone"] == prof_phone

    def test_myinfo_invalid():
        r = t._post("/api/v1/customer/myinfo", {"session_id": "invalid"})
        body = r.json()
        assert not body["success"] or not body["data"]["customer"]

    t.run("POST /api/v1/customer/myinfo → 获取客户信息", test_myinfo)
    t.run("客户信息包含 customer_id", test_myinfo_has_customer_id)
    t.run("客户信息包含正确 phone", test_myinfo_correct_phone)
    t.run("无效 session 查询客户信息 → 返回错误", test_myinfo_invalid)

    # ════════════════════════════════════════════════════════════════
    t.section("8. 客户发送消息")
    # ════════════════════════════════════════════════════════════════

    send_phone = t.new_phone()
    send_sid = None

    def setup_send_session():
        nonlocal send_sid
        r = t._post("/api/v1/customer/start", {"phone": send_phone})
        send_sid = r.json()["session_id"]
        return send_sid

    def test_send_message():
        nonlocal send_sid
        send_sid = setup_send_session()
        r = t._post("/api/v1/customer/send", {"session_id": send_sid, "content": "测试发送消息"})
        assert r.status_code == 200
        body = r.json()
        assert body["success"]

    def test_send_invalid():
        r = t._post("/api/v1/customer/send", {"session_id": "invalid", "content": "msg"})
        body = r.json()
        assert not body["success"]

    t.run("POST /api/v1/customer/send → 发送消息成功", test_send_message)
    t.run("POST /api/v1/customer/send → 无效 session 返回错误", test_send_invalid)

    # ════════════════════════════════════════════════════════════════
    t.section("9. 跨系统回调（签名验证）")
    # ════════════════════════════════════════════════════════════════

    def test_callback_back_to_ai():
        r = t._post("/api/v1/internal/buyer-back-to-ai", {"session_id": "test"})
        body = r.json()
        assert r.status_code >= 400 or not body["success"]

    def test_callback_message():
        r = t._post("/api/v1/internal/buyer-message", {"session_id": "test", "message": "hi"})
        body = r.json()
        assert r.status_code >= 400 or not body["success"]

    t.run("buyer-back-to-ai → 需正确签名", test_callback_back_to_ai)
    t.run("buyer-message → 需正确签名", test_callback_message)

    # ════════════════════════════════════════════════════════════════
    t.section("10. 限流 & 并发")
    # ════════════════════════════════════════════════════════════════

    rapid_phone = t.new_phone()
    rapid_sid = t._post("/api/v1/customer/start", {"phone": rapid_phone}).json()["session_id"]

    def test_rapid_requests():
        successes = 0
        for i in range(5):
            try:
                r = t._post("/api/v1/customer/chat", {"session_id": rapid_sid, "message": f"快速消息 {i}"})
                if r.ok:
                    successes += 1
            except Exception:
                pass
        assert successes >= 1, f"全部失败，共 5 个请求"

    t.run("快速连续 5 次请求 → 至少部分成功(限流正常)", test_rapid_requests)

    # ════════════════════════════════════════════════════════════════
    t.section("11. 错误处理")
    # ════════════════════════════════════════════════════════════════

    def test_404():
        r = t._get("/api/nonexistent/path")
        assert r.status_code == 404

    def test_missing_message():
        r = t._post("/api/v1/customer/chat", {"session_id": ai_sid})
        body = r.json()
        assert r.status_code == 422 or not body["success"]

    t.run("不存在的 API 路径 → 404", test_404)
    t.run("POST /api/v1/customer/chat 空 body → 422/错误", test_missing_message)

    return t.summary()


# ─── 入口 ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"\n{'═' * 70}")
    print(f"  Ruitalk 买方 API E2E 测试")
    print(f"  目标服务: {BUYER_BASE}")
    print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'═' * 70}\n")

    try:
        r = requests.get(f"{BUYER_BASE}/health", timeout=5)
        if r.status_code != 200:
            print(fail(f"买方服务未响应 HTTP {r.status_code}，请先启动买方 FastAPI"))
            print("启动命令: python AI客服买方系统/backend/main_buyer.py")
            sys.exit(1)
    except requests.exceptions.ConnectionError:
        print(fail("无法连接到买方服务 http://127.0.0.1:8001"))
        print("请先启动买方 FastAPI:")
        print("  python AI客服买方系统/backend/main_buyer.py")
        sys.exit(1)

    summary = run_tests()

    out_path = "d:/Ruitalk1/tests/buyer_e2e_report.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "service": "buyer",
            **summary
        }, f, ensure_ascii=False, indent=2)
    print(f"  JSON 报告: {out_path}")

    sys.exit(0 if summary["failed"] == 0 else 1)
