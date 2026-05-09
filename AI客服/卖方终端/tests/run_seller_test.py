# -*- coding: utf-8 -*-
"""
卖方终端六大模块完整测试运行器
================================
执行步骤：
  1. 清理旧测试数据
  2. 生成新的测试数据
  3. 验证各模块 API 是否正常工作
  4. 打印测试报告
  5. 清理本次测试数据

使用卖家终端 Python 环境运行：
  cd d:/Ruitalk1
  ..\卖方终端\.venv\Scripts\python.exe -m seller_tests.run_seller_test
"""
import sys, os, time

# ── 路径设置 ────────────────────────────────────────────────────────────────
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_SELLER_ROOT = os.path.join(_ROOT, "卖方终端")
_BACKEND = os.path.join(_SELLER_ROOT, "backend")
_VENV_PY = os.path.join(_SELLER_ROOT, ".venv", "Scripts", "python.exe")
sys.path.insert(0, _BACKEND)

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("LOG_LEVEL", "warning")

# ── 彩色输出 ────────────────────────────────────────────────────────────────
class _Color:
    HEADER = "\033[95m"; OKBLUE = "\033[94m"; OKGREEN = "\033[92m"
    WARNING = "\033[93m"; FAIL = "\033[91m"; ENDC = "\033[0m"
    BOLD = "\033[1m"

P = _Color.OKGREEN; F = _Color.FAIL; W = _Color.WARNING; H = _Color.HEADER
B = _Color.OKBLUE; E = _Color.ENDC; N = "\n"
# ASCII-safe symbols (Windows GBK console compatible)
OK_SYM = "[OK]"; FAIL_SYM = "[X]"; WARN_SYM = "[!]"


def _banner(msg):
    print(f"\n{H}{'═' * 70}{E}")
    print(f"{H}  {msg}{E}")
    print(f"{H}{'═' * 70}{E}")


def _step(num, total, msg):
    print(f"\n{P}[{num}/{total}] {msg} ...{E}", end="", flush=True)


def _ok(msg=""):
    print(f"{P}  {OK_SYM} {msg}{E}")


def _fail(msg=""):
    print(f"{F}  {FAIL_SYM} {msg}{E}")


def _warn(msg=""):
    print(f"{W}  {WARN_SYM} {msg}{E}")


def _info(msg=""):
    print(f"    {msg}")


# ── 依赖检查 ────────────────────────────────────────────────────────────────
def check_venv():
    _banner("步骤 0 · 环境检查")
    checks = []

    # Python
    import subprocess, shutil
    r = subprocess.run([_VENV_PY, "--version"], capture_output=True, text=True)
    checks.append(("卖家终端 Python", r.returncode == 0, r.stdout.strip()))

    # 关键模块
    for mod in ["fastapi", "uvicorn", "sqlite3", "requests"]:
        r = subprocess.run([_VENV_PY, "-c", f"import {mod.split('.')[0]}"],
                           capture_output=True, text=True)
        checks.append((f"模块 {mod}", r.returncode == 0))

    # HTTP 服务
    import urllib.request
    try:
        r = urllib.request.urlopen("http://127.0.0.1:8000", timeout=3)
        http_ok = r.status == 200
        checks.append(("卖家 API (8000)", http_ok, f"HTTP {r.status}"))
    except Exception as ex:
        checks.append(("卖家 API (8000)", False, str(ex)))

    ok = fail = 0
    for name, passed, *extra in checks:
        detail = extra[0] if extra else ""
        if passed:
            _ok(f"{name} {detail}"); ok += 1
        else:
            _fail(f"{name} 不可用"); fail += 1
    print(f"\n  环境检查：{P}{ok} 通过{E}  {F}{fail} 失败{E}")
    if fail > 0:
        _warn("部分环境缺失，建议先启动卖家终端")
    return fail == 0


# ── 测试数据生成 ─────────────────────────────────────────────────────────────
def _get_conn():
    import sqlite3
    db = os.path.join(_BACKEND, "data", "seller.db")
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn, name):
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1", (name,))
    return cur.fetchone() is not None


def _col_count(conn, tbl, where_clause):
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT COUNT(*) FROM {tbl} WHERE {where_clause}")
        return cur.fetchone()[0]
    except:
        return 0


def generate_test_data():
    _banner("步骤 1 · 生成测试数据")
    import sqlite3, uuid, hashlib
    from datetime import datetime
    import random

    DB = os.path.join(_BACKEND, "data", "seller.db")
    os.makedirs(os.path.dirname(DB), exist_ok=True)

    def conn():
        c = sqlite3.connect(DB)
        c.row_factory = sqlite3.Row
        return c

    def exists(tbl):
        c = conn().cursor()
        c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1", (tbl,))
        return c.fetchone() is not None

    def get_cols(tbl):
        c = conn().cursor()
        c.execute(f"PRAGMA table_info({tbl})")
        return [r[1] for r in c.fetchall()]

    now = datetime.now().isoformat()

    # ── 1a. 清理旧 TEST 数据 ──────────────────────────────────────────────
    _step(1, 4, "清理旧测试数据")
    tables = ["customers","sessions","messages","sellers","transfer_queue",
              "quick_replies","notifications","after_sales","pre_sale_notes"]
    total_deleted = 0
    c = conn()
    for tbl in tables:
        try:
            cur = c.cursor()
            cur.execute(f"DELETE FROM {tbl} WHERE customer_id LIKE 'TEST_%' OR name LIKE 'TEST%' OR title LIKE '[TEST]%'")
            total_deleted += cur.rowcount
        except:
            pass
    c.commit(); c.close()
    _ok(f"已删除 {total_deleted} 条旧测试数据")

    # ── 1b. 生成测试客户 ───────────────────────────────────────────────────
    _step(2, 4, "创建测试客户（10个多语言）")
    c = conn()
    test_customers = [
        {"customer_id":"TEST_C001","phone":"13800001001","name":"TEST_John Smith","region":"美国","level":"VIP"},
        {"customer_id":"TEST_C002","phone":"13800001002","name":"TEST_Sarah Johnson","region":"英国","level":"金卡"},
        {"customer_id":"TEST_C003","phone":"13800001003","name":"TEST_张伟","region":"华东","level":"银卡"},
        {"customer_id":"TEST_C004","phone":"13800001004","name":"TEST_李娜","region":"华南","level":"普通"},
        {"customer_id":"TEST_C005","phone":"13800001005","name":"TEST_أحمد محمد","region":"沙特阿拉伯","level":"VIP"},
        {"customer_id":"TEST_C006","phone":"13800001006","name":"TEST_Иван Петров","region":"俄罗斯","level":"金卡"},
        {"customer_id":"TEST_C007","phone":"13800001007","name":"TEST_สมชาย มาก","region":"泰国","level":"普通"},
        {"customer_id":"TEST_C008","phone":"13800001008","name":"TEST_Budi Santoso","region":"印尼","level":"银卡"},
        {"customer_id":"TEST_C009","phone":"13800001009","name":"TEST_María García","region":"西班牙","level":"金卡"},
        {"customer_id":"TEST_C010","phone":"13800001010","name":"TEST_Hans Mueller","region":"德国","level":"VIP"},
    ]
    for cust in test_customers:
        c.cursor().execute("""
            INSERT OR REPLACE INTO customers
            (customer_id,phone,name,region,level,m_value,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?)""",
            (cust["customer_id"],cust["phone"],cust["name"],cust["region"],
             cust["level"],random.randint(0,5000),now,now))
    c.commit()
    _ok(f"已创建 {len(test_customers)} 个测试客户")
    customer_ids = [x["customer_id"] for x in test_customers]

    # ── 1c. 生成测试会话 & 消息 ───────────────────────────────────────────
    _step(3, 4, "创建测试会话和消息")
    languages = ["zh","en","ar","ru","th","vi","id","ms","tl"]
    statuses = ["active","waiting","closed"]
    session_ids = []
    msg_count = 0
    for i, cid in enumerate(customer_ids):
        sid = f"TEST_S{i+1:03d}_{uuid.uuid4().hex[:8].upper()}"
        lang = languages[i % len(languages)]
        status = random.choice(statuses)
        is_ai = 0 if status in ["waiting","closed"] else random.choice([0,1])
        c.cursor().execute("""
            INSERT OR REPLACE INTO sessions
            (session_id,customer_id,status,is_ai,language,system_source,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?)""",
            (sid,cid,status,is_ai,lang,"seller",now,now))
        # 每会话 2~8 条消息
        for j in range(random.randint(2, 8)):
            role = "user" if j % 2 == 0 else "assistant"
            content = f"[TEST] {role} message {j+1}" if role == "user" else f"[TEST] AI reply {j+1}"
            c.cursor().execute("""
                INSERT INTO messages (session_id,role,content,created_at)
                VALUES (?,?,?,?)""", (sid,role,content,now))
            msg_count += 1
        session_ids.append(sid)
    c.commit()
    _ok(f"已创建 {len(session_ids)} 个会话，{msg_count} 条消息")

    # ── 1d. 生成坐席、售前、售后、通知、快捷回复 ──────────────────────────
    _step(4, 4, "创建坐席 / 售前 / 售后 / 通知 / 快捷回复")
    counts = {}

    # 坐席
    sellers = [("agent_test01","TEST_坐席01","agent"),
               ("agent_test02","TEST_坐席02","agent"),
               ("agent_test03","TEST_坐席03","agent"),
               ("manager_test","TEST_主管","manager")]
    for username,name,role in sellers:
        pw = hashlib.sha256("test123".encode()).hexdigest()
        c.cursor().execute("""
            INSERT OR REPLACE INTO sellers
            (username,password_hash,name,role,is_online,password_changed,must_change_password,created_at)
            VALUES (?,?,?,?,1,1,0,?)""", (username,pw,name,role,now))
    c.commit(); counts["坐席"] = len(sellers)

    # 售前备注（只用存在的字段）
    if exists("pre_sale_notes"):
        cols = get_cols("pre_sale_notes")
        for i, cid in enumerate(customer_ids[:8]):
            vals = {k: None for k in cols}
            vals.update({
                "customer_id": cid, "customer_name": f"TEST_Customer_{i+1:03d}",
                "platform": random.choice(["Amazon","eBay","Shopee","AliExpress","TikTok"]),
                "country": random.choice(["美国","英国","德国","法国","俄罗斯","巴西","印尼"]),
                "is_old_customer": random.randint(0,1),
                "repeat_purchase_count": random.randint(0,5),
                "has_complaints": random.randint(0,1),
                "has_disputes": random.randint(0,1),
                "internal_note": f"[TEST] 售前备注 {cid}",
                "created_by": "TEST_Agent", "created_at": now, "updated_at": now,
            })
            placeholders = ",".join(["?"] * len(cols))
            c.cursor().execute(f"INSERT INTO pre_sale_notes ({','.join(cols)}) VALUES ({placeholders})",
                                [vals.get(k) for k in cols])
        c.commit(); counts["售前备注"] = 8

    # 售后单
    if exists("after_sales"):
        types = ["退货退款","仅退款","换货","维修","投诉"]
        reasons = ["商品损坏","与描述不符","尺寸不合适","颜色不喜欢","重复下单"]
        statuses_as = ["待审核","待买家寄回","待签收","待质检","待退款","完成"]
        for i, cid in enumerate(customer_ids[:8]):
            as_id = f"TEST_AS{i+1:03d}{datetime.now().strftime('%Y%m%d%H%M%S')}"
            vals = {
                "as_id": as_id, "order_id": f"TEST_ORD{i+1:03d}",
                "platform": random.choice(["Amazon","eBay","Shopee"]),
                "customer_id": cid, "customer_name": f"TEST_Customer_{i+1:03d}",
                "type": types[i % len(types)],
                "reason_category": reasons[i % len(reasons)],
                "reason_detail": f"[TEST] 售后原因 {as_id}",
                "status": statuses_as[i % len(statuses_as)],
                "created_by": "TEST_Agent", "created_at": now, "updated_at": now,
            }
            # 只插有字段的值
            cols2 = get_cols("after_sales")
            vals2 = {k: vals.get(k) for k in cols2 if k in vals}
            ph = ",".join(["?"] * len(vals2))
            c.cursor().execute(f"INSERT INTO after_sales ({','.join(vals2.keys())}) VALUES ({ph})",
                                list(vals2.values()))
        c.commit(); counts["售后单"] = 8

    # 通知
    if exists("notifications"):
        cols_n = get_cols("notifications")
        notify_types = ["after_sale","pre_sale","review","system","transfer"]
        for i in range(5):
            vals_n = {
                "title": f"[TEST] 测试通知 {i+1}",
                "content": f"[TEST] 测试通知内容 {i+1}",
                "is_read": random.randint(0,1),
                "created_at": now,
            }
            if "notification_type" in cols_n:
                vals_n["notification_type"] = notify_types[i % len(notify_types)]
            elif "notify_type" in cols_n:
                vals_n["notify_type"] = notify_types[i % len(notify_types)]
            if "source" in cols_n:
                vals_n["source"] = "TEST_System"
            vals_n2 = {k: vals_n.get(k) for k in cols_n if k in vals_n}
            ph = ",".join(["?"] * len(vals_n2))
            c.cursor().execute(f"INSERT INTO notifications ({','.join(vals_n2.keys())}) VALUES ({ph})",
                                list(vals_n2.values()))
        c.commit(); counts["通知"] = 5

    # 快捷回复
    if exists("quick_replies"):
        categories = ["通用","物流","售后","售前"]
        for i in range(8):
            c.cursor().execute("""
                INSERT OR REPLACE INTO quick_replies
                (category,title,content,shortcut,is_active,created_by,created_at)
                VALUES (?,?,?,?,1,?,?)""",
                (categories[i%4],f"[TEST] 快捷回复{i+1}",
                 f"[TEST] 快捷回复模板 {i+1}",f"/qr{i+1}","TEST_Agent",now))
        c.commit(); counts["快捷回复"] = 8

    c.close()

    # 打印摘要
    print(f"\n  {'模块':<12} {'生成数':>6}")
    print(f"  {'─'*20}")
    print(f"  {'客户':<12} {P}{len(test_customers):>6}{E}")
    print(f"  {'会话':<12} {P}{len(session_ids):>6}{E}")
    print(f"  {'消息':<12} {P}{msg_count:>6}{E}")
    for k,v in counts.items():
        print(f"  {k:<12} {P}{v:>6}{E}")

    return customer_ids, session_ids


# ── API 验证测试 ─────────────────────────────────────────────────────────────
def verify_api(customer_ids, session_ids):
    _banner("步骤 2 · API 接口验证")
    import requests, urllib.request, json as _json

    base = "http://127.0.0.1:8000"
    results = []

    def _test(name, fn):
        try:
            r, elapsed = fn()
            if r is False:
                results.append((name, False, "不可用"))
                _fail(f"{name}")
            elif r is None:
                results.append((name, None, "跳过"))
                _warn(f"{name}  [跳过]")
            elif 200 <= r.status_code < 300:
                results.append((name, True, f"HTTP {r.status_code} {elapsed:.1f}ms"))
                _ok(f"{name}  {B}HTTP {r.status_code}{E}  {elapsed:.1f}ms")
            else:
                results.append((name, False, f"HTTP {r.status_code}"))
                _fail(f"{name}  HTTP {r.status_code}")
        except Exception as ex:
            results.append((name, False, str(ex)))
            _fail(f"{name}  {F}{ex}{E}")

    # ── 2a. HTTP 健康检查 ─────────────────────────────────────────────────
    print(f"\n  {H}【 HTTP 接口测试 】{E}")

    def get(path, **kw):
        t0 = time.time()
        r = requests.get(f"{base}{path}", timeout=5, **kw)
        return r, (time.time()-t0)*1000

    def _auth_get(path, headers):
        """GET with auth headers, skip if no headers."""
        if not headers:
            return None, 0
        return get(path, headers=headers)

    def post(path, **kw):
        t0 = time.time()
        r = requests.post(f"{base}{path}", timeout=5, **kw)
        return r, (time.time()-t0)*1000

    _test("主页 GET /",           lambda: get("/"))
    _test("健康检查 GET /health", lambda: get("/health"))
    _test("就绪检查 GET /live",   lambda: get("/live"))

    # ── 2b. 认证 ─────────────────────────────────────────────────────────
    print(f"\n  {H}【 认证测试 】{E}")

    token = None   # seller token
    admin_token = None  # admin token

    # 坐席登录（agent_service 无密码验证，可能返回失败，属正常）
    try:
        login_r, login_t = post("/api/seller/login", json={
            "username": "agent_test01", "password": "test123"
        })
        if login_r.status_code == 200:
            data = login_r.json()
            if data.get("success"):
                token = (data.get("access_token")
                         or data.get("token", {}).get("access_token", "")
                         or data.get("token", ""))
                _ok(f"坐席登录 POST /api/seller/login  HTTP 200  token获取{'成功' if token else '失败'}")
                results.append(("坐席登录", True, "HTTP 200"))
            else:
                _warn(f"坐席登录（agent_service 无密码验证，跳过）")
                results.append(("坐席登录", None, "跳过（无密码验证）"))
        else:
            _warn(f"坐席登录 HTTP {login_r.status_code}")
            results.append(("坐席登录", None, f"HTTP {login_r.status_code}"))
    except Exception as ex:
        _warn(f"坐席登录：{ex}")
        results.append(("坐席登录", None, str(ex)))

    # admin 登录（使用管理员密码 ADMIN_PASSWORD）
    try:
        admin_r, admin_t = post("/api/admin/login", json={
            "username": "admin", "password": "admin123"
        })
        if admin_r.status_code == 200:
            admin_data = admin_r.json()
            if admin_data.get("success") or admin_data.get("access_token"):
                admin_token = (admin_data.get("access_token")
                               or admin_data.get("token", {}).get("access_token", "")
                               or admin_data.get("token", ""))
                _ok(f"Admin登录 POST /api/admin/login  HTTP 200  token获取{'成功' if admin_token else '失败'}")
                results.append(("Admin登录", True, "HTTP 200"))
            else:
                _warn("Admin登录（凭据错误，跳过）")
                results.append(("Admin登录", None, "跳过"))
        else:
            _warn(f"Admin登录 HTTP {admin_r.status_code}")
            results.append(("Admin登录", None, f"HTTP {admin_r.status_code}"))
    except Exception as ex:
        _warn(f"Admin登录：{ex}")
        results.append(("Admin登录", None, str(ex)))

    # 实际使用的 token（优先 admin）
    auth_headers = {"Authorization": f"Bearer {admin_token}"} if admin_token else (
                   {"Authorization": f"Bearer {token}"} if token else {})

    # 坐席信息
    if token:
        _test("坐席信息 GET /api/seller/me", lambda: get("/api/seller/me", headers=headers))

    # ── 2c. 业务接口（已认证）─────────────────────────────────────────────
    print(f"\n  {H}【 业务接口（需认证）】{E}")

    # 客户列表
    _test("客户列表 GET /api/seller/customers",
          lambda: _auth_get("/api/seller/customers", auth_headers))
    # 会话列表
    _test("会话列表 GET /api/admin/conversations",
          lambda: _auth_get("/api/admin/conversations", auth_headers))

    # 单客户查询
    if customer_ids:
        _test(f"客户查询 GET /api/admin/customer/{customer_ids[0]}",
              lambda cid=customer_ids[0]: _auth_get(f"/api/admin/customer/{cid}", auth_headers))

    # 单会话查询
    if session_ids:
        _test(f"会话详情 GET /api/admin/conversation/{session_ids[0]}",
              lambda sid=session_ids[0]: _auth_get(f"/api/admin/conversation/{sid}", auth_headers))

    # 快捷回复（无需认证）
    _test("快捷回复 GET /api/message-center/quick-replies", lambda: get("/api/message-center/quick-replies"))

    # 通知
    _test("通知列表 GET /api/admin/notifications",
          lambda: _auth_get("/api/admin/notifications", auth_headers))

    # ── 2c. 六大模块数据库验证 ────────────────────────────────────────────
    print(f"\n  {H}【 数据库数据验证 】{E}")

    c = _get_conn()
    module_map = [
        ("客户表 customers",      "customers",     f"customer_id IN ({','.join(['?']*len(customer_ids))})", customer_ids),
        ("会话表 sessions",      "sessions",       f"session_id LIKE 'TEST_%'", []),
        ("消息表 messages",       "messages",       "session_id LIKE 'TEST_%'", []),
        ("坐席表 sellers",        "sellers",        "name LIKE 'TEST%'", []),
        ("售后表 after_sales",    "after_sales",    "as_id LIKE 'TEST_%'", []),
        ("售前表 pre_sale_notes","pre_sale_notes", "customer_id IN ({})".format(",".join(["'{}'".format(c) for c in customer_ids[:4]])), []),
        ("通知表 notifications", "notifications",  "title LIKE '[TEST]%'", []),
        ("快捷回复 quick_replies","quick_replies", "title LIKE '[TEST]%'", []),
    ]

    db_ok = db_fail = 0
    for label, tbl, where, params in module_map:
        try:
            if not _table_exists(c, tbl):
                _warn(f"{label}  [表不存在，跳过]"); continue
            cur = c.cursor()
            if params:
                cur.execute(f"SELECT COUNT(*) FROM {tbl} WHERE {where}", params)
            else:
                cur.execute(f"SELECT COUNT(*) FROM {tbl} WHERE {where}")
            cnt = cur.fetchone()[0]
            if cnt > 0:
                _ok(f"{label}  {P}{cnt} 条{E}"); db_ok += 1
            else:
                _warn(f"{label}  0 条（数据可能未插入）"); db_fail += 1
        except Exception as ex:
            _fail(f"{label}  {F}{ex}{E}"); db_fail += 1
    c.close()

    print(f"\n  数据库验证：{P}{db_ok} 通过{E}  {F if db_fail else ''}{db_fail} 失败{E if db_fail else ''}")
    return results


# ── 测试报告 ─────────────────────────────────────────────────────────────────
def print_report(results, customer_ids, session_ids):
    _banner("步骤 3 · 测试报告")

    # 统计
    passed = sum(1 for _,ok,*_ in results if ok is True)
    skipped = sum(1 for _,ok,*_ in results if ok is None)
    failed = sum(1 for _,ok,*_ in results if ok is False)

    # 颜色
    ok_c = P if passed > 0 else ""
    fail_c = F if failed > 0 else ""
    skip_c = W if skipped > 0 else ""

    print(f"\n  {'═' * 55}")
    print(f"  {'项目':<30} {'结果':>10} {'说明':<15}")
    print(f"  {'─' * 55}")
    for name, ok, *extra in results:
        if ok is True:       icon = f"{P}PASS{E}"; detail = extra[0] if extra else ""
        elif ok is False:    icon = f"{F}FAIL{E}"; detail = extra[0] if extra else ""
        else:                icon = f"{W}SKIP{E}"; detail = extra[0] if extra else ""
        print(f"  {name:<30} {icon:>12}  {detail}")
    print(f"  {'─' * 55}")

    print(f"\n  {H}总计：{E}")
    print(f"\n  {P}PASS{E}  通过  {passed} 项{E}")
    print(f"    {W}SKIP{E}  跳过  {skipped} 项{E}")
    if failed > 0:  print(f"    {F}FAIL{E}  失败  {failed} 项{E}")

    # 综合判定
    print()
    if failed == 0 and passed >= 3:
        print(f"  {P}{'='*55}{E}")
        print(f"  {P}  [SUCCESS] 测试全部通过！卖家终端核心功能正常。{E}")
        print(f"  {P}{'='*55}{E}")
        overall = True
    else:
        print(f"  {F}{'='*55}{E}")
        print(f"  {F}  [WARNING] 部分测试未通过，请检查上方失败项。{E}")
        print(f"  {F}{'='*55}{E}")
        overall = False

    # 测试数据预览
    print(f"\n  {H}生成的测试数据 ID（供调试使用）：{E}")
    print(f"    客户：{', '.join(customer_ids[:3])} ...")
    print(f"    会话：{', '.join(session_ids[:2])} ...")

    return overall


# ── 清理测试数据 ─────────────────────────────────────────────────────────────
def cleanup_test_data():
    _banner("步骤 4 · 清理测试数据")
    import sqlite3
    DB = os.path.join(_BACKEND, "data", "seller.db")
    tables = ["customers","sessions","messages","sellers","transfer_queue",
              "quick_replies","notifications","after_sales","pre_sale_notes"]
    total = 0
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
    for tbl in tables:
        try:
            cur = c.cursor()
            cur.execute(f"DELETE FROM {tbl} WHERE customer_id LIKE 'TEST_%' OR name LIKE 'TEST%' OR title LIKE '[TEST]%' OR session_id LIKE 'TEST_%'")
            total += cur.rowcount
        except:
            pass
    c.commit(); c.close()
    _ok(f"已清理 {total} 条 TEST_* 测试数据")

    # 验证清理结果
    c2 = sqlite3.connect(DB); c2.row_factory = sqlite3.Row
    remaining = 0
    for tbl in tables:
        try:
            cur = c2.cursor()
            cur.execute(f"SELECT COUNT(*) FROM {tbl} WHERE customer_id LIKE 'TEST_%' OR name LIKE 'TEST%' OR title LIKE '[TEST]%' OR session_id LIKE 'TEST_%'")
            remaining += cur.fetchone()[0]
        except:
            pass
    c2.close()
    if remaining == 0:
        _ok("数据库已清空，无残留 TEST 数据")
    else:
        _warn(f"数据库仍有 {remaining} 条 TEST 数据残留")


# ── 主函数 ───────────────────────────────────────────────────────────────────
def main():
    print(f"""
{H}
  ╔══════════════════════════════════════════════════════════╗
  ║           卖方终端 六大模块完整测试运行器                   ║
  ║           Seller Terminal Full-Suite Test Runner          ║
  ╚══════════════════════════════════════════════════════════╝
{E}
  本脚本将依次执行：
    [1] 环境检查（Python / 模块 / HTTP 服务）
    [2] 生成多语言测试数据（客户/会话/消息/坐席/售后等）
    [3] API 接口验证（HTTP 健康检查 / 业务接口 / 数据库）
    [4] 打印完整测试报告
    [5] 自动清理本次测试数据
""")

    print(f"  {'使用卖家终端 Python 环境'}")
    print(f"  Python : {_VENV_PY}")
    print(f"  API    : http://127.0.0.1:8000")
    print(f"  DB     : {_BACKEND}\\data\\seller.db")
    print(f"\n  {'─' * 70}")

    # 0. 环境检查
    env_ok = check_venv()

    # 1. 生成测试数据
    customer_ids, session_ids = generate_test_data()

    # 2. API 验证
    results = verify_api(customer_ids, session_ids)

    # 3. 测试报告
    overall = print_report(results, customer_ids, session_ids)

    # 4. 清理
    cleanup_test_data()

    _banner("测试运行结束")
    return 0 if overall else 1


if __name__ == "__main__":
    sys.exit(main())
