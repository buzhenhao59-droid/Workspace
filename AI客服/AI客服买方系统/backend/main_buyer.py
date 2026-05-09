# -*- coding: utf-8 -*-
"""
买方AI客服系统 - 独立 FastAPI 后端
端口: 8001（可配置）

职责:
  - 客户 AI 聊天（AI模式/人工模式）
  - 多语言支持（中/英/阿/俄/泰/越南/印尼/马来/菲律宾）
  - 转人工时通知卖方坐席系统
  - 独立数据库 buyer.db（会话/客户/消息）
  - 接收卖方回调（人工→AI 转移通知）

API 版本: v1
"""
import sys as _sys
import os as _os

_sp = r"D:\lib\site-packages"
if _sp not in _sys.path:
    _sys.path.insert(0, _sp)

import uuid
import threading
import json
import os
import asyncio
import subprocess
import sys
import time
from contextlib import asynccontextmanager
from typing import Optional, List
from datetime import datetime
from enum import Enum
from pathlib import Path
from pydantic import BaseModel
from fastapi import FastAPI, Request, HTTPException, Depends, Query, Body, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, HTMLResponse

# ============== 日志配置 ==============
import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ============== Sentry APM ==============
_sentry_dsn = os.getenv("SENTRY_DSN", "").strip()
if _sentry_dsn:
    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.starlette import StarletteIntegration
    from sentry_sdk.integrations.asyncio import AsyncioIntegration
    sentry_sdk.init(
        dsn=_sentry_dsn,
        integrations=[
            FastApiIntegration(auto_session_tracking=True),
            StarletteIntegration(),
            AsyncioIntegration(),
        ],
        traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.1")),
        profiles_sample_rate=float(os.getenv("SENTRY_PROFILES_SAMPLE_RATE", "0.1")),
        environment=os.getenv("ENVIRONMENT", "production"),
        release=os.getenv("APP_VERSION", "ruitalk-buyer-1.0.0"),
        attach_stacktrace=True,
        max_breadcrumbs=50,
    )
    logger.info(f"[Sentry] APM 已接入 (DSN: ...{_sentry_dsn[-12:] if _sentry_dsn else '未配置'})")
else:
    logger.info("[Sentry] DSN 未配置，跳过 APM 接入")

import requests

# ============== 配置加载 ==============
_buyer_parent = Path(__file__).resolve().parent.parent

try:
    from dotenv import load_dotenv
    _ROOT_ENV = _buyer_parent.parent / ".env"
    if _ROOT_ENV.exists():
        load_dotenv(_ROOT_ENV, override=False)
except Exception:
    pass

# 关键配置
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_API_URL = os.getenv("DEEPSEEK_API_URL", "https://api.deepseek.com/v1/chat/completions")
GRAPHRAG_API_URL = os.getenv("GRAPHRAG_API_URL", "http://localhost:5050/query")
SELLER_API_HOST = os.getenv("SELLER_API_HOST", "http://127.0.0.1:8000")
SELLER_INTERNAL_TOKEN = os.getenv("SELLER_INTERNAL_TOKEN", "UvSuW5LSkzf6lBxIoeHFnwpQ9eQYIzlQ4Skz0dcB5Wg")
BUYER_CALLBACK_TOKEN = os.getenv("BUYER_CALLBACK_TOKEN", "UvSuW5LSkzf6lBxIoeHFnwpQ9eQYIzlQ4Skz0dcB5Wg")
BUYER_PORT = int(os.getenv("BUYER_PORT", "8001"))
BUYER_API_HOST = os.getenv("BUYER_API_HOST", "http://127.0.0.1:8001")
BUYER_DB_PATH = os.getenv("BUYER_DB_PATH", "")
SECRET_KEY = os.getenv("SECRET_KEY", "buyer-secret-key")
_ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173")
ALLOWED_ORIGINS = [origin.strip() for origin in _ALLOWED_ORIGINS.split(",") if origin.strip()]

if not BUYER_DB_PATH:
    BUYER_DB_PATH = str((_buyer_parent / "backend" / "data" / "buyer.db").resolve())
Path(BUYER_DB_PATH).parent.mkdir(parents=True, exist_ok=True)

BUYER_ROOT = _buyer_parent
BUYER_DB = Path(BUYER_DB_PATH)
BUYER_DB.parent.mkdir(parents=True, exist_ok=True)
FRONTEND_DIR = BUYER_ROOT / "frontend"
UPLOAD_DIR = BUYER_ROOT / "data" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def _frontend_index_path() -> Path:
    primary = FRONTEND_DIR / "index.html"
    return primary


def _get_buyer_db_connection():
    try:
        from mysql_db_buyer import _get_sqlite_conn
        return _get_sqlite_conn()
    except Exception:
        import sqlite3
        try:
            return sqlite3.connect(str(BUYER_DB), check_same_thread=False)
        except Exception as e:
            logger.error(f"无法连接买方数据库 {BUYER_DB_PATH}: {e}")
            return None


# ============== MySQL 统一查询工具 ==============

def _is_mysql_available() -> bool:
    try:
        from mysql_db_buyer import is_mysql
        return is_mysql()
    except ImportError:
        return False


def _sqlite_cols(cursor) -> list:
    """Return column names from cursor.description (SQLite compatible)."""
    return [d[0] for d in cursor.description] if cursor.description else []


def _session_exists(session_id: str) -> bool:
    """Check if a session exists in the database."""
    row = _buyer_query("SELECT 1 FROM sessions WHERE session_id = ?", (session_id,), fetch_one=True)
    return row is not None


def _sqlite_row_to_dict(row, cols: list) -> dict:
    """Convert a sqlite row to dict."""
    if row is None:
        return None
    return dict(zip(cols, row))


def _buyer_query(sql: str, params: tuple = (), fetch_one: bool = False):
    # Lazy import: only load mysql wrapper when MySQL is confirmed available
    if not _is_mysql_available():
        conn = _get_buyer_db_connection()
        if not conn:
            return None if fetch_one else []
        cursor = conn.cursor()
        try:
            cursor.execute(sql, params)
            cols = _sqlite_cols(cursor)
            if fetch_one:
                row = cursor.fetchone()
                return _sqlite_row_to_dict(row, cols) if row else None
            return [_sqlite_row_to_dict(row, cols) for row in cursor.fetchall()]
        finally:
            cursor.close()
    else:
        from mysql_db_buyer import get_db, _cols, _row_to_dict
        adapted = sql
        if '?' in adapted:
            adapted = adapted.replace('?', '%s')
        with get_db() as (conn, cursor):
            cursor.execute(adapted, params)
            cols = _cols(cursor)
            if fetch_one:
                row = cursor.fetchone()
                return _row_to_dict(row, cols) if row else None
            return [_row_to_dict(row, cols) for row in cursor.fetchall()]


def _buyer_execute(sql: str, params: tuple = (), many: bool = False, params_list: list = None):
    if not _is_mysql_available():
        conn = _get_buyer_db_connection()
        if not conn:
            return
        cursor = conn.cursor()
        try:
            if many and params_list:
                cursor.executemany(sql, params_list)
            else:
                cursor.execute(sql, params)
            conn.commit()
        finally:
            cursor.close()
    else:
        from mysql_db_buyer import get_db
        adapted = sql
        if '?' in adapted:
            adapted = adapted.replace('?', '%s')
        with get_db() as (conn, cursor):
            if many and params_list:
                cursor.executemany(adapted, params_list)
            else:
                cursor.execute(adapted, params)


def _adapt_buyer_sql(sql: str) -> str:
    import re
    sql = sql.replace('INSERT OR IGNORE', 'INSERT IGNORE')
    sql = re.sub(r"datetime\(\s*'now'\s*,\s*'-?\s*(\d+)\s*days?\s*\)",
                 lambda m: f"DATE_SUB(NOW(), INTERVAL {m.group(1)} DAY)", sql)
    sql = re.sub(r"datetime\(\s*'now'\s*\)", "NOW()", sql)
    return sql


def _init_buyer_db():
    try:
        from mysql_db_buyer import _init_mysql_pool
        from init_mysql_schema_buyer import init_buyer_db_schema
        _init_mysql_pool()
        init_buyer_db_schema()
        logger.info("[BuyerDB] MySQL 数据库初始化完成")
    except Exception as e:
        logger.warning(f"[BuyerDB] MySQL 初始化失败，回退到 SQLite: {e}")
        _init_buyer_db_sqlite_fallback()


def _init_buyer_db_sqlite_fallback():
    conn = _get_buyer_db_connection()
    if not conn:
        return
    cursor = conn.cursor()
    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS customers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id TEXT UNIQUE,
                phone TEXT,
                name TEXT,
                region TEXT,
                level TEXT DEFAULT '普通',
                m_value INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT UNIQUE NOT NULL,
                customer_id TEXT,
                status TEXT DEFAULT 'active',
                assign_to TEXT,
                is_ai INTEGER DEFAULT 1,
                language TEXT DEFAULT 'zh',
                system_source TEXT DEFAULT 'buyer',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sessions_sid ON sessions(session_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sessions_cid ON sessions(customer_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_sid ON messages(session_id)")
        conn.commit()
        logger.info(f"[BuyerSQLite] 买方数据库初始化完成: {BUYER_DB_PATH}")
    finally:
        pass  # 不关闭单例连接（由 mysql_db_buyer._get_sqlite_conn 管理）


# ============== 数据模型 ==============
class StartSessionRequest(BaseModel):
    phone: Optional[str] = None
    customer_id: Optional[str] = None


class ChatRequest(BaseModel):
    session_id: str
    message: str
    client_message_id: Optional[str] = ""


class ChatResponse(BaseModel):
    success: bool
    response: Optional[str] = None
    language: Optional[str] = None
    message: Optional[str] = None
    auto_transfer: Optional[str] = None
    # 融合源文件：增强响应元数据
    intent: Optional[str] = None       # 8类意图: product_inquiry/logistics/payment/refund_return/policy/account/complaint/general
    emotion: Optional[str] = None      # 情绪: angry/sad/anxious/happy/neutral
    confidence: Optional[float] = None # 置信度 0.0-1.0


class StartSessionResponse(BaseModel):
    success: bool
    session_id: Optional[str] = None
    customer_info: Optional[dict] = None
    welcome_message: Optional[str] = None
    language: Optional[str] = None
    message: Optional[str] = None


class ChangeLanguageResponse(BaseModel):
    success: bool
    language: Optional[str] = None
    message: Optional[str] = None


class TranslateRequest(BaseModel):
    text: Optional[str] = None
    target: Optional[str] = None


class TranslateResponse(BaseModel):
    success: bool
    translated: Optional[str] = None
    target: Optional[str] = None
    message: Optional[str] = None


class JsonSessionId(BaseModel):
    session_id: str


class CustomerSendJSON(BaseModel):
    session_id: str
    content: str


class ChangeLangJSON(BaseModel):
    session_id: str
    language: str


def _session_row_to_api_dict(row) -> dict:
    d = dict(row)
    if "is_ai" in d and d["is_ai"] is not None:
        d["is_ai"] = bool(d["is_ai"])
    return d


# ============== 内存会话管理器 ==============

# 导入滑动窗口记忆模块
try:
    from conversation_memory import ConversationMemory, get_memory, clear_memory
    MEMORY_ENABLED = True
except ImportError:
    MEMORY_ENABLED = False
    import logging
    logging.warning("[Memory] 滑动窗口记忆模块未加载，使用传统模式")


class BuyerSessionManager:
    def __init__(self):
        self.sessions = {}
        self.lock = threading.RLock()
        self._dedup_cache = {}
        self._dedup_lock = threading.RLock()

    def create_session(self, customer_info: dict, language: str = "zh") -> str:
        session_id = str(uuid.uuid4())
        with self.lock:
            self.sessions[session_id] = {
                "customer_info": customer_info,
                "language": language,
                "conversation_history": [],
                "created_at": datetime.now().isoformat(),
                "system": "buyer"
            }
        # 初始化滑动窗口记忆
        if MEMORY_ENABLED:
            memory = get_memory(session_id)
            memory.clear()
        return session_id

    def get_session(self, session_id: str) -> Optional[dict]:
        with self.lock:
            session = self.sessions.get(session_id)
            if session and not session.get("conversation_history"):
                try:
                    rows = _buyer_query(
                        "SELECT role, content FROM messages WHERE session_id = ? ORDER BY id ASC",
                        (session_id,))
                    if rows:
                        session["conversation_history"] = [
                            {"role": r.get("role") if hasattr(r, 'get') else r[0],
                             "content": r.get("content") if hasattr(r, 'get') else r[1]}
                            for r in rows
                        ]
                        # 同步到滑动窗口记忆
                        if MEMORY_ENABLED:
                            memory = get_memory(session_id)
                            for r in rows:
                                role = r.get("role") if hasattr(r, 'get') else r[0]
                                content = r.get("content") if hasattr(r, 'get') else r[1]
                                memory.add_message(role, content)
                except Exception:
                    pass
            return session

    def update_session_language(self, session_id: str, language: str):
        with self.lock:
            if session_id in self.sessions:
                self.sessions[session_id]["language"] = language

    def add_message(self, session_id: str, role: str, content: str):
        with self.lock:
            if session_id in self.sessions:
                self.sessions[session_id]["conversation_history"].append({
                    "role": role, "content": content})
        # 同步到滑动窗口记忆
        if MEMORY_ENABLED:
            memory = get_memory(session_id)
            memory.add_message(role, content)

    def close_session(self, session_id: str):
        with self.lock:
            if session_id in self.sessions:
                del self.sessions[session_id]
        # 清理滑动窗口记忆
        if MEMORY_ENABLED:
            clear_memory(session_id)

    def is_duplicate(self, session_id: str, client_message_id: str, ttl: int = 120) -> bool:
        if not client_message_id:
            return False
        with self._dedup_lock:
            now = datetime.now().timestamp()
            cache = self._dedup_cache.get(session_id, {})
            for mid, ts in list(cache.items()):
                if now - ts > ttl:
                    del cache[mid]
            if session_id not in self._dedup_cache:
                self._dedup_cache[session_id] = {}
            if client_message_id in self._dedup_cache[session_id]:
                return True
            self._dedup_cache[session_id][client_message_id] = now
            return False


buyer_session_manager = BuyerSessionManager()


# ============== Neo4j 连接 ==============
def _neo4j_safe_str(obj):
    if obj is None:
        return None
    if hasattr(obj, "iso_format"):
        return obj.iso_format()
    if hasattr(obj, "_properties"):
        return _neo4j_safe_str(dict(obj._properties))
    if isinstance(obj, dict):
        return {k: _neo4j_safe_str(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_neo4j_safe_str(i) for i in obj]
    return obj


class BuyerNeo4jConnection:
    def __init__(self):
        self.driver = None
        self._neo4j_available = False

    def connect(self):
        drv = None
        try:
            from neo4j import GraphDatabase
            drv = GraphDatabase.driver(
                NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD),
                max_connection_lifetime=3600, connection_timeout=10)
            with drv.session() as session:
                session.run("RETURN 1")
            self.driver = drv
            self._neo4j_available = True
            logger.info(f"[Neo4j] 连接成功: {NEO4J_URI}")
            return True
        except Exception as e:
            self._neo4j_available = False
            logger.warning(f"[Neo4j] 连接失败: {e}")
            if drv:
                try:
                    drv.close()
                except Exception:
                    pass
            self.driver = None
            return False

    def close(self):
        if self.driver:
            self.driver.close()
            self.driver = None
            self._neo4j_available = False

    def _sqlite_find_customer(self, phone: str = None, customer_id: str = None) -> Optional[dict]:
        if phone:
            return _buyer_query("SELECT * FROM customers WHERE phone = ? LIMIT 1", (phone,), fetch_one=True)
        elif customer_id:
            return _buyer_query("SELECT * FROM customers WHERE customer_id = ? LIMIT 1", (customer_id,), fetch_one=True)
        return None

    def _sqlite_get_full_profile(self, customer_id: str) -> dict:
        customer = _buyer_query("SELECT * FROM customers WHERE customer_id = ? LIMIT 1", (customer_id,), fetch_one=True)
        return {"customer": customer or {"customer_id": customer_id}, "orders": [], "skus": [], "communications": []}

    def _ensure_customer_in_sqlite(self, phone: str = None, customer_id: str = None, name: str = None, region: str = None):
        existing = _buyer_query(
            "SELECT customer_id FROM customers WHERE customer_id = ? OR phone = ?",
            (customer_id, phone), fetch_one=True)
        if not existing:
            # 生成默认名称：优先用 phone 后4位，否则用 customer_id 后8位
            if phone:
                _name = name or f"客户{phone[-4:]}"
            else:
                _name = name or f"客户_{str(customer_id)[-8:]}"
            if _is_mysql_available():
                _buyer_execute(
                    "INSERT IGNORE INTO customers (customer_id, phone, name, region, level) VALUES (%s, %s, %s, %s, '普通')",
                    (customer_id, phone, _name, region or "未知"))
            else:
                _buyer_execute(
                    "INSERT OR IGNORE INTO customers (customer_id, phone, name, region, level) VALUES (?, ?, ?, ?, '普通')",
                    (customer_id, phone, _name, region or "未知"))

    def find_customer(self, phone: str = None, customer_id: str = None):
        if self.driver:
            try:
                with self.driver.session() as session:
                    if phone:
                        result = session.run("MATCH (c:Customer {phone: $phone}) RETURN c LIMIT 1", phone=phone)
                    elif customer_id:
                        result = session.run("MATCH (c:Customer {id: $cid}) RETURN c LIMIT 1", cid=customer_id)
                    else:
                        return None
                    record = result.single()
                    if record:
                        c = _neo4j_safe_str(dict(record["c"]))
                        cid = c.get("customer_id") or c.get("id") or customer_id
                        if "customer_id" not in c:
                            c["customer_id"] = cid
                        return c
            except Exception as e:
                logger.warning(f"[Neo4j] 查询客户失败: {e}")
        if phone or customer_id:
            customer = self._sqlite_find_customer(phone=phone, customer_id=customer_id)
            if customer:
                return customer
        return None

    def get_full_profile(self, customer_id: str) -> dict:
        if self.driver:
            try:
                with self.driver.session() as session:
                    r = session.run("MATCH (c:Customer {id: $cid}) RETURN c LIMIT 1", cid=customer_id)
                    rec = r.single()
                    if not rec:
                        return self._sqlite_get_full_profile(customer_id)
                    customer = _neo4j_safe_str(dict(rec["c"]))
                    if "customer_id" not in customer:
                        customer["customer_id"] = customer_id
                    orders, products, comms = [], [], []
                    r2 = session.run(
                        "MATCH (c:Customer {id: $cid})-[r:PURCHASED]->(o:Order) "
                        "RETURN o ORDER BY o.created_at DESC LIMIT 20", cid=customer_id)
                    for rec2 in r2:
                        orders.append(_neo4j_safe_str(dict(rec2["o"])))
                    r3 = session.run(
                        "MATCH (c:Customer {id: $cid})-[r:PURCHASED]->(o:Order)-[:CONTAINS]->(p:Product) "
                        "RETURN p, COUNT(*) AS times ORDER BY times DESC LIMIT 10", cid=customer_id)
                    for rec3 in r3:
                        products.append(_neo4j_safe_str(dict(rec3["p"])))
                    r4 = session.run(
                        "MATCH (c:Customer {id: $cid})-[r:HAS_COMMUNICATION]->(com) "
                        "RETURN com ORDER BY com.created_at DESC LIMIT 10", cid=customer_id)
                    for rec4 in r4:
                        comms.append(_neo4j_safe_str(dict(rec4["com"])))
                    return {"customer": customer, "orders": orders, "skus": products, "communications": comms}
            except Exception as e:
                logger.warning(f"[Neo4j] 获取档案失败: {e}")
        return self._sqlite_get_full_profile(customer_id)


_neo4j_conn = None


def _get_neo4j():
    global _neo4j_conn
    if _neo4j_conn is None:
        _neo4j_conn = BuyerNeo4jConnection()
        _neo4j_conn.connect()
    return _neo4j_conn


# ============== AI 服务层 ==============
_buyer_circuit_open = False
_buyer_circuit_count = 0
_buyer_circuit_time = 0.0
_BUYER_CIRCUIT_THRESHOLD = 5
_BUYER_CIRCUIT_TIMEOUT = 30.0


def _check_circuit():
    global _buyer_circuit_open, _buyer_circuit_count, _buyer_circuit_time
    import time as _time
    if _buyer_circuit_open:
        if _time.time() - _buyer_circuit_time > _BUYER_CIRCUIT_TIMEOUT:
            _buyer_circuit_open = False
            _buyer_circuit_count = 0
            logger.info("[CircuitBreaker] 买方 AI 恢复 CLOSED")
        else:
            return False
    return True


def _record_circuit(success: bool):
    global _buyer_circuit_open, _buyer_circuit_count, _buyer_circuit_time
    import time as _time
    if success:
        _buyer_circuit_count = 0
        _buyer_circuit_open = False
    else:
        _buyer_circuit_count += 1
        if _buyer_circuit_count >= _BUYER_CIRCUIT_THRESHOLD:
            _buyer_circuit_open = True
            _buyer_circuit_time = _time.time()
            logger.warning(f"[CircuitBreaker] 买方 AI 熔断 OPEN（{_BUYER_CIRCUIT_THRESHOLD}次失败）")


def _detect_emotion(msg: str) -> str:
    msg = (msg or "").lower()
    angry = ["生气", "投诉", "退款", "退货", "垃圾", "烂", "angry", "refund", "return", "hate"]
    if any(k in msg for k in angry):
        return "angry"
    happy = ["谢谢", "好", "棒", "喜欢", "满意", "thank", "great", "love"]
    if any(k in msg for k in happy):
        return "happy"
    return "neutral"


_LANG_SWITCH_PATTERNS = {
    "zh": ["说中文", "用中文", "切换中文", "换中文", "讲中文", "中文回复"],
    "en": ["speak english", "switch to english", "说英语", "用英语"],
    "ar": ["العربية", "切换阿拉伯", "阿拉伯语"],
    "ru": ["по-русски", "切换俄语", "на русском"],
    "th": ["ภาษาไทย", "พูดไทย", "切换泰语"],
    "vi": ["tiếng việt", "nói tiếng việt", "切换越南语"],
    "id": ["bahasa indonesia", "切换印尼语"],
    "ms": ["bahasa melayu", "切换马来语"],
    "tl": ["filipino", "切换菲律宾语", "in filipino", "tagalog"],
}


def _check_lang_switch(msg: str) -> Optional[str]:
    msg_lower = (msg or "").lower()
    for lang, patterns in _LANG_SWITCH_PATTERNS.items():
        for p in patterns:
            if p in msg_lower:
                return lang
    return None


def _call_deepseek(messages: list, temperature: float = 0.65, max_tokens: int = 400) -> Optional[str]:
    if not DEEPSEEK_API_KEY:
        return None
    if not _check_circuit():
        return None
    try:
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {DEEPSEEK_API_KEY}"}
        payload = {"model": "deepseek-chat", "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
        resp = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=(15, 60))
        if resp.status_code == 200:
            data = resp.json()
            choices = data.get("choices") or []
            if choices:
                content = (choices[0].get("message") or {}).get("content") or ""
                if content.strip():
                    _record_circuit(True)
                    return content.strip()
        _record_circuit(False)
    except Exception as e:
        logger.error(f"DeepSeek API 失败: {e}")
        _record_circuit(False)
    return None


def _translate_text(text: str, target_lang: str) -> str:
    if not text or not DEEPSEEK_API_KEY:
        return text
    lang_map = {"zh": "简体中文", "en": "英语", "ar": "阿拉伯语", "ru": "俄语",
                "th": "泰语", "vi": "越南语", "id": "印尼语", "ms": "马来语", "tl": "菲律宾语"}
    try:
        result = _call_deepseek(
            [{"role": "system", "content": f"你是专业翻译引擎。只输出翻译后的文本，禁止添加任何解释。输出语言：{lang_map.get(target_lang, '英语')}。原文：{text}"}],
            temperature=0.1, max_tokens=300)
        return result if result else text
    except Exception:
        return text


# 语言映射
_LANG_NAMES = {"zh": "中文", "en": "English", "ar": "العربية", "ru": "Русский",
               "th": "ภาษาไทย", "vi": "Tiếng Việt", "id": "Bahasa Indonesia",
               "ms": "Bahasa Melayu", "tl": "Filipino"}
_DEAR_MAP = {"zh": "亲爱的", "en": "Dear", "ar": "عزيزي", "ru": "Дорогой",
             "th": "สวัสดีค่ะ/ครับ", "vi": "Kính chào quý khách",
             "id": "Hai, selamat datang", "ms": "Hai, pelanggan tersayang", "tl": "Mahal na customer"}
_TAIL_MAP = {
    "zh": "我在呢~有需要随时叫我~",
    "en": "I'm right here — ping me anytime!",
    "ar": "أنا هنا، لا تتردد في السؤال في أي وقت.",
    "ru": "Я на связи — обращайтесь в любое время!",
    "th": "มีอะไรสอบถามเพิ่มเติมได้เลยนะค่ะ/ครับ พร้อมช่วยเสมอค่ะ/ครับ",
    "vi": "Tôi ở đây rồi — liên hệ bất cứ lúc nào nhé!",
    "id": "Saya siap membantu kapan saja, jangan ragu ya!",
    "ms": "Saya sedia membantu bila-bila masa, jangan segan bertanya ya!",
    "tl": "Nandito lang ako — makikipag-chat ka paano man, huwag mahiya!"
}

_EMOTION_GUIDE = {
    "angry": {
        "zh": "先道歉+解决，再加一句温暖结尾",
        "en": "Apologize sincerely first, then add ONE warm human-like closing line.",
        "ar": "اعتذر أولاً بصدق، ثم أضف سطراً دافئاً واحداً مثل客户服务.",
        "ru": "Сначала искренне извинитесь, затем добавьте одну тёплую фразу.",
        "th": "ขอโทษก่อนอย่างจริงใจ แล้วตบท้ายด้วยประโยคอบอุ่นหนึ่งประโยค",
        "vi": "Xin lỗi chân thành trước, rồi kết thúc bằng một câu ấm áp như người thật.",
        "id": "Minta maaf dengan tulus dulu, lalu tutup dengan satu kalimat hangat seperti manusia.",
        "ms": "Minta maaf dengan ikhlas dulu, lepas tu tutup dengan satu ayat mesra manusia.",
        "tl": "Humiling ng sorry muna nang tapat, tapos magdagdag ng isang mainit na linya."
    },
    "happy": {
        "zh": "回应开心情绪+活泼一句结尾",
        "en": "Acknowledge their happiness, then add ONE lively human-like closing.",
        "ar": "اعترف بسعادة العميل، ثم أضف سطراً دافئاً واحداً.",
        "ru": "Примите радость клиента, затем добавьте одну тёплую фразу.",
        "th": "ตอบรับความสุขของลูกค้า แล้วปิดท้ายด้วยประโยคอบอุ่นหนึ่งประโยค",
        "vi": "Đáp lại niềm vui, rồi kết bằng một câu ấm áp như người thật.",
        "id": "Apresiasi kebahagiaannya, lalu tutup dengan satu kalimat hangat.",
        "ms": "Apresiasi kegembiraan mereka, lepas tu tutup dengan satu ayat mesra.",
        "tl": "Kilalanin ang kaligayahan, tapos magdagdag ng isang mainit na linya."
    },
    "neutral": {
        "zh": "答完问题+拟人化一句结尾",
        "en": "Answer the question concisely, then ALWAYS end with ONE human-like closing line (from the tail list).",
        "ar": "أجب على سؤال العميل بإيجاز، ثم أضف سطراً دافئاً واحداً دائماً.",
        "ru": "Ответьте кратко, затем ВСЕГДА добавьте одну тёплую фразу.",
        "th": "ตอบคำถามกระชับ แล้วปิดท้ายด้วยประโยคอบอุ่นหนึ่งประโยคเสมอ",
        "vi": "Trả lời ngắn gọn, rồi LUÔN kết bằng một câu ấm áp như người thật.",
        "id": "Jawab pertanyaan secara ringkas, lalu SELALU akhiri dengan satu kalimat hangat.",
        "ms": "Jawab soalan secara ringkas, lepas tu SENTIASA tutup dengan satu ayat mesra.",
        "tl": "Sumagot nang maikli, tapos LAGING magdagdag ng isang mainit na linya sa dulo."
    }
}


def _generate_ai_response(user_message: str, customer_info: dict, conversation_history: list, language: str = "zh") -> tuple[str, Optional[str]]:
    user_message = (user_message or "").strip()
    if not user_message:
        return (_DEAR_MAP.get(language, "亲爱的") + "，我在呢~请问有什么可以帮您？", None)

    explicit_switch = _check_lang_switch(user_message)
    if explicit_switch:
        confirm = {
            "zh": f"好的，已切换到{_LANG_NAMES.get(explicit_switch, explicit_switch)}回复。",
            "en": f"Switched to {_LANG_NAMES.get(explicit_switch, explicit_switch)}.",
        }
        return confirm.get(explicit_switch, confirm["zh"]), explicit_switch

    detected_lang = language
    msg = user_message
    zh_chars = sum(1 for c in msg if '\u4e00' <= c <= '\u9fff')
    if zh_chars >= max(3, len(msg) * 0.3):
        detected_lang = "zh"

    if detected_lang != language:
        confirm = {
            "zh": f"好的，已自动切换到{_LANG_NAMES.get(detected_lang, detected_lang)}回复。",
            "en": f"Auto-switched to {_LANG_NAMES.get(detected_lang, detected_lang)}.",
        }
        return confirm.get(detected_lang, confirm["zh"]), detected_lang

    transfer_kw = ["转人工", "人工客服", "真人", "投诉", "退款", "退货",
                   "transfer to human", "live agent", "refund", "complaint"]
    if any(kw.lower() in user_message.lower() for kw in transfer_kw):
        return "好的，正在为您转接人工客服，请稍候...", None

    orders_in_db = (customer_info or {}).get("orders") or []
    order_kw = ["订单", "order", "ord-", "单号", "快递", "物流", "tracking", "refund", "return"]
    has_order_kw = any(kw in user_message.lower() for kw in order_kw)
    if has_order_kw and not orders_in_db:
        dear = _DEAR_MAP.get(language, "亲爱的")
        tail = _TAIL_MAP.get(language, _TAIL_MAP["zh"])
        no_orders = {
            "zh": f"{dear}，档案里暂无订单记录，建议您提供订单号我来帮查。",
            "en": f"{dear}, no orders in your profile. Please provide the order number.",
        }
        return f"{no_orders.get(language, no_orders['zh'])}\n\n{tail}", None

    cust = customer_info or {}
    orders = cust.get("orders") or []
    profile_summary = f"客户等级：{cust.get('customer', {}).get('level', '普通')}\n累计订单：{len(orders)}单\n"
    history_text = ""
    if conversation_history:
        lines = []
        for m in conversation_history[-6:]:
            role = "你" if m.get("role") == "user" else "AI"
            lines.append(f"  {role}：{m.get('content', '')[:80]}")
        history_text = "\n".join(lines)
    else:
        history_text = "（首次对话）"

    emotion = _detect_emotion(user_message)
    em_guide = _EMOTION_GUIDE.get(emotion, _EMOTION_GUIDE["neutral"]).get(language, _EMOTION_GUIDE[emotion]["zh"])
    lang_display = _LANG_NAMES.get(language, "中文")
    tail = _TAIL_MAP.get(language, _TAIL_MAP["zh"])

    system_prompt = f"""【角色】你是金牌AI客服，回复要干练、先答后暖。
【必须遵守 — 违反者将被投诉】
1) 先直接回答客户问题：给事实/步骤/数据；不铺垫、不空泛共情。
2) 回答完立即追加1句拟人化结尾语，格式为：
   "{tail}"
   ← 这一句必须出现，不能省略！
3) 全程用 {lang_display} 回复，禁止混写其他语言。
4) 字数：中文80-120字，英文50-80词，其他语言同短。
5) 拟人化结尾语必须放在回复最后一行，前面加一个空行隔开。
【语气】{em_guide}
【铁律】禁止捏造任何订单号/物流单号/发货时间。若档案中无订单，对订单类询问必须回复：「档案里暂无订单记录，建议您提供订单号我来帮查」。
【客户档案摘要】{profile_summary}
【对话历史】{history_text}
【客户消息】「{user_message}」
请严格按以下格式回复：
[直接回答部分]

{tail}"""

    messages = [{"role": "system", "content": system_prompt}]
    for h in conversation_history[-10:]:
        messages.append(h)
    messages.append({"role": "user", "content": user_message})

    ai_reply = _call_deepseek(messages)
    if not ai_reply:
        fallback = {
            "zh": "亲爱的，我在呢~刚才网络有点忙，你可以再说一下问题，我帮你看看。",
            "en": "Dear, I'm here! The line was busy -- could you say that again?",
            "ar": "عزيزي، أنا هنا! الشبكة مشغولة قليلاً، هل يمكنك المحاولة مرة أخرى؟",
            "ru": "Дорогой, я здесь! Сеть немного занята, попробуйте ещё раз.",
            "th": "สวัสดีค่ะ มีอะไรสอบถามเพิ่มเติมได้เลยนะค่ะ/ครับ",
            "vi": "Kính chào quý khách, tôi ở đây rồi! Mạng hơi bận, bạn thử lại nhé.",
            "id": "Hai, saya di sini! Jaringan agak sibuk, coba lagi ya!",
            "ms": "Hai, saya sedia di sini! Rangkaian agak sibuk, cuba lagi ya!",
            "tl": "Mahal na customer, nandito lang ako! Medyo busy ang linya, subukan mo ulit!",
        }
        return fallback.get(language, fallback["zh"]), None

    # 确保拟人化结尾语存在，若缺失则追加
    tail_ok = any(
        t.lower() in ai_reply.lower()
        for t in [
            "i'm right here", "ping me anytime", "ask me anything",
            "لا تتردد", "в любое время", "มีอะไรสอบถาม",
            "lien he", "bất cứ lúc nào", "bisa saya bantu",
            "sedia membantu", "makikipag-chat", "随时叫我",
            "我在呢", "nandito lang ako"
        ]
    )
    if not tail_ok:
        ai_reply = ai_reply.strip() + "\n\n" + tail
    return ai_reply, None


# ============== AI回复生成（滑动窗口优化版）===============
def _generate_ai_response_optimized(
    user_message: str,
    customer_info: dict,
    optimized_history: list,
    language: str = "zh"
) -> tuple[str, Optional[str]]:
    """
    AI回复生成（滑动窗口优化版）

    使用滑动窗口上下文管理：
    - 最近10轮核心摘要
    - 最近3轮原始对话
    - Token预算控制（<=2000 tokens）
    """
    user_message = (user_message or "").strip()
    if not user_message:
        return (_DEAR_MAP.get(language, "亲爱的") + "，我在呢~请问有什么可以帮您？", None)

    explicit_switch = _check_lang_switch(user_message)
    if explicit_switch:
        confirm = {
            "zh": f"好的，已切换到{_LANG_NAMES.get(explicit_switch, explicit_switch)}回复。",
            "en": f"Switched to {_LANG_NAMES.get(explicit_switch, explicit_switch)}.",
        }
        return confirm.get(explicit_switch, confirm["zh"]), explicit_switch

    detected_lang = language
    msg = user_message
    zh_chars = sum(1 for c in msg if '\u4e00' <= c <= '\u9fff')
    if zh_chars >= max(3, len(msg) * 0.3):
        detected_lang = "zh"

    if detected_lang != language:
        confirm = {
            "zh": f"好的，已自动切换到{_LANG_NAMES.get(detected_lang, detected_lang)}回复。",
            "en": f"Auto-switched to {_LANG_NAMES.get(detected_lang, detected_lang)}.",
        }
        return confirm.get(detected_lang, confirm["zh"]), detected_lang

    transfer_kw = ["转人工", "人工客服", "真人", "投诉", "退款", "退货",
                   "transfer to human", "live agent", "refund", "complaint"]
    if any(kw.lower() in user_message.lower() for kw in transfer_kw):
        return "好的，正在为您转接人工客服，请稍候...", None

    orders_in_db = (customer_info or {}).get("orders") or []
    order_kw = ["订单", "order", "ord-", "单号", "快递", "物流", "tracking", "refund", "return"]
    has_order_kw = any(kw in user_message.lower() for kw in order_kw)
    if has_order_kw and not orders_in_db:
        dear = _DEAR_MAP.get(language, "亲爱的")
        tail = _TAIL_MAP.get(language, _TAIL_MAP["zh"])
        no_orders = {
            "zh": f"{dear}，档案里暂无订单记录，建议您提供订单号我来帮查。",
            "en": f"{dear}, no orders in your profile. Please provide the order number.",
        }
        return f"{no_orders.get(language, no_orders['zh'])}\n\n{tail}", None

    cust = customer_info or {}
    orders = cust.get("orders") or []
    profile_summary = f"客户等级：{cust.get('customer', {}).get('level', '普通')}\n累计订单：{len(orders)}单\n"

    # === 滑动窗口：使用优化的上下文 ===
    # 区分摘要消息和原始对话
    summary_messages = []
    recent_messages = []
    for msg in optimized_history:
        if msg.get("role") == "system":
            summary_messages.append(msg)
        else:
            recent_messages.append(msg)

    # 构建对话历史文本
    history_text = ""
    if recent_messages:
        lines = []
        for m in recent_messages[-6:]:  # 最近3轮原始对话
            role = "你" if m.get("role") == "user" else "AI"
            lines.append(f"  {role}：{m.get('content', '')[:80]}")
        history_text = "\n".join(lines)
    else:
        history_text = "（首次对话）"

    # 合并摘要
    if summary_messages:
        summary_text = "\n".join([m.get("content", "") for m in summary_messages])
        history_text = f"{summary_text}\n{history_text}"

    emotion = _detect_emotion(user_message)
    em_guide = _EMOTION_GUIDE.get(emotion, _EMOTION_GUIDE["neutral"]).get(language, _EMOTION_GUIDE[emotion]["zh"])
    lang_display = _LANG_NAMES.get(language, "中文")
    tail = _TAIL_MAP.get(language, _TAIL_MAP["zh"])

    system_prompt = f"""【角色】你是金牌AI客服，回复要干练、先答后暖。

【上下文记忆策略 - 滑动窗口模式】
- 上方【对话摘要】是历史核心信息
- 下方【最近对话】是最近3轮原始对话

【必须遵守 — 违反者将被投诉】
1) 先直接回答客户问题：给事实/步骤/数据；不铺垫、不空泛共情。
2) 回答完立即追加1句拟人化结尾语，格式为：
   "{tail}"
   ← 这一句必须出现，不能省略！
3) 全程用 {lang_display} 回复，禁止混写其他语言。
4) 字数：中文80-120字，英文50-80词，其他语言同短。

【语气】{em_guide}

【铁律】禁止捏造任何订单号/物流单号/发货时间。若档案中无订单，对订单类询问必须回复：「档案里暂无订单记录，建议您提供订单号我来帮查」。

【客户档案摘要】{profile_summary}

【对话历史】
{history_text}

【客户消息】「{user_message}」

请严格按以下格式回复：
[直接回答部分]

{tail}"""

    messages = [{"role": "system", "content": system_prompt}]

    # 只添加原始对话到 messages（摘要已在 system_prompt 中）
    for h in recent_messages[-6:]:
        messages.append(h)

    messages.append({"role": "user", "content": user_message})

    ai_reply = _call_deepseek(messages)
    if not ai_reply:
        fallback = {
            "zh": "亲爱的，我在呢~刚才网络有点忙，你可以再说一下问题，我帮你看看。",
            "en": "Dear, I'm here! The line was busy -- could you say that again?",
            "ar": "عزيزي، أنا هنا! الشبكة مشغولة قليلاً، هل يمكنك المحاولة مرة أخرى؟",
            "ru": "Дорогой, я здесь! Сеть немного занята, попробуйте ещё раз.",
            "th": "สวัสดีค่ะ มีอะไรสอบถามเพิ่มเติมได้เลยนะค่ะ/ครับ",
            "vi": "Kính chào quý khách, tôi ở đây rồi! Mạng hơi bận, bạn thử lại nhé.",
            "id": "Hai, saya di sini! Jaringan agak sibuk, coba lagi ya!",
            "ms": "Hai, saya sedia di sini! Rangkaian agak sibuk, cuba lagi ya!",
            "tl": "Mahal na customer, nandito lang ako! Medyo busy ang linya, subukan mo ulit!",
        }
        return fallback.get(language, fallback["zh"]), None

    # 确保拟人化结尾语存在，若缺失则追加
    tail_ok = any(
        t.lower() in ai_reply.lower()
        for t in [
            "i'm right here", "ping me anytime", "ask me anything",
            "لا تتردد", "в любое время", "มีอะไรสอบถาม",
            "lien he", "bất cứ lúc nào", "bisa saya bantu",
            "sedia membantu", "makikipag-chat", "随时叫我",
            "我在呢", "nandito lang ako"
        ]
    )
    if not tail_ok:
        ai_reply = ai_reply.strip() + "\n\n" + tail
    return ai_reply, None


# ============== 数据库写操作 ==============
def _db_save_session(session_id: str, customer_id: str, is_ai: int = 1):
    if _is_mysql_available():
        _buyer_execute(
            "INSERT IGNORE INTO sessions (session_id, customer_id, is_ai, status, system_source) VALUES (%s, %s, %s, 'active', 'buyer')",
            (session_id, customer_id, is_ai))
    else:
        _buyer_execute(
            "INSERT OR IGNORE INTO sessions (session_id, customer_id, is_ai, status, system_source) VALUES (?, ?, ?, 'active', 'buyer')",
            (session_id, customer_id, is_ai))


def _db_save_message(session_id: str, role: str, content: str):
    _buyer_execute("INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)",
                   (session_id, role, content))
    if _is_mysql_available():
        _buyer_execute("UPDATE sessions SET updated_at = NOW() WHERE session_id = ?", (session_id,))
    else:
        _buyer_execute("UPDATE sessions SET updated_at = CURRENT_TIMESTAMP WHERE session_id = ?", (session_id,))


def _db_get_active_session(customer_id: str) -> Optional[dict]:
    if _is_mysql_available():
        sql = """SELECT * FROM sessions WHERE customer_id = %s AND status IN ('active', 'waiting')
                 AND updated_at >= DATE_SUB(NOW(), INTERVAL 7 DAY) ORDER BY updated_at DESC LIMIT 1"""
        return _buyer_query(sql, (customer_id,), fetch_one=True)
    else:
        sql = """SELECT * FROM sessions WHERE customer_id = ? AND status IN ('active', 'waiting')
                 AND updated_at >= datetime('now', '-7 days') ORDER BY updated_at DESC LIMIT 1"""
        return _buyer_query(sql, (customer_id,), fetch_one=True)


def _db_update_session(session_id: str, **kwargs):
    if not kwargs:
        return
    fields = ", ".join([f"{k} = ?" for k in kwargs.keys()])
    values = list(kwargs.values()) + [session_id]
    if _is_mysql_available():
        sql = f"UPDATE sessions SET {fields}, updated_at = NOW() WHERE session_id = ?"
    else:
        sql = f"UPDATE sessions SET {fields}, updated_at = CURRENT_TIMESTAMP WHERE session_id = ?"
    _buyer_execute(sql, tuple(values))


# ============== 跨系统 API 客户端 ==============
def _make_internal_headers(method: str, path: str) -> dict:
    import hmac, base64, time as _time, hashlib as _hmaclib
    secret = SELLER_INTERNAL_TOKEN.encode("utf-8")
    ts = str(int(_time.time()))
    payload = f"{ts}{method}{path}"
    sig = base64.b64encode(
        hmac.new(secret, payload.encode("utf-8"), _hmaclib.sha256).digest()
    ).decode("utf-8")
    return {"X-Internal-Signature": sig, "X-Internal-Timestamp": ts, "Content-Type": "application/json"}


def _notify_seller_transfer(session_id: str, customer_id: str, language: str = "zh") -> dict:
    try:
        path = "/api/v1/agent/buyer-transfer"
        headers = _make_internal_headers("POST", path)
        url = f"{SELLER_API_HOST}{path}"
        payload = {
            "session_id": session_id,
            "customer_id": customer_id,
            "language": language,
            "source": "buyer_system",
        }
        resp = requests.post(url, json=payload, headers=headers, timeout=10)
        if resp.status_code == 200:
            logger.info(f"成功通知卖方系统转人工: session={session_id}")
            return resp.json()
        else:
            logger.warning(f"卖方系统返回异常: {resp.status_code} - {resp.text[:200]}")
            return {"success": False, "message": f"卖方系统返回 {resp.status_code}"}
    except requests.exceptions.ConnectionError:
        logger.error(f"无法连接到卖方系统 {SELLER_API_HOST}，请确认卖方系统正在运行（端口 8000）")
        return {"success": False, "message": "无法连接到卖方系统（端口8000未启动）"}
    except Exception as e:
        logger.error(f"通知卖方系统失败: {e}")
        return {"success": False, "message": str(e)}


# ============== 转人工关键词 ==============
_TRANSFER_HUMAN_KW = ["转人工", "人工客服", "真人", "找客服", "要人工", "人工",
                       "我要投诉", "投诉", "举报", "差评", "退款", "退货",
                       "transfer to human", "real agent", "live agent", "speak to human",
                       "complaint", "refund request"]
_TRANSFER_AI_KW = ["转AI", "转回AI", "切回AI", "回AI模式", "switch to AI", "back to AI"]


def _should_transfer_to_human(message: str) -> bool:
    return any(kw.lower() in (message or "").lower() for kw in _TRANSFER_HUMAN_KW)


def _should_transfer_to_ai(message: str) -> bool:
    return any(kw.lower() in (message or "").lower() for kw in _TRANSFER_AI_KW)


def _verify_internal_token(x_token: str = Header(default="")) -> bool:
    """Verify internal callback token from header."""
    expected = BUYER_CALLBACK_TOKEN
    if not expected:
        return False
    return x_token == expected


def _verify_internal_token_body(body_customer_id: str) -> bool:
    expected = BUYER_CALLBACK_TOKEN
    if not expected:
        return False
    return True


# ============== FastAPI 应用 ==============
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=" * 50)
    logger.info("  买方AI客服系统 启动中...")
    logger.info(f"  端口: {BUYER_PORT}")
    logger.info(f"  买方数据库: {BUYER_DB}")
    logger.info(f"  卖方系统API: {SELLER_API_HOST}")
    logger.info("=" * 50)
    _init_buyer_db()
    neo = _get_neo4j()
    if neo.driver:
        logger.info("[数据层] Neo4j 已连接（完整档案模式）")
    else:
        logger.warning("[数据层] Neo4j 未连接，已切换 SQLite 回退模式")
    yield
    logger.info("买方系统关闭中...")
    if _neo4j_conn:
        _neo4j_conn.close()
    logger.info("买方系统已关闭")


app = FastAPI(
    title="买方AI客服系统",
    description="面向买方的AI客服，支持转人工到卖方坐席系统",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Internal-Token", "X-Session-Id"],
)

# 限流中间件
try:
    from rate_limiter import RateLimitMiddleware, rate_limiter
    app.add_middleware(RateLimitMiddleware, limiter=rate_limiter)
    logger.info("[限流] 买方限流中间件已启用")
except ImportError:
    logger.info("[限流] rate_limiter 未安装，跳过")


# ============== 静态文件 ==============
if UPLOAD_DIR.exists():
    app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")


# ============== 卖家回调接口（internal）==============
@app.post("/api/v1/internal/buyer-back-to-ai", tags=["internal"])
async def internal_buyer_back_to_ai(
    session_id: str = Body(...),
    customer_id: str = Body(default=""),
    x_buyer_callback_token: str = Header(default=""),
):
    if not _verify_internal_token(x_buyer_callback_token):
        return JSONResponse({"success": False, "message": "Unauthorized"}, status_code=403)
    _db_update_session(session_id, is_ai=1, status="active")
    lang = buyer_session_manager.get_session(session_id).get("language", "zh") \
        if buyer_session_manager.get_session(session_id) else "zh"
    buyer_session_manager.update_session_language(session_id, lang)
    logger.info(f"卖方回调：会话 {session_id} 已转回AI模式")
    return {"success": True}


@app.post("/api/v1/internal/buyer-message", tags=["internal"])
async def internal_buyer_message(
    session_id: str = Body(...),
    content: str = Body(...),
    customer_id: str = Body(default=""),
):
    if not _verify_internal_token_body(customer_id):
        return JSONResponse({"success": False, "message": "Unauthorized"}, status_code=403)
    _db_save_message(session_id, "assistant", content)
    return {"success": True}


# ============== 页面路由 ===============
@app.get("/")
async def buyer_home():
    html_path = _frontend_index_path()
    if html_path.exists():
        return FileResponse(html_path)
    return HTMLResponse(
        "<h1>买方AI客服系统</h1><p>未找到 index.html。</p>"
        "<p>请将买方 frontend/index.html 准备好，或确认 BUYER_DB_PATH 正确。</p>",
        status_code=404)


@app.get("/entry")
async def buyer_entry():
    return await buyer_home()


@app.get("/customer")
async def buyer_customer_page():
    html_path = FRONTEND_DIR / "customer" / "chat.html"
    if html_path.exists():
        return FileResponse(html_path)
    return HTMLResponse("<h1>聊天页面未找到</h1>", status_code=404)


@app.get("/chat")
async def buyer_chat_alias():
    return await buyer_customer_page()


@app.get("/customer/chat.html")
async def buyer_chat_page():
    return await buyer_customer_page()


@app.get("/customer/human_chat.html")
async def buyer_human_chat_page():
    html_path = FRONTEND_DIR / "customer" / "human_chat.html"
    if html_path.exists():
        return FileResponse(html_path)
    return HTMLResponse("<h1>人工聊天页面未找到</h1>", status_code=404)


# ============== 健康检查 ===============
@app.get("/health")
async def health_check():
    neo = _get_neo4j()
    neo_ok = neo.driver is not None
    sqlite_ok = False
    try:
        conn = _get_buyer_db_connection()
        if conn:
            conn.execute("SELECT 1")
            conn.close()
            sqlite_ok = True
    except Exception:
        pass
    return {
        "status": "ok",
        "version": "1.0.0",
        "system": "buyer",
        "port": BUYER_PORT,
        "neo4j": "connected" if neo_ok else "disconnected",
        "data_mode": "neo4j_full" if neo_ok else "sqlite_fallback",
        "sqlite": "ok" if sqlite_ok else "error",
        "buyer_db": str(BUYER_DB),
        "seller_api": SELLER_API_HOST,
        "circuit_breaker": "open" if _buyer_circuit_open else "closed",
    }


@app.get("/ready")
async def readiness_probe():
    checks = {"db": "ok"}
    try:
        conn = _get_buyer_db_connection()
        if conn:
            conn.execute("SELECT 1")
            conn.close()
    except Exception as e:
        checks["db"] = f"error: {e}"
        return {"status": "not_ready", "checks": checks}, 503
    return {"status": "ready", "checks": checks}


@app.get("/live")
async def liveness_probe():
    return {"status": "alive"}


@app.get("/api/status")
async def api_status_compat():
    """兼容性别名：前端体检页面使用 /api/status，与卖方系统一致"""
    return await api_status()


@app.get("/api/v1/status")
async def api_status():
    neo4j_ok = False
    try:
        neo = _get_neo4j()
        if neo.driver:
            with neo.driver.session() as session:
                session.run("RETURN 1")
            neo4j_ok = True
    except Exception:
        pass
    return {
        "neo4j": neo4j_ok,
        "graphrag": True,
        "redis": True,
        "deepseek": True,
        "service": "buyer-ai-service",
        "circuit_breaker": "open" if _buyer_circuit_open else "closed",
    }


# ============== 核心 API：开始会话 ===============
@app.post("/api/v1/customer/start", response_model=StartSessionResponse)
async def start_session(req: StartSessionRequest):
    phone = req.phone
    customer_id = req.customer_id
    if not phone and not customer_id:
        return StartSessionResponse(success=False, message="请提供手机号或客户ID")

    neo = _get_neo4j()
    customer = neo.find_customer(phone=phone, customer_id=customer_id)

    if not customer:
        if phone:
            auto_cid = f"buyer_auto_{phone}"
            neo._ensure_customer_in_sqlite(phone=phone, customer_id=auto_cid,
                                           name=f"客户{phone[-4:]}", region="未知")
            customer = neo._sqlite_find_customer(phone=phone)
            if customer:
                logger.info(f"[自动注册] 新客户 {phone} -> {customer.get('customer_id')}")
        elif customer_id:
            neo._ensure_customer_in_sqlite(phone=None, customer_id=customer_id, name=f"客户_{customer_id[-8:]}")
            customer = neo._sqlite_find_customer(customer_id=customer_id)
        if not customer:
            return StartSessionResponse(success=False, message="未找到客户信息")

    cid = customer.get("customer_id") or customer.get("id")
    customer["customer_id"] = cid
    profile = neo.get_full_profile(cid)
    if not profile:
        profile = {"customer": customer, "orders": [], "skus": [], "communications": []}

    existing = _db_get_active_session(cid)
    if existing:
        session_id = existing["session_id"]
        history = []
        try:
            rows = _buyer_query(
                "SELECT role, content FROM messages WHERE session_id = ? ORDER BY id ASC", (session_id,))
            if rows:
                history = [{"role": r.get("role") if hasattr(r, 'get') else r[0],
                            "content": r.get("content") if hasattr(r, 'get') else r[1]} for r in rows]
        except Exception:
            history = []
        active_lang = "zh"
        name = customer.get("name", "朋友")
        welcome = f"欢迎回来，{name}！请问有什么可以帮您？"
        buyer_session_manager.sessions[session_id] = {
            "customer_info": profile, "language": active_lang,
            "conversation_history": history, "system": "buyer"}
        buyer_session_manager.sessions[session_id]["customer_info"]["session_id"] = session_id
        return StartSessionResponse(
            success=True, session_id=session_id, customer_info=profile,
            welcome_message=welcome, language=active_lang)

    session_id = buyer_session_manager.create_session(profile, language="zh")
    customer["session_id"] = session_id
    _db_save_session(session_id, cid, is_ai=1)
    name = customer.get("name", "尊贵的朋友")
    welcome = f"您好，{name}！我是您的专属AI客服，请问有什么可以帮您？"
    _db_save_message(session_id, "assistant", welcome)
    return StartSessionResponse(
        success=True, session_id=session_id, customer_info=profile,
        welcome_message=welcome, language="zh")


# ============== 增强版 AI 响应器（融合 cross-border-ecommerce-chatbot.md 源文件）===============
_enhanced_responder = None

def _get_enhanced_responder():
    """获取增强版 AI 响应器（延迟初始化）"""
    global _enhanced_responder
    if _enhanced_responder is None:
        try:
            from ai_enhanced_response import EnhancedAIResponder
            neo4j_conn = _get_neo4j()
            _enhanced_responder = EnhancedAIResponder(
                neo4j_conn=neo4j_conn,
                llm_call_func=_call_deepseek
            )
            logger.info("[AI] 增强版响应器初始化成功（RAG + 知识图谱 + 意图分类）")
        except ImportError as e:
            logger.warning(f"[AI] 增强版响应器未找到，使用传统模式: {e}")
            return None
        except Exception as e:
            logger.warning(f"[AI] 增强版响应器初始化失败: {e}")
            return None
    return _enhanced_responder


# ============== 核心 API：聊天 ===============
@app.post("/api/v1/customer/chat", response_model=ChatResponse)
async def customer_chat(req: ChatRequest):
    session_id = req.session_id
    message = req.message
    if not session_id or not message:
        return ChatResponse(success=False, message="缺少参数")

    if buyer_session_manager.is_duplicate(session_id, req.client_message_id):
        return ChatResponse(success=True, message="duplicate", response="")

    session = buyer_session_manager.get_session(session_id)
    if not session:
        return ChatResponse(success=False, message="会话不存在或已过期")

    customer_info = session.get("customer_info") or {}
    language = session.get("language", "zh")

    _db_save_message(session_id, "user", message)
    buyer_session_manager.add_message(session_id, "user", message)

    if _should_transfer_to_human(message):
        logger.info(f"买方会话 {session_id} 检测到转人工关键词")
        _db_update_session(session_id, is_ai=0, status="waiting")
        cid = customer_info.get("customer", {}).get("customer_id") or customer_info.get("customer_id", "")
        _notify_seller_transfer(session_id, cid, language)
        transfer_msg = {
            "zh": "好的，正在为您转接人工客服，请稍候...",
            "en": "Transferring you to a human agent, please wait...",
            "ar": "جارٍ تحويلك إلى موظف خدمة عملاء، يرجى الانتظار...",
            "ru": "Переключаю вас على оператора, пожалуйста, подождите..."}
        msg = transfer_msg.get(language, transfer_msg["zh"])
        _db_save_message(session_id, "assistant", msg)
        buyer_session_manager.add_message(session_id, "assistant", msg)
        return ChatResponse(success=True, response=msg, language=language, auto_transfer="human")

    # === AI拟人化记忆力：使用滑动窗口上下文 ===
    if MEMORY_ENABLED:
        try:
            from conversation_memory import get_memory
            memory = get_memory(session_id)
            optimized_history = memory.get_context()
        except Exception:
            optimized_history = session.get("conversation_history") or []
    else:
        optimized_history = session.get("conversation_history") or []

    # === 优先使用增强版响应器（融合 RAG + 知识图谱 + 8类意图分类）===
    enhanced = _get_enhanced_responder()
    if enhanced is not None:
        try:
            result = enhanced.generate(
                user_message=message,
                customer_info=customer_info,
                conversation_history=optimized_history,
                language=language
            )
            if result.auto_transfer == "human":
                _db_update_session(session_id, is_ai=0, status="waiting")
                cid = customer_info.get("customer", {}).get("customer_id") or ""
                _notify_seller_transfer(session_id, cid, language)
                _db_save_message(session_id, "assistant", result.reply)
                buyer_session_manager.add_message(session_id, "assistant", result.reply)
                logger.info(f"[AI-Enhanced] 会话 {session_id} 自动转人工 (intent={result.intent})")
                return ChatResponse(
                    success=True, response=result.reply,
                    language=language, auto_transfer="human",
                    intent=result.intent, emotion=result.emotion, confidence=result.confidence
                )
            if result.language != language:
                buyer_session_manager.update_session_language(session_id, result.language)
                _db_update_session(session_id, language=result.language)
            _db_save_message(session_id, "assistant", result.reply)
            buyer_session_manager.add_message(session_id, "assistant", result.reply)
            logger.info(
                f"[AI-Enhanced] 会话 {session_id} | intent={result.intent} "
                f"| emotion={result.emotion}({result.emotion_intensity:.0%}) "
                f"| confidence={result.confidence:.0%}"
            )
            return ChatResponse(
                success=True, response=result.reply, language=result.language,
                intent=result.intent, emotion=result.emotion, confidence=result.confidence
            )
        except Exception as e:
            logger.warning(f"[AI-Enhanced] 增强响应失败，回退到传统模式: {e}")

    # === 传统回退模式（补充意图/情绪字段以保持兼容性）===
    try:
        from ai_intelligence import classify_intent, detect_emotion_enhanced
        fallback_intent = classify_intent(message, language)
        fallback_emotion, _ = detect_emotion_enhanced(message, language)
    except Exception:
        fallback_intent = "general"
        fallback_emotion = "neutral"

    ai_reply, lang_switch_to = _generate_ai_response_optimized(
        message, customer_info, optimized_history, language
    )

    if lang_switch_to:
        buyer_session_manager.update_session_language(session_id, lang_switch_to)
        _db_update_session(session_id, language=lang_switch_to)
        confirm = {"zh": "已切换到中文回复。", "en": "Switched to English.",
                   "ar": "تم التحويل إلى اللغة العربية.", "ru": "Переключено на русский язык."}
        ai_reply = confirm.get(lang_switch_to, ai_reply)
        _db_save_message(session_id, "assistant", ai_reply)
        buyer_session_manager.add_message(session_id, "assistant", ai_reply)
        return ChatResponse(
            success=True, response=ai_reply, language=lang_switch_to,
            intent=fallback_intent.intent, emotion=fallback_emotion, confidence=0.3
        )

    _db_save_message(session_id, "assistant", ai_reply)
    buyer_session_manager.add_message(session_id, "assistant", ai_reply)
    return ChatResponse(
        success=True, response=ai_reply, language=language,
        intent=fallback_intent.intent, emotion=fallback_emotion, confidence=0.3
    )


# ============== API：转回 AI ===============
@app.post("/api/v1/customer/transfer-to-ai")
async def transfer_to_ai(session_id: str = Query(...)):
    if not session_id:
        return {"success": False, "message": "缺少 session_id"}
    _db_update_session(session_id, is_ai=1, status="active")
    lang = buyer_session_manager.get_session(session_id).get("language", "zh") \
        if buyer_session_manager.get_session(session_id) else "zh"
    buyer_session_manager.update_session_language(session_id, lang)
    cid = ""
    session = buyer_session_manager.get_session(session_id)
    if session:
        cid = session.get("customer_info", {}).get("customer", {}).get("customer_id", "")
    try:
        requests.post(
            f"{SELLER_API_HOST}/api/v1/agent/buyer-switch-to-ai",
            json={"session_id": session_id, "customer_id": cid},
            headers={"X-Internal-Signature": "deprecated", "X-Internal-Timestamp": "0"},
            timeout=5)
    except Exception:
        pass
    return {"success": True, "ai_mode_since": datetime.now().isoformat()}


# ============== API：语言切换 ===============
@app.post("/api/v1/customer/change_language", response_model=ChangeLanguageResponse)
async def change_language(body: ChangeLangJSON):
    session_id = body.session_id
    language = body.language
    if not session_id or not language:
        return ChangeLanguageResponse(success=False, message="缺少参数")
    valid_langs = ["zh", "en", "ar", "ru", "th", "vi", "id", "ms", "tl"]
    if language not in valid_langs:
        return ChangeLanguageResponse(success=False, message=f"不支持的语言: {language}")
    buyer_session_manager.update_session_language(session_id, language)
    _db_update_session(session_id, language=language)
    confirm = {"zh": "已切换到中文回复。", "en": "Switched to English.",
               "ar": "تم التحويل إلى اللغة العربية.", "ru": "Переключено на русский язык.",
               "th": "สลับเป็นภาษาไทยแล้วค่ะ/ครับ", "vi": "Đã chuyển sang Tiếng Việt.",
               "id": "Sudah beralih ke Bahasa Indonesia.",
               "ms": "Telah bertukar ke Bahasa Melayu.", "tl": "Na-switch na sa Filipino."}
    msg = confirm.get(language, "语言已切换。")
    _db_save_message(session_id, "assistant", msg)
    buyer_session_manager.add_message(session_id, "assistant", msg)
    return ChangeLanguageResponse(success=True, language=language, message=msg)


# ============== API：获取消息 ===============
@app.get("/api/v1/customer/messages")
async def get_messages(session_id: str = Query(...)):
    if not _session_exists(session_id):
        return {"success": False, "message": "会话不存在"}
    rows = _buyer_query(
        "SELECT * FROM messages WHERE session_id = ? ORDER BY created_at ASC", (session_id,))
    if rows is None:
        return {"success": False, "data": {"messages": []}}
    messages = [
        {"id": str(row["id"]) if isinstance(row, dict) else str(row[0]),
         "role": row["role"] if isinstance(row, dict) else row[1],
         "content": row["content"] if isinstance(row, dict) else row[2],
         "created_at": row["created_at"] if isinstance(row, dict) else row[3]}
        for row in rows]
    return {"success": True, "data": {"messages": messages}}


# ============== API：获取会话状态 ===============
@app.get("/api/v1/customer/session")
async def get_session_info(session_id: str = Query(...)):
    row = _buyer_query("SELECT * FROM sessions WHERE session_id = ?", (session_id,), fetch_one=True)
    if not row:
        return {"success": False}
    return {"success": True, "data": _session_row_to_api_dict(row)}


# ============== API：客户资料（chat 页刷新用）==============
@app.post("/api/v1/customer/myinfo")
async def customer_myinfo(body: JsonSessionId):
    session_id = body.session_id
    if not session_id:
        return {"success": False, "message": "缺少 session_id"}
    mem = buyer_session_manager.get_session(session_id)
    if mem and mem.get("customer_info"):
        cinfo = mem["customer_info"]
        cust = cinfo.get("customer") or {}
        return {"success": True, "data": {"customer": cust, "customer_info": cinfo}}
    row = _buyer_query("SELECT customer_id FROM sessions WHERE session_id = ?", (session_id,), fetch_one=True)
    if not row:
        return {"success": False, "message": "会话不存在"}
    cid = row["customer_id"] if isinstance(row, dict) else row[0]
    if not cid:
        return {"success": False, "message": "会话不存在"}
    neo = _get_neo4j()
    profile = neo.get_full_profile(cid) if neo.driver else None
    if not profile:
        profile = {"customer": {"customer_id": cid, "id": cid}, "orders": [], "skus": [], "communications": []}
    with buyer_session_manager.lock:
        if session_id in buyer_session_manager.sessions:
            buyer_session_manager.sessions[session_id]["customer_info"] = profile
    return {"success": True, "data": {"customer": profile.get("customer", {}), "customer_info": profile}}


# ============== API：转人工 ===============
@app.post("/api/v1/customer/transfer-to-human")
async def transfer_to_human(session_id: str = Query(..., description="会话ID")):
    if not _session_exists(session_id):
        return {"success": False, "message": "会话不存在"}
    row = _buyer_query(
        "SELECT customer_id, language FROM sessions WHERE session_id = ?", (session_id,), fetch_one=True)
    customer_id = ""
    language = "zh"
    if row:
        customer_id = row.get("customer_id", row[0] if not isinstance(row, dict) else "") if isinstance(row, dict) else (row[0] or "")
        language = row.get("language", "zh") if isinstance(row, dict) else (row[1] or "zh")
    _db_update_session(session_id, is_ai=0, status="waiting")
    _notify_seller_transfer(session_id, customer_id, language)
    return {"success": True, "message": "已转接人工客服"}


# ============== API：翻译 ===============
@app.post("/api/v1/translate", response_model=TranslateResponse)
async def translate(req: TranslateRequest):
    text = (req.text or "").strip()
    target = req.target
    if not text or not target:
        return TranslateResponse(success=False, message="缺少参数")
    translated = _translate_text(text, target)
    return TranslateResponse(success=True, translated=translated, target=target)


# ============== API：发送消息（人工模式）==============
@app.post("/api/v1/customer/send")
async def customer_send(body: CustomerSendJSON):
    session_id = body.session_id
    content = body.content
    if not session_id or not content:
        return {"success": False, "message": "缺少参数"}
    if not _session_exists(session_id):
        return {"success": False, "message": "会话不存在"}
    _db_save_message(session_id, "user", content)
    buyer_session_manager.add_message(session_id, "user", content)
    cid = ""
    s = buyer_session_manager.get_session(session_id)
    if s:
        cid = s.get("customer_info", {}).get("customer", {}).get("customer_id", "")
    try:
        requests.post(
            f"{SELLER_API_HOST}/api/v1/internal/buyer-message",
            json={"session_id": session_id, "customer_id": cid, "content": content, "token": SELLER_INTERNAL_TOKEN},
            timeout=5)
    except Exception:
        pass
    return {"success": True}


# ============== API：会话登出 ===============
@app.post("/api/v1/customer/logout")
async def customer_logout(body: JsonSessionId = None):
    if body and body.session_id:
        buyer_session_manager.close_session(body.session_id)
    return {"success": True}
