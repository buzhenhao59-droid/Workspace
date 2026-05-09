# -*- coding: utf-8 -*-
"""
店铺管理系统 API - 业务逻辑层
提供店铺、商品、SKU、库存、定价规则、批量刊登等完整业务逻辑
MySQL 优先，SQLite 作为回退
"""
import os
import json
import math
import uuid
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any
from decimal import Decimal

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ============== MySQL 连接池 ==============
_mysql_pool = None
_use_mysql = False
_sqlite_conn = None
_sqlite_lock = __import__("threading").Lock()


def _get_mysql_config():
    return {
        "host": os.getenv("SHOP_MYSQL_HOST", os.getenv("MYSQL_HOST", "localhost")),
        "port": int(os.getenv("SHOP_MYSQL_PORT", os.getenv("MYSQL_PORT", "3306"))),
        "user": os.getenv("SHOP_MYSQL_USER", os.getenv("MYSQL_USER", "root")),
        "password": os.getenv("SHOP_MYSQL_PASSWORD", os.getenv("MYSQL_PASSWORD", "")),
        "database": os.getenv("SHOP_MYSQL_DATABASE", os.getenv("MYSQL_DATABASE", "shop_manager")),
        "charset": "utf8mb4",
    }


def _init_mysql_pool():
    global _mysql_pool, _use_mysql
    # 强制 SQLite 时绝不尝试连接 MySQL（避免无 MySQL 时每次启动报错、拖慢导入）
    force_sqlite = os.getenv("SHOP_USE_MYSQL", "false").lower() in ("false", "0", "no")
    if force_sqlite:
        _mysql_pool = None
        _use_mysql = False
        logger.info("[shop_api] SHOP_USE_MYSQL=false，使用 SQLite 存储店铺数据")
        return False
    try:
        import pymysql
        config = _get_mysql_config()
        _mysql_pool = pymysql.connect(
            host=config["host"], port=config["port"], user=config["user"],
            password=config["password"], database=config["database"],
            charset=config["charset"], autocommit=True
        )
        _use_mysql = True
        logger.info(f"[shop_api] MySQL 连接成功: {config['host']}:{config['port']}/{config['database']}")
        return True
    except Exception as e:
        logger.warning(f"[shop_api] MySQL 连接失败，使用 SQLite 回退: {e}")
        _mysql_pool = None
        _use_mysql = False
        return False


def _get_sqlite_path():
    # 与 build_demo_data / shop_db 一致：数据库在 backend/data/，勿用 parent.parent（会指到 卖方终端/data）
    default = os.path.join(os.path.dirname(__file__), "data", "shop_manager.db")
    raw = os.getenv("SHOP_SQLITE_PATH")
    path = (raw.strip() if raw else "") or default
    path = os.path.abspath(path)
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    return path


def _get_sqlite_conn():
    global _sqlite_conn
    if _sqlite_conn is None:
        with _sqlite_lock:
            if _sqlite_conn is None:
                import sqlite3
                _sqlite_conn = sqlite3.connect(_get_sqlite_path(), check_same_thread=False)
                _sqlite_conn.row_factory = sqlite3.Row
                _init_sqlite_schema()
    return _sqlite_conn


@property
def _conn(self):
    if _use_mysql and _mysql_pool:
        return _mysql_pool
    return _get_sqlite_conn()


class _DummyConn:
    """上下文管理器替代品"""
    def __enter__(self):
        return self.cursor
    def __exit__(self, *args):
        self.cursor.close()
    def commit(self):
        pass


def _exec(sql, params=None):
    """统一执行接口，返回 (cursor, results)"""
    params = params or ()
    if _use_mysql and _mysql_pool:
        cur = _mysql_pool.cursor()
        cur.execute(sql, params)
        return cur, cur.fetchall(), cur.lastrowid, cur.rowcount
    else:
        conn = _get_sqlite_conn()
        cur = conn.cursor()
        cur.execute(sql, params)
        rows = cur.fetchall()
        last_id = cur.lastrowid
        rowcount = cur.rowcount
        conn.commit()
        return cur, rows, last_id, rowcount


def _execmany(sql, params_list):
    if _use_mysql and _mysql_pool:
        cur = _mysql_pool.cursor()
        cur.executemany(sql, params_list)
        return cur.lastrowid
    else:
        conn = _get_sqlite_conn()
        cur = conn.cursor()
        cur.executemany(sql, params_list)
        conn.commit()
        return cur.lastrowid


def _row_to_dict(row):
    if row is None:
        return None
    if hasattr(row, "_asdict"):
        return row._asdict()
    if isinstance(row, dict):
        return row
    return dict(zip([d[0] for d in row.cursor_description], row)) if hasattr(row, "cursor_description") else dict(row)


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _gen_code(prefix=""):
    return f"{prefix}{datetime.now().strftime('%Y%m%d%H%M%S')}{str(uuid.uuid4())[:4].upper()}"


# ============== 平台名称映射 ==============
PLATFORM_NAMES = {
    "aliexpress": "速卖通",
    "amazon": "亚马逊",
    "shopee": "Shopee",
    "temu": "Temu",
    "tiktok": "TikTok Shop",
    "lazada": "Lazada",
    "ebay": "eBay",
    "shopify": "Shopify",
    "1688": "1688",
}


# ============== Pydantic 模型 ==============
class ShopCreate(BaseModel):
    shop_name: str
    platform: str
    shop_id: Optional[str] = None
    app_key: Optional[str] = None
    app_secret: Optional[str] = None
    access_token: Optional[str] = None
    country: Optional[str] = None
    currency: Optional[str] = "USD"
    is_default: bool = False
    status: Optional[str] = "active"


class ShopUpdate(BaseModel):
    shop_name: Optional[str] = None
    platform: Optional[str] = None
    shop_id: Optional[str] = None
    app_key: Optional[str] = None
    app_secret: Optional[str] = None
    access_token: Optional[str] = None
    country: Optional[str] = None
    currency: Optional[str] = None
    is_default: Optional[bool] = None
    status: Optional[str] = None


class ProductCreate(BaseModel):
    title: str
    title_en: Optional[str] = None
    description: Optional[str] = None
    source_platform: Optional[str] = None
    brand: Optional[str] = None
    material: Optional[str] = None
    weight: Optional[float] = None
    images: Optional[List[str]] = []
    status: Optional[str] = "draft"
    category_id: Optional[int] = None


class ProductUpdate(BaseModel):
    title: Optional[str] = None
    title_en: Optional[str] = None
    description: Optional[str] = None
    source_platform: Optional[str] = None
    brand: Optional[str] = None
    material: Optional[str] = None
    weight: Optional[float] = None
    images: Optional[List[str]] = None
    status: Optional[str] = None
    category_id: Optional[int] = None


class SKUCreate(BaseModel):
    product_id: int
    sku_code: Optional[str] = None
    sku_name: Optional[str] = None
    source_price: Optional[float] = 0
    attributes: Optional[Dict] = {}
    images: Optional[List[str]] = []
    weight: Optional[float] = None


class PricingRuleCreate(BaseModel):
    rule_name: str
    rule_type: str = "margin"
    platform: Optional[str] = None
    shop_id: Optional[int] = None
    margin_percent: Optional[float] = 30
    platform_fee_percent: Optional[float] = 10
    shipping_cost: Optional[float] = 0
    payment_fee_percent: Optional[float] = 2
    round_mode: Optional[str] = "ceil"
    priority: Optional[int] = 0
    is_active: bool = True


class PublishRequest(BaseModel):
    product_ids: List[int]
    shop_ids: List[int]
    price_type: str = "cost_plus"
    price_adjustment: float = 0
    stock_sync: bool = True


class CollectRequest(BaseModel):
    platform: str
    url: str
    auto_create_sku: bool = True


# ============== 表结构初始化 ==============
def _init_sqlite_schema():
    conn = _get_sqlite_conn()
    cur = conn.cursor()

    tables = {
        "shops": """
            CREATE TABLE IF NOT EXISTS shops (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                shop_name TEXT NOT NULL, platform TEXT NOT NULL,
                shop_id TEXT, app_key TEXT, app_secret TEXT, access_token TEXT,
                country TEXT, currency TEXT DEFAULT 'USD', status TEXT DEFAULT 'active',
                is_default INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """,
        "products": """
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL, title_en TEXT, description TEXT,
                source_platform TEXT, product_code TEXT UNIQUE,
                brand TEXT, material TEXT, weight REAL,
                images TEXT DEFAULT '[]',
                status TEXT DEFAULT 'draft',
                category_id INTEGER,
                sku_count INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """,
        "product_skus": """
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
        """,
        "inventory": """
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
        """,
        "pricing_rules": """
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
        """,
        "shop_products": """
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
        """,
        "collect_history": """
            CREATE TABLE IF NOT EXISTS collect_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                platform TEXT NOT NULL, source_url TEXT,
                title TEXT, status TEXT DEFAULT 'success',
                product_id INTEGER,
                error_message TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """,
        "categories": """
            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL, name_en TEXT,
                parent_id INTEGER, platform TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (parent_id) REFERENCES categories(id) ON DELETE SET NULL
            )
        """,
        "exchange_rates": """
            CREATE TABLE IF NOT EXISTS exchange_rates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_currency TEXT NOT NULL, to_currency TEXT NOT NULL,
                rate REAL NOT NULL, updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(from_currency, to_currency)
            )
        """,
    }

    for name, sql in tables.items():
        try:
            cur.execute(sql)
        except Exception as e:
            logger.warning(f"[shop_api] 表 {name} 初始化跳过: {e}")

    conn.commit()
    logger.info(f"[shop_api] SQLite schema 就绪: {_get_sqlite_path()}")


def _init_mysql_schema():
    cur, rows, _, _ = _exec("SHOW TABLES LIKE 'shops'")
    if not rows:
        schema_sqls = [
            """CREATE TABLE IF NOT EXISTS shops (
                id INT AUTO_INCREMENT PRIMARY KEY,
                shop_name VARCHAR(255) NOT NULL, platform VARCHAR(50) NOT NULL,
                shop_id VARCHAR(255), app_key TEXT, app_secret TEXT, access_token TEXT,
                country VARCHAR(100), currency VARCHAR(10) DEFAULT 'USD', status VARCHAR(20) DEFAULT 'active',
                is_default TINYINT(1) DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
            """CREATE TABLE IF NOT EXISTS products (
                id INT AUTO_INCREMENT PRIMARY KEY,
                title TEXT NOT NULL, title_en TEXT, description TEXT,
                source_platform VARCHAR(50), product_code VARCHAR(100) UNIQUE,
                brand VARCHAR(255), material VARCHAR(255), weight DECIMAL(10,3),
                images JSON, status VARCHAR(20) DEFAULT 'draft',
                category_id INT, sku_count INT DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
            """CREATE TABLE IF NOT EXISTS product_skus (
                id INT AUTO_INCREMENT PRIMARY KEY,
                product_id INT NOT NULL,
                sku_code VARCHAR(100) UNIQUE,
                sku_name TEXT,
                source_price DECIMAL(10,2) DEFAULT 0,
                attributes JSON NOT NULL,
                images JSON NOT NULL,
                weight DECIMAL(10,3),
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
            """CREATE TABLE IF NOT EXISTS inventory (
                id INT AUTO_INCREMENT PRIMARY KEY,
                sku_id INT NOT NULL,
                shop_id INT,
                available_stock INT DEFAULT 0,
                reserved_stock INT DEFAULT 0,
                low_stock_threshold INT DEFAULT 10,
                last_sync_at DATETIME,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                FOREIGN KEY (shop_id) REFERENCES shops(id) ON DELETE SET NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
            """CREATE TABLE IF NOT EXISTS pricing_rules (
                id INT AUTO_INCREMENT PRIMARY KEY,
                rule_name VARCHAR(255) NOT NULL, rule_type VARCHAR(20) NOT NULL,
                platform VARCHAR(50), shop_id INT,
                margin_percent DECIMAL(5,2) DEFAULT 30,
                platform_fee_percent DECIMAL(5,2) DEFAULT 10, shipping_cost DECIMAL(10,2) DEFAULT 0,
                payment_fee_percent DECIMAL(5,2) DEFAULT 2, round_mode VARCHAR(10) DEFAULT 'ceil',
                priority INT DEFAULT 0, is_active TINYINT(1) DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
            """CREATE TABLE IF NOT EXISTS shop_products (
                id INT AUTO_INCREMENT PRIMARY KEY,
                product_id INT NOT NULL, shop_id INT NOT NULL,
                sku_id INT,
                price DECIMAL(10,2), stock INT DEFAULT 0,
                publish_status VARCHAR(20) DEFAULT 'draft',
                published_at DATETIME,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE,
                FOREIGN KEY (shop_id) REFERENCES shops(id) ON DELETE CASCADE,
                FOREIGN KEY (sku_id) REFERENCES product_skus(id) ON DELETE SET NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
            """CREATE TABLE IF NOT EXISTS collect_history (
                id INT AUTO_INCREMENT PRIMARY KEY,
                platform VARCHAR(50) NOT NULL, source_url TEXT,
                title TEXT, status VARCHAR(20) DEFAULT 'success',
                product_id INT,
                error_message TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
            """CREATE TABLE IF NOT EXISTS categories (
                id INT AUTO_INCREMENT PRIMARY KEY,
                name TEXT NOT NULL, name_en TEXT,
                parent_id INT, platform VARCHAR(50),
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (parent_id) REFERENCES categories(id) ON DELETE SET NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
            """CREATE TABLE IF NOT EXISTS exchange_rates (
                id INT AUTO_INCREMENT PRIMARY KEY,
                from_currency VARCHAR(10) NOT NULL, to_currency VARCHAR(10) NOT NULL,
                rate DECIMAL(15,6) NOT NULL, updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                UNIQUE KEY unique_currency_pair (from_currency, to_currency)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
        ]
        for sql in schema_sqls:
            try:
                _exec(sql)
            except Exception as e:
                logger.warning(f"[shop_api] MySQL schema 跳过: {e}")
        logger.info("[shop_api] MySQL schema 初始化完成")


# 启动时初始化
_init_mysql_pool()
if not _use_mysql:
    _init_sqlite_schema()
else:
    _init_mysql_schema()


# ============== 价格计算 ==============
def calculate_price_by_rule(sku_id: int, shop_id: int = None, platform: str = None) -> Dict:
    """根据定价规则计算商品售价"""
    sku = get_sku_by_id(sku_id)
    if not sku:
        return {"error": "SKU 不存在"}

    cost = sku.get("source_price") or 0

    rule = None
    if shop_id:
        shop = get_shop_by_id(shop_id)
        if shop:
            platform = shop["platform"]
        rule = _get_active_rule(platform, shop_id)
    elif platform:
        rule = _get_active_rule(platform, None)

    if not rule:
        return {"price": round(cost * 1.3, 2), "cost": cost, "rule": None}

    price = _apply_pricing(cost, rule)
    return {"price": price, "cost": cost, "rule": rule}


def _get_active_rule(platform: str = None, shop_id: int = None) -> Optional[Dict]:
    p = "%s" if _use_mysql else "?"
    where = f" AND platform={p}" if platform else "1=1"
    cur, rows, _, _ = _exec(
        f"SELECT * FROM pricing_rules WHERE is_active=1 {where} ORDER BY priority DESC LIMIT 1",
        ((platform,) if platform else ())
    )
    row = rows[0] if rows else None
    return _row_to_dict(row) if row else None


def _apply_pricing(cost: float, rule: Dict) -> float:
    rule_type = rule.get("rule_type", "margin")
    margin = float(rule.get("margin_percent", 30)) / 100
    platform_fee = float(rule.get("platform_fee_percent", 10)) / 100
    shipping = float(rule.get("shipping_cost", 0))
    payment_fee = float(rule.get("payment_fee_percent", 2)) / 100
    round_mode = rule.get("round_mode", "ceil")

    if rule_type == "margin":
        base = cost * (1 + margin + platform_fee + payment_fee) + shipping
    elif rule_type == "fixed":
        base = cost + float(rule.get("margin_percent", 0)) + shipping
    elif rule_type == "target":
        target = float(rule.get("margin_percent", 30))
        base = target
    else:
        base = cost * (1 + margin + platform_fee + payment_fee) + shipping

    price = base
    if round_mode == "ceil":
        return math.ceil(price * 100) / 100
    elif round_mode == "floor":
        return math.floor(price * 100) / 100
    else:
        return round(price, 2)


# ============== 店铺 CRUD ==============
def create_shop(data: ShopCreate) -> int:
    if data.is_default:
        _exec("UPDATE shops SET is_default=0")
    images_json = json.dumps(data.images, ensure_ascii=False) if hasattr(data, "images") and data.images else "[]"
    if _use_mysql:
        sql = ("INSERT INTO shops (shop_name, platform, shop_id, app_key, app_secret, access_token, country, currency, status, is_default) "
               "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)")
    else:
        sql = ("INSERT INTO shops (shop_name, platform, shop_id, app_key, app_secret, access_token, country, currency, status, is_default) "
               "VALUES (?,?,?,?,?,?,?,?,?,?)")
    cur, _, lid, _ = _exec(
        sql,
        (data.shop_name, data.platform, data.shop_id, data.app_key, data.app_secret,
         data.access_token, data.country, data.currency, data.status or "active", int(data.is_default))
    )
    return lid


def get_shops(platform: str = None, status: str = None) -> List[Dict]:
    conds, params = [], []
    if platform:
        conds.append("platform=%s" if _use_mysql else "platform=?")
        params.append(platform)
    if status:
        conds.append("status=%s" if _use_mysql else "status=?")
        params.append(status)
    where = ("WHERE " + " AND ".join(conds)) if conds else ""
    cur, rows, _, _ = _exec(f"SELECT * FROM shops {where} ORDER BY is_default DESC, id DESC", params)
    return [_row_to_dict(r) for r in rows]


def get_shop_by_id(shop_id: int) -> Optional[Dict]:
    cur, rows, _, _ = _exec("SELECT * FROM shops WHERE id=%s" if _use_mysql else "SELECT * FROM shops WHERE id=?", (shop_id,))
    return _row_to_dict(rows[0]) if rows else None


def update_shop(shop_id: int, data: ShopUpdate) -> bool:
    updates, params = [], []
    for field in ["shop_name", "platform", "shop_id", "app_key", "app_secret", "access_token",
                  "country", "currency", "status"]:
        val = getattr(data, field, None)
        if val is not None:
            updates.append(f"{field}=%s" if _use_mysql else f"{field}=?")
            params.append(val)
    is_default = getattr(data, "is_default", None)
    if is_default is not None:
        if is_default:
            _exec("UPDATE shops SET is_default=0")
        updates.append("is_default=%s" if _use_mysql else "is_default=?")
        params.append(int(is_default))
    if not updates:
        return False
    updates.append("updated_at=%s" if _use_mysql else "updated_at=?")
    params.append(_now())
    params.append(shop_id)
    cur, _, _, rc = _exec(
        f"UPDATE shops SET {','.join(updates)} WHERE id=%s" if _use_mysql
        else f"UPDATE shops SET {','.join(updates)} WHERE id=?",
        params
    )
    return rc > 0


def delete_shop(shop_id: int) -> bool:
    cur, _, _, rc = _exec("DELETE FROM shops WHERE id=%s" if _use_mysql else "DELETE FROM shops WHERE id=?", (shop_id,))
    return rc > 0


def test_shop_connection(shop_id: int) -> Dict:
    shop = get_shop_by_id(shop_id)
    if not shop:
        return {"success": False, "message": "店铺不存在"}
    if not shop.get("app_key") and not shop.get("access_token"):
        return {"success": False, "message": f"{PLATFORM_NAMES.get(shop['platform'], shop['platform'])} 店铺未配置 App Key 或 Access Token"}
    return {"success": True, "message": f"{PLATFORM_NAMES.get(shop['platform'], shop['platform'])} 连接配置正常（请在平台后台验证实际连接）"}


# ============== 商品 CRUD ==============
def create_product(data: ProductCreate) -> int:
    product_code = _gen_code("PRD")
    images = json.dumps(data.images or [], ensure_ascii=False)
    if _use_mysql:
        sql = ("INSERT INTO products (title, title_en, description, source_platform, product_code, brand, material, weight, images, status, category_id) "
               "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)")
    else:
        sql = ("INSERT INTO products (title, title_en, description, source_platform, product_code, brand, material, weight, images, status, category_id) "
               "VALUES (?,?,?,?,?,?,?,?,?,?,?)")
    cur, _, lid, _ = _exec(
        sql,
        (data.title, data.title_en, data.description, data.source_platform, product_code,
         data.brand, data.material, data.weight, images, data.status or "draft", data.category_id)
    )
    return lid


def get_products(status: str = None, category_id: int = None, source_platform: str = None,
                 page: int = 1, page_size: int = 20) -> Dict:
    conds, params = [], []
    if status:
        conds.append("status=%s" if _use_mysql else "status=?")
        params.append(status)
    if category_id:
        conds.append("category_id=%s" if _use_mysql else "category_id=?")
        params.append(category_id)
    if source_platform:
        conds.append("source_platform=%s" if _use_mysql else "source_platform=?")
        params.append(source_platform)
    where = ("WHERE " + " AND ".join(conds)) if conds else ""
    cur, rows, _, _ = _exec(f"SELECT COUNT(*) FROM products {where}", params)
    total = rows[0][0] if rows else 0
    total_pages = (total + page_size - 1) // page_size if total else 1
    offset = (page - 1) * page_size
    cur, rows, _, _ = _exec(
        f"SELECT * FROM products {where} ORDER BY id DESC LIMIT %s OFFSET %s" if _use_mysql
        else f"SELECT * FROM products {where} ORDER BY id DESC LIMIT ? OFFSET ?",
        params + [page_size, offset]
    )
    items = [_row_to_dict(r) for r in rows]
    return {"items": items, "total": total, "page": page, "page_size": page_size, "total_pages": total_pages}


def get_product_by_id(product_id: int) -> Optional[Dict]:
    cur, rows, _, _ = _exec("SELECT * FROM products WHERE id=%s" if _use_mysql else "SELECT * FROM products WHERE id=?", (product_id,))
    product = _row_to_dict(rows[0]) if rows else None
    if product:
        cur, skus, _, _ = _exec(
            "SELECT * FROM product_skus WHERE product_id=%s ORDER BY id" if _use_mysql
            else "SELECT * FROM product_skus WHERE product_id=? ORDER BY id",
            (product_id,)
        )
        product["skus"] = [_row_to_dict(s) for s in skus]
    return product


def update_product(product_id: int, data: ProductUpdate) -> bool:
    updates, params = [], []
    for field in ["title", "title_en", "description", "source_platform", "brand",
                  "material", "weight", "status", "category_id"]:
        val = getattr(data, field, None)
        if val is not None:
            updates.append(f"{field}=%s" if _use_mysql else f"{field}=?")
            params.append(val)
    images = getattr(data, "images", None)
    if images is not None:
        updates.append("images=%s" if _use_mysql else "images=?")
        params.append(json.dumps(images, ensure_ascii=False))
    if not updates:
        return False
    updates.append("updated_at=%s" if _use_mysql else "updated_at=?")
    params.append(_now())
    params.append(product_id)
    cur, _, _, rc = _exec(
        f"UPDATE products SET {','.join(updates)} WHERE id=%s" if _use_mysql
        else f"UPDATE products SET {','.join(updates)} WHERE id=?",
        params
    )
    return rc > 0


def delete_product(product_id: int) -> bool:
    cur, _, _, rc = _exec("DELETE FROM products WHERE id=%s" if _use_mysql else "DELETE FROM products WHERE id=?", (product_id,))
    return rc > 0


# ============== SKU CRUD ==============
def create_sku(data: SKUCreate) -> int:
    sku_code = data.sku_code or _gen_code("SKU")
    attrs = json.dumps(data.attributes or {}, ensure_ascii=False)
    imgs = json.dumps(data.images or [], ensure_ascii=False)
    if _use_mysql:
        sql = ("INSERT INTO product_skus (product_id, sku_code, sku_name, source_price, attributes, images, weight) "
               "VALUES (%s,%s,%s,%s,%s,%s,%s)")
    else:
        sql = ("INSERT INTO product_skus (product_id, sku_code, sku_name, source_price, attributes, images, weight) "
               "VALUES (?,?,?,?,?,?,?)")
    cur, _, lid, _ = _exec(
        sql,
        (data.product_id, sku_code, data.sku_name, data.source_price or 0, attrs, imgs, data.weight)
    )
    # 更新商品 SKU 计数
    cur2, cnt_rows, _, _ = _exec(
        "SELECT COUNT(*) FROM product_skus WHERE product_id=%s" if _use_mysql
        else "SELECT COUNT(*) FROM product_skus WHERE product_id=?",
        (data.product_id,)
    )
    cnt = cnt_rows[0][0] if cnt_rows else 0
    _exec("UPDATE products SET sku_count=%s, updated_at=%s WHERE id=%s" if _use_mysql
          else "UPDATE products SET sku_count=?, updated_at=? WHERE id=?",
          (cnt, _now(), data.product_id))
    return lid


def get_sku_by_id(sku_id: int) -> Optional[Dict]:
    cur, rows, _, _ = _exec("SELECT * FROM product_skus WHERE id=%s" if _use_mysql else "SELECT * FROM product_skus WHERE id=?", (sku_id,))
    return _row_to_dict(rows[0]) if rows else None


def update_sku(sku_id: int, data: Dict) -> bool:
    updates, params = [], []
    for field in ["sku_name", "source_price", "weight"]:
        if field in data:
            updates.append(f"{field}=%s" if _use_mysql else f"{field}=?")
            params.append(data[field])
    if "attributes" in data:
        updates.append("attributes=%s" if _use_mysql else "attributes=?")
        params.append(json.dumps(data["attributes"], ensure_ascii=False))
    if "images" in data:
        updates.append("images=%s" if _use_mysql else "images=?")
        params.append(json.dumps(data["images"], ensure_ascii=False))
    if not updates:
        return False
    updates.append("updated_at=%s" if _use_mysql else "updated_at=?")
    params.append(_now())
    params.append(sku_id)
    cur, _, _, rc = _exec(
        f"UPDATE product_skus SET {','.join(updates)} WHERE id=%s" if _use_mysql
        else f"UPDATE product_skus SET {','.join(updates)} WHERE id=?",
        params
    )
    return rc > 0


def delete_sku(sku_id: int) -> bool:
    cur, _, _, rc = _exec("DELETE FROM product_skus WHERE id=%s" if _use_mysql else "DELETE FROM product_skus WHERE id=?", (sku_id,))
    return rc > 0


# ============== 商品采集 ==============
def collect_product_from_source(data: CollectRequest) -> Dict:
    """采集商品（演示模式）"""
    try:
        if data.platform == "1688":
            title = f"【1688采集】{data.url.split('/')[-1] if '/' in data.url else '商品'}"
        elif data.platform == "amazon":
            title = f"【Amazon采集】{data.url}"
        elif data.platform == "aliexpress":
            title = f"【AliExpress采集】{data.url}"
        elif data.platform == "shopee":
            title = f"【Shopee采集】{data.url}"
        elif data.platform == "temu":
            title = f"【Temu采集】{data.url}"
        else:
            title = f"【{data.platform}采集】{data.url}"

        product_id = create_product(ProductCreate(title=title, source_platform=data.platform, status="draft"))

        if data.auto_create_sku:
            create_sku(SKUCreate(product_id=product_id, sku_name="默认SKU", source_price=0))

        _exec(
            "INSERT INTO collect_history (platform, source_url, title, status, product_id) VALUES (%s,%s,%s,%s,%s)"
            if _use_mysql
            else "INSERT INTO collect_history (platform, source_url, title, status, product_id) VALUES (?,?,?,?,?)",
            (data.platform, data.url, title, "success", product_id)
        )

        return {"success": True, "product_id": product_id, "message": f"{PLATFORM_NAMES.get(data.platform, data.platform)} 商品采集成功"}
    except Exception as e:
        _exec(
            "INSERT INTO collect_history (platform, source_url, title, status, error_message) VALUES (%s,%s,%s,%s,%s)"
            if _use_mysql
            else "INSERT INTO collect_history (platform, source_url, title, status, error_message) VALUES (?,?,?,?,?)",
            (data.platform, data.url, "", "failed", str(e))
        )
        return {"success": False, "message": f"采集失败: {str(e)}"}


# ============== 批量刊登 ==============
def publish_products(data: PublishRequest) -> Dict:
    """批量刊登商品到店铺"""
    published = []
    for product_id in data.product_ids:
        product = get_product_by_id(product_id)
        if not product:
            continue

        skus = product.get("skus", [])
        targets = skus if skus else [None]

        for shop_id in data.shop_ids:
            shop = get_shop_by_id(shop_id)
            if not shop:
                continue
            rule = _get_active_rule(shop["platform"], shop_id)

            for sku in targets:
                cost = sku.get("source_price", 0) if sku else 0
                price = _apply_pricing(cost, rule) if rule else round(cost * 1.3, 2)
                price = round(price * (1 + data.price_adjustment / 100), 2)

                stock = 0
                if data.stock_sync and sku:
                    cur, inv_rows, _, _ = _exec(
                        "SELECT available_stock FROM inventory WHERE sku_id=%s LIMIT 1" if _use_mysql
                        else "SELECT available_stock FROM inventory WHERE sku_id=? LIMIT 1",
                        (sku["id"],)
                    )
                    if inv_rows:
                        stock = inv_rows[0][0] if _use_mysql else inv_rows[0]["available_stock"]

                sku_id = sku["id"] if sku else None
                if _use_mysql:
                    sql = ("INSERT INTO shop_products (product_id, shop_id, sku_id, price, stock, publish_status, published_at) "
                           "VALUES (%s,%s,%s,%s,%s,%s,%s)")
                else:
                    sql = ("INSERT INTO shop_products (product_id, shop_id, sku_id, price, stock, publish_status, published_at) "
                           "VALUES (?,?,?,?,?,?,?)")
                cur, _, lid, _ = _exec(
                    sql,
                    (product_id, shop_id, sku_id, price, stock, "published", _now())
                )
                published.append(lid)

        update_product(product_id, ProductUpdate(status="published"))

    return {
        "success": True,
        "published_count": len(published),
        "published_ids": published,
        "message": f"成功刊登 {len(published)} 个商品"
    }


def get_shop_products(shop_id: int = None, product_id: int = None,
                      publish_status: str = None, page: int = 1, page_size: int = 20) -> Dict:
    conds, params = [], []
    if shop_id:
        conds.append("sp.shop_id=%s" if _use_mysql else "sp.shop_id=?")
        params.append(shop_id)
    if product_id:
        conds.append("sp.product_id=%s" if _use_mysql else "sp.product_id=?")
        params.append(product_id)
    if publish_status:
        conds.append("sp.publish_status=%s" if _use_mysql else "sp.publish_status=?")
        params.append(publish_status)
    where = ("WHERE " + " AND ".join(conds)) if conds else ""

    cur, cnt_rows, _, _ = _exec(f"SELECT COUNT(*) FROM shop_products sp {where}", params)
    total = cnt_rows[0][0] if cnt_rows else 0
    total_pages = (total + page_size - 1) // page_size if total else 1
    offset = (page - 1) * page_size

    cur, rows, _, _ = _exec(
        f"""SELECT sp.*, p.title as product_title, p.images as product_images,
                   sh.shop_name, sh.platform, s.sku_code, s.sku_name
            FROM shop_products sp
            LEFT JOIN products p ON sp.product_id = p.id
            LEFT JOIN shops sh ON sp.shop_id = sh.id
            LEFT JOIN product_skus s ON sp.sku_id = s.id
            {where}
            ORDER BY sp.id DESC
            LIMIT %s OFFSET %s""" if _use_mysql else
        f"""SELECT sp.*, p.title as product_title, p.images as product_images,
                   sh.shop_name, sh.platform, s.sku_code, s.sku_name
            FROM shop_products sp
            LEFT JOIN products p ON sp.product_id = p.id
            LEFT JOIN shops sh ON sp.shop_id = sh.id
            LEFT JOIN product_skus s ON sp.sku_id = s.id
            {where}
            ORDER BY sp.id DESC
            LIMIT ? OFFSET ?""",
        params + [page_size, offset]
    )
    items = [_row_to_dict(r) for r in rows]
    return {"items": items, "total": total, "page": page, "page_size": page_size, "total_pages": total_pages}


# ============== 库存 ==============
def get_inventory(sku_id: int = None, shop_id: int = None) -> List[Dict]:
    conds, params = [], []
    if sku_id:
        conds.append("i.sku_id=%s" if _use_mysql else "i.sku_id=?")
        params.append(sku_id)
    if shop_id:
        conds.append("i.shop_id=%s" if _use_mysql else "i.shop_id=?")
        params.append(shop_id)
    where = ("WHERE " + " AND ".join(conds)) if conds else ""
    cur, rows, _, _ = _exec(
        f"""SELECT i.*, s.sku_code, s.sku_name, s.source_price,
                   p.title as product_title, sh.shop_name, sh.platform
            FROM inventory i
            LEFT JOIN product_skus s ON i.sku_id = s.id
            LEFT JOIN products p ON s.product_id = p.id
            LEFT JOIN shops sh ON i.shop_id = sh.id
            {where}
            ORDER BY i.id DESC""" if _use_mysql else
        f"""SELECT i.*, s.sku_code, s.sku_name, s.source_price,
                   p.title as product_title, sh.shop_name, sh.platform
            FROM inventory i
            LEFT JOIN product_skus s ON i.sku_id = s.id
            LEFT JOIN products p ON s.product_id = p.id
            LEFT JOIN shops sh ON i.shop_id = sh.id
            {where}
            ORDER BY i.id DESC""",
        params
    )
    return [_row_to_dict(r) for r in rows]


def update_inventory(sku_id: int, shop_id: int = None, available_stock: int = None,
                    reserved_stock: int = None, total_stock: int = None) -> Dict:
    try:
        p = "%s" if _use_mysql else "?"
        where_clause = f"sku_id={p}" + (f" AND shop_id={p}" if shop_id else " AND shop_id IS NULL")
        cur, existing, _, _ = _exec(
            f"SELECT * FROM inventory WHERE {where_clause}",
            ((sku_id, shop_id) if shop_id else (sku_id,))
        )
        if not existing:
            cur, _, lid, _ = _exec(
                "INSERT INTO inventory (sku_id, shop_id, available_stock, reserved_stock, updated_at) VALUES (%s,%s,%s,%s,%s)" if _use_mysql
                else "INSERT INTO inventory (sku_id, shop_id, available_stock, reserved_stock, updated_at) VALUES (?,?,?,?,?)",
                (sku_id, shop_id, available_stock or 0, reserved_stock or 0, _now())
            )
            return {"success": True, "id": lid, "message": "库存记录创建成功"}

        updates, params = [], []
        if available_stock is not None:
            updates.append("available_stock=%s" if _use_mysql else "available_stock=?")
            params.append(available_stock)
        if reserved_stock is not None:
            updates.append("reserved_stock=%s" if _use_mysql else "reserved_stock=?")
            params.append(reserved_stock)
        if updates:
            updates.append("updated_at=%s" if _use_mysql else "updated_at=?")
            params.append(_now())
            p2 = "%s" if _use_mysql else "?"
            where_clause = f"sku_id={p2}" + (f" AND shop_id={p2}" if shop_id else " AND shop_id IS NULL")
            cur, _, _, rc = _exec(
                f"UPDATE inventory SET {','.join(updates)} WHERE {where_clause}",
                params + [(sku_id, shop_id) if shop_id else (sku_id,)]
            )
        return {"success": True, "message": "库存更新成功"}
    except Exception as e:
        return {"success": False, "message": str(e)}


def sync_inventory(shop_id: int = None) -> Dict:
    """同步库存（演示模式）"""
    inventory = get_inventory(shop_id=shop_id)
    return {
        "success": True,
        "synced_count": len(inventory),
        "message": f"库存同步完成，共 {len(inventory)} 条记录（演示模式）"
    }


# ============== 定价规则 ==============
def create_pricing_rule(data: PricingRuleCreate) -> int:
    if _use_mysql:
        sql = ("INSERT INTO pricing_rules (rule_name, rule_type, platform, shop_id, margin_percent, "
               "platform_fee_percent, shipping_cost, payment_fee_percent, round_mode, priority, is_active) "
               "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)")
    else:
        sql = ("INSERT INTO pricing_rules (rule_name, rule_type, platform, shop_id, margin_percent, "
               "platform_fee_percent, shipping_cost, payment_fee_percent, round_mode, priority, is_active) "
               "VALUES (?,?,?,?,?,?,?,?,?,?,?)")
    cur, _, lid, _ = _exec(
        sql,
        (data.rule_name, data.rule_type, data.platform, data.shop_id,
         data.margin_percent or 30, data.platform_fee_percent or 10,
         data.shipping_cost or 0, data.payment_fee_percent or 2,
         data.round_mode or "ceil", data.priority or 0, int(data.is_active))
    )
    return lid


def get_pricing_rules(platform: str = None, shop_id: int = None,
                      rule_type: str = None, is_active: bool = None) -> List[Dict]:
    conds, params = [], []
    if platform:
        conds.append("platform=%s" if _use_mysql else "platform=?")
        params.append(platform)
    if shop_id:
        conds.append("shop_id=%s" if _use_mysql else "shop_id=?")
        params.append(shop_id)
    if rule_type:
        conds.append("rule_type=%s" if _use_mysql else "rule_type=?")
        params.append(rule_type)
    if is_active is not None:
        conds.append("is_active=%s" if _use_mysql else "is_active=?")
        params.append(int(is_active))
    where = ("WHERE " + " AND ".join(conds)) if conds else ""
    cur, rows, _, _ = _exec(
        f"SELECT * FROM pricing_rules {where} ORDER BY priority DESC, id DESC",
        params
    )
    return [_row_to_dict(r) for r in rows]


def delete_pricing_rule(rule_id: int) -> bool:
    cur, _, _, rc = _exec("DELETE FROM pricing_rules WHERE id=%s" if _use_mysql else "DELETE FROM pricing_rules WHERE id=?", (rule_id,))
    return rc > 0


# ============== 分类 ==============
def get_categories(parent_id: int = None, platform: str = None) -> List[Dict]:
    conds, params = [], []
    if parent_id is not None:
        conds.append("parent_id=%s" if _use_mysql else "parent_id=?")
        params.append(parent_id)
    if platform:
        conds.append("platform=%s" if _use_mysql else "platform=?")
        params.append(platform)
    where = ("WHERE " + " AND ".join(conds)) if conds else ""
    cur, rows, _, _ = _exec(f"SELECT * FROM categories {where} ORDER BY id", params)
    return [_row_to_dict(r) for r in rows]


def create_category(name: str, name_en: str = None, parent_id: int = None, platform: str = None) -> int:
    if _use_mysql:
        sql = "INSERT INTO categories (name, name_en, parent_id, platform) VALUES (%s,%s,%s,%s)"
    else:
        sql = "INSERT INTO categories (name, name_en, parent_id, platform) VALUES (?,?,?,?)"
    cur, _, lid, _ = _exec(
        sql,
        (name, name_en, parent_id, platform)
    )
    return lid


# ============== 仪表盘统计 ==============
def get_dashboard_stats() -> Dict:
    cur, r1, _, _ = _exec("SELECT COUNT(*) FROM shops WHERE status='active'")
    total_shops = r1[0][0] if r1 else 0

    cur, r2, _, _ = _exec("SELECT COUNT(*) FROM products")
    total_products = r2[0][0] if r2 else 0

    cur, r3, _, _ = _exec("SELECT COUNT(*) FROM shop_products WHERE publish_status='published'")
    total_published = r3[0][0] if r3 else 0

    cur, r4, _, _ = _exec("SELECT COUNT(*) FROM inventory WHERE available_stock <= low_stock_threshold")
    low_stock = r4[0][0] if r4 else 0

    cur, rows, _, _ = _exec(
        "SELECT platform, COUNT(*) as count FROM shops WHERE status='active' AND platform IS NOT NULL GROUP BY platform"
        if _use_mysql else
        "SELECT platform, COUNT(*) as count FROM shops WHERE status='active' AND platform IS NOT NULL GROUP BY platform"
    )
    shops_by_platform = [_row_to_dict(r) for r in rows]

    return {
        "total_shops": total_shops,
        "total_products": total_products,
        "total_published": total_published,
        "low_stock_count": low_stock,
        "shops_by_platform": shops_by_platform,
    }
