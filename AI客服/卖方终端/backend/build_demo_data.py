# -*- coding: utf-8 -*-
"""
精进演示数据生成脚本
覆盖所有功能模块：客户档案、会话消息、坐席管理、售后单、售前记录、
快捷回复、通知公告、审计日志、店铺商品、库存定价、平台评价

使用方法：python build_demo_data.py
"""
import os
import sys
import sqlite3
import random
import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path

# ============== 路径配置 ==============
SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = SCRIPT_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

SELLER_DB = DATA_DIR / "seller.db"
SHOP_DB = DATA_DIR / "shop_manager.db"
SYNC_DB = DATA_DIR / "platform_sync.db"

# ============== 时间工具 ==============
def dt(days_offset=0, hours_offset=0):
    """生成 datetime 字符串，days_offset 为负表示过去"""
    return (datetime.now() + timedelta(days=days_offset, hours=hours_offset)).strftime("%Y-%m-%d %H:%M:%S")

def days_ago(days):
    return dt(-days)

def rand_time(start_days=30, end_days=0):
    """随机过去时间点"""
    total_hours = random.randint((start_days - end_days) * 24, start_days * 24)
    return (datetime.now() - timedelta(hours=total_hours)).strftime("%Y-%m-%d %H:%M:%S")

# ============== 通用连接 ==============
def get_conn(db_path):
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn

# ============== 数据种子 ==============

# 平台
PLATFORMS = ["tiktok", "lazada", "shopee", "aliexpress", "amazon", "temu", "ebay"]
PLATFORM_NAMES_ZH = {
    "aliexpress": "速卖通", "amazon": "亚马逊", "shopee": "Shopee",
    "temu": "Temu", "lazada": "Lazada", "ebay": "eBay"
}

# 地区
REGIONS = ["华东", "华南", "华北", "华中", "西南", "西北", "东北"]
COUNTRIES = ["美国", "英国", "德国", "法国", "西班牙", "俄罗斯", "巴西", "墨西哥", "印尼", "泰国"]
LANGUAGES = ["en", "zh", "es", "fr", "de", "ru", "pt"]

# 售后类型
AS_TYPES = ["退货退款", "仅退款", "换货", "退货重发", "部分退款", "全额退款"]
AS_REASON_CATEGORIES = [
    "尺码偏差", "色差问题", "面料薄透", "做工瑕疵", "发错款式",
    "漏发配件", "质量问题", "七天无理由", "物流延误", "其他"
]
AS_STATUSES = ["待审核", "处理中", "待买家寄回", "已退货", "待退款", "完成", "已取消"]
WAREHOUSES = ["深圳仓", "义乌仓", "广州仓", "上海仓", "郑州仓"]
REFUND_METHODS = ["原路退回", "平台余额", "银行卡", "PayPal", "信用卡"]

# 坐席角色
SELLER_ROLES = ["admin", "supervisor", "agent"]
SESSION_STATUSES = ["waiting", "assigned", "in_progress", "resolved", "transferred", "closed"]
SESSION_LANGS = ["zh", "en", "es", "fr", "de"]
MSG_ROLES = ["customer", "agent", "bot", "system"]
QUEUE_STATUSES = ["waiting", "assigned", "processing", "completed", "cancelled"]

# 商品类目
CATEGORIES = ["女装", "泳装", "瑜伽健身", "内衣裤", "配饰", "沙滩度假", "舞蹈运动", "大码女装"]

# 店铺状态
SHOP_STATUSES = ["active", "inactive", "suspended", "pending_review"]
PRODUCT_STATUSES = ["draft", "active", "published", "offline", "archived"]
PUBLISH_STATUSES = ["draft", "published", "offline", "pending"]
RULE_TYPES = ["margin", "fixed", "target"]
ROUND_MODES = ["ceil", "floor", "round"]

# 评价星级
STAR_RATINGS = [5, 5, 5, 5, 4, 4, 4, 3, 3, 2, 1]  # 偏向好评分布
REVIEW_STATUSES = ["pending", "replied", "auto_replied", "hidden"]

# 通知类型
NOTIF_TYPES = ["system", "order", "refund", "review", "transfer", "alert", "announcement"]

# 快捷回复分类
QR_CATEGORIES = ["通用", "尺码咨询", "款式咨询", "物流咨询", "商品咨询", "退款退货", "差评安抚", "好评感谢", "节日问候"]

# 审计事件类型
AUDIT_EVENTS = [
    "登录", "登出", "查看客户", "创建售后", "处理退款", "回复评价",
    "更新订单", "转接会话", "创建会话", "导出数据", "修改配置", "批量操作"
]


# ============== 辅助函数 ==============
def gen_uuid():
    return lambda: f"{random.randint(10**19, 10**20-1):020d}"

def gen_phone():
    return f"+{random.choice(['1','44','49','33','34','7'])}{random.randint(10**9, 10**10-1)}"

def gen_customer_id(platform, idx):
    prefixes = {
        "tiktok": "TT",
        "aliexpress": "AE",
        "amazon": "AMZ",
        "shopee": "SP",
        "temu": "TM",
        "lazada": "LZ",
        "ebay": "EB",
    }
    return f"{prefixes.get(platform, 'XX')}{idx:06d}"

def gen_order_id(platform, idx):
    prefixes = {
        "tiktok": "TTO",
        "aliexpress": "AEO",
        "amazon": "AMZO",
        "shopee": "SPO",
        "temu": "TMO",
        "lazada": "LZO",
        "ebay": "EBO",
    }
    return f"{prefixes.get(platform, 'XX')}{datetime.now().year}{(idx+1):08d}"

def gen_review_id(platform, idx):
    prefixes = {
        "tiktok": "TTR",
        "aliexpress": "AER",
        "amazon": "AMZR",
        "shopee": "SPR",
        "temu": "TMR",
        "lazada": "LZR",
        "ebay": "EBR",
    }
    return f"{prefixes.get(platform, 'XX')}{idx:08d}"

def gen_as_id(idx):
    return f"AS{datetime.now().year}{idx:08d}"

def gen_note_id(idx):
    return f"PN{datetime.now().year}{idx:06d}"

def weighted_choice(options, weights):
    return random.choices(options, weights=weights, k=1)[0]

def img_placeholder(title, size=200):
    """生成占位图 URL"""
    bg = "%23" + "%02x%02x%02x" % (
        random.randint(200, 240), random.randint(200, 240), random.randint(200, 240)
    )
    return f"https://via.placeholder.com/{size}/{bg}/666666?text={title[:8]}"

def bulk_insert(conn, table, rows, batch=200):
    """批量插入"""
    if not rows:
        return
    cols = list(rows[0].keys())
    placeholders = ", ".join(["?"] * len(cols))
    sql = f"INSERT OR IGNORE INTO {table} ({','.join(cols)}) VALUES ({placeholders})"
    for i in range(0, len(rows), batch):
        conn.executemany(sql, [tuple(r[c] for c in cols) for r in rows[i:i+batch]])
    conn.commit()

def clear_table(conn, table):
    """清空表数据（保留结构）"""
    conn.execute(f"DELETE FROM {table}")
    conn.commit()

# ============== 顾客姓名生成 ==============
FIRST_NAMES_CN = ["王", "李", "张", "刘", "陈", "杨", "赵", "黄", "周", "吴", "徐", "孙", "马", "朱", "胡", "郭", "何", "林", "罗", "高"]
LAST_NAMES_CN = ["伟", "芳", "娜", "敏", "静", "丽", "强", "磊", "军", "洋", "勇", "艳", "杰", "娟", "涛", "明", "超", "秀英", "霞", "平"]
FIRST_NAMES_EN = ["John", "Emma", "Michael", "Sophia", "David", "Olivia", "James", "Isabella", "William", "Mia", "Alexander", "Charlotte", "Benjamin", "Amelia", "Daniel", "Harper", "Henry", "Evelyn", "Sebastian", "Luna"]
LAST_NAMES_EN = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez", "Wilson", "Anderson", "Taylor", "Thomas", "Moore", "Jackson", "Martin", "Lee", "Thompson", "White"]

def gen_cn_name():
    return random.choice(FIRST_NAMES_CN) + random.choice(LAST_NAMES_CN)

def gen_en_name():
    return random.choice(FIRST_NAMES_EN) + " " + random.choice(LAST_NAMES_EN)

# ============== 评价内容（泳装/女装）==============
POSITIVE_REVIEWS = [
    "Great swimsuit! The fabric is thick and not see-through at all. Very satisfied!",
    "Beautiful bikini! Exactly as shown in photos, fast shipping too.",
    "Excellent quality for the price. The stitching is neat and durable.",
    "Perfect fit! True to size, very flattering. Love the color!",
    "Fast delivery, well packaged, the fabric feels premium. Highly recommend!",
    "Very good quality, exceeded my expectations! The adjustable straps are a nice touch.",
    "Arrived quickly and in perfect condition. The padding is thick enough. Thank you!",
    "Outstanding swimsuit, will buy again from this seller. The material is smooth and comfortable.",
    "Nice design and great material. Fits perfectly! Very happy with this purchase.",
    "Five stars! Everything was perfect from order to delivery. The wrap style is so flattering!",
    "Very professional seller, product is exactly as shown. The fabric is not cheap at all.",
    "Impressed with the quality. The lining is comfortable and the coverage is perfect.",
]
NEUTRAL_REVIEWS = [
    "Swimsuit is okay, but shipping took longer than expected.",
    "Item matches description, but the padding could be thicker.",
    "Average quality for the price, nothing special but not bad either.",
    "Decent swimsuit, slight color difference from photos but still acceptable.",
    "It's fine, does the job. Not amazing but the fit is decent.",
]
NEGATIVE_REVIEWS = [
    "Swimsuit arrived damaged with a torn strap, very disappointed.",
    "Not as described at all. The color is completely different from photos. Requesting refund.",
    "Quality is very poor, the fabric is thin and see-through. Waste of money.",
    "Item came without the correct size tag, cannot use it.",
    "Seller sent wrong item, still waiting for resolution after 2 weeks.",
    "Took forever to arrive, the swimsuit is mediocre at best.",
    "Extremely disappointed. The stitching came loose after one use. Will never buy again.",
    "False advertising, product looks nothing like the photos. The fabric is totally different.",
]
REPLY_TEMPLATES = [
    "Dear customer, thank you for your purchase! We're glad you had a great experience with our swimsuit. Looking forward to serving you again!",
    "Thank you so much for your positive feedback! We will continue to provide excellent swimwear products and service.",
    "We sincerely appreciate your support. If you have any questions about sizing or care instructions, please don't hesitate to contact us.",
    "Dear valued customer, thank you for choosing our swimwear. We hope you enjoy your beach vacation! Best regards!",
    "Thank you for your review! We take all feedback seriously and will keep improving our swimwear quality and service.",
]

# ============== 售前记录模板（泳装/女装）==============
PREF_STYLES = ["简约", "复古", "甜美", "运动", "性感", "波西米亚", "欧美风", "韩系", "日系", "度假风"]
PREF_COLORS = ["黑色", "白色", "红色", "粉色", "蓝色", "绿色", "紫色", "金色", "橙色", "米白"]
PRICE_SENSITIVITY = ["低", "中", "高", "只看价格"]
LOGISTICS_CHANNELS = ["DHL", "FedEx", "UPS", "YANWEN", "4PX", "云途", "燕文", "小包"]
PACKAGING_TYPES = ["纸盒", "塑料袋", "气泡袋", "密封袋", "环保包装"]
# 泳装专用尺码（各国对照）
SWIM_SIZES_CN = ["155/80A-XS", "160/84A-S", "165/88A-M", "170/92A-L", "175/96A-XL", "180/100A-XXL", "均码"]


# ==============================================================================
# 模块一：seller.db — 坐席、顾客、会话、售后、售前、快捷回复、通知、审计
# ==============================================================================
def build_seller_db():
    print("\n[1/3] 生成 seller.db 演示数据...")
    conn = get_conn(SELLER_DB)

    # 1-1. 坐席账号
    print("  [-] 坐席账号...")
    clear_table(conn, "sellers")
    pw_hash = hashlib.sha256("admin123".encode()).hexdigest()
    sellers = [
        {"username": "admin", "password_hash": pw_hash, "name": "系统管理员", "role": "admin",
         "is_online": 1, "created_at": days_ago(90), "last_login": days_ago(0), "password_changed": 1, "must_change_password": 0},
        {"username": "alice", "password_hash": hashlib.sha256("alice123".encode()).hexdigest(),
         "name": "Alice Chen", "role": "supervisor", "is_online": 1,
         "created_at": days_ago(60), "last_login": days_ago(1), "password_changed": 1, "must_change_password": 0},
        {"username": "bob", "password_hash": hashlib.sha256("bob123".encode()).hexdigest(),
         "name": "Bob Wang", "role": "agent", "is_online": 0,
         "created_at": days_ago(45), "last_login": days_ago(2), "password_changed": 1, "must_change_password": 0},
        {"username": "cathy", "password_hash": hashlib.sha256("cathy123".encode()).hexdigest(),
         "name": "Cathy Liu", "role": "agent", "is_online": 1,
         "created_at": days_ago(30), "last_login": days_ago(0), "password_changed": 0, "must_change_password": 1},
        {"username": "david", "password_hash": hashlib.sha256("david123".encode()).hexdigest(),
         "name": "David Zhang", "role": "agent", "is_online": 0,
         "created_at": days_ago(20), "last_login": days_ago(3), "password_changed": 1, "must_change_password": 0},
        {"username": "eva", "password_hash": hashlib.sha256("eva123".encode()).hexdigest(),
         "name": "Eva Yang", "role": "agent", "is_online": 1,
         "created_at": days_ago(15), "last_login": days_ago(1), "password_changed": 1, "must_change_password": 0},
    ]
    bulk_insert(conn, "sellers", sellers)

    # 1-2. 客户档案
    print("  [-] 客户档案...")
    clear_table(conn, "customers")
    customers = []
    for i in range(1, 81):  # 80 个客户
        platform = random.choice(PLATFORMS)
        is_cn = random.random() < 0.3
        name = gen_cn_name() if is_cn else gen_en_name()
        customer = {
            "customer_id": gen_customer_id(platform, i),
            "phone": gen_phone(),
            "name": name,
            "region": random.choice(REGIONS),
            "level": weighted_choice(["普通", "银牌", "金牌", "VIP"], [50, 25, 15, 10]),
            "m_value": random.randint(0, 5000),
            "created_at": rand_time(90, 5),
            "updated_at": rand_time(30, 0),
        }
        customers.append(customer)
    bulk_insert(conn, "customers", customers)

    # 1-3. 会话记录
    print("  [-] 会话记录...")
    clear_table(conn, "sessions")
    sessions = []
    for i in range(1, 61):  # 60 条会话
        status = random.choice(SESSION_STATUSES)
        platform = random.choice(PLATFORMS)
        customer = random.choice(customers)
        session = {
            "session_id": f"SES{datetime.now().year}{i:06d}",
            "customer_id": customer["customer_id"],
            "status": status,
            "assign_to": random.choice(["alice", "bob", "cathy", "david", "eva"]) if status != "waiting" else None,
            "is_ai": 1 if status == "waiting" else random.randint(0, 1),
            "language": random.choice(SESSION_LANGS),
            "system_source": random.choice(["buyer", "buyer", "buyer", "self"]),
            "created_at": rand_time(30, 0),
            "updated_at": rand_time(10, 0),
        }
        sessions.append(session)
    bulk_insert(conn, "sessions", sessions)

    # 1-4. 消息记录（泳装咨询，每条会话 2-10 条消息）
    print("  [-] 消息记录...")
    clear_table(conn, "messages")
    messages = []
    swim_topics = [
        "您好，请问这款比基尼有黑色M码吗？",
        "请问泳装的材质是莱卡的吗？弹性怎么样？",
        "请问这件连体泳衣适合多大的女生穿？",
        "请问尺码偏大还是偏小？我平时穿S码",
        "请问发货到美国需要多久？",
        "收到泳装了，但是感觉尺码偏小，能换货吗？",
        "请问这款泳衣有色差吗？",
        "请问支持退换货吗？",
        "请问有适合大码女生的泳装推荐吗？",
        "请问这款泳衣的胸垫是可拆卸的吗？",
    ]
    msg_id = 1
    for session in sessions[:50]:
        num_msgs = random.randint(2, 10)
        for j in range(num_msgs):
            topic = random.choice(swim_topics)
            if j == 0:
                content = f"您好，请问有什么泳装方面的问题我可以帮您解答的吗？"
            elif j == 1:
                content = f"感谢您的咨询！{topic}，我帮您查一下。"
            elif j == 2:
                content = random.choice([
                    f"您好，这款泳装的尺码我们建议您参考详情页的尺码表。一般偏小，建议选平时尺码或大一号。",
                    f"感谢您的耐心等待！这款比基尼有黑色M码现货，1-3个工作日可以发货。",
                    f"您好！我们的泳装面料是高弹莱卡材质，耐氯漂不起球，建议手洗阴干避免暴晒。",
                ])
            else:
                content = random.choice([
                    f"请问还有其他关于泳装尺码、款式或物流的问题吗？我们很乐意为您解答。",
                    f"好的，祝您购物愉快！夏天到了，沙滩玩得开心！🏖️",
                    f"如有其他问题随时联系我们，感谢您的咨询！",
                ])
            msg = {
                "session_id": session["session_id"],
                "role": "system" if j == 0 else random.choices(MSG_ROLES, weights=[0.4, 0.3, 0.2, 0.1])[0],
                "content": content,
                "created_at": (datetime.strptime(session["created_at"], "%Y-%m-%d %H:%M:%S") + timedelta(minutes=j * random.randint(1, 5))).strftime("%Y-%m-%d %H:%M:%S"),
            }
            messages.append(msg)
            msg_id += 1
    bulk_insert(conn, "messages", messages)

    # 1-5. 转接队列
    print("  [-] 转接队列...")
    clear_table(conn, "transfer_queue")
    queues = []
    for i, session in enumerate(sessions[:30]):
        if session["status"] in ["waiting", "assigned", "processing"]:
            queue = {
                "session_id": session["session_id"],
                "customer_id": session["customer_id"],
                "language": session["language"],
                "enqueued_at": session["created_at"],
                "assigned_to": session.get("assign_to") if random.random() > 0.3 else None,
                "status": "completed" if session["status"] == "resolved" else session["status"],
            }
            queues.append(queue)
    bulk_insert(conn, "transfer_queue", queues)

    # 1-6. 快捷回复
    print("  [-] 快捷回复...")
    clear_table(conn, "quick_replies")
    quick_replies = [
        # 通用
        {"category": "通用", "title": "问候", "content": "您好！感谢您的来信！夏天到了，有什么关于泳装或沙滩装备的问题我可以帮您解答的吗？", "shortcut": "/hello", "is_active": 1, "created_by": "admin"},
        {"category": "通用", "title": "告别", "content": "祝您购物愉快，夏日沙滩玩得开心！如有其他问题随时联系我们！", "shortcut": "/bye", "is_active": 1, "created_by": "admin"},
        {"category": "通用", "title": "请稍等", "content": "请稍等，我正在为您查询库存和尺码信息...", "shortcut": "/hold", "is_active": 1, "created_by": "alice"},
        {"category": "通用", "title": "无法理解", "content": "抱歉，我暂时无法理解您的问题，能否请您详细描述一下您咨询的是哪款泳装或沙滩商品？", "shortcut": "/unclear", "is_active": 1, "created_by": "admin"},
        # 尺码咨询（泳装特有）
        {"category": "尺码咨询", "title": "尺码建议", "content": "您好！泳装尺码建议您参考详情页的尺码表，并提供您的身高体重，我们可以为您推荐更合适的尺码。泳装面料有弹性，建议按平时尺码或稍选大一码。", "shortcut": "/size", "is_active": 1, "created_by": "alice"},
        {"category": "尺码咨询", "title": "尺码偏小", "content": "您好，我们的泳装面料是高弹性莱卡材质，部分款式可能偏小。建议您选平时尺码或稍大一号，特别是比基尼上装如有钢圈建议选大一码穿着更舒适。", "shortcut": "/size_small", "is_active": 1, "created_by": "alice"},
        {"category": "尺码咨询", "title": "面料说明", "content": "您好，我们的泳装面料以锦纶+氨纶（莱卡）为主，触感光滑，弹性好，耐氯漂，不起球不起毛。洗涤建议手洗阴干，避免机洗和暴晒。", "shortcut": "/material", "is_active": 1, "created_by": "bob"},
        # 颜色/款式
        {"category": "款式咨询", "title": "显瘦推荐", "content": "您好！想要显瘦推荐高腰比基尼下装或连体褶皱款，可以有效遮住腹部赘肉同时拉长腿部比例。我们的遮肚连体泳衣特别受微胖女生欢迎！", "shortcut": "/slim", "is_active": 1, "created_by": "alice"},
        {"category": "款式咨询", "title": "小胸推荐", "content": "您好！小胸女生推荐荷叶边比基尼、公主袖款或带聚拢胸垫的款式，可以增加视觉效果。我们的韩版甜美泳装特别设计了上薄下厚胸垫，专为小胸女生设计。", "shortcut": "/small_bust", "is_active": 1, "created_by": "bob"},
        {"category": "款式咨询", "title": "大码推荐", "content": "您好！我们有多款大码泳装（XL-5XL），全面遮肚、高腰收腹设计，专为微胖女生打造。面料高弹不勒肉，穿着舒适，沙滩美美拍照！", "shortcut": "/plus_size", "is_active": 1, "created_by": "cathy"},
        # 物流
        {"category": "物流咨询", "title": "发货时间", "content": "您好，我们通常在付款后 1-3 个工作日内发货。由于泳装为贴身商品，发货前均经过质检，请您耐心等待。", "shortcut": "/ship_time", "is_active": 1, "created_by": "bob"},
        {"category": "物流咨询", "title": "物流查询", "content": "您好，您可以点击订单详情中的物流追踪链接查看实时物流信息。如有物流异常请联系我们帮您查询。", "shortcut": "/track", "is_active": 1, "created_by": "bob"},
        {"category": "物流咨询", "title": "海关延误", "content": "您好，部分国家/地区可能因海关清关导致延迟，特别是欧美和巴西地区，通常 10-20 个工作日内送达，请您耐心等待。", "shortcut": "/customs", "is_active": 1, "created_by": "cathy"},
        # 色差问题（泳装高频投诉）
        {"category": "商品咨询", "title": "色差说明", "content": "您好！我们的泳装图片均为实物拍摄，但因显示器和灯光不同可能存在轻微色差，请您以实物为准。如严重不符我们支持退换货。", "shortcut": "/color_diff", "is_active": 1, "created_by": "alice"},
        # 退款退货（泳装特有）
        {"category": "退款退货", "title": "退货政策", "content": "您好，泳装属于贴身商品，我们支持 7 天无理由退货（不影响二次销售）。退货运费由买家承担，退货前请先联系我们获取退换地址。泳装请保持干净勿试穿泳池。", "shortcut": "/return_policy", "is_active": 1, "created_by": "alice"},
        {"category": "退款退货", "title": "退款进度", "content": "您好，退款通常在收到退货并检查无误后 3-5 个工作日内原路退回，请您耐心等待。退款到账时间以支付平台为准。", "shortcut": "/refund_status", "is_active": 1, "created_by": "alice"},
        {"category": "退款退货", "title": "换货说明", "content": "您好，换泳装尺码或颜色请联系客服确认库存，我们会在收到退货后尽快为您发出换货商品。换货运费各承担一半。", "shortcut": "/exchange", "is_active": 1, "created_by": "bob"},
        {"category": "退款退货", "title": "尺码不合换货", "content": "您好，收到泳装尺码不合？我们可以为您提供免费换货服务！只需提供您的身高体重和平时穿什么码，我们为您推荐合适的尺码寄出。", "shortcut": "/size_exchange", "is_active": 1, "created_by": "cathy"},
        # 差评安抚（泳装高频问题）
        {"category": "差评安抚", "title": "差评回复-尺码", "content": "非常抱歉尺码给您带来不好的体验！我们的泳装偏小是我们的疏忽，请您联系我们提供换货服务，往后我们会完善尺码表。感谢您的反馈！", "shortcut": "/neg_size", "is_active": 1, "created_by": "alice"},
        {"category": "差评安抚", "title": "差评回复-色差", "content": "非常抱歉泳装颜色与您的期望不符，我们会重视每一份反馈。若您愿意接受部分退款作为补偿，请联系我们。感谢您的理解！", "shortcut": "/neg_color", "is_active": 1, "created_by": "alice"},
        {"category": "差评安抚", "title": "差评回复-物流", "content": "非常抱歉物流给您带来不好的体验，我们会与物流公司沟通改善。感谢您的反馈，我们会不断提升服务质量！", "shortcut": "/neg_logistics", "is_active": 1, "created_by": "alice"},
        # 好评感谢
        {"category": "好评感谢", "title": "五星感谢", "content": "感谢您的好评！您的支持是我们最大的动力，期待再次为您服务！祝您沙滩玩得开心！🌟", "shortcut": "/thanks_review", "is_active": 1, "created_by": "admin"},
        {"category": "好评感谢", "title": "长期客户", "content": "感谢您一直以来的支持！夏日泳装旺季即将来临，新款陆续上线，欢迎再次选购！", "shortcut": "/vip_thanks", "is_active": 1, "created_by": "admin"},
        # 节日/旺季
        {"category": "节日问候", "title": "夏日祝福", "content": "☀️ 夏日炎炎，祝您购物愉快！沙滩度假注意防晒，祝您玩得开心！", "shortcut": "/summer", "is_active": 1, "created_by": "admin"},
        {"category": "节日问候", "title": "旺季感谢", "content": "🎊 感谢您选择我们！泳装旺季已至，新款不断，欢迎继续关注！祝您沙滩美照拍不停！", "shortcut": "/peak_season", "is_active": 1, "created_by": "admin"},
        # 停用示例
        {"category": "通用", "title": "旧版模板(停用)", "content": "此模板已停用，请使用新泳装话术模板。", "shortcut": "/old", "is_active": 0, "created_by": "admin"},
    ]
    for i, qr in enumerate(quick_replies):
        qr["created_at"] = days_ago(90 - i * 2)
        qr["updated_at"] = days_ago(random.randint(0, 30))
    bulk_insert(conn, "quick_replies", quick_replies)

    # 1-7. 通知公告
    print("  [-] 通知公告...")
    clear_table(conn, "notifications")
    notifications = [
        {"notification_type": "announcement", "title": "夏季泳装旺季备货提醒", "content": "6-8月为泳装销售旺季，请各店铺提前备货，确保热卖款库存充足，避免断货影响排名。",
         "source": "system", "is_read": 0, "is_important": 1, "created_at": days_ago(1)},
        {"notification_type": "alert", "title": "差评预警", "content": "本月差评率上升 15%，主要集中在色差和尺码偏小问题，请各坐席注意服务质量和回复速度。",
         "source": "system", "is_read": 0, "is_important": 1, "created_at": days_ago(0)},
        {"notification_type": "order", "title": "大额订单提醒", "content": "您有一笔金额 $800 的大客户订单待处理，订购比基尼套装 200 件，请尽快安排备货。",
         "source": "system", "is_read": 0, "is_important": 0, "created_at": days_ago(0)},
        {"notification_type": "refund", "title": "退款单待审批", "content": "您有 3 个退款单待处理（涉及泳装色差投诉），请登录系统尽快审批。",
         "source": "system", "is_read": 0, "is_important": 1, "created_at": days_ago(1)},
        {"notification_type": "review", "title": "差评提醒", "content": "您收到了 1 条 1 星差评（反映泳装尺码偏小），请及时处理并回复。",
         "source": "system", "is_read": 0, "is_important": 1, "created_at": days_ago(0)},
        {"notification_type": "transfer", "title": "新会话转接", "content": "客户 Sophia 咨询女士连体泳衣尺码问题，已转接至您，请及时处理。",
         "source": "system", "is_read": 1, "is_important": 0, "created_at": days_ago(1)},
        {"notification_type": "announcement", "title": "夏季新款培训通知", "content": "本周五下午 3 点将进行夏季新款泳装功能和话术培训，请所有坐席准时参加。",
         "source": "admin", "is_read": 1, "is_important": 0, "created_at": days_ago(3)},
        {"notification_type": "system", "title": "会话超时提醒", "content": "您有 2 个会话已超过 10 分钟未回复，客户正在咨询瑜伽服尺码，请及时响应。",
         "source": "system", "is_read": 0, "is_important": 1, "created_at": days_ago(0)},
        {"notification_type": "alert", "title": "库存预警", "content": "SKU BK-S-001（黑色比基尼 S码）库存不足 10 件，旺季将至，请及时补货。",
         "source": "system", "is_read": 0, "is_important": 0, "created_at": days_ago(2)},
        {"notification_type": "announcement", "title": "夏季节假日运营安排", "content": "暑期（7月1日-8月31日）客服工作量激增，请合理安排排班，确保响应速度。",
         "source": "admin", "is_read": 1, "is_important": 0, "created_at": days_ago(5)},
    ]
    for n in notifications:
        n["read_at"] = n["created_at"] if n["is_read"] else None
    bulk_insert(conn, "notifications", notifications)

    # 1-8. 售后记录
    print("  [-] 售后记录...")
    clear_table(conn, "after_sales")
    after_sales = []
    for i in range(1, 51):  # 50 条售后单
        as_type = random.choice(AS_TYPES)
        status = random.choice(AS_STATUSES)
        platform = random.choice(PLATFORMS)
        customer = random.choice(customers)
        reason_cat = random.choice(AS_REASON_CATEGORIES)
        refund_product = round(random.uniform(5, 200), 2)
        refund_shipping = round(random.uniform(0, 20), 2)
        refund_subsidy = round(random.uniform(0, 30), 2)
        refund_total = round(refund_product + refund_shipping + refund_subsidy, 2)

        as_record = {
            "as_id": gen_as_id(i),
            "order_id": gen_order_id(platform, i),
            "platform": platform,
            "customer_id": customer["customer_id"],
            "customer_name": customer["name"],
            "type": as_type,
            "reason_category": reason_cat,
            "reason_detail": f"{reason_cat}相关描述：{random.choice(['尺码偏小穿不上', '颜色与图片差距大', '面料太薄有些透', '线头较多做工一般', '收到不是下单的款式', '少了泳衣配套配件'])}",
            "status": status,
            "warehouse": random.choice(WAREHOUSES),
            "return_address_type": random.choice(["华南仓", "华东仓", "自定义地址"]),
            "refund_product": refund_product,
            "refund_shipping": refund_shipping,
            "refund_subsidy": refund_subsidy,
            "refund_customs": round(random.uniform(0, 10), 2),
            "refund_commission": round(refund_product * 0.06, 2),
            "refund_other": 0,
            "refund_total": refund_total,
            "refund_method": random.choice(REFUND_METHODS),
            "return_tracking": f"YTO{random.randint(100000000, 999999999)}" if status in ["returned", "completed"] else None,
            "return_carrier": random.choice(["YTO", "ZTO", "STO", "EMS", "DHL"]) if status in ["returned", "completed"] else None,
            "return_shipping_cost": round(random.uniform(3, 25), 2),
            "qc_result": random.choice(["合格", "不合格", "待检", None]) if status in ["returned", "completed"] else None,
            "qc_note": random.choice(["包装完好", "商品完好", "有使用痕迹", "包装破损", None]),
            "exchange_product": f"{random.choice(['换同款-S', '换同款-M', '换同款-L', None])}",
            "exchange_qty": random.randint(0, 2) if as_type == "换货" else 0,
            "internal_note": random.choice(["客户为老客VIP，已给予优惠券安抚", "核实后色差符合描述范围，拒绝退款", "建议给小额补偿5元了结", "客户情绪激动，已转交主管处理", "面料投诉较多，建议反馈给仓库质检"]),
            "buyer_note": random.choice(["急需，请尽快处理退款", "可以接受部分退款，留商品", "希望换大一号而非退款", "请提供退货地址和退货运费说明", "这件送给我吧，不需要退了"]),
            "created_by": random.choice(["alice", "bob", "cathy"]),
            "created_at": rand_time(45, 0),
            "updated_at": rand_time(10, 0),
            "completed_at": rand_time(5, 0) if status == "completed" else None,
        }
        after_sales.append(as_record)
    bulk_insert(conn, "after_sales", after_sales)

    # 1-9. 售前记录
    print("  [-] 售前记录...")
    clear_table(conn, "pre_sale_notes")
    pre_sales = []
    for i in range(1, 41):  # 40 条售前记录
        platform = random.choice(PLATFORMS)
        customer = random.choice(customers)
        country = random.choice(COUNTRIES)
        ps = {
            "note_id": gen_note_id(i),
            "order_id": gen_order_id(platform, i),
            "customer_id": customer["customer_id"],
            "customer_name": customer["name"],
            "nickname": f"user_{i:04d}",
            "platform": platform,
            "platform_id": f"{platform.upper()[:2]}{i:06d}",
            "country": country,
            "region": random.choice(REGIONS),
            "language": random.choice(LANGUAGES),
            "is_old_customer": random.randint(0, 1),
            "repeat_purchase_count": random.randint(0, 8),
            "has_complaints": random.randint(0, 1),
            "has_disputes": random.randint(0, 1),
            "has_negative_reviews": random.randint(0, 1),
            "has_asked_shipping": random.randint(0, 1),
            "has_asked_logistics": random.randint(0, 1),
            "preference_style": random.choice(PREF_STYLES),
            "preference_color": random.choice(PREF_COLORS),
            "preference_size": random.choice(SWIM_SIZES_CN),
            "price_sensitivity": random.choice(PRICE_SENSITIVITY),
            "needs_gift": random.randint(0, 1),
            "needs_card": random.randint(0, 1),
            "needs_privacy_packaging": random.randint(0, 1),
            "product_color": random.choice(PREF_COLORS),
            "product_size": random.choice(SWIM_SIZES_CN),
            "product_model": f"{random.choice(['比基尼', '连体', '分体', '套装'])}-{random.randint(100, 999)}",
            "packaging_type": random.choice(PACKAGING_TYPES),
            "no_invoice": random.randint(0, 1),
            "no_price_list": random.randint(0, 1),
            "logistics_channel": random.choice(LOGISTICS_CHANNELS),
            "must_combine": random.randint(0, 1),
            "urgent_shipping": random.randint(0, 1),
            "needs_gift_item": random.randint(0, 1),
            "needs_card_item": random.randint(0, 1),
            "customer_message_translation": "Please ship urgently, thank you." if random.random() < 0.2 else None,
            "fragile_need_extra_protection": random.randint(0, 1),
            "high_risk_area": random.randint(0, 1),
            "suspected_scammer": 0,
            "price_modification": random.choice(["减5%", "减10%", "维持原价", None]),
            "discount": random.choice(["9折", "95折", "无优惠", None]),
            "free_shipping": random.randint(0, 1),
            "out_of_stock": random.randint(0, 1),
            "pre_order": random.randint(0, 1),
            "waiting_days": random.randint(1, 15),
            "internal_note": random.choice([
                "客户VIP，已给予优惠", "客户情绪稳定，耐心解答即可",
                "建议推荐店铺其他热销款", "该客户有历史投诉，需谨慎处理",
                "客户对物流有特殊要求，已备注", "客户议价能力强，建议给小额优惠促成交易"
            ]),
            "raw_note": json.dumps({
                "source": "chat_export",
                "original_msg": f"Hi, I want to know about product #{i}, can you ship to {country}?",
                "agent_reply": "Yes we can ship to your country, usually takes 10-15 days.",
            }, ensure_ascii=False),
            "created_by": random.choice(["alice", "bob", "cathy", "david"]),
            "created_at": rand_time(60, 0),
            "updated_at": rand_time(15, 0),
        }
        pre_sales.append(ps)
    bulk_insert(conn, "pre_sale_notes", pre_sales)

    # 1-10. 审计日志
    print("  [-] 审计日志...")
    clear_table(conn, "audit_logs")
    audit_logs = []
    for i in range(1, 101):  # 100 条审计日志
        event = random.choice(AUDIT_EVENTS)
        operator = random.choice(["admin", "alice", "bob", "cathy", "david", "eva"])
        log = {
            "event_type": event,
            "operator": operator,
            "target_type": random.choice(["session", "after_sales", "review", "order", "customer", "config"]),
            "target_id": str(random.randint(1, 200)),
            "detail": json.dumps({
                "description": f"{event}操作成功",
                "before": {"status": "pending"},
                "after": {"status": "resolved"},
            }, ensure_ascii=False),
            "ip_address": f"192.168.{random.randint(1,10)}.{random.randint(1,254)}",
            "user_agent": random.choice([
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Safari/605.1.15",
                "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Mobile/15E148",
            ]),
            "created_at": rand_time(30, 0),
        }
        audit_logs.append(log)
    bulk_insert(conn, "audit_logs", audit_logs)

    conn.close()
    print(f"  [OK] seller.db 完成：{len(sellers)} 坐席 | {len(customers)} 客户 | {len(sessions)} 会话 | "  # NOCHARS
          f"{len(messages)} 消息 | {len(after_sales)} 售后 | {len(pre_sales)} 售前 | "
          f"{len(quick_replies)} 快捷回复 | {len(notifications)} 通知 | {len(audit_logs)} 审计日志")


# ==============================================================================
# 补充写入 seller.db 的 reviews / reply_templates / auto_reply_rules 表
# （reviews 数据在 seller.db 里，sync_reviews 在 platform_sync.db 里）
# ==============================================================================
def _write_reviews_to_seller_db():
    """向 seller.db 的 reviews 表写入演示数据"""
    conn = get_conn(SELLER_DB)

    # reviews 表在 init_mysql_schema.init_sqlite_schema() 中会自动创建
    # 若不存在则建表
    conn.execute("""
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            review_id TEXT UNIQUE,
            order_id TEXT,
            customer_id TEXT,
            customer_name TEXT,
            star_rating INTEGER DEFAULT 5,
            content TEXT,
            reply_content TEXT,
            replied_at TEXT,
            replied_by TEXT,
            status TEXT DEFAULT 'pending',
            platform TEXT DEFAULT 'other',
            product_name TEXT,
            product_image TEXT,
            review_date TEXT,
            is_negative INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS reply_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            content TEXT NOT NULL,
            category TEXT DEFAULT 'general',
            is_default INTEGER DEFAULT 0,
            created_by TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS auto_reply_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rule_type TEXT NOT NULL,
            star_min INTEGER,
            star_max INTEGER,
            reply_content TEXT NOT NULL,
            is_enabled INTEGER DEFAULT 1,
            created_by TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()

    # 清空旧数据
    conn.execute("DELETE FROM reviews")
    conn.execute("DELETE FROM reply_templates")
    conn.execute("DELETE FROM auto_reply_rules")
    conn.commit()

    # 1) 回复模板
    templates = [
        {"name": "好评感谢（通用）", "content": "Dear customer, thank you for your purchase! We're glad you had a great experience. Looking forward to serving you again!", "category": "好评", "is_default": 1, "created_by": "admin"},
        {"name": "好评感谢（中文）", "content": "感谢您的好评！您的支持是我们最大的动力，期待再次为您服务！", "category": "好评", "is_default": 0, "created_by": "admin"},
        {"name": "中评回复", "content": "Dear valued customer, thank you for your feedback. We take all feedback seriously and will keep improving. Please feel free to contact us if you have any further concerns.", "category": "中评", "is_default": 1, "created_by": "alice"},
        {"name": "差评-物流", "content": "We sincerely apologize for the logistics delay. We have communicated with our logistics partners to improve delivery times. Thank you for your patience.", "category": "差评", "is_default": 1, "created_by": "admin"},
        {"name": "差评-质量", "content": "We are very sorry about your experience. Please contact us directly and we will resolve this for you promptly. Your satisfaction is our priority.", "category": "差评", "is_default": 0, "created_by": "bob"},
        {"name": "差评-发错货", "content": "We sincerely apologize for the shipping error. We will resend the correct item immediately and you may keep the wrong item as our apology. Please accept our sincere apologies.", "category": "差评", "is_default": 0, "created_by": "alice"},
        {"name": "催好评模板", "content": "Dear customer, if you are satisfied with your purchase, we would greatly appreciate it if you could leave a 5-star review. It helps small sellers like us grow. Thank you!", "category": "催好评", "is_default": 0, "created_by": "admin"},
        {"name": "退货安抚", "content": "We are sorry the product did not meet your expectations. Please initiate a return and we will process your refund within 3-5 business days. Thank you for giving us a chance to improve.", "category": "退款退货", "is_default": 0, "created_by": "cathy"},
    ]
    for t in templates:
        t["created_at"] = days_ago(random.randint(5, 60))
        t["updated_at"] = days_ago(random.randint(0, 5))

    # 2) 自动回复规则
    rules = [
        {"rule_type": "good", "star_min": 4, "star_max": 5, "reply_content": "Thank you so much for your positive review! We truly appreciate your support and look forward to serving you again. Have a wonderful day!", "is_enabled": 1, "created_by": "admin"},
        {"rule_type": "neutral", "star_min": 3, "star_max": 3, "reply_content": "Thank you for your feedback. We are always looking to improve our products and service. If you have any specific suggestions, please don't hesitate to reach out.", "is_enabled": 1, "created_by": "alice"},
        {"rule_type": "negative", "star_min": 1, "star_max": 2, "reply_content": "We are deeply sorry for your experience. We take this very seriously and would like to make it right. Please contact us so we can resolve this immediately.", "is_enabled": 1, "created_by": "admin"},
        {"rule_type": "neutral", "star_min": 3, "star_max": 3, "reply_content": "Thank you for your honest review. We will use your feedback to improve our products. We hope to serve you better next time.", "is_enabled": 0, "created_by": "bob"},
    ]
    for r in rules:
        r["created_at"] = days_ago(random.randint(10, 60))
        r["updated_at"] = days_ago(random.randint(0, 10))

    # 3) 评价数据（100条，覆盖所有星级和状态）
    reviews = []
    products = [
        "Women's Sexy Bikini 3-Piece Set Bandeau", "Women's High Waist Bikini Retro Style",
        "Women's Surfing Swimsuit UPF50+ Rash Guard", "Women's Cute Ruffle Bikini 2-Piece Set",
        "Women's Leopard Print Bikini Set", "Women's Halter Neck Bikini Rhinestones",
        "Women's Deep V One-Piece Cutout Swimsuit", "Women's Vintage Polka Dot One-Piece Ruffle",
        "Women's Tummy Control One-Piece Ruched", "Women's Plus Size One-Piece Full Coverage",
        "Women's Beach Cover Up Lace Embroidered", "Women's UV Protection Beach Tunic",
        "Women's High Waist Yoga Set Sports Bra + Leggings", "Women's Athletic Swim Shorts Beach",
        "Women's Seamless Underwear Set Light", "Women's Lace Lingerie Set Sheer Mesh",
        "Beach Resort Straw Hat Wide Brim", "Anti-Fog Swimming Goggles UV Protection",
        "Women's Beach Maxi Dress Bohemian Style", "Waterproof Phone Pouch Neck Strap",
    ]
    platform_list = ["aliexpress", "amazon", "shopee", "temu", "lazada", "ebay"]
    review_statuses = ["pending", "replied", "replied", "replied"]  # 偏向已回复

    for i in range(1, 101):
        platform = platform_list[i % len(platform_list)]
        star = STAR_RATINGS[i % len(STAR_RATINGS)]
        is_neg = star <= 2
        status = "pending" if (is_neg and i % 3 == 0) else random.choice(review_statuses)

        # 多语言内容
        if star >= 4:
            content = random.choice([
                "Great swimsuit! The fabric is thick and not see-through at all. Very satisfied!",
                "Beautiful bikini! Exactly as shown in photos, fast shipping too. Highly recommend!",
                "Excellent quality for the price. The stitching is neat and the color is vibrant. Love it!",
                "Perfect fit! True to size, very flattering. The padding is thick enough. Thank you!",
                "Five stars! Everything was perfect from ordering to delivery. The wrap style is so cute!",
                "Impressed with the quality and packaging. Highly recommend this seller for swimwear!",
                "Super fast shipping and the product is exactly what I wanted. The fabric feels premium!",
                "Outstanding swimsuit, will buy again from this seller. The color is even prettier in person!",
            ])
        elif star == 3:
            content = random.choice([
                "Swimsuit is okay, but shipping took longer than expected.",
                "Item matches description, but the padding could be thicker and the color a bit dull.",
                "Average quality for the price. The fabric feels a bit thin but still acceptable.",
            ])
        else:
            content = random.choice([
                "Swimsuit arrived with a torn strap. Very disappointed with the quality. Waste of money.",
                "Not as described at all. The color is completely different from photos. Requesting refund.",
                "Arrived with broken stitching. Packaging was terrible. The fabric is see-through. Unhappy.",
                "Item came without the correct size. Cannot use it. Extremely disappointed with the experience.",
            ])

        replied_at = rand_time(30, 0) if status == "replied" else None
        reply_content_map = {
            "Great swimsuit!": "Dear customer, thank you so much for your wonderful review! We are thrilled you had a great experience with our swimsuit. Your support means the world to us!",
            "Beautiful bikini!": "Thank you for your kind words! We truly appreciate your support and look forward to serving you again for your next beach vacation!",
            "Excellent quality": "Dear valued customer, thank you for your positive feedback! We will continue to provide excellent swimwear and service.",
            "Perfect fit!": "Thank you so much! We are delighted to hear you are satisfied with the fit and padding. Have a wonderful day at the beach!",
            "Five stars!": "Thank you for the 5-star review! Your support drives us to keep improving our swimwear quality. We hope to see you again soon!",
            "Swimsuit is okay,": "Dear customer, thank you for your honest feedback. We have noted your comments and will work to improve our shipping times. We appreciate your patience and understanding.",
            "Swimsuit arrived with a torn": "We sincerely apologize for the damage. Please contact us immediately and we will process a replacement or refund right away. Your satisfaction is our top priority.",
            "Not as described": "We are very sorry for the experience. Please initiate a return and we will process a full refund immediately. We apologize for any inconvenience caused by the color difference.",
        }
        reply_content = next((v for k, v in reply_content_map.items() if content.startswith(k.split("!")[0])), None) if status == "replied" else None

        rev = {
            "review_id": gen_review_id(platform, i),
            "order_id": gen_order_id(platform, i),
            "customer_id": gen_customer_id(platform, i),
            "customer_name": gen_en_name(),
            "star_rating": star,
            "content": content,
            "reply_content": reply_content,
            "replied_at": replied_at,
            "replied_by": random.choice(["alice", "bob", "cathy"]) if status == "replied" else None,
            "status": status,
            "platform": platform,
            "product_name": random.choice(products),
            "product_image": img_placeholder(random.choice(products), 200),
            "review_date": rand_time(60, 0),
            "is_negative": 1 if star <= 2 else 0,
            "created_at": rand_time(60, 0),
            "updated_at": rand_time(10, 0),
        }
        reviews.append(rev)

    bulk_insert(conn, "reviews", reviews)
    bulk_insert(conn, "reply_templates", templates)
    bulk_insert(conn, "auto_reply_rules", rules)

    # 打印统计
    cur = conn.execute("SELECT COUNT(*) as c FROM reviews")
    rev_count = cur.fetchone()[0]
    cur = conn.execute("SELECT COUNT(*) as c FROM reply_templates")
    tmpl_count = cur.fetchone()[0]
    cur = conn.execute("SELECT COUNT(*) as c FROM auto_reply_rules")
    rule_count = cur.fetchone()[0]
    conn.close()
    return rev_count, tmpl_count, rule_count


# ==============================================================================
# 模块二：shop_manager.db — 店铺、商品、SKU、库存、定价、刊登、采集
# ==============================================================================
def build_shop_db():
    print("\n[2/3] 生成 shop_manager.db 演示数据...")
    conn = get_conn(SHOP_DB)

    # 初始化 schema（如果表不存在）
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS shops (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                shop_name TEXT NOT NULL, platform TEXT NOT NULL,
                shop_id TEXT, app_key TEXT, app_secret TEXT, access_token TEXT,
                country TEXT, currency TEXT DEFAULT 'USD', status TEXT DEFAULT 'active',
                is_default INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL, title_en TEXT, description TEXT,
                source_platform TEXT, product_code TEXT UNIQUE,
                brand TEXT, material TEXT, weight REAL,
                images TEXT DEFAULT '[]',
                status TEXT DEFAULT 'draft',
                sku_count INTEGER DEFAULT 0, category_id INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS product_skus (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                sku_code TEXT UNIQUE,
                sku_name TEXT,
                source_price REAL DEFAULT 0,
                attributes TEXT DEFAULT '{}',
                images TEXT DEFAULT '[]',
                weight REAL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS inventory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sku_id INTEGER NOT NULL,
                shop_id INTEGER,
                available_stock INTEGER DEFAULT 0,
                reserved_stock INTEGER DEFAULT 0,
                low_stock_threshold INTEGER DEFAULT 10,
                last_sync_at TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (sku_id) REFERENCES product_skus(id) ON DELETE CASCADE,
                FOREIGN KEY (shop_id) REFERENCES shops(id) ON DELETE SET NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pricing_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rule_name TEXT NOT NULL, rule_type TEXT NOT NULL,
                platform TEXT, shop_id INTEGER,
                margin_percent REAL DEFAULT 30,
                platform_fee_percent REAL DEFAULT 10, shipping_cost REAL DEFAULT 0,
                payment_fee_percent REAL DEFAULT 2, round_mode TEXT DEFAULT 'ceil',
                priority INTEGER DEFAULT 0, is_active INTEGER DEFAULT 1,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS shop_products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL, shop_id INTEGER NOT NULL,
                sku_id INTEGER,
                price REAL, stock INTEGER DEFAULT 0,
                publish_status TEXT DEFAULT 'draft',
                published_at TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE,
                FOREIGN KEY (shop_id) REFERENCES shops(id) ON DELETE CASCADE,
                FOREIGN KEY (sku_id) REFERENCES product_skus(id) ON DELETE SET NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS collect_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                platform TEXT NOT NULL, source_url TEXT,
                title TEXT, status TEXT DEFAULT 'success',
                product_id INTEGER,
                error_message TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS exchange_rates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_currency TEXT NOT NULL, to_currency TEXT NOT NULL,
                rate REAL NOT NULL, updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(from_currency, to_currency)
            )
        """)
        conn.commit()
    except Exception as e:
        print(f"  [!] Schema init: {e}")

    # 2-1. 店铺
    print("  [-] 店铺...")
    for t in ["shop_products", "inventory", "collect_history", "products", "shops"]:
        clear_table(conn, t)
    clear_table(conn, "pricing_rules")
    clear_table(conn, "exchange_rates")

    shops = []
    for i in range(1, 13):  # 12 家店铺
        platform = PLATFORMS[(i - 1) % len(PLATFORMS)]
        country = random.choice(COUNTRIES)
        currencies = {"aliexpress": "USD", "amazon": "USD", "shopee": ["USD", "MYR", "THB", "PHP"][i % 4],
                      "temu": "USD", "lazada": ["USD", "MYR", "SGD"][i % 3], "ebay": "USD"}
        shop = {
            "shop_name": f"{PLATFORM_NAMES_ZH[platform]}官方旗舰店 {chr(64+i)}",
            "platform": platform,
            "shop_id": f"{platform.upper()[:2]}SHOP{i:04d}",
            "app_key": f"AK{random.randint(100000, 999999)}",
            "app_secret": f"SK{random.randint(100000, 999999)}SECRET",
            "access_token": f"TOKEN_{random.randint(10**20, 10**21-1)}",
            "country": country,
            "currency": currencies.get(platform, "USD"),
            "status": random.choices(SHOP_STATUSES, weights=[70, 10, 15, 5])[0],
            "is_default": 1 if i == 1 else 0,
            "created_at": rand_time(90, 0),
            "updated_at": rand_time(5, 0),
        }
        shops.append(shop)
    bulk_insert(conn, "shops", shops)

    # 2-2. 定价规则
    print("  [-] 定价规则...")
    pricing_rules = [
        # 通用规则（适用于所有平台）
        {"rule_name": "通用利润率定价", "rule_type": "margin", "platform": None, "shop_id": None,
         "margin_percent": 30, "platform_fee_percent": 10, "shipping_cost": 5.0,
         "payment_fee_percent": 2, "round_mode": "ceil", "priority": 0, "is_active": 1,
         "created_at": days_ago(60), "updated_at": days_ago(10)},
        # 按平台
        {"rule_name": "速卖通高利润率", "rule_type": "margin", "platform": "aliexpress", "shop_id": None,
         "margin_percent": 40, "platform_fee_percent": 8, "shipping_cost": 4.0,
         "payment_fee_percent": 2, "round_mode": "ceil", "priority": 5, "is_active": 1,
         "created_at": days_ago(50), "updated_at": days_ago(5)},
        {"rule_name": "亚马逊标准定价", "rule_type": "margin", "platform": "amazon", "shop_id": None,
         "margin_percent": 35, "platform_fee_percent": 15, "shipping_cost": 6.0,
         "payment_fee_percent": 2.5, "round_mode": "floor", "priority": 5, "is_active": 1,
         "created_at": days_ago(45), "updated_at": days_ago(3)},
        {"rule_name": "Shopee 薄利多销", "rule_type": "margin", "platform": "shopee", "shop_id": None,
         "margin_percent": 20, "platform_fee_percent": 6, "shipping_cost": 3.0,
         "payment_fee_percent": 1.5, "round_mode": "round", "priority": 3, "is_active": 1,
         "created_at": days_ago(40), "updated_at": days_ago(2)},
        {"rule_name": "Temu 激进定价", "rule_type": "margin", "platform": "temu", "shop_id": None,
         "margin_percent": 25, "platform_fee_percent": 12, "shipping_cost": 4.5,
         "payment_fee_percent": 2, "round_mode": "ceil", "priority": 4, "is_active": 1,
         "created_at": days_ago(30), "updated_at": days_ago(1)},
        # 固定加价
        {"rule_name": "固定加价$10", "rule_type": "fixed", "platform": None, "shop_id": None,
         "margin_percent": 10, "platform_fee_percent": 0, "shipping_cost": 0,
         "payment_fee_percent": 0, "round_mode": "ceil", "priority": 1, "is_active": 0,
         "created_at": days_ago(20), "updated_at": days_ago(5)},
        # 目标价
        {"rule_name": "目标价$50", "rule_type": "target", "platform": None, "shop_id": None,
         "margin_percent": 50, "platform_fee_percent": 0, "shipping_cost": 0,
         "payment_fee_percent": 0, "round_mode": "ceil", "priority": 2, "is_active": 0,
         "created_at": days_ago(15), "updated_at": days_ago(2)},
        # Lazada 东南亚
        {"rule_name": "Lazada 东南亚", "rule_type": "margin", "platform": "lazada", "shop_id": None,
         "margin_percent": 28, "platform_fee_percent": 9, "shipping_cost": 3.5,
         "payment_fee_percent": 2, "round_mode": "ceil", "priority": 4, "is_active": 1,
         "created_at": days_ago(35), "updated_at": days_ago(3)},
        # eBay
        {"rule_name": "eBay 拍卖定价", "rule_type": "margin", "platform": "ebay", "shop_id": None,
         "margin_percent": 32, "platform_fee_percent": 11, "shipping_cost": 5.5,
         "payment_fee_percent": 2, "round_mode": "floor", "priority": 5, "is_active": 1,
         "created_at": days_ago(25), "updated_at": days_ago(1)},
    ]
    bulk_insert(conn, "pricing_rules", pricing_rules)

    # 2-3. 商品（含标题、描述、图片、分类）
    print("  [-] 商品...")
    products = []
    product_data = [
        # 女式比基尼
        {"title": "女士性感比基尼三件套 绑带款", "title_en": "Women's Sexy Bikini 3-Piece Set Bandeau",
         "desc": "绑带比基尼三件套，含上衣+下装+罩衫，莱卡面料，速干，沙滩度假必备，S-XL",
         "source": "1688", "brand": "BeachQueen", "material": "锦纶+莱卡",
         "weight": 0.12, "category": "泳装"},
        {"title": "女士高腰绑带比基尼 复古款", "title_en": "Women's High Waist Bikini Retro Style",
         "desc": "复古高腰设计，优雅绑带，80s复古风格，不掉色不起球，M-XXL",
         "source": "1688", "brand": "VintageSwim", "material": "聚酯纤维+氨纶",
         "weight": 0.1, "category": "泳装"},
        {"title": "女士运动冲浪泳衣 连体防晒款", "title_en": "Women's Surfing Swimsuit UPF50+ Rash Guard",
         "desc": "冲浪专用连体泳衣，UPF50+防晒面料，长袖设计，适合冲浪/潜水/浮潜",
         "source": "1688", "brand": "SurfGear", "material": "锦纶+氨纶",
         "weight": 0.25, "category": "泳装"},
        {"title": "女士韩版可爱泳装 荷叶边两件套", "title_en": "Korean Cute Swimsuit Ruffle 2-Piece Set",
         "desc": "韩版甜美荷叶边两件套，公主袖设计，适合小胸女生，上薄下厚，S-M",
         "source": "1688", "brand": "KSwimStyle", "material": "锦纶+涤纶",
         "weight": 0.15, "category": "泳装"},
        {"title": "女士比基尼套装 豹纹印花", "title_en": "Women's Leopard Print Bikini Set",
         "desc": "时尚豹纹印花，V领绑带上装，高腰三角裤，厚胸垫防走光，M-XL",
         "source": "1688", "brand": "WildSwim", "material": "涤纶+氨纶",
         "weight": 0.11, "category": "泳装"},
        {"title": "女士挂脖比基尼 亮片闪钻款", "title_en": "Women's Halter Neck Bikini with Rhinestones",
         "desc": "挂脖亮片闪钻设计，聚拢厚胸垫，适合派对/海边/温泉，L-XXL",
         "source": "1688", "brand": "GlamSwim", "material": "涤纶+亮片",
         "weight": 0.13, "category": "泳装"},
        # 连体泳衣
        {"title": "女士性感深V连体泳衣 镂空款", "title_en": "Women's Sexy Deep V One-Piece Swimsuit Cutout",
         "desc": "深V镂空设计，侧面绑带，后背大面积露背，高弹性面料，S-XL",
         "source": "1688", "brand": "CamiSwim", "material": "锦纶+氨纶",
         "weight": 0.18, "category": "泳装"},
        {"title": "女士复古波点连体泳衣 荷叶边", "title_en": "Women's Vintage Polka Dot One-Piece Ruffle",
         "desc": "50s复古波点图案，胸前荷叶边，高腰收腹设计，不挑身材，M-XXL",
         "source": "1688", "brand": "RetroWave", "material": "聚酯纤维+氨纶",
         "weight": 0.16, "category": "泳装"},
        {"title": "女士遮肚显瘦连体泳衣 褶皱款", "title_en": "Women's Tummy Control One-Piece Swimsuit Ruched",
         "desc": "褶皱遮肚设计，显瘦收腹，可拆卸罩杯，侧面可调节绑带，S-XXL",
         "source": "1688", "brand": "CurveFit", "material": "锦纶+莱卡",
         "weight": 0.2, "category": "泳装"},
        {"title": "女士大码连体泳衣 保守遮肚款", "title_en": "Women's Plus Size One-Piece Swimsuit Full Coverage",
         "desc": "大码加肥款式，全面遮肚，褶皱腰线显瘦，适合XL-5XL，微胖女生首选",
         "source": "1688", "brand": "FullFigured", "material": "锦纶+氨纶",
         "weight": 0.22, "category": "大码女装"},
        # 沙滩度假周边
        {"title": "女士沙滩罩衫 镂空刺绣款", "title_en": "Women's Beach Cover Up Lace Embroidered",
         "desc": "沙滩罩衫外套，镂空刺绣工艺，轻薄透气防晒，可做空调衫，M-XXL",
         "source": "1688", "brand": "BeachVibe", "material": "棉麻+蕾丝",
         "weight": 0.08, "category": "沙滩度假"},
        {"title": "女士海边防晒长袖罩衫 渐变色", "title_en": "Women's UV Protection Beach Tunic Gradient",
         "desc": "UPF40+防晒面料，长袖薄款，渐变色彩，沙滩/泳池/水上乐园通用",
         "source": "1688", "brand": "SunShield", "material": "聚酯纤维",
         "weight": 0.1, "category": "沙滩度假"},
        # 瑜伽健身服
        {"title": "女士高弹瑜伽健身服套装 运动bra+ leggings", "title_en": "Women's High Waist Yoga Set Sports Bra + Leggings",
         "desc": "裸感莱卡面料，高弹四向弹力，高腰收腹，运动Bra可调节，工字背，S-XL",
         "source": "1688", "brand": "YogaFlow", "material": "锦纶+莱卡",
         "weight": 0.22, "category": "瑜伽健身"},
        {"title": "女士运动泳池短裤 沙滩两用款", "title_en": "Women's Athletic Swim Shorts Beach Versatile",
         "desc": "宽松运动短裤，内置短裤内衬，防走光设计，适合游泳/健身/沙滩，M-XXL",
         "source": "1688", "brand": "ActiveWave", "material": "聚酯纤维+网眼布",
         "weight": 0.14, "category": "瑜伽健身"},
        # 内衣裤
        {"title": "女士无痕内衣套装 薄款透气", "title_en": "Women's Seamless Underwear Set Light Breathable",
         "desc": "无痕一片式，薄款透气，棉质底档，适合春夏，3条装，M-XL",
         "source": "1688", "brand": "ComfiFit", "material": "锦纶+棉",
         "weight": 0.06, "category": "内衣裤"},
        {"title": "女士蕾丝性感内衣套装 薄纱款", "title_en": "Women's Lace Lingerie Set Sheer Mesh",
         "desc": "法式蕾丝薄纱，3/4罩杯，聚拢型，钢圈可拆卸，70B-90D",
         "source": "1688", "brand": "LaceDream", "material": "蕾丝+锦纶",
         "weight": 0.08, "category": "内衣裤"},
        # 配饰
        {"title": "沙滩度假草帽 宽檐防晒", "title_en": "Beach Resort Straw Hat Wide Brim UV Protection",
         "desc": "东南亚进口拉菲草，宽檐防晒，可折叠收纳，配发绳，沙滩拍照凹造型必备",
         "source": "1688", "brand": "StrawLux", "material": "拉菲草",
         "weight": 0.12, "category": "配饰"},
        {"title": "女士防水平光泳镜 游泳潜水镜", "title_en": "Women's Anti-Fog Swimming Goggles UV Protection",
         "desc": "防雾防UV镜片，硅胶密封圈不勒眼，可调节鼻扣，适合游泳/浮潜/冲浪",
         "source": "1688", "brand": "AquaPro", "material": "硅胶+PC镜片",
         "weight": 0.05, "category": "配饰"},
        {"title": "女士沙滩长裙 波西米亚风", "title_en": "Women's Beach Maxi Dress Bohemian Style",
         "desc": "波西米亚印花长裙，轻薄雪纺面料，海边度假/拍照/日常皆可，可做罩衫",
         "source": "1688", "brand": "BohoBeach", "material": "雪纺",
         "weight": 0.18, "category": "沙滩度假"},
        {"title": "女士沙滩防水手机袋 挂脖款", "title_en": "Women's Waterproof Phone Pouch Neck Strap",
         "desc": "IPX8防水等级，可装6.7寸手机，触屏灵敏，挂脖设计，沙滩/泳池必备",
         "source": "1688", "brand": "BeachTech", "material": "PVC+TPU",
         "weight": 0.04, "category": "配饰"},
    ]

    all_skus = []
    all_inventory = []

    for i, pd in enumerate(product_data):
        status = random.choices(PRODUCT_STATUSES, weights=[15, 30, 40, 10, 5])[0]
        product_code = f"PRD{datetime.now().year}{(i+1):04d}"
        product = {
            "title": pd["title"],
            "title_en": pd["title_en"],
            "description": pd["desc"],
            "source_platform": pd["source"],
            "product_code": product_code,
            "brand": pd["brand"],
            "material": pd["material"],
            "weight": pd["weight"],
            "images": json.dumps([
                img_placeholder(pd["title"], 400),
                img_placeholder(pd["title"] + "-2", 400),
                img_placeholder(pd["title"] + "-3", 400),
            ], ensure_ascii=False),
            "status": status,
            "sku_count": 0,  # 后续更新
            "category_id": random.randint(1, 8),
            "created_at": rand_time(60, 0),
            "updated_at": rand_time(5, 0),
        }
        products.append(product)

    # 写入商品，获取自增ID
    conn.execute("DELETE FROM products")
    for p in products:
        cols = list(p.keys())
        vals = tuple(p[c] for c in cols)
        placeholders = ", ".join(["?"] * len(cols))
        conn.execute(f"INSERT INTO products ({','.join(cols)}) VALUES ({placeholders})", vals)
    conn.commit()

    # 重新查询获取ID
    cur = conn.execute("SELECT id, title, product_code FROM products")
    product_rows = cur.fetchall()

    # 2-4. SKU（每个商品 1-4 个 SKU）
    print("  [-] SKU...")
    swim_colors = ["黑色", "白色", "红色", "粉色", "蓝色", "绿色", "紫色", "橙色", "米白", "豹纹"]
    for pr in product_rows:
        pid = pr["id"]
        title = pr["title"]
        product_code = pr["product_code"]
        num_skus = random.randint(1, 4)
        sku_prices = sorted([round(random.uniform(8, 120), 2) for _ in range(num_skus)], reverse=True)
        for j in range(num_skus):
            attrs = {
                "颜色": random.choice(swim_colors),
                "尺码": random.choice(SWIM_SIZES_CN),
            }
            if num_skus >= 3:
                attrs["款式"] = random.choice(["比基尼上装", "比基尼下装", "连体款", "分体款"])
            elif num_skus == 2:
                attrs["套装"] = random.choice(["单件", "两件套", "三件套"])
            sku = {
                "product_id": pid,
                "sku_code": f"{pr['product_code']}-SKU{j+1:02d}",
                "sku_name": f"{title} - {attrs.get('颜色', '默认')}",
                "source_price": sku_prices[j] if j < len(sku_prices) else sku_prices[0],
                "attributes": json.dumps({**attrs, "index": j+1}, ensure_ascii=False),
                "images": json.dumps([img_placeholder(f"{title}-SKU{j}", 300)], ensure_ascii=False),
                "weight": round(random.uniform(0.05, 2.5), 3),
                "created_at": rand_time(50, 0),
                "updated_at": rand_time(5, 0),
            }
            all_skus.append(sku)

    bulk_insert(conn, "product_skus", all_skus)

    # 更新商品 SKU 计数
    for pr in product_rows:
        cur = conn.execute("SELECT COUNT(*) as cnt FROM product_skus WHERE product_id=?", (pr["id"],))
        cnt = cur.fetchone()[0]
        conn.execute("UPDATE products SET sku_count=? WHERE id=?", (cnt, pr["id"]))
    conn.commit()

    # 2-5. 库存（每个 SKU 至少有一条库存记录）
    print("  [-] 库存...")
    cur = conn.execute("SELECT id, source_price FROM product_skus")
    sku_rows = cur.fetchall()
    shop_cur = conn.execute("SELECT id FROM shops WHERE status='active'")
    shop_ids = [r["id"] for r in shop_cur.fetchall()]

    for sr in sku_rows:
        sku_id = sr["id"]
        # 全局库存（shop_id=NULL）
        global_inv = {
            "sku_id": sku_id,
            "shop_id": None,
            "available_stock": random.randint(0, 500),
            "reserved_stock": random.randint(0, 20),
            "low_stock_threshold": random.choice([5, 10, 20, 30]),
            "last_sync_at": rand_time(1, 0),
            "created_at": rand_time(40, 0),
            "updated_at": rand_time(1, 0),
        }
        all_inventory.append(global_inv)

        # 店铺级库存（随机 1-3 家店）
        for shop_id in random.sample(shop_ids, min(random.randint(1, 3), len(shop_ids))):
            shop_inv = {
                "sku_id": sku_id,
                "shop_id": shop_id,
                "available_stock": random.randint(0, 200),
                "reserved_stock": random.randint(0, 10),
                "low_stock_threshold": random.choice([5, 10, 15]),
                "last_sync_at": rand_time(1, 0),
                "created_at": rand_time(30, 0),
                "updated_at": rand_time(1, 0),
            }
            all_inventory.append(shop_inv)

    bulk_insert(conn, "inventory", all_inventory)

    # 2-6. 刊登记录（shop_products）
    print("  [-] 刊登记录...")
    shop_products = []
    for pr in product_rows:
        pid = pr["id"]
        sku_cur = conn.execute("SELECT id FROM product_skus WHERE product_id=?", (pid,))
        sku_ids = [r["id"] for r in sku_cur.fetchall()]
        if not sku_ids:
            continue
        # 随机刊登到 1-4 家店
        target_shops = random.sample(shop_ids, min(random.randint(1, 4), len(shop_ids)))
        # 查询每个 SKU 的进价（刊登需要用进价计算售价）
        price_map = {}
        for sid in sku_ids:
            cur = conn.execute("SELECT source_price FROM product_skus WHERE id=?", (sid,))
            row = cur.fetchone()
            price_map[sid] = row["source_price"] if row else 0
        for shop_id in target_shops:
            for sku_id in sku_ids[:random.randint(1, len(sku_ids))]:
                base_price = price_map.get(sku_id, 0)
                price = round(base_price * random.uniform(1.3, 1.6), 2)
                sp = {
                    "product_id": pid,
                    "shop_id": shop_id,
                    "sku_id": sku_id,
                    "price": price,
                    "stock": random.randint(0, 100),
                    "publish_status": random.choices(PUBLISH_STATUSES, weights=[10, 70, 15, 5])[0],
                    "published_at": rand_time(30, 0),
                    "created_at": rand_time(30, 0),
                    "updated_at": rand_time(5, 0),
                }
                shop_products.append(sp)
    bulk_insert(conn, "shop_products", shop_products)

    # 2-7. 采集历史
    print("  [-] 采集历史...")
    collect_history = []
    for i in range(1, 31):
        platform = random.choice(PLATFORMS)
        url_base = f"https://www.{platform}.com/item/{random.randint(100000, 999999)}"
        status = random.choices(["success", "failed", "pending"], weights=[70, 20, 10])[0]
        ch = {
            "platform": platform,
            "source_url": url_base,
            "title": f"【{platform}采集】商品编号 {random.randint(10000, 99999)}",
            "status": status,
            "product_id": random.randint(1, len(product_rows)) if status == "success" else None,
            "error_message": "网络超时，请重试" if status == "failed" else None,
            "created_at": rand_time(30, 0),
        }
        collect_history.append(ch)
    bulk_insert(conn, "collect_history", collect_history)

    # 2-8. 汇率
    print("  [-] 汇率...")
    exchange_rates = [
        {"from_currency": "USD", "to_currency": "CNY", "rate": 7.25, "updated_at": days_ago(0)},
        {"from_currency": "EUR", "to_currency": "CNY", "rate": 7.85, "updated_at": days_ago(0)},
        {"from_currency": "GBP", "to_currency": "CNY", "rate": 9.15, "updated_at": days_ago(0)},
        {"from_currency": "USD", "to_currency": "EUR", "rate": 0.92, "updated_at": days_ago(0)},
        {"from_currency": "USD", "to_currency": "GBP", "rate": 0.79, "updated_at": days_ago(0)},
        {"from_currency": "USD", "to_currency": "MYR", "rate": 4.72, "updated_at": days_ago(0)},
        {"from_currency": "USD", "to_currency": "THB", "rate": 35.50, "updated_at": days_ago(0)},
        {"from_currency": "USD", "to_currency": "PHP", "rate": 56.20, "updated_at": days_ago(0)},
        {"from_currency": "USD", "to_currency": "SGD", "rate": 1.35, "updated_at": days_ago(0)},
        {"from_currency": "USD", "to_currency": "RUB", "rate": 92.50, "updated_at": days_ago(0)},
    ]
    bulk_insert(conn, "exchange_rates", exchange_rates)

    conn.close()
    print(f"  [OK] shop_manager.db 完成：{len(shops)} 店铺 | {len(products)} 商品 | "  # NOCHARS
          f"{len(all_skus)} SKU | {len(all_inventory)} 库存记录 | "
          f"{len(pricing_rules)} 定价规则 | {len(shop_products)} 刊登记录 | "
          f"{len(collect_history)} 采集历史 | {len(exchange_rates)} 汇率")


# ==============================================================================
# 模块三：platform_sync.db — 订单、退款、评价
# ==============================================================================
def build_sync_db():
    print("\n[3/3] 生成 platform_sync.db 演示数据...")
    conn = get_conn(SYNC_DB)

    # 初始化 schema
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sync_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id TEXT UNIQUE, platform TEXT, customer_id TEXT, customer_name TEXT,
                status TEXT, total_amount REAL, currency TEXT, items_count INTEGER,
                payment_method TEXT, shipping_address TEXT, raw_data TEXT,
                created_at TEXT, updated_at TEXT, synced_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sync_returns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                return_id TEXT UNIQUE, order_id TEXT, platform TEXT, customer_id TEXT,
                customer_name TEXT, type TEXT, reason TEXT, status TEXT, amount REAL,
                currency TEXT, raw_data TEXT, created_at TEXT, updated_at TEXT,
                synced_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sync_reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                review_id TEXT UNIQUE, order_id TEXT, platform TEXT, customer_id TEXT,
                customer_name TEXT, star_rating INTEGER, content TEXT, product_name TEXT,
                product_image TEXT, reply_content TEXT, status TEXT, review_date TEXT,
                raw_data TEXT, synced_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sync_exchange_rates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                base_currency TEXT, target_currency TEXT, rate REAL,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(base_currency, target_currency)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sync_status (
                id INTEGER PRIMARY KEY,
                platform TEXT, last_sync TEXT, sync_status TEXT,
                error_message TEXT, order_count INTEGER, updated_at TEXT
            )
        """)
        conn.commit()
    except Exception as e:
        print(f"  [!] Schema init: {e}")

    for t in ["sync_orders", "sync_returns", "sync_reviews", "sync_status"]:
        clear_table(conn, t)

    # 3-1. 平台同步订单
    print("  [-] 平台订单...")
    ORDER_STATUSES = [
        "pending", "processing", "shipped", "delivered", "cancelled",
        "refund_requested", "refunded", "disputed"
    ]
    PAYMENT_METHODS = ["PayPal", "信用卡", "本地钱包", "银行转账", "货到付款"]
    orders = []
    for i in range(1, 81):  # 80 条订单
        platform = random.choice(PLATFORMS)
        status = random.choices(ORDER_STATUSES, weights=[10, 15, 25, 25, 8, 7, 5, 5])[0]
        currency = "USD" if random.random() > 0.3 else random.choice(["EUR", "GBP", "BRL"])
        country = random.choice(COUNTRIES)
        total = round(random.uniform(10, 500), 2)
        order = {
            "order_id": gen_order_id(platform, i),
            "platform": platform,
            "customer_id": gen_customer_id(platform, i),
            "customer_name": gen_en_name(),
            "status": status,
            "total_amount": total,
            "currency": currency,
            "items_count": random.randint(1, 5),
            "payment_method": random.choice(PAYMENT_METHODS),
            "shipping_address": json.dumps({
                "country": country,
                "city": f"City_{random.randint(1, 100)}",
                "zip": f"{random.randint(10000, 99999)}",
                "address": f"{random.randint(1, 999)} Main Street, Apt {random.randint(1, 50)}",
            }, ensure_ascii=False),
            "raw_data": json.dumps({
                "platform_order_id": f"{platform.upper()}ORDER{i:08d}",
                "phone": f"+1{random.randint(2000000000, 9999999999)}",
                "email": f"buyer{i:04d}@swim.demo",
                "items": [{"name": random.choice([
                    "黑色比基尼套装 S", "连体泳衣 M 深蓝", "分体泳装 L 碎花",
                    "运动款泳衣 XL", "儿童连体泳装 130", "男士沙滩裤 L",
                ])}],
            }, ensure_ascii=False),
            "created_at": rand_time(60, 0),
            "updated_at": rand_time(15, 0),
            "synced_at": rand_time(1, 0),
        }
        orders.append(order)
    bulk_insert(conn, "sync_orders", orders)

    # 3-2. 退款记录
    print("  [-] 平台退款...")
    RETURN_STATUSES = ["pending", "approved", "rejected", "received", "refunded", "cancelled"]
    returns = []
    for i in range(1, 31):
        platform = random.choice(PLATFORMS)
        status = random.choice(RETURN_STATUSES)
        currency = "USD"
        return_record = {
            "return_id": f"RET{datetime.now().year}{i:06d}",
            "order_id": gen_order_id(platform, random.randint(1, 80)),
            "platform": platform,
            "customer_id": gen_customer_id(platform, random.randint(1, 80)),
            "customer_name": gen_en_name(),
            "type": random.choice(["退款", "退货退款", "换货"]),
            "reason": random.choice(AS_REASON_CATEGORIES),
            "status": status,
            "amount": round(random.uniform(5, 150), 2),
            "currency": currency,
            "raw_data": json.dumps({"reason_detail": random.choice(["泳装面料与描述不符", "尺码偏差较大", "色差严重", "做工有瑕疵"])}, ensure_ascii=False),
            "created_at": rand_time(30, 0),
            "updated_at": rand_time(5, 0),
            "synced_at": rand_time(1, 0),
        }
        returns.append(return_record)
    bulk_insert(conn, "sync_returns", returns)

    # 3-3. 平台评价（核心！要精进）
    print("  [-] 平台评价...")
    reviews = []

    # 多语言好评内容（泳装/女装）
    POSITIVE_MULTI = {
        "en": [
            "Absolutely love this bikini! Great fabric quality and not see-through at all. Fits perfectly! ⭐⭐⭐⭐⭐",
            "Great value for money, quality exceeded my expectations. The color is even prettier in person!",
            "Perfect swimsuit, well packaged and arrived quickly. Very satisfied with the fit!",
            "Excellent seller, responsive and helpful. Swimsuit is exactly as described.",
            "Very good quality fabric, comfortable and looks exactly like the photos. Love it!",
            "Five stars! Everything was perfect from ordering to delivery. The packaging was beautiful!",
            "Impressed with the quality and packaging. Highly recommend this seller for swimwear!",
            "Super fast shipping and the swimsuit is exactly what I wanted. Perfect for beach vacation!",
            "Beautiful bikini, great quality. Thank you so much for the excellent service!",
            "Outstanding swimsuit, fast delivery. This is my second purchase and still satisfied!",
        ],
        "de": [
            "Sehr gute Badeanzug Qualität, schnelle Lieferung! Danke für das tolle Produkt.",
            "Ausgezeichnet! Entspricht genau der Beschreibung, sehr zufrieden mit der Passform.",
            "Gute Qualität, schneller Versand. Gerne wieder! Perfekt für den Strand!",
        ],
        "fr": [
            "Excellent bikini! Livraison très rapide. Je recommande ce vendeur!",
            "Très bonne qualité, conforme à la description. Merci beaucoup! Le tissu est magnifique.",
            "Parfait! Expédition rapide, bikini impeccable. J'adore!",
        ],
        "es": [
            "¡Excelente bikini! Llegó muy rápido, estoy muy satisfechos con la calidad.",
            "Muy buena calidad, igual que en las fotos. ¡Gracias! Perfecto para la playa.",
            "Producto perfecto, envío rápido. ¡Cinco estrellas! El ajuste es perfecto.",
        ],
        "ru": [
            "Отличное бикини! Быстрая доставка, качество отличное. Спасибо!",
            "Хорошее качество, соответствует описанию. Рекомендую! Пляжный сезон открыт!",
            "Посылка пришла быстро. Товар как на картинке. Спасибо продавцу!",
        ],
    }
    NEGATIVE_MULTI = {
        "en": [
            "Swimsuit arrived damaged. The strap was torn. Very disappointed with the quality.",
            "Not as described at all. The color is completely different from photos. Requesting refund.",
            "Arrived with broken stitching. Packaging was terrible. Requesting full refund.",
            "Fabric is very thin and see-through. Cannot use it. Extremely disappointed.",
            "Item size is way too small. Cannot even fit. Size chart was completely wrong.",
        ],
        "de": [
            "Badeanzug kam beschädigt an. Sehr enttäuscht mit der Qualität.",
            "Nicht wie beschrieben. Die Farbe ist völlig anders als auf den Fotos.",
        ],
        "fr": [
            "Maillot de bain arrivé endommagé. Très déçu avec la qualité.",
            "Ne correspond pas à la description. La taille est complètement différente.",
        ],
    }

    # 生成 100 条评价，覆盖所有星级、状态、平台
    for i in range(1, 101):
        platform = PLATFORMS[i % len(PLATFORMS)]
        star = STAR_RATINGS[i % len(STAR_RATINGS)]
        is_neg = star <= 2
        status = "pending" if (is_neg and i % 3 == 0) else (
            random.choices(["replied", "auto_replied", "pending"], weights=[40, 30, 30])[0]
            if not is_neg else
            random.choices(["pending", "replied", "auto_replied"], weights=[40, 35, 25])[0]
        )
        lang = random.choice(["en", "en", "en", "de", "fr", "es", "ru"])

        if is_neg:
            content_pool = NEGATIVE_MULTI.get(lang, NEGATIVE_MULTI["en"])
        else:
            content_pool = POSITIVE_MULTI.get(lang, POSITIVE_MULTI["en"])
        content = random.choice(content_pool)

        customer_name = gen_en_name()
        product_name = random.choice([
            "Women's Bikini 3-Piece Set Bandeau", "Women's High Waist Bikini Retro",
            "Women's Surfing Rash Guard UPF50+", "Women's Ruffle 2-Piece Bikini Set",
            "Women's Leopard Print Bikini", "Women's Halter Neck Bikini Rhinestones",
            "Women's Deep V One-Piece Cutout", "Women's Polka Dot One-Piece Ruffle",
            "Women's Tummy Control One-Piece Ruched", "Women's Plus Size One-Piece",
            "Women's Beach Cover Up Lace", "Women's UV Protection Beach Tunic",
            "Women's Yoga Set Sports Bra + Leggings", "Women's Athletic Swim Shorts",
            "Women's Seamless Underwear Set", "Women's Lace Lingerie Set Sheer Mesh",
            "Beach Resort Straw Hat Wide Brim", "Anti-Fog Swimming Goggles UV",
            "Women's Beach Maxi Dress Bohemian", "Waterproof Phone Pouch Beach",
        ])
        review = {
            "review_id": gen_review_id(platform, i),
            "order_id": gen_order_id(platform, random.randint(1, 80)),
            "platform": platform,
            "customer_id": gen_customer_id(platform, random.randint(1, 80)),
            "customer_name": customer_name,
            "star_rating": star,
            "content": content,
            "product_name": product_name,
            "product_image": img_placeholder(product_name, 200),
            "reply_content": random.choice(REPLY_TEMPLATES) if status in ["replied", "auto_replied"] else None,
            "status": status,
            "review_date": rand_time(60, 0),
            "raw_data": json.dumps({
                "original_language": lang,
                "helpful_count": random.randint(0, 50),
                "verified_purchase": random.randint(0, 1),
            }, ensure_ascii=False),
            "synced_at": rand_time(1, 0),
        }
        reviews.append(review)
    bulk_insert(conn, "sync_reviews", reviews)

    # 3-4. 同步状态记录
    print("  [-] 同步状态...")
    sync_statuses = []
    for platform in PLATFORMS:
        ss = {
            "platform": platform,
            "last_sync": rand_time(0, 0),
            "sync_status": random.choice(["success", "success", "success", "partial", "failed"]),
            "error_message": random.choice([None, None, None, "API rate limit exceeded", "Authentication expired"]),
            "order_count": random.randint(100, 5000),
            "updated_at": rand_time(1, 0),
        }
        sync_statuses.append(ss)
    bulk_insert(conn, "sync_status", sync_statuses)

    # 3-5. 汇率
    print("  [-] 汇率...")
    sync_rates = [
        {"base_currency": "USD", "target_currency": "CNY", "rate": 7.25, "updated_at": days_ago(0)},
        {"base_currency": "EUR", "target_currency": "USD", "rate": 1.09, "updated_at": days_ago(0)},
        {"base_currency": "GBP", "target_currency": "USD", "rate": 1.27, "updated_at": days_ago(0)},
    ]
    bulk_insert(conn, "sync_exchange_rates", sync_rates)

    conn.close()
    print(f"  [OK] platform_sync.db 完成：{len(orders)} 订单 | {len(returns)} 退款 | "  # NOCHARS
          f"{len(reviews)} 评价 | {len(sync_statuses)} 平台同步状态")


# ==============================================================================
# 汇总报告
# ==============================================================================
def print_summary():
    print("\n" + "=" * 60)
    print("  演示数据生成完毕！")
    print("=" * 60)

    def count_table(conn, table):
        try:
            cur = conn.execute(f"SELECT COUNT(*) as c FROM {table}")
            return cur.fetchone()[0]
        except:
            return "?"

    for db_path, db_name in [(SELLER_DB, "seller.db"), (SHOP_DB, "shop_manager.db"), (SYNC_DB, "platform_sync.db")]:
        if db_path.exists():
            conn = get_conn(db_path)
            cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
            tables = [r["name"] for r in cur.fetchall()]
            conn.close()
            print(f"\n  [{db_name}]")
            for t in tables:
                conn = get_conn(db_path)
                cnt = count_table(conn, t)
                conn.close()
                print(f"    {t:<25} {cnt:>6} 条")
    print()


# ==============================================================================
# 入口
# ==============================================================================
if __name__ == "__main__":
    print("=" * 60)
    print("  Ruitalk 演示数据生成脚本 v1.0")
    print("  覆盖：客户·会话·坐席·售后·售前·快捷回复·通知·审计·店铺·商品·SKU·库存·定价·刊登·采集·平台评价")
    print("=" * 60)
    build_seller_db()
    # 补充 seller.db 中 reviews / reply_templates / auto_reply_rules 数据
    rev_cnt, tmpl_cnt, rule_cnt = _write_reviews_to_seller_db()
    print(f"  [OK] seller.db 补充：{rev_cnt} 评价 | {tmpl_cnt} 回复模板 | {rule_cnt} 自动回复规则")
    build_shop_db()
    build_sync_db()
    print_summary()
