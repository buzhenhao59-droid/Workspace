# -*- coding: utf-8 -*-
"""
店铺管理模块 - MySQL 数据库表结构
跨境电商多平台多店铺商品中心化管理
"""
import pymysql
from datetime import datetime

# ============== 平台枚举 ==============
class PlatformEnum:
    """支持的电商平台"""
    ALIEXPRESS = "aliexpress"      # 速卖通
    AMAZON = "amazon"              # 亚马逊
    SHOPEE = "shopee"              # Shopee
    TEMU = "temu"                  # Temu
    TIKTOK = "tiktok"              # TikTok Shop
    LAZADA = "lazada"              # Lazada
    EBAY = "ebay"                  # eBay
    SHOPIFY = "shopify"            # Shopify
    T1688 = "1688"                 # 1688货源
    
    @classmethod
    def get_all(cls):
        return [cls.ALIEXPRESS, cls.AMAZON, cls.SHOPEE, cls.TEMU, cls.TIKTOK, cls.LAZADA, cls.EBAY, cls.SHOPIFY, cls._1688]
    
    @classmethod
    def get_name(cls, code):
        names = {
            cls.ALIEXPRESS: "速卖通",
            cls.AMAZON: "亚马逊",
            cls.SHOPEE: "Shopee",
            cls.TEMU: "Temu",
            cls.TIKTOK: "TikTok Shop",
            cls.LAZADA: "Lazada",
            cls.EBAY: "eBay",
            cls.SHOPIFY: "Shopify",
            cls.T1688: "1688"
        }
        return names.get(code, code)


class ProductStatus:
    """商品状态"""
    DRAFT = "draft"           # 草稿
    PENDING = "pending"        # 待审核
    PUBLISHED = "published"   # 已发布
    OFFLINE = "offline"       # 已下架
    ARCHIVED = "archived"     # 已归档


class PublishStatus:
    """刊登状态"""
    NOT_PUBLISHED = "not_published"     # 未刊登
    PUBLISHING = "publishing"            # 刊登中
    PUBLISHED = "published"               # 已刊登
    FAILED = "failed"                     # 刊登失败


# ============== 建表 SQL ==============
CREATE_TABLES_SQL = """
-- 店铺表
CREATE TABLE IF NOT EXISTS shops (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    shop_name VARCHAR(100) NOT NULL COMMENT '店铺名称',
    platform VARCHAR(50) NOT NULL COMMENT '平台代码',
    shop_id VARCHAR(100) COMMENT '平台店铺ID',
    app_key VARCHAR(500) COMMENT '应用Key',
    app_secret VARCHAR(500) COMMENT '应用Secret(加密存储)',
    access_token VARCHAR(1000) COMMENT '访问令牌(加密存储)',
    refresh_token VARCHAR(1000) COMMENT '刷新令牌(加密存储)',
    token_expire_at DATETIME COMMENT '令牌过期时间',
    status VARCHAR(20) DEFAULT 'active' COMMENT '状态:active/inactive',
    country VARCHAR(50) COMMENT '目标国家',
    currency VARCHAR(10) COMMENT '货币',
    timezone VARCHAR(50) COMMENT '时区',
    is_default TINYINT DEFAULT 0 COMMENT '是否默认店铺',
    owner_id BIGINT COMMENT '所属用户ID',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_platform (platform),
    INDEX idx_status (status),
    INDEX idx_owner (owner_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='店铺表';

-- 商品主表
CREATE TABLE IF NOT EXISTS products (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    product_code VARCHAR(100) UNIQUE COMMENT '商品编码(系统生成)',
    source_platform VARCHAR(50) COMMENT '货源平台',
    source_url VARCHAR(1000) COMMENT '货源链接',
    source_id VARCHAR(200) COMMENT '货源平台商品ID',
    title VARCHAR(500) COMMENT '商品标题',
    title_en VARCHAR(500) COMMENT '英文标题',
    description TEXT COMMENT '商品描述',
    description_en TEXT COMMENT '英文描述',
    category_id BIGINT COMMENT '分类ID',
    category_path VARCHAR(500) COMMENT '分类路径',
    brand VARCHAR(100) COMMENT '品牌',
    material VARCHAR(200) COMMENT '材质',
    model VARCHAR(200) COMMENT '型号',
    weight DECIMAL(10,3) COMMENT '重量(kg)',
    dimensions LONGTEXT COMMENT '尺寸信息JSON',
    images JSON COMMENT '图片列表',
    videos JSON COMMENT '视频列表',
    attributes JSON COMMENT '属性列表',
    tags JSON COMMENT '标签',
    status VARCHAR(20) DEFAULT 'draft' COMMENT '状态:draft/pending/published/offline/archived',
    version INT DEFAULT 1 COMMENT '版本号',
    created_by BIGINT COMMENT '创建人',
    approved_by BIGINT COMMENT '审核人',
    approved_at DATETIME COMMENT '审核时间',
    published_at DATETIME COMMENT '发布时间',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_code (product_code),
    INDEX idx_source (source_platform, source_id),
    INDEX idx_status (status),
    INDEX idx_category (category_id),
    FULLTEXT INDEX idx_title (title, title_en, description, description_en)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='商品主表';

-- 商品SKU表
CREATE TABLE IF NOT EXISTS product_skus (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    product_id BIGINT NOT NULL,
    sku_code VARCHAR(100) UNIQUE COMMENT 'SKU编码',
    sku_name VARCHAR(200) COMMENT 'SKU名称',
    barcode VARCHAR(100) COMMENT '条形码',
    color VARCHAR(100) COMMENT '颜色',
    color_code VARCHAR(50) COMMENT '颜色代码',
    size VARCHAR(50) COMMENT '尺码',
    size_chart_id BIGINT COMMENT '尺码表ID',
    weight DECIMAL(10,3) COMMENT '重量(g)',
    dimensions LONGTEXT COMMENT '尺寸JSON',
    purchase_price DECIMAL(10,2) COMMENT '采购价(人民币)',
    packaging_cost DECIMAL(10,2) COMMENT '包装费',
    shipping_cost DECIMAL(10,2) COMMENT '运费',
    other_cost DECIMAL(10,2) COMMENT '其他成本',
    cost_price DECIMAL(10,2) COMMENT '总成本(计算得出)',
    retail_price DECIMAL(10,2) COMMENT '零售价',
    status VARCHAR(20) DEFAULT 'active' COMMENT '状态:active/inactive',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_product (product_id),
    INDEX idx_sku_code (sku_code),
    INDEX idx_barcode (barcode)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='商品SKU表';

-- 商品多语言表
CREATE TABLE IF NOT EXISTS product_translations (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    product_id BIGINT NOT NULL,
    sku_id BIGINT,
    locale VARCHAR(10) NOT NULL COMMENT '语言代码:en/ar/ru/es/fr/de/pt/ja/ko',
    title VARCHAR(500) COMMENT '本地化标题',
    description TEXT COMMENT '本地化描述',
    attributes JSON COMMENT '本地化属性',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_product_locale (product_id, sku_id, locale),
    INDEX idx_product (product_id),
    INDEX idx_locale (locale)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='商品多语言表';

-- 尺码表
CREATE TABLE IF NOT EXISTS size_charts (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(100) NOT NULL COMMENT '尺码表名称',
    platform VARCHAR(50) COMMENT '适用平台',
    sizes JSON NOT NULL COMMENT '尺码列表',
    measurements JSON COMMENT '测量数据',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_platform (platform)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='尺码表';

-- 分类表
CREATE TABLE IF NOT EXISTS categories (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    parent_id BIGINT DEFAULT 0 COMMENT '父分类ID',
    name VARCHAR(100) NOT NULL COMMENT '分类名称',
    name_en VARCHAR(100) COMMENT '英文名称',
    level INT DEFAULT 1 COMMENT '层级',
    sort_order INT DEFAULT 0 COMMENT '排序',
    platform VARCHAR(50) COMMENT '平台',
    platform_category_id VARCHAR(100) COMMENT '平台分类ID',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_parent (parent_id),
    INDEX idx_platform (platform)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='商品分类表';

-- 店铺商品关联表(已刊登商品)
CREATE TABLE IF NOT EXISTS shop_products (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    shop_id BIGINT NOT NULL,
    product_id BIGINT NOT NULL,
    sku_id BIGINT,
    platform_product_id VARCHAR(200) COMMENT '平台商品ID',
    platform_sku_id VARCHAR(200) COMMENT '平台SKU ID',
    platform_url VARCHAR(1000) COMMENT '平台商品链接',
    listing_id VARCHAR(200) COMMENT '刊登ID',
    publish_status VARCHAR(20) DEFAULT 'not_published' COMMENT '刊登状态',
    price DECIMAL(10,2) COMMENT '售价',
    original_price DECIMAL(10,2) COMMENT '原价',
    stock INTEGER DEFAULT 0 COMMENT '库存',
    status VARCHAR(20) COMMENT '平台状态',
    title VARCHAR(500) COMMENT '店铺标题(差异化)',
    description TEXT COMMENT '店铺描述(差异化)',
    images JSON COMMENT '店铺图片(差异化)',
    attributes JSON COMMENT '店铺属性(差异化)',
    error_message TEXT COMMENT '错误信息',
    published_at DATETIME COMMENT '发布时间',
    last_sync_at DATETIME COMMENT '最后同步时间',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_shop_product (shop_id, product_id, sku_id),
    INDEX idx_shop (shop_id),
    INDEX idx_product (product_id),
    INDEX idx_platform_product (platform_product_id),
    INDEX idx_status (publish_status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='店铺商品关联表';

-- 库存表
CREATE TABLE IF NOT EXISTS inventory (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    sku_id BIGINT NOT NULL,
    shop_id BIGINT COMMENT '店铺ID(为空表示主库存)',
    platform VARCHAR(50) COMMENT '平台',
    platform_warehouse_id VARCHAR(100) COMMENT '平台仓库ID',
    available_stock INT DEFAULT 0 COMMENT '可用库存',
    reserved_stock INT DEFAULT 0 COMMENT '预留库存',
    total_stock INT DEFAULT 0 COMMENT '总库存',
    low_stock_alert INT DEFAULT 10 COMMENT '低库存预警值',
    last_sync_at DATETIME COMMENT '最后同步时间',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_sku_shop (sku_id, shop_id),
    INDEX idx_sku (sku_id),
    INDEX idx_shop (shop_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='库存表';

-- 定价规则表
CREATE TABLE IF NOT EXISTS pricing_rules (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    rule_name VARCHAR(100) NOT NULL COMMENT '规则名称',
    rule_type VARCHAR(50) NOT NULL COMMENT '规则类型:fixed/margin/target/competition',
    platform VARCHAR(50) COMMENT '适用平台',
    shop_id BIGINT COMMENT '适用店铺',
    priority INT DEFAULT 0 COMMENT '优先级',
    base_cost DECIMAL(10,2) COMMENT '基础成本',
    cost_factor DECIMAL(5,4) COMMENT '成本系数',
    margin_percent DECIMAL(5,2) COMMENT '利润率%',
    target_price DECIMAL(10,2) COMMENT '目标价格',
    competitor_price DECIMAL(10,2) COMMENT '参考竞品价格',
    competition_mode VARCHAR(20) COMMENT '竞争模式:lowest/highest/average',
    shipping_cost DECIMAL(10,2) COMMENT '运费',
    platform_fee_percent DECIMAL(5,2) COMMENT '平台佣金%',
    payment_fee_percent DECIMAL(5,2) COMMENT '支付费率%',
    other_fee DECIMAL(10,2) COMMENT '其他费用',
    round_mode VARCHAR(20) DEFAULT 'ceil' COMMENT '取整模式:ceil/floor/round',
    round_precision INT DEFAULT 2 COMMENT '保留小数位',
    is_active TINYINT DEFAULT 1 COMMENT '是否启用',
    start_date DATE COMMENT '生效开始日期',
    end_date DATE COMMENT '生效结束日期',
    created_by BIGINT COMMENT '创建人',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_type (rule_type),
    INDEX idx_platform (platform),
    INDEX idx_shop (shop_id),
    INDEX idx_active (is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='定价规则表';

-- 活动价格表
CREATE TABLE IF NOT EXISTS price_activities (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    activity_name VARCHAR(100) NOT NULL COMMENT '活动名称',
    activity_type VARCHAR(50) COMMENT '活动类型:sale/flash/bundle',
    platform VARCHAR(50) COMMENT '适用平台',
    shop_ids JSON COMMENT '适用店铺列表',
    discount_type VARCHAR(20) COMMENT '折扣类型:percent/fixed',
    discount_value DECIMAL(10,2) COMMENT '折扣值',
    start_time DATETIME NOT NULL COMMENT '开始时间',
    end_time DATETIME NOT NULL COMMENT '结束时间',
    status VARCHAR(20) DEFAULT 'pending' COMMENT '状态:pending/active/ended',
    created_by BIGINT COMMENT '创建人',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_platform (platform),
    INDEX idx_time (start_time, end_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='活动价格表';

-- 活动商品关联表
CREATE TABLE IF NOT EXISTS activity_products (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    activity_id BIGINT NOT NULL,
    product_id BIGINT,
    sku_id BIGINT,
    activity_price DECIMAL(10,2) COMMENT '活动价格',
    activity_stock INT COMMENT '活动库存',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_activity (activity_id),
    INDEX idx_product (product_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='活动商品关联表';

-- 采购记录表
CREATE TABLE IF NOT EXISTS purchase_orders (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    po_number VARCHAR(50) UNIQUE NOT NULL COMMENT '采购单号',
    supplier_name VARCHAR(200) COMMENT '供应商',
    supplier_contact VARCHAR(200) COMMENT '供应商联系方式',
    total_amount DECIMAL(10,2) COMMENT '总金额',
    currency VARCHAR(10) DEFAULT 'CNY' COMMENT '货币',
    status VARCHAR(20) DEFAULT 'pending' COMMENT '状态',
    expected_date DATE COMMENT '预计到货日期',
    actual_date DATE COMMENT '实际到货日期',
    warehouse VARCHAR(100) COMMENT '入库仓库',
    remark TEXT COMMENT '备注',
    created_by BIGINT COMMENT '创建人',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_po (po_number),
    INDEX idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='采购订单表';

-- 采购明细表
CREATE TABLE IF NOT EXISTS purchase_items (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    po_id BIGINT NOT NULL,
    sku_id BIGINT NOT NULL,
    quantity INT NOT NULL COMMENT '采购数量',
    unit_price DECIMAL(10,2) COMMENT '单价',
    total_price DECIMAL(10,2) COMMENT '总价',
    received_quantity INT DEFAULT 0 COMMENT '已收货数量',
    status VARCHAR(20) DEFAULT 'pending' COMMENT '状态',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_po (po_id),
    INDEX idx_sku (sku_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='采购明细表';

-- 系统配置表
CREATE TABLE IF NOT EXISTS system_config (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    config_key VARCHAR(100) UNIQUE NOT NULL COMMENT '配置键',
    config_value LONGTEXT COMMENT '配置值',
    config_type VARCHAR(20) DEFAULT 'string' COMMENT '类型:string/json/number/boolean',
    description VARCHAR(500) COMMENT '描述',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_key (config_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='系统配置表';

-- 操作日志表
CREATE TABLE IF NOT EXISTS operation_logs (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    user_id BIGINT COMMENT '操作人',
    username VARCHAR(100) COMMENT '操作人用户名',
    module VARCHAR(50) COMMENT '模块',
    action VARCHAR(50) COMMENT '操作',
    target_type VARCHAR(50) COMMENT '目标类型',
    target_id BIGINT COMMENT '目标ID',
    detail TEXT COMMENT '详情JSON',
    ip_address VARCHAR(50) COMMENT 'IP地址',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_user (user_id),
    INDEX idx_module (module),
    INDEX idx_time (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='操作日志表';
"""


# ============== 初始化数据库 ==============
def init_database(host="localhost", port=3306, user="root", password="", database="shop_manager"):
    """
    初始化数据库和表结构
    """
    conn = pymysql.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        charset='utf8mb4'
    )
    try:
        with conn.cursor() as cursor:
            # 创建数据库
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{database}` DEFAULT CHARACTER SET utf8mb4")
            cursor.execute(f"USE `{database}`")
            
            # 执行建表语句
            for sql in CREATE_TABLES_SQL.split(';'):
                sql = sql.strip()
                if sql:
                    cursor.execute(sql)
        
        conn.commit()
        print(f"数据库 {database} 初始化成功!")
        return True
    except Exception as e:
        print(f"数据库初始化失败: {e}")
        return False
    finally:
        conn.close()


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        init_database(
            host=sys.argv[1] if len(sys.argv) > 1 else "localhost",
            port=int(sys.argv[2]) if len(sys.argv) > 2 else 3306,
            user=sys.argv[3] if len(sys.argv) > 3 else "root",
            password=sys.argv[4] if len(sys.argv) > 4 else "",
            database=sys.argv[5] if len(sys.argv) > 5 else "shop_manager"
        )
    else:
        print("Usage: python db_shop.py [host] [port] [user] [password] [database]")
        print("Example: python db_shop.py localhost 3306 root 123456 shop_manager")
