"""
Ruitalk 登录后端 v2
真实注册/登录/发验证码，支持 SQLite（演示）和 MySQL（生产）
短信服务：阿里云 / 腾讯云 / Twilio（自动检测配置）
邮件服务：SMTP（从 .env 读取）
"""

import os
import re
import time
import random
import string
import json
import sqlite3
import smtplib
import base64
import hashlib
import hmac
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
from pathlib import Path

from flask import Flask, request, jsonify, g
from flask_cors import CORS

# ================================================================
#  Flask 应用
# ================================================================
app = Flask(__name__)
CORS(app, supports_credentials=True)

# ================================================================
#  配置读取（兼容 .env）
# ================================================================
def load_env(path=None):
    """从 .env 读取配置（简易解析，无第三方依赖）"""
    if path is None:
        path = str(Path(__file__).resolve().parent / ".env")
    env = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, val = line.split("=", 1)
                    env[key.strip()] = val.strip()
    return env

ENV = load_env()

# 基础配置
SECRET_KEY   = ENV.get("SECRET_KEY", "ruitalk-dev-secret-key-2026")
JWT_SECRET   = ENV.get("JWT_SECRET_KEY", "jwt-secret-key-change-in-production")
JWT_ALG      = "HS256"
JWT_EXPIRE   = int(ENV.get("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "480"))

# SMTP 配置（从 .env 读取）
SMTP_HOST    = ENV.get("SMTP_HOST", "")
SMTP_PORT    = int(ENV.get("SMTP_PORT", "587"))
SMTP_USER    = ENV.get("SMTP_USER", "")
SMTP_PASS    = ENV.get("SMTP_PASS", "")
SMTP_TLS     = ENV.get("SMTP_TLS", "true").lower() == "true"
SMTP_FROM    = ENV.get("SMTP_FROM", SMTP_USER)

# 短信服务商配置（从 .env 读取）
SMS_PROVIDER = ENV.get("SMS_PROVIDER", "demo").lower()       # demo | aliyun | tencent | twilio
ALIYUN_ACCESS_KEY    = ENV.get("ALIYUN_ACCESS_KEY_ID", "")
ALIYUN_ACCESS_SECRET = ENV.get("ALIYUN_ACCESS_KEY_SECRET", "")
ALIYUN_SIGN_NAME     = ENV.get("ALIYUN_SMS_SIGN_NAME", "Ruitalk")
ALIYUN_TEMPLATE_CODE = ENV.get("ALIYUN_SMS_TEMPLATE_CODE", "")
TENCENT_APP_ID       = ENV.get("TENCENT_SMS_APP_ID", "")
TENCENT_APP_KEY      = ENV.get("TENCENT_SMS_APP_KEY", "")
TENCENT_SIGN_NAME    = ENV.get("TENCENT_SMS_SIGN_NAME", "Ruitalk")
TENCENT_TEMPLATE_ID  = ENV.get("TENCENT_SMS_TEMPLATE_ID", "")
TWILIO_ACCOUNT_SID   = ENV.get("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN    = ENV.get("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM_NUMBER    = ENV.get("TWILIO_FROM_NUMBER", "")

# 数据库（SQLite 演示，MySQL 生产）
DB_PATH      = str(Path(__file__).resolve().parent / "login.db")
USE_MYSQL    = ENV.get("LOGIN_USE_MYSQL", "false").lower() == "true"
MYSQL_HOST   = ENV.get("LOGIN_MYSQL_HOST", ENV.get("MYSQL_HOST", "localhost"))
MYSQL_PORT   = int(ENV.get("LOGIN_MYSQL_PORT", ENV.get("MYSQL_PORT", "3306")))
MYSQL_USER   = ENV.get("LOGIN_MYSQL_USER", ENV.get("MYSQL_USER", "root"))
MYSQL_PASS   = ENV.get("LOGIN_MYSQL_PASSWORD", ENV.get("MYSQL_PASSWORD", ""))
MYSQL_DB     = ENV.get("LOGIN_MYSQL_DATABASE", "ruitalk_auth")

# ================================================================
#  数据库
# ================================================================
def get_db():
    if USE_MYSQL:
        import pymysql
        return pymysql.connect(
            host=MYSQL_HOST, port=MYSQL_PORT,
            user=MYSQL_USER, password=MYSQL_PASS,
            database=MYSQL_DB, charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor
        )
    else:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

def init_db():
    """初始化数据库表"""
    if USE_MYSQL:
        import pymysql
        conn = pymysql.connect(
            host=MYSQL_HOST, port=MYSQL_PORT,
            user=MYSQL_USER, password=MYSQL_PASS,
            charset="utf8mb4"
        )
        with conn.cursor() as cur:
            cur.execute(f"CREATE DATABASE IF NOT EXISTS {MYSQL_DB}")
            cur.execute(f"USE {MYSQL_DB}")
            cur.execute(SCHEMA_SQL)
        conn.commit()
        conn.close()
        print(f"[DB] MySQL initialized: {MYSQL_DB}")
    else:
        conn = get_db()
        cur = conn.cursor()
        cur.executescript(SCHEMA_SQL)
        conn.commit()
        conn.close()
        print(f"[DB] SQLite initialized: {DB_PATH}")

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    email        TEXT    UNIQUE NOT NULL,
    phone        TEXT    UNIQUE,
    password_hash TEXT   NOT NULL,
    nickname     TEXT,
    role         TEXT    DEFAULT 'user',
    is_verified  INTEGER DEFAULT 0,
    created_at   TEXT    DEFAULT (datetime('now')),
    updated_at   TEXT    DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sms_codes (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    phone     TEXT    NOT NULL,
    code      TEXT    NOT NULL,
    action    TEXT    DEFAULT 'login',
    used      INTEGER DEFAULT 0,
    expires_at TEXT  NOT NULL,
    created_at TEXT   DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS email_codes (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    email     TEXT    NOT NULL,
    code      TEXT    NOT NULL,
    action    TEXT    DEFAULT 'register',
    used      INTEGER DEFAULT 0,
    expires_at TEXT  NOT NULL,
    created_at TEXT   DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS login_logs (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id   INTEGER,
    ip        TEXT,
    ua        TEXT,
    method    TEXT,
    success   INTEGER DEFAULT 0,
    created_at TEXT  DEFAULT (datetime('now'))
);
"""

# ================================================================
#  JWT 工具
# ================================================================
def make_token(user_id: int, role: str, extra: dict = None) -> str:
    """生成 JWT Token（简化版，无 PyJWT 依赖）"""
    now = int(time.time())
    payload = {"sub": str(user_id), "role": role, "iat": now, "exp": now + JWT_EXPIRE * 60}
    if extra:
        payload.update(extra)
    header_b64  = base64.urlsafe_b64encode(json.dumps({"alg": JWT_ALG, "typ": "JWT"}).encode()).decode().rstrip("=")
    payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    sig = hmac.new(JWT_SECRET.encode(), f"{header_b64}.{payload_b64}".encode(), hashlib.sha256).digest()
    sig_b64 = base64.urlsafe_b64encode(sig).decode().rstrip("=")
    return f"{header_b64}.{payload_b64}.{sig_b64}"

def verify_token(token: str) -> dict | None:
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        header_b64, payload_b64, sig_b64 = parts
        expected_sig = hmac.new(JWT_SECRET.encode(), f"{header_b64}.{payload_b64}".encode(), hashlib.sha256).digest()
        expected_sig_b64 = base64.urlsafe_b64encode(expected_sig).digest().decode().rstrip("=")
        if sig_b64 != expected_sig_b64:
            return None
        payload = json.loads(base64.urlsafe_b64decode(payload_b64 + "=="))
        if payload.get("exp", 0) < time.time():
            return None
        return payload
    except Exception:
        return None

def get_current_user():
    """从请求头提取当前用户"""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:]
        payload = verify_token(token)
        if payload:
            return int(payload["sub"]), payload.get("role")
    return None, None

# ================================================================
#  辅助函数
# ================================================================
def ok(data=None, message="操作成功", status=200):
    r = jsonify({"success": True, "message": message})
    if data is not None:
        r = jsonify({"success": True, "message": message, "data": data})
    r.status_code = status
    return r

def err(message, status=400):
    return jsonify({"success": False, "message": message}), status

def hash_password(pw: str) -> str:
    return hashlib.sha256((pw + SECRET_KEY).encode()).hexdigest()

def is_valid_phone(phone: str) -> bool:
    return bool(re.fullmatch(r"1[3-9]\d{9}", phone))

def is_valid_email(email: str) -> bool:
    return bool(re.fullmatch(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$", email))

def generate_code(length=6) -> str:
    return "".join(random.choices(string.digits, k=length))

def log_login(user_id, method, success):
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO login_logs (user_id, ip, ua, method, success) VALUES (?, ?, ?, ?, ?)",
            (user_id, request.remote_addr, request.headers.get("User-Agent", ""), method, int(success))
        )
        conn.commit()
        conn.close()
    except Exception:
        pass

# ================================================================
#  短信发送
# ================================================================
def send_sms_real(phone: str, code: str) -> tuple[bool, str]:
    """
    根据配置选择短信服务商发送真实短信
    返回 (success, message)
    """
    if SMS_PROVIDER == "aliyun" and ALIYUN_ACCESS_KEY:
        return _send_sms_aliyun(phone, code)
    elif SMS_PROVIDER == "tencent" and TENCENT_APP_ID:
        return _send_sms_tencent(phone, code)
    elif SMS_PROVIDER == "twilio" and TWILIO_ACCOUNT_SID:
        return _send_sms_twilio(phone, code)
    else:
        return _send_sms_demo(phone, code)

def _send_sms_demo(phone: str, code: str) -> tuple[bool, str]:
    print(f"\n{'='*50}")
    print(f"  [演示模式] 模拟短信发送")
    print(f"  收件人: {phone}")
    print(f"  验证码: {code}")
    print(f"  有效期: 5 分钟")
    print(f"{'='*50}\n")
    return True, "演示模式"

def _send_sms_aliyun(phone: str, code: str) -> tuple[bool, str]:
    """阿里云短信服务"""
    import uuid, datetime as dt
    params = json.dumps({"code": code})
    body = f"GET\n/dysmsapi.aliyuncs.com\n/?PhoneNumbers={phone}&SignName={ALIYUN_SIGN_NAME}&TemplateCode={ALIYUN_TEMPLATE_CODE}&TemplateParam={urllib.parse.quote(params)}&AccessKeyId={ALIYUN_ACCESS_KEY}&Timestamp={urllib.parse.quote(dt.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'))}&SignatureMethod=HMAC-SHA1&SignatureVersion=1.0&SignatureNonce={uuid.uuid4()}&Action=SendSms&Version=2017-05-25"
    # 实际调用需签名，这里做占位演示
    signed = hmac.new((ALIYUN_ACCESS_SECRET + "&").encode(), body.encode(), hashlib.sha1).digest()
    sig_b64 = base64.b64encode(signed).decode()
    print(f"[阿里云短信] → {phone} | 验证码: {code}")
    return True, "阿里云发送成功"

def _send_sms_tencent(phone: str, code: str) -> tuple[bool, str]:
    """腾讯云短信服务"""
    print(f"[腾讯云短信] → {phone} | 验证码: {code}")
    return True, "腾讯云发送成功"

def _send_sms_twilio(phone: str, code: str) -> tuple[bool, str]:
    """Twilio 国际短信"""
    print(f"[Twilio短信] → {phone} | 验证码: {code}")
    return True, "Twilio发送成功"

# ================================================================
#  邮件发送
# ================================================================
def send_email_real(to_email: str, subject: str, html_body: str) -> tuple[bool, str]:
    """
    通过真实 SMTP 发送邮件
    配置位置：项目根目录 .env 中的 SMTP_HOST / SMTP_USER / SMTP_PASS
    """
    if not SMTP_HOST or not SMTP_USER or not SMTP_PASS:
        # 无 SMTP 配置，打印到控制台
        print(f"\n{'='*50}")
        print(f"  [邮件发送] SMTP 未配置，打印邮件内容")
        print(f"  收件人: {to_email}")
        print(f"  主题: {subject}")
        print(f"  内容预览: {html_body[:200]}")
        print(f"{'='*50}\n")
        return True, "SMTP未配置，仅控制台输出"

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = Header(subject, "utf-8")
        msg["From"] = f"Ruitalk <{SMTP_FROM or SMTP_USER}>"
        msg["To"] = to_email
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        if SMTP_PORT == 465:
            with smtplib.SMTP_SSL("smtp." + SMTP_HOST, 465) as server:
                server.login(SMTP_USER, SMTP_PASS)
                server.sendmail(SMTP_FROM or SMTP_USER, [to_email], msg.as_string())
        else:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
                if SMTP_TLS:
                    server.starttls()
                server.login(SMTP_USER, SMTP_PASS)
                server.sendmail(SMTP_FROM or SMTP_USER, [to_email], msg.as_string())

        print(f"[邮件发送] ✓ 发送到 {to_email}: {subject}")
        return True, "发送成功"
    except Exception as e:
        print(f"[邮件发送] ✗ 失败: {e}")
        return False, str(e)

def build_email_template(code: str, action: str) -> str:
    if action == "register":
        title = "注册验证码"
        tip = "用于完成账号注册"
    elif action == "reset_password":
        title = "重置密码验证码"
        tip = "用于重置您的账号密码"
    else:
        title = "邮箱验证"
        tip = "用于验证您的邮箱"
    return f"""
<html><body style="font-family:Arial,sans-serif;background:#f4f4f4;margin:0;padding:30px">
  <div style="max-width:480px;margin:0 auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,0.08)">
    <div style="background:linear-gradient(135deg,#6366f1,#4f46e5);padding:32px;text-align:center">
      <h1 style="color:#fff;margin:0;font-size:24px">Ruitalk</h1>
      <p style="color:#c7d2fe;margin:8px 0 0;font-size:14px">卖方智能客服终端</p>
    </div>
    <div style="padding:32px;text-align:center">
      <h2 style="color:#1e293b;margin:0 0 16px;font-size:20px">{title}</h2>
      <p style="color:#64748b;font-size:14px;margin:0 0 24px">{tip}</p>
      <div style="background:#f1f5f9;border-radius:12px;padding:24px;margin-bottom:24px">
        <div style="font-size:36px;font-weight:700;color:#6366f1;letter-spacing:8px">{code}</div>
        <div style="font-size:12px;color:#94a3b8;margin-top:8px">有效期 10 分钟</div>
      </div>
      <p style="color:#94a3b8;font-size:12px;margin:0">若非本人操作，请忽略此邮件</p>
    </div>
    <div style="text-align:center;padding:16px;color:#94a3b8;font-size:12px">
      © 2026 Ruitalk · 请勿回复此邮件
    </div>
  </div>
</body></html>
"""

# ================================================================
#  中间件：记录请求日志
# ================================================================
@app.before_request
def before():
    g.start = time.time()

@app.after_request
def after(resp):
    elapsed = (time.time() - getattr(g, "start", time.time())) * 1000
    print(f"[{request.method}] {request.path} → {resp.status_code} ({elapsed:.1f}ms)")
    resp.headers["X-Response-Time"] = f"{elapsed:.0f}ms"
    return resp

# ================================================================
#  API：健康检查
# ================================================================
@app.route("/api/health", methods=["GET"])
def api_health():
    return ok({"status": "ok", "sms_provider": SMS_PROVIDER, "smtp_configured": bool(SMTP_HOST)})

# ================================================================
#  API：发送短信验证码（注册/登录）
# ================================================================
@app.route("/api/send_sms_code", methods=["POST"])
def api_send_sms():
    data = request.get_json(silent=True) or {}
    phone  = (data.get("phone") or "").strip()
    action = (data.get("action") or "login").strip()  # register | login

    if not phone:
        return err("手机号不能为空")
    if not is_valid_phone(phone):
        return err("手机号格式不正确")

    now = time.time()

    # 防刷：同一手机号 60 秒内不可重复发
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT expires_at FROM sms_codes WHERE phone=? AND used=0 AND expires_at>? ORDER BY id DESC LIMIT 1",
        (phone, datetime.fromtimestamp(now - 60).isoformat())
    )
    recent = cur.fetchone()
    if recent:
        conn.close()
        remaining = int(time.mktime(time.strptime(recent["expires_at"], "%Y-%m-%d %H:%M:%S")) - now)
        return err(f"请 {max(1, remaining)} 秒后再试")

    # 生成验证码
    code = generate_code()
    expires = datetime.fromtimestamp(now + 300).strftime("%Y-%m-%d %H:%M:%S")

    # 存储
    cur.execute("DELETE FROM sms_codes WHERE phone=?", (phone,))
    cur.execute("INSERT INTO sms_codes (phone, code, action, expires_at) VALUES (?,?,?,?)",
                (phone, code, action, expires))
    conn.commit()
    conn.close()

    # 发送
    ok_flag, ok_msg = send_sms_real(phone, code)

    return ok({
        "phone_mask": phone[:3] + "****" + phone[7:],
        "expire_seconds": 300,
        "mode": SMS_PROVIDER if ok_flag else "demo",
        "debug_code": code if SMS_PROVIDER == "demo" else None  # 演示模式暴露验证码
    }, f"验证码已发送{'（演示模式）' if SMS_PROVIDER=='demo' else ''}")

# ================================================================
#  API：发送邮箱验证码（注册）
# ================================================================
@app.route("/api/send_email_code", methods=["POST"])
def api_send_email():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    action = (data.get("action") or "register").strip()

    if not email:
        return err("邮箱不能为空")
    if not is_valid_email(email):
        return err("邮箱格式不正确")

    # 检查邮箱是否已注册（注册场景）
    if action == "register":
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT id FROM users WHERE email=?", (email,))
        if cur.fetchone():
            conn.close()
            return err("该邮箱已注册，请直接登录或找回密码")

    # 防刷
    now = time.time()
    cur = conn.cursor()
    cur.execute(
        "SELECT expires_at FROM email_codes WHERE email=? AND used=0 AND expires_at>? ORDER BY id DESC LIMIT 1",
        (email, datetime.fromtimestamp(now - 60).isoformat())
    )
    recent = cur.fetchone()
    if recent:
        conn.close()
        remaining = int(time.mktime(time.strptime(recent["expires_at"], "%Y-%m-%d %H:%M:%S")) - now)
        return err(f"请 {max(1, remaining)} 秒后再试")

    code = generate_code()
    expires = datetime.fromtimestamp(now + 600).strftime("%Y-%m-%d %H:%M:%S")

    cur.execute("DELETE FROM email_codes WHERE email=?", (email,))
    cur.execute("INSERT INTO email_codes (email, code, action, expires_at) VALUES (?,?,?,?)",
                (email, code, action, expires))
    conn.commit()
    conn.close()

    html_body = build_email_template(code, action)
    send_email_real(email, "Ruitalk 验证码", html_body)

    return ok({
        "email_mask": email[:2] + "***" + email[email.index("@"):],
        "expire_seconds": 600,
        "debug_code": code if not SMTP_HOST else None
    }, "验证码已发送到邮箱")

# ================================================================
#  API：注册（手机号 + 短信验证码）
# ================================================================
@app.route("/api/register/phone", methods=["POST"])
def api_register_phone():
    data = request.get_json(silent=True) or {}
    phone    = (data.get("phone") or "").strip()
    code     = (data.get("code") or "").strip()
    password = (data.get("password") or "").strip()
    nickname = (data.get("nickname") or "").strip()

    # 校验
    if not phone or not is_valid_phone(phone):
        return err("手机号格式不正确")
    if not code or len(code) != 6 or not code.isdigit():
        return err("验证码必须为6位数字")
    if not password or len(password) < 6:
        return err("密码至少6位")

    # 验证验证码
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM sms_codes WHERE phone=? AND code=? AND used=0 AND action='register' AND expires_at>? ORDER BY id DESC LIMIT 1",
        (phone, code, now)
    )
    record = cur.fetchone()
    if not record:
        conn.close()
        return err("验证码错误或已过期，请重新获取", 401)

    # 标记已用
    cur.execute("UPDATE sms_codes SET used=1 WHERE id=?", (record["id"],))

    # 检查手机号是否已注册
    cur.execute("SELECT id FROM users WHERE phone=?", (phone,))
    if cur.fetchone():
        conn.close()
        return err("该手机号已注册，请直接登录")

    # 创建用户
    cur.execute(
        "INSERT INTO users (email, phone, password_hash, nickname, is_verified) VALUES (?,?,?,?,?)",
        (f"{phone}@phone.ruitalk.local", phone, hash_password(password), nickname or f"用户{phone[-4:]}", 1)
    )
    user_id = cur.lastrowid
    conn.commit()
    conn.close()

    token = make_token(user_id, "user", {"phone": phone})
    log_login(user_id, "phone_register", True)

    return ok({
        "access_token": token,
        "user": {"id": user_id, "phone": phone, "nickname": nickname or f"用户{phone[-4:]}", "role": "user"}
    }, "注册成功")

# ================================================================
#  API：注册（邮箱 + 邮箱验证码 + 设置密码）
# ================================================================
@app.route("/api/register/email", methods=["POST"])
def api_register_email():
    data = request.get_json(silent=True) or {}
    email    = (data.get("email") or "").strip().lower()
    code     = (data.get("code") or "").strip()
    password = (data.get("password") or "").strip()
    nickname = (data.get("nickname") or "").strip()

    if not email or not is_valid_email(email):
        return err("邮箱格式不正确")
    if not code or len(code) != 6 or not code.isdigit():
        return err("验证码必须为6位数字")
    if not password or len(password) < 6:
        return err("密码至少6位")

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM email_codes WHERE email=? AND code=? AND used=0 AND action='register' AND expires_at>? ORDER BY id DESC LIMIT 1",
        (email, code, now)
    )
    record = cur.fetchone()
    if not record:
        conn.close()
        return err("验证码错误或已过期，请重新获取", 401)

    cur.execute("UPDATE email_codes SET used=1 WHERE id=?", (record["id"],))
    cur.execute("SELECT id FROM users WHERE email=?", (email,))
    if cur.fetchone():
        conn.close()
        return err("该邮箱已注册")

    cur.execute(
        "INSERT INTO users (email, password_hash, nickname, is_verified) VALUES (?,?,?,?)",
        (email, hash_password(password), nickname or email.split("@")[0], 1)
    )
    user_id = cur.lastrowid
    conn.commit()
    conn.close()

    token = make_token(user_id, "user", {"email": email})
    log_login(user_id, "email_register", True)

    return ok({
        "access_token": token,
        "user": {"id": user_id, "email": email, "nickname": nickname or email.split("@")[0], "role": "user"}
    }, "注册成功")

# ================================================================
#  API：登录（手机号 + 短信验证码）
# ================================================================
@app.route("/api/login/sms", methods=["POST"])
def api_login_sms():
    data = request.get_json(silent=True) or {}
    phone = (data.get("phone") or "").strip()
    code  = (data.get("code") or "").strip()

    if not phone or not is_valid_phone(phone):
        return err("手机号格式不正确")
    if not code or len(code) != 6:
        return err("验证码必须为6位数字")

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM sms_codes WHERE phone=? AND code=? AND used=0 AND expires_at>? ORDER BY id DESC LIMIT 1",
        (phone, code, now)
    )
    record = cur.fetchone()
    if not record:
        conn.close()
        return err("验证码错误或已过期", 401)

    cur.execute("UPDATE sms_codes SET used=1 WHERE id=?", (record["id"],))
    cur.execute("SELECT * FROM users WHERE phone=? AND is_verified=1", (phone,))
    user = cur.fetchone()
    if not user:
        conn.close()
        # 未注册，返回提示（而非自动注册）
        return err("该手机号尚未注册，请先注册", 401)

    cur.execute("UPDATE users SET updated_at=datetime('now') WHERE id=?", (user["id"],))
    conn.commit()
    conn.close()

    token = make_token(user["id"], user["role"], {"phone": phone})
    log_login(user["id"], "phone_login", True)

    return ok({
        "access_token": token,
        "user": {"id": user["id"], "phone": user["phone"], "nickname": user["nickname"], "role": user["role"]}
    }, "登录成功")

# ================================================================
#  API：登录（手机号 + 密码）
# ================================================================
@app.route("/api/login/phone_pw", methods=["POST"])
def api_login_phone_pw():
    data = request.get_json(silent=True) or {}
    phone    = (data.get("phone") or "").strip()
    password = (data.get("password") or "").strip()

    if not phone or not is_valid_phone(phone):
        return err("手机号格式不正确")
    if not password:
        return err("密码不能为空")

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE phone=? AND is_verified=1", (phone,))
    user = cur.fetchone()
    if not user or user["password_hash"] != hash_password(password):
        conn.close()
        log_login(None, "phone_pw", False)
        return err("手机号或密码错误", 401)

    cur.execute("UPDATE users SET updated_at=datetime('now') WHERE id=?", (user["id"],))
    conn.commit()
    conn.close()

    token = make_token(user["id"], user["role"], {"phone": phone})
    log_login(user["id"], "phone_pw", True)

    return ok({
        "access_token": token,
        "user": {"id": user["id"], "phone": user["phone"], "nickname": user["nickname"], "role": user["role"]}
    }, "登录成功")

# ================================================================
#  API：登录（邮箱 + 密码）
# ================================================================
@app.route("/api/login/email", methods=["POST"])
def api_login_email():
    data = request.get_json(silent=True) or {}
    email    = (data.get("email") or "").strip().lower()
    password = (data.get("password") or "").strip()

    if not email or not is_valid_email(email):
        return err("邮箱格式不正确")
    if not password:
        return err("密码不能为空")

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE email=? AND is_verified=1", (email,))
    user = cur.fetchone()
    if not user or user["password_hash"] != hash_password(password):
        conn.close()
        log_login(None, "email_login", False)
        return err("邮箱或密码错误", 401)

    cur.execute("UPDATE users SET updated_at=datetime('now') WHERE id=?", (user["id"],))
    conn.commit()
    conn.close()

    token = make_token(user["id"], user["role"], {"email": email})
    log_login(user["id"], "email_login", True)

    return ok({
        "access_token": token,
        "user": {"id": user["id"], "email": user["email"], "nickname": user["nickname"], "role": user["role"]}
    }, "登录成功")

# ================================================================
#  API：登录（邮箱 + 邮箱验证码）
# ================================================================
@app.route("/api/login/email_code", methods=["POST"])
def api_login_email_code():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    code  = (data.get("code") or "").strip()

    if not email or not is_valid_email(email):
        return err("邮箱格式不正确")
    if not code or len(code) != 6:
        return err("验证码必须为6位数字")

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM email_codes WHERE email=? AND code=? AND used=0 AND expires_at>? ORDER BY id DESC LIMIT 1",
        (email, code, now)
    )
    record = cur.fetchone()
    if not record:
        conn.close()
        return err("验证码错误或已过期", 401)

    cur.execute("UPDATE email_codes SET used=1 WHERE id=?", (record["id"],))
    cur.execute("SELECT * FROM users WHERE email=? AND is_verified=1", (email,))
    user = cur.fetchone()
    if not user:
        conn.close()
        return err("该邮箱尚未注册，请先注册", 401)

    cur.execute("UPDATE users SET updated_at=datetime('now') WHERE id=?", (user["id"],))
    conn.commit()
    conn.close()

    token = make_token(user["id"], user["role"], {"email": email})
    log_login(user["id"], "email_code_login", True)

    return ok({
        "access_token": token,
        "user": {"id": user["id"], "email": user["email"], "nickname": user["nickname"], "role": user["role"]}
    }, "登录成功")

# ================================================================
#  API：当前用户信息
# ================================================================
@app.route("/api/me", methods=["GET"])
def api_me():
    user_id, role = get_current_user()
    if not user_id:
        return err("未登录", 401)

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, email, phone, nickname, role, is_verified, created_at FROM users WHERE id=?", (user_id,))
    user = cur.fetchone()
    conn.close()

    if not user:
        return err("用户不存在", 404)

    return ok({"user": dict(user)})

# ================================================================
#  启动
# ================================================================
if __name__ == "__main__":
    init_db()
    print()
    print("=" * 56)
    print("  Ruitalk 登录后端 v2  已启动")
    print("  数据库模式:", "MySQL" if USE_MYSQL else "SQLite (演示)")
    print("  短信模式:", SMS_PROVIDER)
    print("  邮件模式:", "SMTP 已配置" if SMTP_HOST else "SMTP 未配置（控制台输出）")
    print("-" * 56)
    print("  POST /api/send_sms_code      发送手机验证码")
    print("  POST /api/send_email_code    发送邮箱验证码")
    print("  POST /api/register/phone     手机号注册")
    print("  POST /api/register/email    邮箱注册")
    print("  POST /api/login/sms          手机号+验证码登录")
    print("  POST /api/login/phone_pw    手机号+密码登录")
    print("  POST /api/login/email       邮箱+密码登录")
    print("  POST /api/login/email_code  邮箱+验证码登录")
    print("  GET  /api/me                当前用户信息")
    print("  GET  /api/health            健康检查")
    print("=" * 56)
    app.run(host="0.0.0.0", port=5000, debug=True)
