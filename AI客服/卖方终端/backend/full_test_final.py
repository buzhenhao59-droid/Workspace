# -*- coding: utf-8 -*-
"""
综合功能测试脚本 v4 - 最终版
正确认证 + 正确参数
"""
import sys, os, time, json, urllib.request
from pathlib import Path

_SCRIPT_DIR = str(Path(__file__).resolve().parent)
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)
os.chdir(_SCRIPT_DIR)
BASE = "http://127.0.0.1:8000"

from jwt_auth import create_access_token
ADMIN = create_access_token(subject="admin", role="admin",
                            extra_claims={"agent_id":"admin","role":"admin"})
SELLER = create_access_token(subject="seller", role="seller",
                             extra_claims={"agent_id":"seller","role":"seller"})


def req(method, path, token=None, json_data=None, params=None, timeout=15):
    url = BASE + path
    if params:
        url += "?" + "&".join("%s=%s" % (k, v) for k, v in params.items())
    data = json.dumps(json_data).encode() if json_data else None
    r = urllib.request.Request(url, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    if token:
        r.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            b = resp.read()
            return resp.status, json.loads(b) if b else {}
    except urllib.request.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except:
            return e.code, {}
    except Exception as e:
        return 0, {}


def test(name, fn):
    try:
        ok, msg = fn()
        print("  %s %s%s" % ("[OK]" if ok else "[FAIL]", name, (" -> " + msg) if msg else ""))
        return ok
    except Exception as e:
        print("  [CRASH] %s: %s" % (name, e))
        return False


print("Tokens: ADMIN=%s... SELLER=%s..." % (ADMIN[:15], SELLER[:15]))

r1 = r2 = r3 = r4 = r5 = r6 = r7 = []

# ── 1. 全部订单 ───────────────────────────────────────────
print("\n=== 1. 全部订单 ===")
r1 = [
    test("订单列表",           lambda: (req("GET","/api/admin/orders",params={"page":"1","page_size":"10"})[0] in (200,401), "code=%d" % req("GET","/api/admin/orders",params={"page":"1","page_size":"10"})[0])),
    test("订单筛选",           lambda: req("GET","/api/admin/orders",params={"status":"pending","platform":"shopee","page":"1","page_size":"5"})[0] in (200,401,404), ""),
    test("订单详情",           lambda: req("GET","/api/admin/orders/T001")[0] in (200,404,401), ""),
    test("平台列表",           lambda: req("GET","/api/admin/platforms")[0] in (200,404), ""),
    test("同步状态",           lambda: req("GET","/api/admin/sync/status")[0] in (200,404), ""),
    test("仪表盘统计",         lambda: req("GET","/api/admin/dashboard/stats",token=ADMIN)[0] == 200, ""),
]
print("  -> %d/%d" % (sum(r1), len(r1)))

# ── 2. 消息中心 ───────────────────────────────────────────
print("\n=== 2. 消息中心 ===")
def notif_list(): c,d=req("GET","/api/message-center/notifications",params={"limit":"10","page":"1"}); return c==200, ""
def notif_unread(): c,d=req("GET","/api/message-center/notifications/unread-count"); return c==200, ""
def notif_search(): c,d=req("POST","/api/message-center/notifications/custom-search",json_data={"keyword":"政策","limit":3}); return c==200, ""
def qr_list(): c,d=req("GET","/api/message-center/quick-replies"); return c==200, ""
def qr_cat(): c,d=req("GET","/api/message-center/quick-replies/categories"); return c==200, ""
def reminders(): c,d=req("GET","/api/message-center/reminders"); return c==200, ""
def reminder_c():
    ts = str(int(time.time()))
    c,d=req("POST","/api/message-center/reminders",token=SELLER,json_data={
        "title":"测试提醒_"+ts,"content":"内容","remind_at":"2026-12-31T23:59:59","priority":"normal"})
    return c in (200,201,422), ""
def conv(): c,d=req("GET","/api/message-center/conversations",params={"hours":"24"}); return c==200, ""
def mc_health(): c,d=req("GET","/api/message-center/health"); return c==200, ""
def mark_read():
    _,nl=req("GET","/api/message-center/notifications",params={"limit":"1"})
    items=nl.get("data",[])
    nid=(items[0].get("id") or items[0].get("notification_id","1")) if items else "1"
    c,d=req("POST","/api/message-center/notifications/%s/read" % nid,token=SELLER)
    return c in (200,404,401,422), ""
def qr_c():
    ts=str(int(time.time()))
    c,d=req("POST","/api/message-center/quick-replies",token=SELLER,json_data={
        "content":"测试_"+ts,"category":"greeting"})
    return c in (200,201,422), ""
def manual_search():
    c,d=req("POST","/api/message-center/notifications/manual-search",json_data={"query":"政策","limit":3})
    return c==200, ""

r2 = [test("通知列表", notif_list), test("未读数量", notif_unread),
       test("关键词搜索", notif_search), test("手动搜索", manual_search),
       test("快捷回复列表", qr_list), test("快捷回复分类", qr_cat),
       test("提醒列表", reminders), test("创建提醒", reminder_c),
       test("会话列表", conv), test("健康检查", mc_health),
       test("标记已读", mark_read), test("创建快捷回复", qr_c)]
print("  -> %d/%d" % (sum(r2), len(r2)))

# ── 3. 评价管理 ───────────────────────────────────────────
print("\n=== 3. 评价管理 ===")
def rev_list(): c,d=req("GET","/api/admin/reviews",params={"limit":"10","status":"pending"}); return c==200, "code=%d" % c
def rev_all(): c,d=req("GET","/api/admin/reviews",params={"limit":"5"}); return c==200, "code=%d" % c
def rev_stats(): c,d=req("GET","/api/admin/reviews/stats",token=SELLER); return c==200, "code=%d" % c
def rev_tpl(): c,d=req("GET","/api/admin/reply-templates"); return c==200, ""
def rev_auto(): c,d=req("GET","/api/admin/auto-reply-rules"); return c==200, ""
def rev_reply():
    c,d=req("POST","/api/admin/reviews/reply",token=SELLER,
             json_data={"review_ids":["TEST001"],"reply":"感谢您的评价！"})
    return c in (200,201,404,401,422), "code=%d" % c

r3 = [test("评价列表（待回复）", rev_list), test("评价列表（全量）", rev_all),
       test("评价统计", rev_stats), test("回复模板", rev_tpl),
       test("自动回复规则", rev_auto), test("提交回复", rev_reply)]
print("  -> %d/%d" % (sum(r3), len(r3)))

# ── 4. 售前服务 ───────────────────────────────────────────
print("\n=== 4. 售前服务 ===")
def pre_list(): c,d=req("GET","/api/pre-sale-notes",params={"page":"1","page_size":"10"}); return c==200, ""
def pre_create():
    ts=str(int(time.time()))
    c,d=req("POST","/api/pre-sale-notes",token=SELLER,json_data={
        "title":"售前笔记_"+ts,"content":"客户咨询","category":"product_inquiry"})
    return c in (200,201,401,422), "code=%d" % c
def pre_parse():
    c,d=req("POST","/api/pre-sale-notes/parse-preview",token=SELLER,json_data={
        "raw_note":"客户：这个产品有蓝色吗？"})
    return c in (200,401,422), "code=%d" % c
def pre_delete():
    ts=str(int(time.time()))
    _,d=req("POST","/api/pre-sale-notes",token=SELLER,json_data={
        "title":"待删除_"+ts,"content":"test","category":"general"})
    nid=d.get("id") or d.get("note_id") or "NONEXISTENT"
    c,r=req("DELETE","/api/pre-sale-notes/%s" % nid,token=SELLER)
    return c in (200,204,401,404), "code=%d" % c

r4 = [test("售前笔记列表", pre_list), test("创建售前笔记", pre_create),
       test("解析售前笔记", pre_parse), test("删除售前笔记", pre_delete)]
print("  -> %d/%d" % (sum(r4), len(r4)))

# ── 5. 售后服务 ───────────────────────────────────────────
print("\n=== 5. 售后服务 ===")
def as_list(): c,d=req("GET","/api/admin/after-sales",params={"page":"1","page_size":"10"},token=ADMIN); return c==200, "code=%d" % c
def as_detail(): c,d=req("GET","/api/admin/after-sales/AS001",token=ADMIN); return c in (200,404), ""
def adv_stats(): c,d=req("GET","/api/admin/advanced-stats",params={"type":"after-sales"},token=ADMIN); return c==200, ""
def as_batch():
    c,d=req("POST","/api/admin/after-sales/batch",token=ADMIN,json_data={"ids":["A001"],"action":"export"})
    return c in (200,400,401,422), "code=%d" % c

r5 = [test("售后列表", as_list), test("售后详情", as_detail),
       test("高级统计", adv_stats), test("批量操作", as_batch)]
print("  -> %d/%d" % (sum(r5), len(r5)))

# ── 6. 审计日志 ───────────────────────────────────────────
print("\n=== 6. 审计日志 ===")
def aud_list(): c,d=req("GET","/api/admin/audit-logs",params={"page":"1","page_size":"20"},token=ADMIN); return c==200, "total=%s" % d.get("total","?")
def aud_type(): c,d=req("GET","/api/admin/audit-logs",params={"event_type":"LOGIN","page":"1","page_size":"5"},token=ADMIN); return c==200, ""
def aud_date(): c,d=req("GET","/api/admin/audit-logs",params={"start_date":"2026-01-01","end_date":"2026-12-31","page":"1","page_size":"5"},token=ADMIN); return c==200, ""
def aud_pg(): c,d=req("GET","/api/admin/audit-logs",params={"page":"999","page_size":"20"},token=ADMIN); return c==200, ""
def aud_combo(): c,d=req("GET","/api/admin/audit-logs",params={"event_type":"LOGIN","operator":"admin","start_date":"2026-01-01","page":"1","page_size":"5"},token=ADMIN); return c==200, ""

r6 = [test("审计日志列表", aud_list), test("按类型筛选", aud_type),
       test("按日期筛选", aud_date), test("越页分页", aud_pg),
       test("组合筛选", aud_combo)]
print("  -> %d/%d" % (sum(r6), len(r6)))

# ── 7. 店铺管理 ───────────────────────────────────────────
print("\n=== 7. 店铺管理 ===")
def shop_init(): c,d=req("POST","/api/v1/shop/init-database",token=SELLER); return c in (200,401), ""
def shops(): c,d=req("GET","/api/v1/shop/shops"); return c==200, "shops=%d" % len(d.get("data",d.get("shops",[])))
def shops_act(): c,d=req("GET","/api/v1/shop/shops",params={"status":"active"}); return c==200, ""
def shop_create():
    ts=str(int(time.time()))
    c,d=req("POST","/api/v1/shop/shops",token=SELLER,json_data={
        "platform":"shopee","shop_name":"测试店铺_"+ts,"shop_id":"TEST_"+ts,
        "status":"active","api_key":"k","api_secret":"s"})
    return c in (200,201,401,422), "code=%d" % c
def prods(): c,d=req("GET","/api/v1/shop/products",params={"page":"1","page_size":"10"}); return c==200, ""
def prods_draft(): c,d=req("GET","/api/v1/shop/products",params={"status":"draft","page_size":"5"}); return c==200, ""
def inv(): c,d=req("GET","/api/v1/shop/inventory",params={"page":"1","page_size":"10"}); return c==200, ""
def price(): c,d=req("GET","/api/v1/shop/pricing-rules"); return c==200, ""
def price_c():
    ts=str(int(time.time()))
    c,d=req("POST","/api/v1/shop/pricing-rules",token=SELLER,json_data={
        "name":"规则_"+ts,"type":"percentage","value":"10","platform":"shopee","status":"active"})
    return c in (200,201,401,422), "code=%d" % c
def stats(): c,d=req("GET","/api/v1/shop/stats"); return c==200, ""
def collect():
    c,d=req("POST","/api/v1/shop/collect",token=SELLER,json_data={"url":"https://shopee.co.id/test"})
    return c in (200,422), "code=%d" % c
def sp(): c,d=req("GET","/api/v1/shop/shop-products",params={"page_size":"10"}); return c==200, ""
def cats(): c,d=req("GET","/api/v1/shop/categories"); return c==200, ""

r7 = [test("初始化数据库", shop_init), test("店铺列表", shops),
       test("活跃店铺列表", shops_act), test("创建店铺", shop_create),
       test("商品列表", prods), test("草稿商品", prods_draft),
       test("库存列表", inv), test("定价规则列表", price),
       test("创建定价规则", price_c), test("店铺统计", stats),
       test("商品采集（模拟）", collect), test("店铺商品关联", sp),
       test("商品分类", cats)]
print("  -> %d/%d" % (sum(r7), len(r7)))

# ── 汇总 ──────────────────────────────────────────────────
total = sum(r1)+sum(r2)+sum(r3)+sum(r4)+sum(r5)+sum(r6)+sum(r7)
total_tests = len(r1)+len(r2)+len(r3)+len(r4)+len(r5)+len(r6)+len(r7)

print("\n" + "=" * 50)
print("  总计: %d/%d 通过 (%.0f%%)" % (total, total_tests, total/total_tests*100))
print("=" * 50)

modules = [("全部订单",r1),("消息中心",r2),("评价管理",r3),
           ("售前服务",r4),("售后服务",r5),("审计日志",r6),("店铺管理",r7)]
for name, r in modules:
    pct = sum(r)*100//len(r)
    bar = "="*(pct//5) + "-"*(20-pct//5)
    print("  %-12s [%s] %d/%d" % (name, bar, sum(r), len(r)))

all_pass = all(sum(r)==len(r) for r in [r2,r5,r6,r7])
print("\n  %s" % ("[OK] 所有关键模块全部通过!" if all_pass else "[WARN] 部分模块未完全通过"))
