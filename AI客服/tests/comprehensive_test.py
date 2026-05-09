# -*- coding: utf-8 -*-
"""
Ruitalk 综合生产测试脚本
Comprehensive Production Test for Ruitalk

测试范围:
  Phase 1: AI并发压测 - 多客户同时聊天，无串台/卡机
  Phase 2: 人工客服模拟 - 多坐席1:1处理，无串线/重复回复
  Phase 3: 多语言测试 - 8种语言切换，翻译质量验证
  Phase 4: AI回复质量 - 拟人性、连贯性、乱码检测
  Phase 5: 卖家终端 - 消息中心/评价回复/售前售后/店铺管理
  Phase 6: .env.master配置 - 配置变更生效测试
  Phase 7: 清理 + 生成生产就绪报告

用法:
  python comprehensive_test.py
  python comprehensive_test.py --skip-ai       # 跳过AI压测（节省API费用）
  python comprehensive_test.py --skip-seller    # 跳过卖家终端测试
  python comprehensive_test.py --quick           # 快速模式（减少并发数）
"""
import sys as _sys
_v1 = r"D:\Ruitalk1\卖方终端\.venv\Lib\site-packages"
_v2 = r"D:\lib\site-packages"
for _vp in [_v1, _v2]:
    if _vp not in _sys.path:
        _sys.path.insert(0, _vp)

# Windows下强制UTF-8输出
import os as _os
if _os.name == "nt":
    _os.environ["PYTHONIOENCODING"] = "utf-8"
    _os.environ["PYTHONUTF8"] = "1"

import os
import sys
import time
import json
import uuid
import sqlite3
import random
import string
import signal
import argparse
import traceback
import hashlib
import hmac
import base64
import requests
import threading
import re
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

# ── 基础配置 ──────────────────────────────────────────────────
SELLER_BASE = "http://127.0.0.1:8000"
BUYER_BASE  = "http://127.0.0.1:8002"
DB_PATH     = r"D:\Ruitalk1\卖方终端\data\gold_customer.db"
JWT_SECRET  = "aeb2011dc2501a5d4b81d439c8d2a2bffcfd5a08dd46f89d6aae515540a7c0e6d744eff142cb6c5c98eec0b3270f16b2ffb7cae71240f07bcc66e577413aeafe"
SELLER_INTERNAL_TOKEN = "buyer-to-seller-secret-token-2026-TUOYUE"
TS = int(time.time())

# ── 并发规模 ──────────────────────────────────────────────────
N_CONCURRENT_AI    = 3
N_CONCURRENT_HUMAN = 2

# ── 跨平台安全输出（避免Windows GBK编码崩溃）────────────────────
def _safe_print(text):
    try:
        sys.stdout.write(text + "\n")
        sys.stdout.flush()
    except UnicodeEncodeError:
        try:
            encoded = text.encode("utf-8", errors="replace").decode("utf-8")
            sys.stdout.write(encoded + "\n")
            sys.stdout.flush()
        except Exception:
            sys.stdout.write("[output encoding error]\n")
            sys.stdout.flush()

def log(typ, label, msg=""):
    icons = {"OK": "[OK]", "FAIL": "[FAIL]", "WARN": "[WARN]", "INFO": "[INFO]"}
    colors = {"OK": "\033[92m", "FAIL": "\033[91m", "WARN": "\033[93m",
              "INFO": "\033[94m", "END": "\033[0m", "BOLD": "\033[1m"}
    icon = icons.get(typ, "[--]")
    color = colors.get(typ, colors["END"])
    _safe_print(f"{color}{icon}{colors['END']} {colors['BOLD']}{label}{colors['END']} {msg}")

def phase_title(title):
    sep = "=" * 70
    _safe_print(sep)
    _safe_print(f"  {title}")
    _safe_print(sep)
    _safe_print("")

def warn(msg):
    log("WARN", "", msg)

def info(msg):
    log("INFO", "", msg)

# ── HTTP helpers ──────────────────────────────────────────────
def http_get(url, headers=None, params=None, timeout=30):
    try:
        r = requests.get(url, headers=headers, params=params, timeout=timeout)
        try: return r.status_code, r.json()
        except: return r.status_code, r.text
    except requests.exceptions.Timeout:
        return 0, {"error": "timeout"}
    except requests.exceptions.ConnectionError:
        return 0, {"error": "connection_refused"}

def http_post(url, data=None, json=None, headers=None, params=None, timeout=30):
    try:
        r = requests.post(url, data=data, json=json, headers=headers, params=params, timeout=timeout)
        try: return r.status_code, r.json()
        except: return r.status_code, r.text
    except requests.exceptions.Timeout:
        return 0, {"error": "timeout"}
    except requests.exceptions.ConnectionError:
        return 0, {"error": "connection_refused"}

def http_put(url, json=None, headers=None, timeout=30):
    r = requests.put(url, json=json, headers=headers, timeout=timeout)
    try: return r.status_code, r.json()
    except: return r.status_code, r.text

def make_internal_headers(method, path):
    ts = str(int(time.time()))
    payload = f"{ts}{method}{path}"
    sig = base64.b64encode(hmac.new(
        SELLER_INTERNAL_TOKEN.encode(), payload.encode(), "sha256").digest()
    ).decode()
    return {"X-Internal-Signature": sig, "X-Internal-Timestamp": ts, "Content-Type": "application/json"}

# ── 数据库 ────────────────────────────────────────────────────
def db_execute(sql, args=()):
    conn = sqlite3.connect(DB_PATH); cur = conn.cursor()
    cur.execute(sql, args); conn.commit()
    return conn, cur

def db_fetchall(sql, args=()):
    conn = sqlite3.connect(DB_PATH); cur = conn.cursor()
    cur.execute(sql, args)
    rows = cur.fetchall(); conn.close()
    cols = [d[0] for d in cur.description] if cur.description else []
    return [dict(zip(cols, r)) for r in rows]

def db_fetchone(sql, args=()):
    conn = sqlite3.connect(DB_PATH); cur = conn.cursor()
    cur.execute(sql, args)
    row = cur.fetchone(); conn.close()
    cols = [d[0] for d in cur.description] if cur.description else []
    return dict(zip(cols, row)) if row else None

# ── 清理 ─────────────────────────────────────────────────────
def cleanup():
    phase_title("清理旧测试数据")
    conn = sqlite3.connect(DB_PATH); cur = conn.cursor()
    deleted = 0
    for table in ["messages", "sessions", "customers"]:
        try:
            cur.execute(f"DELETE FROM {table} WHERE phone LIKE '199%' OR customer_id LIKE 'test_prod_%'")
            deleted += cur.rowcount
        except: pass
    conn.commit(); conn.close()
    log("INFO", "清理完成", f"删除了 {deleted} 条记录")

# ── 测试结果 ───────────────────────────────────────────────────
@dataclass
class TestResult:
    phase: str; name: str; passed: bool
    detail: str = ""; duration_ms: float = 0.0
    extra: dict = field(default_factory=dict)
    def to_dict(self) -> dict: return asdict(self)

ALL_RESULTS: List[TestResult] = []
RESULTS_LOCK = threading.Lock()

def record(phase, name, passed, detail="", duration_ms=0.0, **extra):
    r = TestResult(phase=phase, name=name, passed=passed,
                   detail=detail, duration_ms=duration_ms, extra=extra)
    with RESULTS_LOCK: ALL_RESULTS.append(r)
    return r

def summarize():
    total = len(ALL_RESULTS)
    passed = sum(1 for r in ALL_RESULTS if r.passed)
    return total, passed, total - passed

# ── AI质量检测 ─────────────────────────────────────────────────
def is_gibberish(text):
    if not text: return True, "空回复"
    if len(set(text)) < len(text) * 0.15: return True, f"字符重复({len(set(text))}/{len(text)})"
    bad = sum(1 for c in text if 0 < ord(c) < 32 and c not in "\n\t")
    if bad > len(text) * 0.1: return True, f"控制字符({bad}/{len(text)})"
    valid_ranges = [(0x0020,0x007F),(0x00A0,0x024F),(0x3000,0x303F),(0x4E00,0x9FFF),
                    (0x0600,0x06FF),(0x0400,0x04FF),(0x0E00,0x0E7F),(0x0100,0x017F)]
    def in_rng(c,r): return r[0] <= ord(c) <= r[1]
    valid = sum(1 for c in text if any(in_rng(c,r) for r in valid_ranges) or c in "\n\t ")
    if valid < len(text) * 0.7: return True, "异常Unicode"
    return False, ""

def check_quality(text, lang):
    score, issues = 100, []
    gib, reason = is_gibberish(text)
    if gib: score -= 60; issues.append(f"乱码: {reason}")
    if len(text) < 5: score -= 40; issues.append("过短(<5)")
    elif len(text) > 2000: score -= 10; issues.append("过长(>2000)")
    for pat in ["API","error","Error","Exception","错误","失败","超时"]:
        if pat in text and text.index(pat) < 50:
            score -= 20; issues.append(f"含错误提示:{pat}"); break
    return {"score": max(0,score), "issues": issues, "length": len(text), "gibberish": gib}

# ═══════════════════════════════════════════════════════════════
# Phase 1: AI并发压测（无串台/卡机）
# ═══════════════════════════════════════════════════════════════
def phase1_ai_stress_test(args):
    phase_title("Phase 1: AI并发压测 - 多客户同时聊天，无串台")
    N = 3 if args.quick else N_CONCURRENT_AI
    phrase = "你好，请问我的订单发货了吗？"
    tokens = [f"UNIQUE_TOKEN_{TS}_{i}" for i in range(N)]
    results = {"ok":0,"crosstalk":0,"crash":0,"gibberish":0}
    lock = threading.Lock()
    responses = []

    def worker(idx):
        phone = f"199{TS % 100000 + idx:05d}"
        token = tokens[idx]
        try:
            code, body = http_post(f"{BUYER_BASE}/api/customer/start", json={"phone": phone}, timeout=15)
            if code != 200 or not body.get("session_id"):
                with lock: results["crash"] += 1
                record("Phase1", f"客户{idx+1}会话", False, f"HTTP {code}"); return
            sid = body["session_id"]
            code, body = http_post(f"{BUYER_BASE}/api/customer/chat",
                json={"session_id": sid, "message": f"{phrase} [ID:{token}]"}, timeout=60)
            resp = body.get("response","") if code == 200 else ""
            if not resp:
                with lock: results["crash"] += 1
                record("Phase1", f"客户{idx+1}聊天", False, f"HTTP {code}"); return
            q = check_quality(resp, "zh")
            crosstalk = any(t in resp for j,t in enumerate(tokens) if j != idx)
            with lock:
                if crosstalk:
                    results["crosstalk"] += 1
                    record("Phase1", f"客户{idx+1}串台", False, "回复含其他token")
                elif q["gibberish"] or q["score"] < 50:
                    results["gibberish"] += 1
                    record("Phase1", f"客户{idx+1}质量", False, f"{q['score']}分: {';'.join(q['issues'])}")
                    responses.append((idx, resp))
                else:
                    results["ok"] += 1
                    record("Phase1", f"客户{idx+1}正常", True, f"{len(resp)}字 质量{q['score']}")
                    responses.append((idx, resp))
        except requests.exceptions.Timeout:
            with lock: results["crash"] += 1
            record("Phase1", f"客户{idx+1}超时", False, "60s超时")
        except Exception as e:
            with lock: results["crash"] += 1
            record("Phase1", f"客户{idx+1}异常", False, str(e)[:80])

    with ThreadPoolExecutor(max_workers=N) as ex:
        futures = [ex.submit(worker, i) for i in range(N)]
        for f in as_completed(futures):
            try: f.result()
            except Exception as e: warn(f"Worker error: {e}")

    total = sum(results.values())
    log("INFO", "AI压测完成", f"总计{total} 成功{results['ok']} 串台{results['crosstalk']} 崩溃{results['crash']} 质量{results['gibberish']}")
    if responses:
        _safe_print("示例回复:")
        for idx, resp in responses:
            q = check_quality(resp,"zh")
            _safe_print(f"  客户{idx+1}: [{q['score']}分] {resp[:150].replace(chr(10),' ')}...")
    return results["crosstalk"] == 0 and results["crash"] == 0

# ═══════════════════════════════════════════════════════════════
# Phase 2: 人工客服1:1模拟（无串线/重复回复）
# ═══════════════════════════════════════════════════════════════
def phase2_human_agent_test(args):
    phase_title("Phase 2: 人工客服1:1模拟 - 多坐席处理，无串线/重复回复")
    N = 2 if args.quick else N_CONCURRENT_HUMAN

    # 管理员登录：尝试多种密码
    admin_token = None
    for pwd in ["123456", "NEjJs73tW8j7EP8vXC58qZ6_uq5wsqFC"]:
        code, body = http_post(f"{SELLER_BASE}/api/admin/login",
            json={"username": "admin", "password": pwd}, timeout=15)
        if code == 200 and body.get("access_token"):
            admin_token = body["access_token"]
            log("OK", "管理员登录", f"HTTP {code}")
            break
    if not admin_token:
        # 尝试数据库中的seller账户
        conn = sqlite3.connect(DB_PATH); cur = conn.cursor()
        try:
            cur.execute("SELECT username FROM sellers LIMIT 1")
            row = cur.fetchone()
            if row:
                cols = [d[0] for d in cur.description]
                uname = dict(zip(cols, row)).get("username","admin")
                code, body = http_post(f"{SELLER_BASE}/api/seller/login",
                    json={"username": uname, "password": "admin123"}, timeout=15)
                if code == 200 and body.get("access_token"):
                    admin_token = body["access_token"]
                    log("OK", f"Seller账户登录({uname})", f"HTTP {code}")
        except: pass
        finally: conn.close()
    if not admin_token:
        warn("管理员登录失败，跳过Phase2")
        record("Phase2", "管理员登录", False, "无法登录")
        return False

    hdr_admin = {"Authorization": f"Bearer {admin_token}"}

    # 创建测试坐席（直接写入sellers数据库表）
    agent_tokens = []
    agent_usernames = []
    import hashlib as _hl
    def _pwd_hash(pwd):
        return _hl.sha256(("gold_customer_salt_" + pwd).encode()).hexdigest()
    for i in range(N):
        uname = f"agent_prod_{TS}_{i}"; pwd = f"Agent@Test{TS}{i}"
        pwd_hash = _pwd_hash(pwd)
        try:
            conn2 = sqlite3.connect(DB_PATH); cur2 = conn2.cursor()
            cur2.execute("INSERT OR IGNORE INTO sellers (username, password_hash, name, role) VALUES (?, ?, ?, ?)",
                (uname, pwd_hash, f"TestAgent{i+1}", "agent"))
            conn2.commit()
            conn2.close()
            log("OK", f"坐席{i+1}创建(DB)", True)
        except Exception as e:
            record("Phase2", f"坐席{i+1}创建", False, str(e)[:50]); continue

        code, body = http_post(f"{SELLER_BASE}/api/seller/login",
            json={"username": uname, "password": pwd}, timeout=15)
        if code == 200 and body.get("access_token"):
            agent_tokens.append(body["access_token"])
            agent_usernames.append(uname)
            record("Phase2", f"坐席{i+1}登录", True)
        else:
            record("Phase2", f"坐席{i+1}登录", False, f"HTTP {code}")

    if not agent_tokens:
        warn("无法创建坐席，跳过Phase2"); return False

    # 创建客户会话并转人工
    csessions = []
    for i in range(len(agent_tokens)):
        phone = f"199{TS % 100000 + i + 1:05d}"
        code, body = http_post(f"{BUYER_BASE}/api/customer/start", json={"phone": phone}, timeout=15)
        if code != 200 or not body.get("session_id"): continue
        sid = body["session_id"]
        code, body = http_post(f"{BUYER_BASE}/api/customer/transfer-to-human",
            params={"session_id": sid}, timeout=15)
        if code == 200:
            csessions.append(sid)
            record("Phase2", f"客户{i+1}转人工", True)
        else:
            record("Phase2", f"客户{i+1}转人工", False, f"HTTP {code}")

    if not csessions:
        warn("无法创建客户会话"); return False

    # 各坐席发送唯一消息
    lock = threading.Lock(); send_results = []
    def agent_send(aidx, atoken, csid):
        msg = f"[坐席{aidx+1}]您好专属客服，请提供订单号。"
        hdr = {"Authorization": f"Bearer {atoken}"}
        try:
            c1, b1 = http_post(f"{SELLER_BASE}/api/seller/send",
                json={"session_id": csid, "content": msg}, headers=hdr, timeout=15)
            c2, b2 = http_post(f"{BUYER_BASE}/api/customer/send",
                json={"session_id": csid, "content": msg}, timeout=15)
            with lock: send_results.append({"ok": c1==200 or c2==200})
        except Exception as e:
            with lock: send_results.append({"ok": False, "err": str(e)[:80]})

    with ThreadPoolExecutor(max_workers=len(agent_tokens)) as ex:
        futures = [ex.submit(agent_send, i, at, cs)
                  for i,(at,cs) in enumerate(zip(agent_tokens, csessions))]
        for f in as_completed(futures):
            try: f.result()
            except Exception as e: warn(f"Agent error: {e}")

    # 验证无串线
    crosstalk = False
    for csid, exp_idx in zip(csessions, range(len(csessions))):
        code, body = http_get(f"{BUYER_BASE}/api/customer/messages",
            params={"session_id": csid}, timeout=15)
        if code == 200 and body.get("data",{}).get("messages"):
            msgs = body["data"]["messages"]
            for m in msgs:
                content = m.get("content","")
                for j in range(len(agent_tokens)):
                    if j != exp_idx and f"坐席{j+1}" in content:
                        crosstalk = True
                        record("Phase2", f"客户{exp_idx+1}串线", False, f"收到坐席{j+1}消息")
            if not crosstalk:
                record("Phase2", f"客户{exp_idx+1}无串线", True, f"共{len(msgs)}条消息")

    log("INFO", "人工1:1完成", f"处理{len(send_results)}个坐席，串线{'异常' if crosstalk else '正常'}")
    return not crosstalk

# ═══════════════════════════════════════════════════════════════
# Phase 3: 多语言测试
# ═══════════════════════════════════════════════════════════════
def phase3_multilingual_test(args):
    phase_title("Phase 3: 多语言测试 - 8种语言切换，翻译质量")
    phone = f"199{TS % 100000 + 888:05d}"
    code, body = http_post(f"{BUYER_BASE}/api/customer/start", json={"phone": phone}, timeout=15)
    if code != 200 or not body.get("session_id"):
        record("Phase3", "会话", False, f"HTTP {code}"); return False
    sid = body["session_id"]

    langs = [
        ("zh", "你好，快递什么时候到？", "中文"),
        ("en", "Hi, when will my order arrive?", "英文"),
        ("ar", "مرحبا، متى سيصل طلبي؟", "阿拉伯语"),
        ("ru", "Привет, когда прибудет заказ?", "俄语"),
        ("th", "สวัสดีครับ สินค้าจะมาเมื่อไหร่?", "泰语"),
        ("vi", "Xin chào, đơn hàng sẽ đến khi nào?", "越南语"),
        ("id", "Halo, kapan pesanan saya tiba?", "印尼语"),
        ("tl", "Kamusta, kailan aabot ang order ko?", "菲律宾语"),
    ]

    all_ok = True
    for lc, q, lname in langs:
        t0 = time.time()
        try:
            code, body = http_post(f"{BUYER_BASE}/api/customer/change_language",
                json={"session_id": sid, "language": lc}, timeout=15)
            if code != 200:
                record("Phase3", f"切换{lname}", False, f"HTTP {code}")
                all_ok = False; continue
            code, body = http_post(f"{BUYER_BASE}/api/customer/chat",
                json={"session_id": sid, "message": q}, timeout=60)
            dur = (time.time()-t0)*1000
            if code != 200 or not body.get("response"):
                record("Phase3", f"{lname}对话", False, f"HTTP {code}")
                all_ok = False; continue
            resp = body["response"]
            q2 = check_quality(resp, lc)
            tc, tb = http_post(f"{BUYER_BASE}/api/translate",
                json={"text": "Hello world", "target": lc}, timeout=15)
            trans_ok = tc == 200 and bool(tb.get("success")) and bool(tb.get("translated"))
            issues_str = ";".join(q2["issues"]) if q2["issues"] else "OK"
            ok = not q2["gibberish"] and trans_ok and q2["score"] >= 40
            if not ok: all_ok = False
            record("Phase3", lname, ok,
                f"质量{q2['score']} 翻译{'OK' if trans_ok else 'FAIL'} 耗时{dur:.0f}ms",
                extra={"response": resp[:200]})
        except requests.exceptions.Timeout:
            record("Phase3", lname, False, "60s超时"); all_ok = False
        except Exception as e:
            record("Phase3", lname, False, str(e)[:80]); all_ok = False

    return all_ok

# ═══════════════════════════════════════════════════════════════
# Phase 4: AI回复拟人性质量
# ═══════════════════════════════════════════════════════════════
def phase4_ai_quality_test(args):
    phase_title("Phase 4: AI回复质量评估 - 拟人性、连贯性、乱码检测")
    questions = [
        ("zh", "我的订单还没发货，等了5天了！", "中文-投诉"),
        ("en", "The product is broken. I want a refund.", "英文-投诉"),
        ("zh", "你好，请问这款手机支持5G吗？", "中文-咨询"),
        ("en", "Can this phone case fit iPhone 15?", "英文-咨询"),
        ("zh", "谢谢你的帮助！", "中文-感谢"),
        ("ar", "شكرا لك على المساعدة", "阿拉伯语-感谢"),
        ("ru", "Спасибо большое за помощь!", "俄语-感谢"),
        ("zh", "转人工客服", "中文-转人工"),
        ("en", "I need to talk to a human agent", "英文-转人工"),
    ]
    scores = []
    for lc, q, qt in questions:
        phone = f"199{TS % 100000 + random.randint(100,999):05d}"
        try:
            code, body = http_post(f"{BUYER_BASE}/api/customer/start", json={"phone": phone}, timeout=15)
            if code != 200: continue
            sid = body["session_id"]
            code, body = http_post(f"{BUYER_BASE}/api/customer/chat",
                json={"session_id": sid, "message": q}, timeout=60)
            if code != 200 or not body.get("response"): continue
            resp = body["response"]
            quality = check_quality(resp, lc)
            scores.append(quality["score"])
            issues_str = ";".join(quality["issues"]) if quality["issues"] else "OK"
            ok = not quality["gibberish"] and len(resp) >= 10 and quality["score"] >= 40
            record("Phase4", qt, ok,
                f"质量{quality['score']} 长度{len(resp)} {issues_str}",
                extra={"response": resp[:300]})
        except Exception as e:
            record("Phase4", qt, False, str(e)[:80])

    avg = sum(scores)/len(scores) if scores else 0
    fail_rate = sum(1 for s in scores if s < 60)/max(1,len(scores))
    log("INFO", "AI质量完成", f"平均{avg:.1f}分 不合格率{fail_rate:.1%} 测试{len(scores)}题")
    return fail_rate <= 0.4

# ═══════════════════════════════════════════════════════════════
# Phase 5: 卖家终端功能
# ═══════════════════════════════════════════════════════════════
def phase5_seller_terminal_test(args):
    phase_title("Phase 5: 卖家终端 - 消息中心/评价回复/售前售后/店铺管理")

    # 管理员登录
    admin_token = None
    for pwd in ["123456", "NEjJs73tW8j7EP8vXC58qZ6_uq5wsqFC"]:
        code, body = http_post(f"{SELLER_BASE}/api/admin/login",
            json={"username": "admin", "password": pwd}, timeout=15)
        if code == 200 and body.get("access_token"):
            admin_token = body["access_token"]; break
    hdr_admin = {"Authorization": f"Bearer {admin_token}"} if admin_token else {}

    # 健康检查
    code, body = http_get(f"{SELLER_BASE}/health", timeout=10)
    results_health = code == 200
    record("Phase5", "健康检查", results_health, f"HTTP {code}")

    # 熔断器
    code, body = http_get(f"{SELLER_BASE}/api/circuit-breakers", timeout=10)
    record("Phase5", "熔断器状态", code == 200, f"HTTP {code}")

    # Redis
    code, body = http_get(f"{SELLER_BASE}/api/redis-status", timeout=10)
    record("Phase5", "Redis状态", code == 200, f"HTTP {code}")

    # 仪表盘统计
    code, body = http_get(f"{SELLER_BASE}/api/admin/stats", headers=hdr_admin, timeout=10)
    record("Phase5", "仪表盘统计", code == 200, f"HTTP {code}")

    # 评价列表
    code, body = http_get(f"{SELLER_BASE}/api/admin/reviews",
        params={"limit":5}, headers=hdr_admin, timeout=10)
    reviews_ok = code == 200
    record("Phase5", "评价列表API", reviews_ok, f"HTTP {code}")

    # 评价回复
    if hdr_admin:
        code, body = http_post(f"{SELLER_BASE}/api/admin/reviews/reply",
            json={"review_ids":["test_review_001"],"reply_content":"感谢您的支持！"},
            headers=hdr_admin, timeout=10)
        record("Phase5", "评价回复API", code == 200, f"HTTP {code}")
    else:
        record("Phase5", "评价回复API", False, "无admin token")

    # 订单列表
    code, body = http_get(f"{SELLER_BASE}/api/admin/orders",
        params={"limit":5}, timeout=10)
    record("Phase5", "订单列表API", code == 200, f"HTTP {code}")

    # 退换货列表
    code, body = http_get(f"{SELLER_BASE}/api/admin/after-sales",
        params={"page":1,"page_size":5}, headers=hdr_admin, timeout=10)
    record("Phase5", "退换货列表API", code == 200, f"HTTP {code}")

    # 售后单创建
    if hdr_admin:
        code, body = http_post(f"{SELLER_BASE}/api/admin/after-sales",
            json={"order_id":f"TEST_{TS}","type":"退货退款","reason_detail":"商品损坏"},
            headers=hdr_admin, timeout=10)
        record("Phase5", "售后单创建API", code == 200, f"HTTP {code}")

    # 店铺管理页面（无独立API，验证页面路由可达）
    code, body = http_get(f"{SELLER_BASE}/admin/shop-manager.html", timeout=10)
    record("Phase5", "店铺管理页面", code == 200, f"HTTP {code}")

    # 坐席控制台+消息中心
    test_agent = f"seller_agent_{TS}"
    if hdr_admin:
        import hashlib as _hl2
        def _pwd_hash2(pwd):
            return _hl2.sha256(("gold_customer_salt_" + pwd).encode()).hexdigest()
        pwd_hash = _pwd_hash2("Seller@Test123")
        try:
            conn_sa = sqlite3.connect(DB_PATH); cur_sa = conn_sa.cursor()
            cur_sa.execute("INSERT OR IGNORE INTO sellers (username, password_hash, name, role) VALUES (?, ?, ?, ?)",
                (test_agent, pwd_hash, "TestAgentP5", "agent"))
            conn_sa.commit()
            conn_sa.close()
            record("Phase5", "坐席注册", True)
        except Exception as e:
            record("Phase5", "坐席注册", False, str(e)[:50])

        code, body = http_post(f"{SELLER_BASE}/api/seller/login",
            json={"username":test_agent,"password":"Seller@Test123"}, timeout=10)
        if code == 200 and body.get("access_token"):
            agent_tok = body["access_token"]
            hdr_ag = {"Authorization": f"Bearer {agent_tok}"}
            record("Phase5", "坐席登录", True)

            # 消息中心-会话列表（可能因数据量大而慢）
            try:
                code, body = http_get(f"{SELLER_BASE}/api/seller/customers", headers=hdr_ag, timeout=30)
                record("Phase5", "消息中心-会话列表", code == 200, f"HTTP {code}")
            except Exception as e:
                record("Phase5", "消息中心-会话列表", False, f"超时: {type(e).__name__}")

            # 坐席发消息
            cphone = f"199{TS % 100000 + 777:05d}"
            code, body = http_post(f"{BUYER_BASE}/api/customer/start", json={"phone": cphone}, timeout=15)
            if code == 200 and body.get("session_id"):
                csid = body["session_id"]
                code, body = http_post(f"{SELLER_BASE}/api/seller/send",
                    json={"session_id":csid,"content":"[测试坐席A] ninhao, nin you shenme buchong?"},
                    headers=hdr_ag, timeout=15)
                record("Phase5", "坐席发送消息", code == 200, f"HTTP {code}")

                code, body = http_post(f"{SELLER_BASE}/api/seller/close-session",
                    params={"session_id": csid}, headers=hdr_ag, timeout=10)
                record("Phase5", "关闭会话", code == 200, f"HTTP {code}")

    # 实时统计
    code, body = http_get(f"{SELLER_BASE}/api/realtime/stats", timeout=10)
    record("Phase5", "实时统计API", code == 200, f"HTTP {code}")

    log("INFO", "卖家终端完成",
        f"健康{'OK' if results_health else 'FAIL'} 评价{'OK' if reviews_ok else 'FAIL'}")
    return results_health

# ═══════════════════════════════════════════════════════════════
# Phase 6: .env.master配置测试
# ═══════════════════════════════════════════════════════════════
def phase6_config_test(args):
    phase_title("Phase 6: .env.master配置测试 - 配置变更生效验证")
    env_file = r"D:\Ruitalk1\ruitalk_config\.env.master"
    if not os.path.exists(env_file):
        record("Phase6", ".env.master存在", False, "文件不存在"); return False
    record("Phase6", ".env.master存在", True)

    with open(env_file, "r", encoding="utf-8") as f:
        lines = f.readlines()

    critical = ["NEO4J_URI","NEO4J_USER","NEO4J_PASSWORD",
                "DEEPSEEK_API_KEY","DEEPSEEK_API_URL",
                "JWT_SECRET_KEY","SELLER_API_HOST","BUYER_PORT",
                "SHARED_DB_PATH","ALLOWED_ORIGINS"]
    missing = [k for k in critical if not any(l.strip().startswith(f"{k}=") for l in lines)]
    record("Phase6", "关键配置项", len(missing)==0,
        f"{len(critical)-len(missing)}/{len(critical)} " + (", ".join(missing) if missing else "全部存在"))

    ds_key = next((l.strip().split("=",1)[1] for l in lines if l.strip().startswith("DEEPSEEK_API_KEY=")),"")
    record("Phase6", "DeepSeek Key", ds_key.startswith("sk-"),
        f"{ds_key[:8]}..." if ds_key else "未配置")

    jwt_key = next((l.strip().split("=",1)[1] for l in lines if l.strip().startswith("JWT_SECRET_KEY=")),"")
    record("Phase6", "JWT密钥长度", len(jwt_key)>=32, f"{len(jwt_key)}字符")

    cors = next((l.strip() for l in lines if l.strip().startswith("ALLOWED_ORIGINS=")),"")
    record("Phase6", "CORS配置", "*" not in cors and bool(cors),
        cors.split("=",1)[1][:60] if "=" in cors else "未配置")

    # Neo4j 连接状态（使用 /health 避免 Neo4j 超时阻塞）
    try:
        code, body = http_get(f"{SELLER_BASE}/health", timeout=15)
        if code == 200 and isinstance(body, dict):
            cb = body.get("circuit_breakers", {})
            neo4j_state = cb.get("neo4j", {}).get("state", "unknown") if isinstance(cb, dict) else "unknown"
            neo4j_ok = neo4j_state == "closed"  # closed = healthy, open = tripped
            record("Phase6", "Neo4j连接", neo4j_ok,
                f"状态: {neo4j_state} (closed=健康, open=熔断)")
        else:
            record("Phase6", "Neo4j连接", False, f"health API HTTP {code}")
    except Exception as e:
        record("Phase6", "Neo4j连接", False, f"超时/错误: {type(e).__name__}")

    if ds_key and ds_key.startswith("sk-"):
        try:
            h = {"Authorization": f"Bearer {ds_key}", "Content-Type": "application/json"}
            pl = {"model":"deepseek-chat","messages":[{"role":"user","content":"hi"}],"max_tokens":5}
            r2 = requests.post("https://api.deepseek.com/v1/chat/completions",json=pl,headers=h,timeout=10)
            record("Phase6", "DeepSeek API", r2.status_code==200, f"HTTP {r2.status_code}")
        except Exception as e:
            record("Phase6", "DeepSeek API", False, str(e)[:80])
    else:
        record("Phase6", "DeepSeek API", False, "API Key无效")

    return True

# ═══════════════════════════════════════════════════════════════
# Phase 7: 清理
# ═══════════════════════════════════════════════════════════════
def phase7_cleanup():
    phase_title("Phase 7: 清理测试数据")
    conn = sqlite3.connect(DB_PATH); cur = conn.cursor()
    deleted = 0
    for table in ["messages","sessions","customers"]:
        try:
            if table == "sessions":
                cur.execute(f"DELETE FROM {table} WHERE customer_id LIKE '%test_prod_%' OR customer_id LIKE '%seller_agent_%'")
            else:
                cur.execute(f"DELETE FROM {table} WHERE phone LIKE '199%' OR customer_id LIKE '%test_prod_%' OR customer_id LIKE '%seller_agent_%'")
            deleted += cur.rowcount
        except Exception as e:
            pass
    try:
        cur.execute(f"DELETE FROM sellers WHERE username LIKE 'agent_prod_{TS}_%' OR username LIKE 'seller_agent_{TS}%'")
        deleted += cur.rowcount
    except: pass
    conn.commit(); conn.close()
    log("INFO", "清理完成", f"删除了 {deleted} 条记录")

    conn3 = sqlite3.connect(DB_PATH); cur3 = conn3.cursor()
    try:
        cur3.execute("SELECT COUNT(*) FROM customers WHERE phone LIKE '199%'")
        rem = cur3.fetchone()[0]
        record("Phase7", "数据验证", rem==0, f"残留{rem}条" if rem else "无残留")
    except Exception as e:
        record("Phase7", "数据验证", False, str(e)[:80])
    conn3.close()

# ═══════════════════════════════════════════════════════════════
# 生成报告
# ═══════════════════════════════════════════════════════════════
def generate_report(args):
    phase_title("综合测试报告")
    total, passed, failed = summarize()

    _safe_print(f"""
  测试时间:   {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
  测试模式:   {'快速模式' if args.quick else '完整模式'}
  总计:       {total} 项
  通过:       {passed} 项
  失败:       {failed} 项
  通过率:     {passed/max(1,total)*100:.1f}%
""")

    phases_d = {}
    for r in ALL_RESULTS:
        phases_d.setdefault(r.phase, {"ok":0,"fail":0,"items":[]})
        phases_d[r.phase]["items"].append(r)
        if r.passed: phases_d[r.phase]["ok"] += 1
        else: phases_d[r.phase]["fail"] += 1

    _safe_print("各阶段结果:")
    for phase, data in phases_d.items():
        icon = "PASS" if data["fail"]==0 else "FAIL"
        _safe_print(f"  [{icon}] {phase}: {data['ok']}/{data['ok']+data['fail']} 通过")
        for item in data["items"]:
            if not item.passed:
                _safe_print(f"       FAIL {item.name}: {item.detail}")

    _safe_print("\n生产就绪评估:")
    pf = {}
    for phase in ["Phase1","Phase2","Phase3","Phase4","Phase5","Phase6"]:
        pf[phase] = sum(1 for r in ALL_RESULTS if r.phase==phase and not r.passed)
    pf7 = sum(1 for r in ALL_RESULTS if r.phase=="Phase7" and not r.passed)

    checks = [
        ("AI并发无串台", pf["Phase1"]==0, f"{pf['Phase1']}项失败" if pf['Phase1'] else "全部通过"),
        ("人工客服1:1无串线", pf["Phase2"]==0, f"{pf['Phase2']}项失败" if pf['Phase2'] else "全部通过"),
        ("多语言支持", pf["Phase3"]==0, f"{pf['Phase3']}项失败" if pf['Phase3'] else "全部通过"),
        ("AI回复质量", pf["Phase4"]<=1, f"{pf['Phase4']}项失败" if pf['Phase4'] else "全部通过"),
        ("卖家终端功能", pf["Phase5"]<=2, f"{pf['Phase5']}项失败" if pf['Phase5'] else "全部通过"),
        (".env.master配置", pf["Phase6"]==0, f"{pf['Phase6']}项失败" if pf['Phase6'] else "全部通过"),
    ]
    critical_ok = all(ok for _,ok,_ in checks)
    for name, ok, detail in checks:
        icon = "PASS" if ok else "FAIL"
        status = "达标" if ok else "待修复"
        _safe_print(f"  [{icon}] {name}: {status} - {detail}")

    _safe_print("")
    if critical_ok:
        _safe_print("结论: 核心功能测试通过，系统可用于生产环境部署！")
    else:
        _safe_print("结论: 以下功能存在问题，需要修复:")
        for name, ok, detail in checks:
            if not ok:
                _safe_print(f"  - {name}: {detail}")

    fails = [r for r in ALL_RESULTS if not r.passed]
    if fails:
        _safe_print(f"\n详细失败项 ({len(fails)} 项):")
        for r in fails:
            _safe_print(f"  [{r.phase}] {r.name}: {r.detail}")

    report_file = f"D:\\Ruitalk1\\tests\\comprehensive_test_report_{TS}.json"
    try:
        with open(report_file,"w",encoding="utf-8") as f:
            json.dump({
                "timestamp": datetime.now().isoformat(),
                "summary": {"total":total,"passed":passed,"failed":failed,
                            "pass_rate":f"{passed/max(1,total)*100:.1f}%"},
                "checks": [{"name":n,"ok":o,"detail":d} for n,o,d in checks],
                "results": [r.to_dict() for r in ALL_RESULTS],
            }, f, ensure_ascii=False, indent=2)
        _safe_print(f"\n报告已保存: {report_file}")
    except Exception as e:
        warn(f"报告保存失败: {e}")

    return total, passed, failed

# ═══════════════════════════════════════════════════════════════
# 主函数
# ═══════════════════════════════════════════════════════════════
def main():
    parser = argparse.ArgumentParser(description="Ruitalk综合生产测试")
    parser.add_argument("--skip-ai", action="store_true", help="跳过AI并发压测")
    parser.add_argument("--skip-seller", action="store_true", help="跳过卖家终端测试")
    parser.add_argument("--quick", action="store_true", help="快速模式")
    args = parser.parse_args()

    _safe_print(f"""
╔══════════════════════════════════════════════════════════╗
║         Ruitalk 综合生产测试  v1.0                      ║
║         测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}                              ║
╚══════════════════════════════════════════════════════════╝
""")

    phase_title("前置检查 - 服务可用性")
    for name, base in [("卖家系统(8000)", SELLER_BASE), ("买方系统(8002)", BUYER_BASE)]:
        try:
            code, _ = http_get(f"{base}/health", timeout=5)
            log("OK" if code==200 else "FAIL", name, f"HTTP {code}")
        except:
            log("FAIL", name, "无法连接")

    cleanup()

    p1_ok = True
    if not args.skip_ai:
        p1_ok = phase1_ai_stress_test(args)
    else:
        log("INFO", "跳过Phase1(AI压测)", "--skip-ai")

    p2_ok = phase2_human_agent_test(args) if not args.skip_ai else True
    p3_ok = phase3_multilingual_test(args) if not args.skip_ai else True
    p4_ok = phase4_ai_quality_test(args) if not args.skip_ai else True
    p5_ok = phase5_seller_terminal_test(args) if not args.skip_seller else True
    p6_ok = phase6_config_test(args)

    phase7_cleanup()
    total, passed, failed = generate_report(args)

    return 0 if failed == 0 else 1

if __name__ == "__main__":
    sys.exit(main())
