# -*- coding: utf-8 -*-
"""
商户注册登录认证模块
支持邮箱/手机号注册和登录，使用 JWT Token 认证
"""
import re
import time
import random
import string
import hashlib
import json
import smtplib
from datetime import datetime, timedelta
import os
from typing import Optional, Dict

from fastapi import APIRouter, Request, HTTPException, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, Field
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header

# 尝试导入配置和数据库
try:
    from config import (
        SECRET_KEY, JWT_SECRET_KEY, JWT_ALGORITHM,
        JWT_ACCESS_TOKEN_EXPIRE_MINUTES, JWT_REFRESH_TOKEN_EXPIRE_DAYS,
        SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, SMTP_TLS, SMTP_FROM,
    )
except ImportError:
    SECRET_KEY = "ruitalk-merchant-secret"
    JWT_SECRET_KEY = "jwt-merchant-secret-key-change-in-production"
    JWT_ALGORITHM = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES = 480
    JWT_REFRESH_TOKEN_EXPIRE_DAYS = 7
    SMTP_HOST = ""
    SMTP_PORT = 587
    SMTP_USER = ""
    SMTP_PASS = ""
    SMTP_TLS = True
    SMTP_FROM = ""

try:
    import jwt
except ImportError:
    import base64, hmac
    def _fake_jwt_encode(payload, secret, algorithm):
        now = int(time.time())
        payload["iat"] = now
        header = {"alg": algorithm, "typ": "JWT"}
        header_b64 = base64.urlsafe_b64encode(json.dumps(header).encode()).decode().rstrip("=")
        payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
        sig = hmac.new(secret.encode(), f"{header_b64}.{payload_b64}".encode(), hashlib.sha256).digest()
        sig_b64 = base64.urlsafe_b64encode(sig).decode().rstrip("=")
        return f"{header_b64}.{payload_b64}.{sig_b64}"
    jwt = type("JwtModule", (), {"encode": _fake_jwt_encode})()

try:
    from db import get_db_path
    import sqlite3
    import threading
    HAS_DB = True
except ImportError:
    HAS_DB = False
    get_db_path = None

# ============== 本地 SQLite 数据库（商户独立存储）===============
_MERCHANT_DB_LOCK = threading.Lock()
_MERCHANT_DB_PATH = None

def _get_merchant_db_path():
    """获取商户数据库路径"""
    global _MERCHANT_DB_PATH
    if _MERCHANT_DB_PATH:
        return _MERCHANT_DB_PATH
    if get_db_path:
        # 复用主数据库目录
        import os
        db_dir = os.path.dirname(get_db_path())
        _MERCHANT_DB_PATH = os.path.join(db_dir, "merchant_auth.db")
    else:
        # 回退到当前目录
        import os
        _MERCHANT_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "merchant_auth.db")
    return _MERCHANT_DB_PATH

def _get_merchant_conn():
    """获取商户数据库连接"""
    db_path = _get_merchant_db_path()
    conn = sqlite3.connect(db_path, check_same_thread=False, timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except Exception:
        pass
    return conn

# ============== 与 main.py 一致的内部测试手机号（.env DEV_PHONE_USERS）==============
def _parse_dev_phone_passwords() -> Dict[str, str]:
    """格式：手机号:密码，多个逗号分隔。用于商户登录页走合成商户 JWT，无需入库。"""
    out: Dict[str, str] = {}
    raw = os.getenv("DEV_PHONE_USERS", "").strip()
    if not raw:
        return out
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        parts = entry.split(":", 1)
        if len(parts) != 2:
            continue
        phone, pw = parts[0].strip(), parts[1].strip()
        if phone and pw:
            out[phone] = pw
    return out


_DEV_PHONE_PASSWORDS: Dict[str, str] = _parse_dev_phone_passwords()
# 合成商户用户 ID，避免与 SQLite 自增冲突；可通过 DEV_MERCHANT_SYNTHETIC_ID 覆盖
DEV_INTERNAL_MERCHANT_ID: int = int(os.getenv("DEV_MERCHANT_SYNTHETIC_ID", "910000000001"))


# ============== 路由实例 ==============
router = APIRouter(prefix="/api/v1/merchant", tags=["商户认证"])

# ============== Pydantic 模型 ==============

class SendSmsCodeRequest(BaseModel):
    phone: str = Field(..., description="手机号")
    action: str = Field(default="login", description="操作类型: login | register")

class SendEmailCodeRequest(BaseModel):
    email: str = Field(..., description="邮箱")
    action: str = Field(default="login", description="操作类型: login | register")

class RegisterPhoneRequest(BaseModel):
    phone: str = Field(..., description="手机号")
    code: str = Field(..., min_length=6, max_length=6, description="验证码")
    password: str = Field(..., min_length=6, description="密码(至少6位)")
    company_name: str = Field(default="", description="公司名称")
    contact_name: str = Field(default="", description="联系人姓名")
    business_type: str = Field(default="individual", description="商户类型: individual(个体户) | company(公司)")

class RegisterEmailRequest(BaseModel):
    email: str = Field(..., description="邮箱")
    code: str = Field(..., min_length=6, max_length=6, description="验证码")
    password: str = Field(..., min_length=6, description="密码(至少6位)")
    company_name: str = Field(default="", description="公司名称")
    contact_name: str = Field(default="", description="联系人姓名")
    business_type: str = Field(default="individual", description="商户类型: individual(个体户) | company(公司)")

class LoginPhoneRequest(BaseModel):
    phone: str = Field(..., description="手机号")
    password: str = Field(..., description="密码")

class LoginPhoneCodeRequest(BaseModel):
    phone: str = Field(..., description="手机号")
    code: str = Field(..., min_length=6, max_length=6, description="验证码")

class LoginEmailRequest(BaseModel):
    email: str = Field(..., description="邮箱")
    password: str = Field(..., description="密码")

class LoginEmailCodeRequest(BaseModel):
    email: str = Field(..., description="邮箱")
    code: str = Field(..., min_length=6, max_length=6, description="验证码")

class RefreshTokenRequest(BaseModel):
    refresh_token: str

# ============== 辅助函数 ==============

def hash_password(password: str) -> str:
    """密码哈希"""
    return hashlib.sha256((password + SECRET_KEY).encode()).hexdigest()

def verify_password(password: str, password_hash: str) -> bool:
    """验证密码"""
    return hash_password(password) == password_hash

def normalize_merchant_phone(phone: str) -> str:
    """统一为 11 位国内手机号（去除空格、+86 等），与发码、校验共用。"""
    if not phone:
        return ""
    digits = re.sub(r"\D", "", str(phone).strip())
    if len(digits) >= 11 and digits.startswith("86"):
        digits = digits[-11:]
    return digits


def normalize_sms_code(code: str) -> str:
    """验证码只保留数字，避免粘贴含空格导致校验失败。"""
    if code is None:
        return ""
    return re.sub(r"\D", "", str(code).strip())[:6]


def is_valid_phone(phone: str) -> bool:
    """验证手机号格式（.env DEV_PHONE_USERS 中的内部号不受 1[3-9] 号段限制）"""
    p = normalize_merchant_phone(phone)
    if p in _DEV_PHONE_PASSWORDS or phone.strip() in _DEV_PHONE_PASSWORDS:
        return True
    return bool(re.fullmatch(r"1[3-9]\d{9}", p))

def is_valid_email(email: str) -> bool:
    """验证邮箱格式"""
    return bool(re.fullmatch(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$", email))


def _admin_jwt_pair_for_dev_phone(phone: str):
    """
    与 main.py 中 DEV_PHONE_USERS 注册的 dev_{phone} 后台账号一致的 JWT，
    使内部号从商户页登录后，八个管理模块能直接拉取 /api/admin/* 数据。
    """
    if phone not in _DEV_PHONE_PASSWORDS:
        return None
    try:
        from jwt_auth import create_access_token as admin_access_token_fn
        from jwt_auth import create_refresh_token as admin_refresh_token_fn
    except ImportError:
        return None
    username = f"dev_{phone}"
    uid = f"dev-{phone}"
    at = admin_access_token_fn(
        subject=username,
        role="admin",
        extra_claims={
            "user_id": uid,
            "username": username,
            "phone": phone,
            "permissions": ["all"],
        },
    )
    rt = admin_refresh_token_fn(subject=username, role="admin")
    return at, rt


def generate_code(length: int = 6) -> str:
    """生成验证码"""
    return "".join(random.choices(string.digits, k=length))

def create_access_token(user_id: int, role: str = "merchant") -> str:
    """创建访问令牌"""
    now = datetime.utcnow()
    expire = now + timedelta(minutes=JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": str(user_id),
        "role": role,
        "type": "access",
        "exp": expire,
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)

def create_refresh_token(user_id: int) -> str:
    """创建刷新令牌"""
    now = datetime.utcnow()
    expire = now + timedelta(days=JWT_REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {
        "sub": str(user_id),
        "type": "refresh",
        "exp": expire,
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)

def verify_token(token: str, token_type: str = "access") -> Optional[dict]:
    """验证令牌"""
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        if payload.get("type") != token_type:
            return None
        return payload
    except:
        return None

def send_sms(phone: str, code: str) -> tuple[bool, str]:
    """发送短信（演示模式直接打印）"""
    print(f"\n{'='*50}")
    print(f"  [商户系统-短信验证码]")
    print(f"  收件人: {phone}")
    print(f"  验证码: {code}")
    print(f"  有效期: 5 分钟")
    print(f"{'='*50}\n")
    return True, "演示模式"

def send_email(to_email: str, subject: str, html_body: str) -> tuple[bool, str]:
    """发送邮件"""
    if not SMTP_HOST or not SMTP_USER or not SMTP_PASS:
        print(f"\n{'='*50}")
        print(f"  [商户系统-邮件验证码]")
        print(f"  收件人: {to_email}")
        print(f"  主题: {subject}")
        print(f"  验证码预览: {html_body[:300]}")
        print(f"{'='*50}\n")
        return True, "SMTP未配置"

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = Header(subject, "utf-8")
        msg["From"] = f"Ruitalk <{SMTP_FROM or SMTP_USER}>"
        msg["To"] = to_email
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        if SMTP_PORT == 465:
            with smtplib.SMTP_SSL(f"smtp.{SMTP_HOST}", 465) as server:
                server.login(SMTP_USER, SMTP_PASS)
                server.sendmail(SMTP_FROM or SMTP_USER, [to_email], msg.as_string())
        else:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
                if SMTP_TLS:
                    server.starttls()
                server.login(SMTP_USER, SMTP_PASS)
                server.sendmail(SMTP_FROM or SMTP_USER, [to_email], msg.as_string())

        return True, "发送成功"
    except Exception as e:
        return False, str(e)

def build_email_template(code: str, action: str, business_type: str = "商户") -> str:
    """构建邮件模板"""
    if action == "register":
        title = "商户注册验证码"
        tip = "用于完成商户账号注册"
    elif action == "reset_password":
        title = "重置密码验证码"
        tip = "用于重置您的商户账号密码"
    else:
        title = "登录验证码"
        tip = "用于验证您的登录身份"

    return f"""
<html><body style="font-family:Arial,sans-serif;background:#f4f4f4;margin:0;padding:30px">
  <div style="max-width:480px;margin:0 auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,0.08)">
    <div style="background:linear-gradient(135deg,#6366f1,#4f46e5);padding:32px;text-align:center">
      <h1 style="color:#fff;margin:0;font-size:24px">Ruitalk</h1>
      <p style="color:#c7d2fe;margin:8px 0 0;font-size:14px">智能客服系统 · {business_type}</p>
    </div>
    <div style="padding:32px;text-align:center">
      <h2 style="color:#1e293b;margin:0 0 16px;font-size:20px">{title}</h2>
      <p style="color:#64748b;font-size:14px;margin:0 0 24px">{tip}</p>
      <div style="background:#f1f5f9;border-radius:12px;padding:24px;margin-bottom:24px">
        <div style="font-size:36px;font-weight:700;color:#6366f1;letter-spacing:8px">{code}</div>
        <div style="font-size:12px;color:#94a3b8;margin-top:8px">有效期 5 分钟</div>
      </div>
      <p style="color:#94a3b8;font-size:12px;margin:0">若非本人操作，请忽略此邮件</p>
    </div>
    <div style="text-align:center;padding:16px;color:#94a3b8;font-size:12px">
      © 2026 Ruitalk · 请勿回复此邮件
    </div>
  </div>
</body></html>
"""

# ============== 数据库操作 ==============

def init_merchant_db():
    """初始化商户数据库表"""
    try:
        conn = _get_merchant_conn()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS merchants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone TEXT UNIQUE,
                email TEXT UNIQUE,
                password_hash TEXT NOT NULL,
                company_name TEXT,
                contact_name TEXT,
                business_type TEXT DEFAULT 'individual',
                status TEXT DEFAULT 'active',
                is_verified INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS merchant_sms_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone TEXT NOT NULL,
                code TEXT NOT NULL,
                action TEXT DEFAULT 'login',
                used INTEGER DEFAULT 0,
                expires_at TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS merchant_email_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL,
                code TEXT NOT NULL,
                action TEXT DEFAULT 'login',
                used INTEGER DEFAULT 0,
                expires_at TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"[商户数据库] 初始化失败: {e}")
        return False

def get_merchant_by_phone(phone: str):
    """根据手机号获取商户"""
    try:
        conn = _get_merchant_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM merchants WHERE phone=? AND is_verified=1",
            (phone,)
        )
        result = cur.fetchone()
        conn.close()
        return dict(result) if result else None
    except Exception as e:
        print(f"[查询商户] 失败: {e}")
        return None

def get_merchant_by_email(email: str):
    """根据邮箱获取商户"""
    try:
        conn = _get_merchant_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM merchants WHERE email=? AND is_verified=1",
            (email,)
        )
        result = cur.fetchone()
        conn.close()
        return dict(result) if result else None
    except Exception as e:
        print(f"[查询商户] 失败: {e}")
        return None

def create_merchant(phone: str = None, email: str = None, password: str = None,
                    company_name: str = "", contact_name: str = "", business_type: str = "individual"):
    """创建商户"""
    try:
        conn = _get_merchant_conn()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO merchants (phone, email, password_hash, company_name, contact_name, business_type, is_verified)
            VALUES (?, ?, ?, ?, ?, ?, 1)
        """, (phone, email, hash_password(password), company_name, contact_name, business_type))
        merchant_id = cur.lastrowid
        conn.commit()
        conn.close()
        return merchant_id
    except Exception as e:
        print(f"[创建商户] 失败: {e}")
        return None

def save_sms_code(phone: str, code: str, action: str) -> bool:
    """保存短信验证码（失败返回 False，避免前端提示已发送但实际未入库）"""
    phone = normalize_merchant_phone(phone)
    action = (action or "login").strip().lower()
    try:
        with _MERCHANT_DB_LOCK:
            conn = _get_merchant_conn()
            cur = conn.cursor()
            expires = (datetime.now() + timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
            cur.execute("DELETE FROM merchant_sms_codes WHERE phone=?", (phone,))
            cur.execute(
                "INSERT INTO merchant_sms_codes (phone, code, action, expires_at) VALUES (?,?,?,?)",
                (phone, code, action, expires)
            )
            conn.commit()
            conn.close()
        return True
    except Exception as e:
        print(f"[保存短信验证码] 失败: {e}")
        return False

def save_email_code(email: str, code: str, action: str) -> bool:
    """保存邮箱验证码"""
    email = (email or "").strip().lower()
    action = (action or "login").strip().lower()
    try:
        with _MERCHANT_DB_LOCK:
            conn = _get_merchant_conn()
            cur = conn.cursor()
            expires = (datetime.now() + timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
            cur.execute("DELETE FROM merchant_email_codes WHERE email=?", (email,))
            cur.execute(
                "INSERT INTO merchant_email_codes (email, code, action, expires_at) VALUES (?,?,?,?)",
                (email, code, action, expires)
            )
            conn.commit()
            conn.close()
        return True
    except Exception as e:
        print(f"[保存邮箱验证码] 失败: {e}")
        return False

def verify_sms_code(phone: str, code: str, action: str) -> bool:
    """验证短信验证码（手机号、验证码、action 均做规范化，过期用 Python 时间比较）"""
    phone = normalize_merchant_phone(phone)
    code = normalize_sms_code(code)
    action = (action or "").strip().lower()
    if len(code) != 6:
        return False
    try:
        with _MERCHANT_DB_LOCK:
            conn = _get_merchant_conn()
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM merchant_sms_codes WHERE phone=? AND action=? AND used=0 ORDER BY id DESC LIMIT 1",
                (phone, action),
            )
            result = cur.fetchone()
            if not result:
                conn.close()
                return False
            if normalize_sms_code(result["code"]) != code:
                conn.close()
                return False
            try:
                exp = datetime.strptime(result["expires_at"], "%Y-%m-%d %H:%M:%S")
            except ValueError:
                conn.close()
                return False
            if datetime.now() > exp:
                conn.close()
                return False
            cur.execute("UPDATE merchant_sms_codes SET used=1 WHERE id=?", (result["id"],))
            conn.commit()
            conn.close()
        return True
    except Exception as e:
        print(f"[验证短信验证码] 失败: {e}")
        return False

def verify_email_code(email: str, code: str, action: str) -> bool:
    """验证邮箱验证码（与短信验证码相同：规范化 + Python 比较过期时间）"""
    email = (email or "").strip().lower()
    code = normalize_sms_code(code)
    action = (action or "").strip().lower()
    if len(code) != 6:
        return False
    try:
        with _MERCHANT_DB_LOCK:
            conn = _get_merchant_conn()
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM merchant_email_codes WHERE email=? AND action=? AND used=0 ORDER BY id DESC LIMIT 1",
                (email, action),
            )
            result = cur.fetchone()
            if not result:
                conn.close()
                return False
            if normalize_sms_code(result["code"]) != code:
                conn.close()
                return False
            try:
                exp = datetime.strptime(result["expires_at"], "%Y-%m-%d %H:%M:%S")
            except ValueError:
                conn.close()
                return False
            if datetime.now() > exp:
                conn.close()
                return False
            cur.execute("UPDATE merchant_email_codes SET used=1 WHERE id=?", (result["id"],))
            conn.commit()
            conn.close()
        return True
    except Exception as e:
        print(f"[验证邮箱验证码] 失败: {e}")
        return False

def check_rate_limit_phone(phone: str, seconds: int = 60) -> tuple[bool, int]:
    """检查手机号发送频率限制"""
    phone = normalize_merchant_phone(phone)
    try:
        conn = _get_merchant_conn()
        cur = conn.cursor()
        since = (datetime.now() - timedelta(seconds=seconds)).strftime("%Y-%m-%d %H:%M:%S")
        cur.execute(
            "SELECT expires_at FROM merchant_sms_codes WHERE phone=? AND expires_at>? ORDER BY id DESC LIMIT 1",
            (phone, since)
        )
        result = cur.fetchone()
        conn.close()
        if result:
            expires = datetime.strptime(result["expires_at"], "%Y-%m-%d %H:%M:%S")
            remaining = int((expires - datetime.now()).total_seconds())
            return False, max(1, remaining)
        return True, 0
    except Exception as e:
        print(f"[检查频率限制] 失败: {e}")
        return True, 0

def check_rate_limit_email(email: str, seconds: int = 60) -> tuple[bool, int]:
    """检查邮箱发送频率限制"""
    try:
        conn = _get_merchant_conn()
        cur = conn.cursor()
        since = (datetime.now() - timedelta(seconds=seconds)).strftime("%Y-%m-%d %H:%M:%S")
        cur.execute(
            "SELECT expires_at FROM merchant_email_codes WHERE email=? AND expires_at>? ORDER BY id DESC LIMIT 1",
            (email, since)
        )
        result = cur.fetchone()
        conn.close()
        if result:
            expires = datetime.strptime(result["expires_at"], "%Y-%m-%d %H:%M:%S")
            remaining = int((expires - datetime.now()).total_seconds())
            return False, max(1, remaining)
        return True, 0
    except Exception as e:
        print(f"[检查频率限制] 失败: {e}")
        return True, 0

# ============== API 端点 ==============

@router.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "ok", "service": "merchant-auth"}

# ---- 发送短信验证码 ----
@router.post("/send-sms-code")
async def send_sms_code(request: Request, body: SendSmsCodeRequest):
    """发送手机验证码"""
    phone = normalize_merchant_phone(body.phone.strip())
    action = (body.action or "login").strip().lower()

    if not is_valid_phone(phone):
        raise HTTPException(status_code=400, detail="手机号格式不正确")

    # 频率限制
    allowed, remaining = check_rate_limit_phone(phone)
    if not allowed:
        raise HTTPException(status_code=429, detail=f"请 {remaining} 秒后再试")

    # 生成验证码
    code = generate_code()
    if not save_sms_code(phone, code, action):
        raise HTTPException(status_code=500, detail="验证码写入失败，请稍后重试或检查磁盘权限")
    send_sms(phone, code)

    return {
        "success": True,
        "message": "验证码已发送",
        "debug_code": code,  # 演示模式暴露
        "phone_mask": phone[:3] + "****" + phone[7:],
        "expire_seconds": 300
    }

# ---- 发送邮箱验证码 ----
@router.post("/send-email-code")
async def send_email_code(request: Request, body: SendEmailCodeRequest):
    """发送邮箱验证码"""
    email = body.email.strip().lower()
    action = (body.action or "login").strip().lower()

    if not is_valid_email(email):
        raise HTTPException(status_code=400, detail="邮箱格式不正确")

    # 频率限制
    allowed, remaining = check_rate_limit_email(email)
    if not allowed:
        raise HTTPException(status_code=429, detail=f"请 {remaining} 秒后再试")

    # 生成验证码
    code = generate_code()
    if not save_email_code(email, code, action):
        raise HTTPException(status_code=500, detail="验证码写入失败，请稍后重试或检查磁盘权限")

    # 发送邮件
    html_body = build_email_template(code, action)
    send_email(email, "Ruitalk 商户验证码", html_body)

    mask_email = email[:2] + "***" + email[email.index("@"):]
    return {
        "success": True,
        "message": "验证码已发送到邮箱",
        "debug_code": code if not SMTP_HOST else None,
        "email_mask": mask_email,
        "expire_seconds": 600
    }

# ---- 手机号注册 ----
@router.post("/register/phone")
async def register_phone(request: Request, body: RegisterPhoneRequest):
    """手机号注册商户"""
    phone = normalize_merchant_phone(body.phone.strip())

    if phone in _DEV_PHONE_PASSWORDS:
        raise HTTPException(
            status_code=400,
            detail="该号为内部测试账号，请使用「手机+密码」直接登录，勿注册",
        )

    if not is_valid_phone(phone):
        raise HTTPException(status_code=400, detail="手机号格式不正确")
    _code = normalize_sms_code(body.code)
    if len(_code) != 6:
        raise HTTPException(status_code=400, detail="验证码必须为6位数字")
    if len(body.password) < 6:
        raise HTTPException(status_code=400, detail="密码至少6位")

    # 验证验证码（业务错误用 400，避免与未登录 401 混淆）
    if not verify_sms_code(phone, _code, "register"):
        raise HTTPException(status_code=400, detail="验证码错误或已过期，请重新获取")

    # 检查手机号是否已注册
    existing = get_merchant_by_phone(phone)
    if existing:
        raise HTTPException(status_code=400, detail="该手机号已注册，请直接登录")

    # 创建商户
    merchant_id = create_merchant(
        phone=phone,
        password=body.password,
        company_name=body.company_name,
        contact_name=body.contact_name,
        business_type=body.business_type
    )

    if not merchant_id:
        raise HTTPException(status_code=500, detail="注册失败，请稍后重试")

    # 生成令牌
    access_token = create_access_token(merchant_id)
    refresh_token = create_refresh_token(merchant_id)

    return {
        "success": True,
        "message": "注册成功",
        "data": {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "merchant": {
                "id": merchant_id,
                "phone": phone,
                "company_name": body.company_name,
                "business_type": body.business_type
            }
        }
    }

# ---- 邮箱注册 ----
@router.post("/register/email")
async def register_email(request: Request, body: RegisterEmailRequest):
    """邮箱注册商户"""
    email = body.email.strip().lower()

    if not is_valid_email(email):
        raise HTTPException(status_code=400, detail="邮箱格式不正确")
    _ecode = normalize_sms_code(body.code)
    if len(_ecode) != 6:
        raise HTTPException(status_code=400, detail="验证码必须为6位数字")
    if len(body.password) < 6:
        raise HTTPException(status_code=400, detail="密码至少6位")

    # 验证验证码
    if not verify_email_code(email, _ecode, "register"):
        raise HTTPException(status_code=400, detail="验证码错误或已过期，请重新获取")

    # 检查邮箱是否已注册
    existing = get_merchant_by_email(email)
    if existing:
        raise HTTPException(status_code=400, detail="该邮箱已注册，请直接登录")

    # 创建商户
    merchant_id = create_merchant(
        email=email,
        password=body.password,
        company_name=body.company_name,
        contact_name=body.contact_name,
        business_type=body.business_type
    )

    if not merchant_id:
        raise HTTPException(status_code=500, detail="注册失败，请稍后重试")

    # 生成令牌
    access_token = create_access_token(merchant_id)
    refresh_token = create_refresh_token(merchant_id)

    return {
        "success": True,
        "message": "注册成功",
        "data": {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "merchant": {
                "id": merchant_id,
                "email": email,
                "company_name": body.company_name,
                "business_type": body.business_type
            }
        }
    }

# ---- 手机号+密码登录 ----
@router.post("/login/phone")
async def login_phone(request: Request, body: LoginPhoneRequest):
    """手机号密码登录"""
    phone = normalize_merchant_phone(body.phone.strip())

    if not is_valid_phone(phone):
        raise HTTPException(status_code=400, detail="手机号格式不正确")

    # 与 DEV_PHONE_USERS 对齐：商户门户走合成商户，此前仅 /api/admin/phone-login 可用
    if phone in _DEV_PHONE_PASSWORDS:
        if body.password != _DEV_PHONE_PASSWORDS[phone]:
            raise HTTPException(status_code=401, detail="手机号或密码错误")
        access_token = create_access_token(DEV_INTERNAL_MERCHANT_ID)
        refresh_token = create_refresh_token(DEV_INTERNAL_MERCHANT_ID)
        data = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "merchant": {
                "id": DEV_INTERNAL_MERCHANT_ID,
                "phone": phone,
                "company_name": "内部测试商户",
                "business_type": "individual",
            },
        }
        pair = _admin_jwt_pair_for_dev_phone(phone)
        if pair:
            data["admin_access_token"], data["admin_refresh_token"] = pair
        return {"success": True, "message": "登录成功", "data": data}

    merchant = get_merchant_by_phone(phone)
    if not merchant:
        raise HTTPException(status_code=401, detail="该手机号尚未注册，请先注册")

    if not verify_password(body.password, merchant["password_hash"]):
        raise HTTPException(status_code=401, detail="手机号或密码错误")

    access_token = create_access_token(merchant["id"])
    refresh_token = create_refresh_token(merchant["id"])

    return {
        "success": True,
        "message": "登录成功",
        "data": {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "merchant": {
                "id": merchant["id"],
                "phone": merchant["phone"],
                "company_name": merchant.get("company_name", ""),
                "business_type": merchant.get("business_type", "individual")
            }
        }
    }

# ---- 手机号+验证码登录 ----
@router.post("/login/phone-code")
async def login_phone_code(request: Request, body: LoginPhoneCodeRequest):
    """手机号验证码登录"""
    phone = normalize_merchant_phone(body.phone.strip())

    if not is_valid_phone(phone):
        raise HTTPException(status_code=400, detail="手机号格式不正确")
    _lcode = normalize_sms_code(body.code)
    if len(_lcode) != 6:
        raise HTTPException(status_code=400, detail="验证码必须为6位数字")

    if not verify_sms_code(phone, _lcode, "login"):
        raise HTTPException(status_code=400, detail="验证码错误或已过期，请重新获取")

    if phone in _DEV_PHONE_PASSWORDS:
        access_token = create_access_token(DEV_INTERNAL_MERCHANT_ID)
        refresh_token = create_refresh_token(DEV_INTERNAL_MERCHANT_ID)
        data = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "merchant": {
                "id": DEV_INTERNAL_MERCHANT_ID,
                "phone": phone,
                "company_name": "内部测试商户",
                "business_type": "individual",
            },
        }
        pair = _admin_jwt_pair_for_dev_phone(phone)
        if pair:
            data["admin_access_token"], data["admin_refresh_token"] = pair
        return {"success": True, "message": "登录成功", "data": data}

    merchant = get_merchant_by_phone(phone)
    if not merchant:
        raise HTTPException(status_code=401, detail="该手机号尚未注册，请先注册")

    access_token = create_access_token(merchant["id"])
    refresh_token = create_refresh_token(merchant["id"])

    return {
        "success": True,
        "message": "登录成功",
        "data": {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "merchant": {
                "id": merchant["id"],
                "phone": merchant["phone"],
                "company_name": merchant.get("company_name", ""),
                "business_type": merchant.get("business_type", "individual")
            }
        }
    }

# ---- 邮箱+密码登录 ----
@router.post("/login/email")
async def login_email(request: Request, body: LoginEmailRequest):
    """邮箱密码登录"""
    email = body.email.strip().lower()

    if not is_valid_email(email):
        raise HTTPException(status_code=400, detail="邮箱格式不正确")

    merchant = get_merchant_by_email(email)
    if not merchant:
        raise HTTPException(status_code=401, detail="该邮箱尚未注册，请先注册")

    if not verify_password(body.password, merchant["password_hash"]):
        raise HTTPException(status_code=401, detail="邮箱或密码错误")

    access_token = create_access_token(merchant["id"])
    refresh_token = create_refresh_token(merchant["id"])

    return {
        "success": True,
        "message": "登录成功",
        "data": {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "merchant": {
                "id": merchant["id"],
                "email": merchant["email"],
                "company_name": merchant.get("company_name", ""),
                "business_type": merchant.get("business_type", "individual")
            }
        }
    }

# ---- 邮箱+验证码登录 ----
@router.post("/login/email-code")
async def login_email_code(request: Request, body: LoginEmailCodeRequest):
    """邮箱验证码登录"""
    email = body.email.strip().lower()

    if not is_valid_email(email):
        raise HTTPException(status_code=400, detail="邮箱格式不正确")
    _lecode = normalize_sms_code(body.code)
    if len(_lecode) != 6:
        raise HTTPException(status_code=400, detail="验证码必须为6位数字")

    if not verify_email_code(email, _lecode, "login"):
        raise HTTPException(status_code=400, detail="验证码错误或已过期，请重新获取")

    merchant = get_merchant_by_email(email)
    if not merchant:
        raise HTTPException(status_code=401, detail="该邮箱尚未注册，请先注册")

    access_token = create_access_token(merchant["id"])
    refresh_token = create_refresh_token(merchant["id"])

    return {
        "success": True,
        "message": "登录成功",
        "data": {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "merchant": {
                "id": merchant["id"],
                "email": merchant["email"],
                "company_name": merchant.get("company_name", ""),
                "business_type": merchant.get("business_type", "individual")
            }
        }
    }

# ---- 刷新令牌 ----
@router.post("/refresh")
async def refresh_token(request: Request, body: RefreshTokenRequest):
    """刷新访问令牌"""
    payload = verify_token(body.refresh_token, "refresh")
    if not payload:
        raise HTTPException(status_code=401, detail="无效的刷新令牌")

    merchant_id = int(payload["sub"])
    access_token = create_access_token(merchant_id)
    new_refresh_token = create_refresh_token(merchant_id)

    return {
        "success": True,
        "data": {
            "access_token": access_token,
            "refresh_token": new_refresh_token
        }
    }

# ---- 获取当前商户信息 ----
@router.get("/me")
async def get_merchant_info(request: Request):
    """获取当前登录商户信息"""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未提供认证凭证")

    token = auth_header[7:]
    payload = verify_token(token, "access")
    if not payload:
        raise HTTPException(status_code=401, detail="无效或已过期的令牌")

    merchant_id = int(payload["sub"])

    if not HAS_DB:
        return {
            "success": True,
            "data": {
                "id": merchant_id,
                "role": "merchant"
            }
        }

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT id, phone, email, company_name, contact_name, business_type, status, created_at FROM merchants WHERE id=?",
            (merchant_id,)
        )
        merchant = cur.fetchone()
        conn.close()

        if not merchant:
            raise HTTPException(status_code=404, detail="商户不存在")

        return {
            "success": True,
            "data": dict(merchant)
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ============== 初始化数据库 ==============
try:
    init_merchant_db()
except Exception as e:
    print(f"[商户认证模块] 数据库初始化: {e}")
