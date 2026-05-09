# -*- coding: utf-8 -*-
"""
店铺管理系统数据库 - MySQL / SQLite 统一层
使用 MySQL（配置后即用），SQLite 作为回退
"""
import os
import json
import uuid
import logging
import threading
from datetime import datetime
from typing import Optional, List, Dict, Any
from contextlib import contextmanager

logger = logging.getLogger(__name__)

# ============== MySQL 连接池 ==============
_mysql_pool = None
_use_mysql = False

def _get_mysql_config():
    """从环境变量获取 MySQL 配置"""
    return {
        "host": os.getenv("SHOP_MYSQL_HOST", os.getenv("MYSQL_HOST", "localhost")),
        "port": int(os.getenv("SHOP_MYSQL_PORT", os.getenv("MYSQL_PORT", "3306"))),
        "user": os.getenv("SHOP_MYSQL_USER", os.getenv("MYSQL_USER", "root")),
        "password": os.getenv("SHOP_MYSQL_PASSWORD", os.getenv("MYSQL_PASSWORD", "")),
        "database": os.getenv("SHOP_MYSQL_DATABASE", os.getenv("MYSQL_DATABASE", "shop_manager")),
        "charset": "utf8mb4",
        "autocommit": True,
    }

def _init_mysql_pool():
    """初始化 MySQL 连接池"""
    global _mysql_pool, _use_mysql
    force_sqlite = os.getenv("SHOP_USE_MYSQL", "false").lower() in ("false", "0", "no")
    if force_sqlite:
        _mysql_pool = None
        _use_mysql = False
        logger.info("[ShopDB] SHOP_USE_MYSQL=false，使用 SQLite")
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
        logger.info(f"[ShopDB] MySQL 连接成功: {config['host']}:{config['port']}/{config['database']}")
        return True
    except Exception as e:
        logger.warning(f"[ShopDB] MySQL 连接失败，使用 SQLite 回退: {e}")
        _mysql_pool = None
        _use_mysql = False
        return False

# ============== SQLite 回退 ==============
_sqlite_conn = None
_sqlite_lock = threading.Lock()

def _get_sqlite_path():
    default = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "shop_manager.db")
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
                _init_sqlite_tables()
    return _sqlite_conn

# ============== 连接管理器 ==============
@contextmanager
def get_db():
    """统一数据库连接上下文管理器"""
    if _use_mysql and _mysql_pool:
        try:
            yield _mysql_pool.cursor()
        except Exception:
            yield None
    else:
        conn = _get_sqlite_conn()
        cursor = conn.cursor()
        try:
            yield cursor
        finally:
            cursor.close()

# ============== 表初始化 ==============
def _init_sqlite_tables():
    """初始化 SQLite 表结构"""
    conn = _get_sqlite_conn()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS shops (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shop_name TEXT NOT NULL, platform TEXT NOT NULL,
            shop_id TEXT, app_key TEXT, app_secret TEXT, access_token TEXT,
            country TEXT, currency TEXT DEFAULT 'USD', status TEXT DEFAULT 'active',
            is_default INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL, title_en TEXT, description TEXT,
            source_platform TEXT, product_code TEXT UNIQUE,
            brand TEXT, material TEXT, weight REAL,
            images TEXT DEFAULT '[]',
            status TEXT DEFAULT 'draft',
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS product_skus (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            sku_code TEXT UNIQUE,
            sku_name TEXT,
            source_price REAL DEFAULT 0,
            attributes TEXT DEFAULT '{}',
            images TEXT DEFAULT '[]',
            weight REAL,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS inventory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sku_id INTEGER NOT NULL,
            shop_id INTEGER,
            available_stock INTEGER DEFAULT 0,
            reserved_stock INTEGER DEFAULT 0,
            low_stock_threshold INTEGER DEFAULT 10,
            last_sync_at TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (sku_id) REFERENCES product_skus(id) ON DELETE CASCADE,
            FOREIGN KEY (shop_id) REFERENCES shops(id) ON DELETE SET NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS pricing_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rule_name TEXT NOT NULL, rule_type TEXT NOT NULL,
            platform TEXT, margin_percent REAL DEFAULT 30,
            platform_fee_percent REAL DEFAULT 10, shipping_cost REAL DEFAULT 0,
            payment_fee_percent REAL DEFAULT 2, round_mode TEXT DEFAULT 'ceil',
            priority INTEGER DEFAULT 0, is_active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS shop_products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL, shop_id INTEGER NOT NULL,
            sku_id INTEGER,
            price REAL, stock INTEGER DEFAULT 0,
            publish_status TEXT DEFAULT 'draft',
            published_at TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE,
            FOREIGN KEY (shop_id) REFERENCES shops(id) ON DELETE CASCADE,
            FOREIGN KEY (sku_id) REFERENCES product_skus(id) ON DELETE SET NULL,
            UNIQUE(product_id, shop_id, sku_id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS collect_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            platform TEXT NOT NULL, source_url TEXT,
            title TEXT, status TEXT DEFAULT 'success',
            product_id INTEGER,
            error_message TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS exchange_rates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_currency TEXT NOT NULL, to_currency TEXT NOT NULL,
            rate REAL NOT NULL, updated_at TEXT DEFAULT (datetime('now')),
            UNIQUE(from_currency, to_currency)
        )
    """)

    # 迁移：确保新字段存在
    for sql, col in [
        ("ALTER TABLE products ADD COLUMN sku_count INTEGER DEFAULT 0", "sku_count"),
        ("ALTER TABLE products ADD COLUMN category_id INTEGER", "category_id"),
        ("ALTER TABLE inventory ADD COLUMN low_stock_threshold INTEGER DEFAULT 10", "low_stock_threshold"),
        ("ALTER TABLE inventory ADD COLUMN last_sync_at TEXT", "last_sync_at"),
        ("ALTER TABLE shop_products ADD COLUMN published_at TEXT", "published_at"),
    ]:
        try:
            cur.execute(sql)
            conn.commit()
        except Exception:
            pass

    conn.commit()
    logger.info(f"[ShopDB] SQLite 表初始化完成: {_get_sqlite_path()}")


def init_database():
    """对外暴露的数据库初始化函数（API 调用）"""
    if _use_mysql:
        _init_mysql_schema()
        return {"success": True, "message": "MySQL 数据库表已就绪"}
    else:
        _init_sqlite_tables()
        return {"success": True, "message": "SQLite 数据库初始化完成"}


def _init_mysql_schema():
    """初始化 MySQL 表结构"""
    with get_db() as cur:
        if cur is None:
            return

        cur.execute("""
            CREATE TABLE IF NOT EXISTS shops (
                id INT AUTO_INCREMENT PRIMARY KEY,
                shop_name VARCHAR(255) NOT NULL, platform VARCHAR(50) NOT NULL,
                shop_id VARCHAR(255), app_key TEXT, app_secret TEXT, access_token TEXT,
                country VARCHAR(100), currency VARCHAR(10) DEFAULT 'USD', status VARCHAR(20) DEFAULT 'active',
                is_default TINYINT(1) DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id INT AUTO_INCREMENT PRIMARY KEY,
                title TEXT NOT NULL, title_en TEXT, description TEXT,
                source_platform VARCHAR(50), product_code VARCHAR(100) UNIQUE,
                brand VARCHAR(255), material VARCHAR(255), weight DECIMAL(10,3),
                images JSON, status VARCHAR(20) DEFAULT 'draft', sku_count INT DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS product_skus (
                id INT AUTO_INCREMENT PRIMARY KEY,
                product_id INT NOT NULL,
                sku_code VARCHAR(100) UNIQUE,
                sku_name TEXT,
                source_price DECIMAL(10,2) DEFAULT 0,
                attributes JSON DEFAULT '{}',
                images JSON DEFAULT '[]',
                weight DECIMAL(10,3),
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS inventory (
                id INT AUTO_INCREMENT PRIMARY KEY,
                sku_id INT NOT NULL,
                shop_id INT,
                available_stock INT DEFAULT 0,
                reserved_stock INT DEFAULT 0,
                low_stock_threshold INT DEFAULT 10,
                last_sync_at DATETIME,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                FOREIGN KEY (sku_id) REFERENCES product_skus(id) ON DELETE CASCADE,
                FOREIGN KEY (shop_id) REFERENCES shops(id) ON DELETE SET NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS pricing_rules (
                id INT AUTO_INCREMENT PRIMARY KEY,
                rule_name VARCHAR(255) NOT NULL, rule_type VARCHAR(20) NOT NULL,
                platform VARCHAR(50), shop_id INT,
                margin_percent DECIMAL(5,2) DEFAULT 30,
                platform_fee_percent DECIMAL(5,2) DEFAULT 10, shipping_cost DECIMAL(10,2) DEFAULT 0,
                payment_fee_percent DECIMAL(5,2) DEFAULT 2, round_mode VARCHAR(10) DEFAULT 'ceil',
                priority INT DEFAULT 0, is_active TINYINT(1) DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS shop_products (
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
                FOREIGN KEY (sku_id) REFERENCES product_skus(id) ON DELETE SET NULL,
                UNIQUE KEY unique_shop_product (product_id, shop_id, sku_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS collect_history (
                id INT AUTO_INCREMENT PRIMARY KEY,
                platform VARCHAR(50) NOT NULL, source_url TEXT,
                title TEXT, status VARCHAR(20) DEFAULT 'success',
                product_id INT,
                error_message TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS exchange_rates (
                id INT AUTO_INCREMENT PRIMARY KEY,
                from_currency VARCHAR(10) NOT NULL, to_currency VARCHAR(10) NOT NULL,
                rate DECIMAL(15,6) NOT NULL, updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                UNIQUE KEY unique_currency_pair (from_currency, to_currency)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        logger.info("[ShopDB] MySQL schema 初始化完成")


# 启动时初始化
_init_mysql_pool()
if not _use_mysql:
    _init_sqlite_tables()


# ============== 辅助函数 ==============
def _gen_code(prefix=""):
    return f"{prefix}{datetime.now().strftime('%Y%m%d%H%M%S')}{str(uuid.uuid4())[:4].upper()}"


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _dict(row):
    if row is None:
        return None
    if hasattr(row, "_asdict"):
        return row._asdict()
    if hasattr(row, "keys"):
        return dict(row)
    return {k: getattr(row, k, None) for k in dir(row) if not k.startswith("_")}


# ============== 店铺 CRUD ==============
def create_shop(data: Dict) -> int:
    """创建店铺"""
    with get_db() as cur:
        if cur is None:
            return -1
        if data.get("is_default"):
            cur.execute("UPDATE shops SET is_default=0")
        cur.execute("""
            INSERT INTO shops (shop_name, platform, shop_id, app_key, app_secret, access_token,
                               country, currency, status, is_default, updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""" if _use_mysql else """
            INSERT INTO shops (shop_name, platform, shop_id, app_key, app_secret, access_token,
                               country, currency, status, is_default, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (data["shop_name"], data["platform"], data.get("shop_id"),
             data.get("app_key"), data.get("app_secret"), data.get("access_token"),
             data.get("country"), data.get("currency", "USD"),
             data.get("status", "active"), int(bool(data.get("is_default"))), _now()))
        return cur.lastrowid


def get_shops(platform: str = None, status: str = None) -> List[Dict]:
    """获取店铺列表"""
    with get_db() as cur:
        if cur is None:
            return []
        cond, params = [], []
        if platform:
            cond.append("platform=%s" if _use_mysql else "platform=?")
            params.append(platform)
        if status:
            cond.append("status=%s" if _use_mysql else "status=?")
            params.append(status)
        where = ("WHERE " + " AND ".join(cond)) if cond else ""
        cur.execute(f"SELECT * FROM shops {where} ORDER BY is_default DESC, id DESC", params)
        return [_dict(r) for r in cur.fetchall()]


def get_shop(shop_id: int) -> Optional[Dict]:
    """获取单个店铺"""
    with get_db() as cur:
        if cur is None:
            return None
        cur.execute("SELECT * FROM shops WHERE id=%s" if _use_mysql else "SELECT * FROM shops WHERE id=?", (shop_id,))
        return _dict(cur.fetchone())


def update_shop(shop_id: int, data: Dict) -> bool:
    """更新店铺"""
    with get_db() as cur:
        if cur is None:
            return False
        if data.get("is_default"):
            cur.execute("UPDATE shops SET is_default=0" if _use_mysql else "UPDATE shops SET is_default=0")
        fields = ", ".join([f"{k}=%s" if _use_mysql else f"{k}=?" for k in data.keys()])
        fields += ", updated_at=%s" if _use_mysql else ", updated_at=?"
        params = list(data.values()) + [_now(), shop_id]
        cur.execute(f"UPDATE shops SET {fields} WHERE id=%s" if _use_mysql else f"UPDATE shops SET {fields} WHERE id=?", params)
        return cur.rowcount > 0


def delete_shop(shop_id: int) -> bool:
    """删除店铺"""
    with get_db() as cur:
        if cur is None:
            return False
        cur.execute("DELETE FROM shops WHERE id=%s" if _use_mysql else "DELETE FROM shops WHERE id=?", (shop_id,))
        return cur.rowcount > 0


def test_shop_connection(shop_id: int) -> Dict:
    """测试店铺 API 连接"""
    shop = get_shop(shop_id)
    if not shop:
        return {"success": False, "message": "店铺不存在"}
    platform = shop["platform"]
    if not shop.get("app_key") and not shop.get("access_token"):
        return {"success": False, "message": f"{platform} 店铺未配置 App Key 或 Access Token"}
    return {"success": True, "message": f"{platform} 连接配置正常（请在平台后台验证实际连接）"}


# ============== 商品 CRUD ==============
def create_product(data: Dict) -> int:
    """创建商品"""
    product_code = data.get("product_code") or _gen_code("PRD")
    images = json.dumps(data.get("images") or [], ensure_ascii=False) if isinstance(data.get("images"), list) else (data.get("images") or "[]")
    with get_db() as cur:
        if cur is None:
            return -1
        cur.execute("""
            INSERT INTO products (title, title_en, description, source_platform, product_code,
                                  brand, material, weight, images, status)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""" if _use_mysql else """
            INSERT INTO products (title, title_en, description, source_platform, product_code,
                                  brand, material, weight, images, status)
            VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (data["title"], data.get("title_en"), data.get("description"),
             data.get("source_platform"), product_code,
             data.get("brand"), data.get("material"), data.get("weight"),
             images, data.get("status", "draft")))
        return cur.lastrowid


def get_products(page: int = 1, page_size: int = 20, status: str = None,
                 source_platform: str = None, keyword: str = None) -> Dict:
    """分页获取商品列表"""
    with get_db() as cur:
        if cur is None:
            return {"items": [], "total": 0, "page": page, "page_size": page_size, "total_pages": 0}
        cond, params = [], []
        if status:
            cond.append("status=%s" if _use_mysql else "status=?")
            params.append(status)
        if source_platform:
            cond.append("source_platform=%s" if _use_mysql else "source_platform=?")
            params.append(source_platform)
        if keyword:
            cond.append("(title LIKE %s OR product_code LIKE %s)" if _use_mysql else "(title LIKE ? OR product_code LIKE ?)")
            params.extend([f"%{keyword}%", f"%{keyword}%"])
        where = ("WHERE " + " AND ".join(cond)) if cond else ""
        cur.execute(f"SELECT COUNT(*) FROM products {where}", params)
        total = cur.fetchone()[0] if _use_mysql else cur.fetchone()[0]
        total_pages = (total + page_size - 1) // page_size if total else 1
        offset = (page - 1) * page_size
        cur.execute(f"SELECT * FROM products {where} ORDER BY id DESC LIMIT %s OFFSET %s" if _use_mysql
                     else f"SELECT * FROM products {where} ORDER BY id DESC LIMIT ? OFFSET ?",
                     params + [page_size, offset])
        items = [_dict(r) for r in cur.fetchall()]
        return {"items": items, "total": total, "page": page, "page_size": page_size, "total_pages": total_pages}


def get_product(product_id: int) -> Optional[Dict]:
    """获取单个商品"""
    with get_db() as cur:
        if cur is None:
            return None
        cur.execute("SELECT * FROM products WHERE id=%s" if _use_mysql else "SELECT * FROM products WHERE id=?", (product_id,))
        return _dict(cur.fetchone())


def get_product_with_skus(product_id: int) -> Optional[Dict]:
    """获取商品及其所有 SKU"""
    product = get_product(product_id)
    if not product:
        return None
    product["skus"] = get_skus_by_product(product_id)
    return product


def update_product(product_id: int, data: Dict) -> bool:
    """更新商品"""
    images = data.get("images")
    if images is not None and isinstance(images, list):
        data["images"] = json.dumps(images, ensure_ascii=False)
    with get_db() as cur:
        if cur is None:
            return False
        fields = ", ".join([f"{k}=%s" if _use_mysql else f"{k}=?" for k in data.keys()])
        fields += ", updated_at=%s" if _use_mysql else ", updated_at=?"
        params = list(data.values()) + [_now(), product_id]
        cur.execute(f"UPDATE products SET {fields} WHERE id=%s" if _use_mysql else f"UPDATE products SET {fields} WHERE id=?", params)
        return cur.rowcount > 0


def delete_product(product_id: int) -> bool:
    """删除商品"""
    with get_db() as cur:
        if cur is None:
            return False
        cur.execute("DELETE FROM products WHERE id=%s" if _use_mysql else "DELETE FROM products WHERE id=?", (product_id,))
        return cur.rowcount > 0


# ============== 库存 CRUD ==============
def get_inventory(sku_id: int = None, shop_id: int = None) -> List[Dict]:
    """获取库存（支持按 SKU / 店铺筛选）"""
    with get_db() as cur:
        if cur is None:
            return []
        cond, params = [], []
        if sku_id:
            cond.append("i.sku_id=%s" if _use_mysql else "i.sku_id=?")
            params.append(sku_id)
        if shop_id:
            cond.append("i.shop_id=%s" if _use_mysql else "i.shop_id=?")
            params.append(shop_id)
        where = ("WHERE " + " AND ".join(cond)) if cond else ""
        cur.execute(f"""
            SELECT i.*, s.sku_code, s.sku_name, s.source_price,
                   p.title as product_title, sh.shop_name, sh.platform
            FROM inventory i
            LEFT JOIN product_skus s ON i.sku_id = s.id
            LEFT JOIN products p ON s.product_id = p.id
            LEFT JOIN shops sh ON i.shop_id = sh.id
            {where}
            ORDER BY i.id DESC
        """ if not _use_mysql else f"""
            SELECT i.*, s.sku_code, s.sku_name, s.source_price,
                   p.title as product_title, sh.shop_name, sh.platform
            FROM inventory i
            LEFT JOIN product_skus s ON i.sku_id = s.id
            LEFT JOIN products p ON s.product_id = p.id
            LEFT JOIN shops sh ON i.shop_id = sh.id
            {where}
            ORDER BY i.id DESC
        """, params)
        return [_dict(r) for r in cur.fetchall()]


def create_inventory(data: Dict) -> int:
    """创建库存记录"""
    with get_db() as cur:
        if cur is None:
            return -1
        cur.execute("""
            INSERT INTO inventory (sku_id, shop_id, available_stock, reserved_stock, low_stock_threshold, updated_at)
            VALUES (%s,%s,%s,%s,%s,%s)""" if _use_mysql else """
            INSERT INTO inventory (sku_id, shop_id, available_stock, reserved_stock, low_stock_threshold, updated_at)
            VALUES (?,?,?,?,?,?)""",
            (data["sku_id"], data.get("shop_id"), data.get("available_stock", 0),
             data.get("reserved_stock", 0), data.get("low_stock_threshold", 10), _now()))
        return cur.lastrowid


def update_inventory(inv_id: int, data: Dict) -> bool:
    """更新库存"""
    with get_db() as cur:
        if cur is None:
            return False
        fields = ", ".join([f"{k}=%s" if _use_mysql else f"{k}=?" for k in data.keys()])
        fields += ", updated_at=%s" if _use_mysql else ", updated_at=?"
        params = list(data.values()) + [_now(), inv_id]
        cur.execute(f"UPDATE inventory SET {fields} WHERE id=%s" if _use_mysql else f"UPDATE inventory SET {fields} WHERE id=?", params)
        return cur.rowcount > 0


# ============== 定价规则 CRUD ==============
def create_pricing_rule(data: Dict) -> int:
    """创建定价规则"""
    with get_db() as cur:
        if cur is None:
            return -1
        cur.execute("""
            INSERT INTO pricing_rules (rule_name, rule_type, platform, shop_id, margin_percent,
                                         platform_fee_percent, shipping_cost, payment_fee_percent,
                                         round_mode, priority, is_active)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""" if _use_mysql else """
            INSERT INTO pricing_rules (rule_name, rule_type, platform, shop_id, margin_percent,
                                         platform_fee_percent, shipping_cost, payment_fee_percent,
                                         round_mode, priority, is_active)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (data["rule_name"], data["rule_type"], data.get("platform"), data.get("shop_id"),
             data.get("margin_percent", 30), data.get("platform_fee_percent", 10),
             data.get("shipping_cost", 0), data.get("payment_fee_percent", 2),
             data.get("round_mode", "ceil"), data.get("priority", 0),
             int(bool(data.get("is_active", True)))))
        return cur.lastrowid


def get_pricing_rules() -> List[Dict]:
    """获取所有定价规则"""
    with get_db() as cur:
        if cur is None:
            return []
        cur.execute("SELECT * FROM pricing_rules ORDER BY priority DESC, id DESC")
        return [_dict(r) for r in cur.fetchall()]


def delete_pricing_rule(rule_id: int) -> bool:
    """删除定价规则"""
    with get_db() as cur:
        if cur is None:
            return False
        cur.execute("DELETE FROM pricing_rules WHERE id=%s" if _use_mysql else "DELETE FROM pricing_rules WHERE id=?", (rule_id,))
        return cur.rowcount > 0


def get_active_pricing_rule(platform: str = None, shop_id: int = None) -> Optional[Dict]:
    """获取适用的定价规则"""
    with get_db() as cur:
        if cur is None:
            return None
        cond, params = ["is_active=1"], []
        if platform:
            cond.append("(platform=%s OR platform IS NULL)" if _use_mysql else "(platform=? OR platform IS NULL)")
            params.append(platform)
        if shop_id:
            cond.append("shop_id=%s" if _use_mysql else "shop_id=?")
            params.append(shop_id)
        where = "WHERE " + " AND ".join(cond)
        cur.execute(
            f"SELECT * FROM pricing_rules {where} ORDER BY priority DESC LIMIT 1"
            if _use_mysql else
            f"SELECT * FROM pricing_rules {where} ORDER BY priority DESC LIMIT 1",
            params
        )
        return _dict(cur.fetchone())


# ============== 批量刊登 ==============
def create_shop_product(data: Dict) -> int:
    """创建店铺商品（刊登记录）"""
    with get_db() as cur:
        if cur is None:
            return -1
        cur.execute("""
            INSERT INTO shop_products (product_id, shop_id, sku_id, price, stock, publish_status, published_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s)""" if _use_mysql else """
            INSERT INTO shop_products (product_id, shop_id, sku_id, price, stock, publish_status, published_at)
            VALUES (?,?,?,?,?,?,?)""",
            (data["product_id"], data["shop_id"], data.get("sku_id"),
             data.get("price", 0), data.get("stock", 0),
             data.get("publish_status", "published"), _now()))
        return cur.lastrowid


def get_shop_products(page: int = 1, page_size: int = 50, shop_id: int = None,
                       status: str = None) -> Dict:
    """获取已刊登商品"""
    with get_db() as cur:
        if cur is None:
            return {"items": [], "total": 0, "page": page, "page_size": page_size, "total_pages": 0}
        cond, params = [], []
        if shop_id:
            cond.append("sp.shop_id=%s" if _use_mysql else "sp.shop_id=?")
            params.append(shop_id)
        if status:
            cond.append("sp.publish_status=%s" if _use_mysql else "sp.publish_status=?")
            params.append(status)
        where = ("WHERE " + " AND ".join(cond)) if cond else ""
        cur.execute(f"""
            SELECT sp.*, p.title as product_title, p.images as product_images,
                   sh.shop_name, sh.platform, s.sku_code, s.sku_name
            FROM shop_products sp
            LEFT JOIN products p ON sp.product_id = p.id
            LEFT JOIN shops sh ON sp.shop_id = sh.id
            LEFT JOIN product_skus s ON sp.sku_id = s.id
            {where}
            ORDER BY sp.id DESC
        """ + (f" LIMIT %s OFFSET %s" if _use_mysql else " LIMIT ? OFFSET ?"), params + [page_size, (page - 1) * page_size])
        items = [_dict(r) for r in cur.fetchall()]
        cur.execute(f"SELECT COUNT(*) FROM shop_products sp {where}", params)
        total = cur.fetchone()[0] if _use_mysql else cur.fetchone()[0]
        return {"items": items, "total": total, "page": page, "page_size": page_size,
                "total_pages": (total + page_size - 1) // page_size if total else 1}


def offline_shop_product(sp_id: int) -> bool:
    """下架商品"""
    with get_db() as cur:
        if cur is None:
            return False
        cur.execute("UPDATE shop_products SET publish_status='offline', updated_at=%s WHERE id=%s"
                     if _use_mysql else "UPDATE shop_products SET publish_status='offline', updated_at=? WHERE id=?",
                     (_now(), sp_id))
        return cur.rowcount > 0


# ============== 采集历史 ==============
def add_collect_history(data: Dict) -> int:
    """添加采集记录"""
    with get_db() as cur:
        if cur is None:
            return -1
        cur.execute("""
            INSERT INTO collect_history (platform, source_url, title, status, product_id, error_message)
            VALUES (%s,%s,%s,%s,%s,%s)""" if _use_mysql else """
            INSERT INTO collect_history (platform, source_url, title, status, product_id, error_message)
            VALUES (?,?,?,?,?,?)""",
            (data["platform"], data.get("source_url"), data.get("title"),
             data.get("status", "success"), data.get("product_id"), data.get("error_message")))
        return cur.lastrowid


def get_collect_history(limit: int = 50) -> List[Dict]:
    """获取采集历史"""
    with get_db() as cur:
        if cur is None:
            return []
        cur.execute("SELECT * FROM collect_history ORDER BY id DESC LIMIT %s" if _use_mysql
                     else "SELECT * FROM collect_history ORDER BY id DESC LIMIT ?", (limit,))
        return [_dict(r) for r in cur.fetchall()]


# ============== 仪表盘统计 ==============
def get_dashboard_stats() -> Dict:
    """获取仪表盘统计数据"""
    with get_db() as cur:
        if cur is None:
            return {"total_shops": 0, "total_products": 0, "total_published": 0, "low_stock_count": 0, "shops_by_platform": []}

        cur.execute("SELECT COUNT(*) FROM shops WHERE status='active'")
        total_shops = cur.fetchone()[0] if _use_mysql else cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM products")
        total_products = cur.fetchone()[0] if _use_mysql else cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM shop_products WHERE publish_status='published'")
        total_published = cur.fetchone()[0] if _use_mysql else cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM inventory WHERE available_stock <= low_stock_threshold")
        low_stock = cur.fetchone()[0] if _use_mysql else cur.fetchone()[0]

        cur.execute("""
            SELECT platform, COUNT(*) as count FROM shops
            WHERE status='active' AND platform IS NOT NULL
            GROUP BY platform
        """ if _use_mysql else """
            SELECT platform, COUNT(*) as count FROM shops
            WHERE status='active' AND platform IS NOT NULL
            GROUP BY platform
        """)
        shops_by_platform = [_dict(r) for r in cur.fetchall()]

        return {
            "total_shops": total_shops,
            "total_products": total_products,
            "total_published": total_published,
            "low_stock_count": low_stock,
            "shops_by_platform": shops_by_platform,
        }


# ============== SKU 操作 ==============
def create_sku(product_id: int, data: Dict) -> int:
    """创建 SKU"""
    sku_code = data.get("sku_code") or _gen_code("SKU")
    attrs = json.dumps(data.get("attributes") or {}, ensure_ascii=False) if isinstance(data.get("attributes"), dict) else "{}"
    imgs = json.dumps(data.get("images") or [], ensure_ascii=False) if isinstance(data.get("images"), list) else "[]"
    with get_db() as cur:
        if cur is None:
            return -1
        cur.execute("""
            INSERT INTO product_skus (product_id, sku_code, sku_name, source_price, attributes, images, weight)
            VALUES (%s,%s,%s,%s,%s,%s,%s)""" if _use_mysql else """
            INSERT INTO product_skus (product_id, sku_code, sku_name, source_price, attributes, images, weight)
            VALUES (?,?,?,?,?,?,?)""",
            (product_id, sku_code, data.get("sku_name"), data.get("source_price", 0), attrs, imgs, data.get("weight")))
        # 更新商品 SKU 计数
        cur.execute("SELECT COUNT(*) FROM product_skus WHERE product_id=%s" if _use_mysql else "SELECT COUNT(*) FROM product_skus WHERE product_id=?", (product_id,))
        cnt = cur.fetchone()[0] if _use_mysql else cur.fetchone()[0]
        cur.execute("UPDATE products SET sku_count=%s, updated_at=%s WHERE id=%s" if _use_mysql else "UPDATE products SET sku_count=?, updated_at=? WHERE id=?",
                     (cnt, _now(), product_id))
        return cur.lastrowid


def get_skus_by_product(product_id: int) -> List[Dict]:
    """获取商品的所有 SKU"""
    with get_db() as cur:
        if cur is None:
            return []
        cur.execute("SELECT * FROM product_skus WHERE product_id=%s ORDER BY id" if _use_mysql
                     else "SELECT * FROM product_skus WHERE product_id=? ORDER BY id", (product_id,))
        return [_dict(r) for r in cur.fetchall()]


def get_sku(sku_id: int) -> Optional[Dict]:
    """获取单个 SKU"""
    with get_db() as cur:
        if cur is None:
            return None
        cur.execute("SELECT * FROM product_skus WHERE id=%s" if _use_mysql else "SELECT * FROM product_skus WHERE id=?", (sku_id,))
        return _dict(cur.fetchone())


def update_sku(sku_id: int, data: Dict) -> bool:
    """更新 SKU"""
    if "attributes" in data and isinstance(data["attributes"], dict):
        data["attributes"] = json.dumps(data["attributes"], ensure_ascii=False)
    if "images" in data and isinstance(data["images"], list):
        data["images"] = json.dumps(data["images"], ensure_ascii=False)
    with get_db() as cur:
        if cur is None:
            return False
        fields = ", ".join([f"{k}=%s" if _use_mysql else f"{k}=?" for k in data.keys()])
        fields += ", updated_at=%s" if _use_mysql else ", updated_at=?"
        params = list(data.values()) + [_now(), sku_id]
        cur.execute(f"UPDATE product_skus SET {fields} WHERE id=%s" if _use_mysql
                     else f"UPDATE product_skus SET {fields} WHERE id=?", params)
        return cur.rowcount > 0


def delete_sku(sku_id: int) -> bool:
    """删除 SKU"""
    with get_db() as cur:
        if cur is None:
            return False
        cur.execute("DELETE FROM product_skus WHERE id=%s" if _use_mysql else "DELETE FROM product_skus WHERE id=?", (sku_id,))
        return cur.rowcount > 0


def get_inventory_by_sku(sku_id: int) -> Optional[Dict]:
    """获取指定 SKU 的库存（全局，无视店铺）"""
    with get_db() as cur:
        if cur is None:
            return None
        cur.execute(
            "SELECT * FROM inventory WHERE sku_id=%s LIMIT 1" if _use_mysql
            else "SELECT * FROM inventory WHERE sku_id=? LIMIT 1",
            (sku_id,)
        )
        return _dict(cur.fetchone())


def upsert_inventory(sku_id: int, shop_id: int = None, available_stock: int = None,
                     reserved_stock: int = None) -> int:
    """更新或新建库存记录（按 sku_id + shop_id）"""
    with get_db() as cur:
        if cur is None:
            return -1
        # 查询是否已存在
        if shop_id:
            cur.execute(
                "SELECT id FROM inventory WHERE sku_id=%s AND shop_id=%s" if _use_mysql
                else "SELECT id FROM inventory WHERE sku_id=? AND shop_id=?",
                (sku_id, shop_id)
            )
        else:
            cur.execute(
                "SELECT id FROM inventory WHERE sku_id=%s AND shop_id IS NULL" if _use_mysql
                else "SELECT id FROM inventory WHERE sku_id=? AND shop_id IS NULL",
                (sku_id,)
            )
        existing = cur.fetchone()

        fields, params = [], []
        if available_stock is not None:
            fields.append("available_stock=%s" if _use_mysql else "available_stock=?")
            params.append(available_stock)
        if reserved_stock is not None:
            fields.append("reserved_stock=%s" if _use_mysql else "reserved_stock=?")
            params.append(reserved_stock)
        fields.append("updated_at=%s" if _use_mysql else "updated_at=?")
        params.append(_now())

        if existing:
            params.append(existing[0] if _use_mysql else existing["id"])
            cur.execute(
                f"UPDATE inventory SET {','.join(fields)} WHERE id=%s" if _use_mysql
                else f"UPDATE inventory SET {','.join(fields)} WHERE id=?",
                params
            )
            return existing[0] if _use_mysql else existing["id"]
        else:
            ins_fields = ["sku_id", "shop_id"] + [f.split("=")[0] for f in fields]
            ins_vals = [sku_id, shop_id] + params
            placeholders = "%s" if _use_mysql else "?"
            cur.execute(
                f"INSERT INTO inventory ({','.join(ins_fields)}) VALUES ({','.join([placeholders]*len(ins_vals))})"
                if _use_mysql else
                f"INSERT INTO inventory ({','.join(ins_fields)}) VALUES ({','.join([placeholders]*len(ins_vals))})",
                ins_vals
            )
            return cur.lastrowid
