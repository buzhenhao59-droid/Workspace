# -*- coding: utf-8 -*-
"""
MySQL 数据库初始化 SQL
统一建表脚本：所有表创建/索引/触发器
由 mysql_db.py 调用，或独立执行 python init_mysql_schema.py --init
"""
import os
import sys
import logging
import argparse
from pathlib import Path
from typing import List

# 添加项目路径
sys.path.insert(0, str(Path(__file__).resolve().parent))
from mysql_db import get_db, _get_mysql_config

logger = logging.getLogger(__name__)


# ============== 建表 SQL ==============

MYSQL_SCHEMA = """
-- ============================================================
-- Ruitalk 统一 MySQL 数据库架构
-- 版本: 1.0.0
-- 更新日期: 2026-03-28
-- 数据库名: ruitalk
-- ============================================================

-- 如果数据库不存在则创建
CREATE DATABASE IF NOT EXISTS `ruitalk`
    DEFAULT CHARACTER SET utf8mb4
    DEFAULT COLLATE utf8mb4_unicode_ci;
USE `ruitalk`;

-- ============================================================
-- 客户表
-- ============================================================
CREATE TABLE IF NOT EXISTS `customers` (
    `id` BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    `customer_id` VARCHAR(64) NOT NULL UNIQUE COMMENT '客户唯一标识',
    `phone` VARCHAR(32) DEFAULT NULL COMMENT '手机号',
    `name` VARCHAR(128) DEFAULT NULL COMMENT '客户姓名',
    `region` VARCHAR(64) DEFAULT NULL COMMENT '所在地区',
    `level` VARCHAR(32) DEFAULT '普通' COMMENT '会员等级',
    `m_value` INT UNSIGNED DEFAULT 0 COMMENT 'M值积分',
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX `idx_customers_phone` (`phone`),
    INDEX `idx_customers_name` (`name`),
    INDEX `idx_customers_level` (`level`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='客户信息表';

-- ============================================================
-- 会话表
-- ============================================================
CREATE TABLE IF NOT EXISTS `sessions` (
    `id` BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    `session_id` VARCHAR(128) NOT NULL UNIQUE COMMENT '会话ID',
    `customer_id` VARCHAR(64) DEFAULT NULL COMMENT '关联客户',
    `status` VARCHAR(32) DEFAULT 'active' COMMENT 'active/waiting/closed',
    `assign_to` VARCHAR(64) DEFAULT NULL COMMENT '分配给坐席',
    `is_ai` TINYINT UNSIGNED DEFAULT 1 COMMENT '1=AI模式,0=人工模式',
    `language` VARCHAR(16) DEFAULT 'zh' COMMENT '会话语言',
    `system_source` VARCHAR(32) DEFAULT 'seller' COMMENT 'seller/buyer',
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX `idx_sessions_customer` (`customer_id`),
    INDEX `idx_sessions_status` (`status`),
    INDEX `idx_sessions_assign` (`assign_to`),
    INDEX `idx_sessions_updated` (`updated_at`),
    INDEX `idx_sessions_system` (`system_source`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='会话表';

-- ============================================================
-- 消息表
-- ============================================================
CREATE TABLE IF NOT EXISTS `messages` (
    `id` BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    `session_id` VARCHAR(128) NOT NULL COMMENT '关联会话',
    `role` VARCHAR(32) NOT NULL COMMENT 'user/assistant/agent',
    `content` TEXT NOT NULL COMMENT '消息内容',
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX `idx_messages_session` (`session_id`),
    INDEX `idx_messages_created` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='消息表';

-- ============================================================
-- 卖家/客服账号表
-- ============================================================
CREATE TABLE IF NOT EXISTS `sellers` (
    `id` BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    `username` VARCHAR(128) NOT NULL UNIQUE COMMENT '用户名',
    `password_hash` VARCHAR(256) NOT NULL COMMENT '密码哈希',
    `name` VARCHAR(128) DEFAULT NULL COMMENT '显示名称',
    `role` VARCHAR(32) DEFAULT 'agent' COMMENT 'admin/manager/agent',
    `is_online` TINYINT UNSIGNED DEFAULT 0 COMMENT '是否在线',
    `password_changed` TINYINT UNSIGNED DEFAULT 0 COMMENT '是否已修改默认密码',
    `must_change_password` TINYINT UNSIGNED DEFAULT 0 COMMENT '下次登录是否强制修改密码',
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `last_login` DATETIME DEFAULT NULL,
    INDEX `idx_sellers_role` (`role`),
    INDEX `idx_sellers_online` (`is_online`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='卖家/坐席账号表';

-- ============================================================
-- 评价表
-- ============================================================
CREATE TABLE IF NOT EXISTS `reviews` (
    `id` BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    `review_id` VARCHAR(128) UNIQUE COMMENT '评价ID',
    `order_id` VARCHAR(128) DEFAULT NULL COMMENT '关联订单',
    `customer_id` VARCHAR(64) DEFAULT NULL COMMENT '客户ID',
    `customer_name` VARCHAR(128) DEFAULT NULL COMMENT '客户姓名',
    `star_rating` TINYINT UNSIGNED DEFAULT 5 COMMENT '星级 1-5',
    `content` TEXT DEFAULT NULL COMMENT '评价内容',
    `reply_content` TEXT DEFAULT NULL COMMENT '商家回复',
    `replied_at` DATETIME DEFAULT NULL COMMENT '回复时间',
    `replied_by` VARCHAR(64) DEFAULT NULL COMMENT '回复人',
    `status` VARCHAR(32) DEFAULT 'pending' COMMENT 'pending/replied',
    `platform` VARCHAR(32) DEFAULT 'other' COMMENT '平台来源',
    `product_name` VARCHAR(512) DEFAULT NULL COMMENT '商品名称',
    `product_image` TEXT DEFAULT NULL COMMENT '商品图片URL',
    `review_date` DATETIME DEFAULT NULL COMMENT '评价日期',
    `is_negative` TINYINT UNSIGNED DEFAULT 0 COMMENT '是否差评(1-2星)',
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX `idx_reviews_order` (`order_id`),
    INDEX `idx_reviews_customer` (`customer_id`),
    INDEX `idx_reviews_status` (`status`),
    INDEX `idx_reviews_platform` (`platform`),
    INDEX `idx_reviews_star` (`star_rating`),
    INDEX `idx_reviews_date` (`review_date`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='客户评价表';

-- ============================================================
-- 回复模板表
-- ============================================================
CREATE TABLE IF NOT EXISTS `reply_templates` (
    `id` BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    `name` VARCHAR(128) NOT NULL COMMENT '模板名称',
    `content` TEXT NOT NULL COMMENT '模板内容',
    `category` VARCHAR(64) DEFAULT 'general' COMMENT '分类',
    `is_default` TINYINT UNSIGNED DEFAULT 0 COMMENT '是否默认模板',
    `created_by` VARCHAR(64) DEFAULT NULL COMMENT '创建人',
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='回复模板表';

-- ============================================================
-- 自动回复规则表
-- ============================================================
CREATE TABLE IF NOT EXISTS `auto_reply_rules` (
    `id` BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    `rule_type` VARCHAR(32) NOT NULL COMMENT '规则类型',
    `star_min` TINYINT UNSIGNED DEFAULT NULL COMMENT '最低星级',
    `star_max` TINYINT UNSIGNED DEFAULT NULL COMMENT '最高星级',
    `reply_content` TEXT NOT NULL COMMENT '回复内容',
    `is_enabled` TINYINT UNSIGNED DEFAULT 1 COMMENT '是否启用',
    `created_by` VARCHAR(64) DEFAULT NULL COMMENT '创建人',
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='自动回复规则表';

-- ============================================================
-- 售后单表
-- ============================================================
CREATE TABLE IF NOT EXISTS `after_sales` (
    `id` BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    `as_id` VARCHAR(128) UNIQUE NOT NULL COMMENT '售后单号',
    `order_id` VARCHAR(128) DEFAULT NULL COMMENT '关联订单',
    `platform` VARCHAR(32) DEFAULT 'other' COMMENT '平台',
    `customer_id` VARCHAR(64) DEFAULT NULL COMMENT '客户ID',
    `customer_name` VARCHAR(128) DEFAULT NULL COMMENT '客户姓名',
    `type` VARCHAR(32) DEFAULT '退货退款' COMMENT '售后类型',
    `reason_category` VARCHAR(128) DEFAULT NULL COMMENT '原因分类',
    `reason_detail` TEXT DEFAULT NULL COMMENT '详细原因',
    `status` VARCHAR(32) DEFAULT '待审核' COMMENT '售后状态',
    `warehouse` VARCHAR(128) DEFAULT NULL COMMENT '仓库',
    `return_address_type` VARCHAR(32) DEFAULT '国内' COMMENT '退货地址类型',
    `refund_product` DECIMAL(10,2) DEFAULT 0.00 COMMENT '商品退款',
    `refund_shipping` DECIMAL(10,2) DEFAULT 0.00 COMMENT '运费退款',
    `refund_subsidy` DECIMAL(10,2) DEFAULT 0.00 COMMENT '补贴退款',
    `refund_customs` DECIMAL(10,2) DEFAULT 0.00 COMMENT '关税退款',
    `refund_commission` DECIMAL(10,2) DEFAULT 0.00 COMMENT '佣金扣除',
    `refund_other` DECIMAL(10,2) DEFAULT 0.00 COMMENT '其他扣除',
    `refund_total` DECIMAL(10,2) DEFAULT 0.00 COMMENT '总退款金额',
    `refund_method` VARCHAR(64) DEFAULT '原路退回' COMMENT '退款方式',
    `return_tracking` VARCHAR(128) DEFAULT NULL COMMENT '退货快递单号',
    `return_carrier` VARCHAR(64) DEFAULT NULL COMMENT '退货快递公司',
    `return_shipping_cost` DECIMAL(10,2) DEFAULT 0.00 COMMENT '退货运费',
    `qc_result` VARCHAR(64) DEFAULT NULL COMMENT '质检结果',
    `qc_note` TEXT DEFAULT NULL COMMENT '质检备注',
    `exchange_product` VARCHAR(256) DEFAULT NULL COMMENT '换货商品',
    `exchange_qty` INT UNSIGNED DEFAULT 1 COMMENT '换货数量',
    `internal_note` TEXT DEFAULT NULL COMMENT '内部备注',
    `buyer_note` TEXT DEFAULT NULL COMMENT '买家备注',
    `created_by` VARCHAR(64) DEFAULT NULL COMMENT '创建人',
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    `completed_at` DATETIME DEFAULT NULL COMMENT '完成时间',
    INDEX `idx_after_sale_order` (`order_id`),
    INDEX `idx_after_sale_customer` (`customer_id`),
    INDEX `idx_after_sale_status` (`status`),
    INDEX `idx_after_sale_platform` (`platform`),
    INDEX `idx_after_sale_created` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='售后单表';

-- ============================================================
-- 售前备注表
-- ============================================================
CREATE TABLE IF NOT EXISTS `pre_sale_notes` (
    `id` BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    `note_id` VARCHAR(128) UNIQUE NOT NULL COMMENT '备注单号',
    `order_id` VARCHAR(128) DEFAULT NULL COMMENT '关联订单',
    `customer_id` VARCHAR(64) DEFAULT NULL COMMENT '客户ID',
    `customer_name` VARCHAR(128) DEFAULT NULL COMMENT '客户姓名',
    `nickname` VARCHAR(128) DEFAULT NULL COMMENT '客户昵称',
    `platform` VARCHAR(32) DEFAULT 'other' COMMENT '平台',
    `platform_id` VARCHAR(128) DEFAULT NULL COMMENT '平台买家ID',
    `country` VARCHAR(64) DEFAULT NULL COMMENT '国家',
    `region` VARCHAR(128) DEFAULT NULL COMMENT '地区',
    `language` VARCHAR(16) DEFAULT 'zh' COMMENT '语言偏好',
    `is_old_customer` TINYINT UNSIGNED DEFAULT 0 COMMENT '是否老客户',
    `repeat_purchase_count` INT UNSIGNED DEFAULT 0 COMMENT '复购次数',
    `has_complaints` TINYINT UNSIGNED DEFAULT 0 COMMENT '是否有投诉',
    `has_disputes` TINYINT UNSIGNED DEFAULT 0 COMMENT '是否有纠纷',
    `has_negative_reviews` TINYINT UNSIGNED DEFAULT 0 COMMENT '是否有差评',
    `has_asked_shipping` TINYINT UNSIGNED DEFAULT 0 COMMENT '是否询问过发货',
    `has_asked_logistics` TINYINT UNSIGNED DEFAULT 0 COMMENT '是否询问过物流',
    `preference_style` VARCHAR(128) DEFAULT NULL COMMENT '偏好风格',
    `preference_color` VARCHAR(64) DEFAULT NULL COMMENT '偏好颜色',
    `preference_size` VARCHAR(64) DEFAULT NULL COMMENT '偏好尺码',
    `price_sensitivity` VARCHAR(32) DEFAULT 'normal' COMMENT '价格敏感度',
    `needs_gift` TINYINT UNSIGNED DEFAULT 0 COMMENT '是否需要赠品',
    `needs_card` TINYINT UNSIGNED DEFAULT 0 COMMENT '是否需要贺卡',
    `needs_privacy_packaging` TINYINT UNSIGNED DEFAULT 0 COMMENT '是否需要隐私包装',
    `product_color` VARCHAR(64) DEFAULT NULL COMMENT '商品颜色',
    `product_size` VARCHAR(64) DEFAULT NULL COMMENT '商品尺码',
    `product_model` VARCHAR(128) DEFAULT NULL COMMENT '商品型号',
    `packaging_type` VARCHAR(64) DEFAULT 'normal' COMMENT '包装要求',
    `no_invoice` TINYINT UNSIGNED DEFAULT 0 COMMENT '不需要发票',
    `no_price_list` TINYINT UNSIGNED DEFAULT 0 COMMENT '不需要价格单',
    `logistics_channel` VARCHAR(128) DEFAULT NULL COMMENT '物流渠道',
    `must_combine` TINYINT UNSIGNED DEFAULT 1 COMMENT '是否必须合并发货',
    `urgent_shipping` TINYINT UNSIGNED DEFAULT 0 COMMENT '是否加急发货',
    `needs_gift_item` TINYINT UNSIGNED DEFAULT 0 COMMENT '是否需要赠品',
    `needs_card_item` TINYINT UNSIGNED DEFAULT 0 COMMENT '是否需要贺卡',
    `customer_message_translation` TEXT DEFAULT NULL COMMENT '买家留言翻译',
    `fragile_need_extra_protection` TINYINT UNSIGNED DEFAULT 0 COMMENT '是否需要额外保护',
    `high_risk_area` TINYINT UNSIGNED DEFAULT 0 COMMENT '是否高风险地区',
    `suspected_scammer` TINYINT UNSIGNED DEFAULT 0 COMMENT '是否疑似骗子',
    `price_modification` VARCHAR(128) DEFAULT NULL COMMENT '价格修改',
    `discount` VARCHAR(128) DEFAULT NULL COMMENT '折扣',
    `free_shipping` TINYINT UNSIGNED DEFAULT 0 COMMENT '是否包邮',
    `out_of_stock` TINYINT UNSIGNED DEFAULT 0 COMMENT '是否缺货',
    `pre_order` TINYINT UNSIGNED DEFAULT 0 COMMENT '是否预售',
    `waiting_days` INT UNSIGNED DEFAULT 0 COMMENT '等待天数',
    `internal_note` TEXT DEFAULT NULL COMMENT '内部备注',
    `raw_note` TEXT DEFAULT NULL COMMENT '原始备注',
    `created_by` VARCHAR(64) DEFAULT NULL COMMENT '创建人',
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX `idx_pre_sale_order` (`order_id`),
    INDEX `idx_pre_sale_customer` (`customer_id`),
    INDEX `idx_pre_sale_platform` (`platform`),
    INDEX `idx_pre_sale_risk` (`high_risk_area`, `suspected_scammer`, `out_of_stock`),
    INDEX `idx_pre_sale_created` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='售前备注表';

-- ============================================================
-- 人工客服设置表
-- ============================================================
CREATE TABLE IF NOT EXISTS `human_settings` (
    `id` INT UNSIGNED PRIMARY KEY CHECK (`id` = 1),
    `quick_phrases` JSON DEFAULT NULL COMMENT '快捷短语 JSON 数组',
    `timeout_seconds` INT UNSIGNED DEFAULT 60 COMMENT '超时秒数',
    `timeout_presets` JSON DEFAULT NULL COMMENT '超时自动回复 JSON 数组',
    `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='人工客服设置';

-- ============================================================
-- 审计日志表
-- ============================================================
CREATE TABLE IF NOT EXISTS `audit_logs` (
    `id` BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    `event_type` VARCHAR(64) NOT NULL COMMENT '事件类型',
    `operator` VARCHAR(64) DEFAULT NULL COMMENT '操作人',
    `target_type` VARCHAR(64) DEFAULT NULL COMMENT '目标类型',
    `target_id` VARCHAR(128) DEFAULT NULL COMMENT '目标ID',
    `detail` TEXT DEFAULT NULL COMMENT '详情',
    `ip_address` VARCHAR(64) DEFAULT NULL COMMENT 'IP地址',
    `user_agent` VARCHAR(512) DEFAULT NULL COMMENT 'User-Agent',
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX `idx_audit_event` (`event_type`),
    INDEX `idx_audit_operator` (`operator`),
    INDEX `idx_audit_target` (`target_type`, `target_id`),
    INDEX `idx_audit_created` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='审计日志表';

-- ============================================================
-- 通知表（增强版：支持垂直领域政策通知）
-- 新增字段：domain / data_source / item_hash / summary / target_audience
--               policy_type / key_benefit / timeliness_check / is_fresh
-- ============================================================
CREATE TABLE IF NOT EXISTS `notifications` (
    `id` BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    `notify_type` VARCHAR(64) NOT NULL COMMENT '通知类型',
    `title` VARCHAR(256) NOT NULL COMMENT '通知标题',
    `content` TEXT DEFAULT NULL COMMENT '通知内容',
    `priority` VARCHAR(16) DEFAULT 'normal' COMMENT '优先级 low/normal/high',
    `is_read` TINYINT UNSIGNED DEFAULT 0 COMMENT '是否已读',
    `related_type` VARCHAR(64) DEFAULT NULL COMMENT '关联类型（用作来源名称）',
    `url` VARCHAR(512) DEFAULT '' COMMENT '相关链接',
    `related_id` VARCHAR(128) DEFAULT NULL COMMENT '关联ID',
    `created_by` VARCHAR(64) DEFAULT NULL COMMENT '创建人',
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    -- 垂直领域新增字段
    `domain` VARCHAR(32) DEFAULT 'cross_border' COMMENT '内容领域：cross_border / government',
    `data_source` VARCHAR(32) DEFAULT '' COMMENT '数据来源：customs / mofcom / amazon / tiktok / ln_gov / ln_rst',
    `item_hash` VARCHAR(64) DEFAULT '' COMMENT '去重哈希 SHA256(title+url)',
    `summary` TEXT COMMENT 'AI生成的一句话摘要',
    `target_audience` VARCHAR(256) COMMENT 'AI提取：政策涉及的人群/企业类型',
    `policy_type` VARCHAR(32) DEFAULT '通知' COMMENT 'AI判断：利好 / 风险 / 通知 / 补贴',
    `key_benefit` VARCHAR(256) COMMENT 'AI提取：核心利好或风险点',
    `timeliness_check` VARCHAR(256) COMMENT 'AI核实：时效一致性',
    `is_fresh` TINYINT UNSIGNED DEFAULT 0 COMMENT '是否新鲜（2小时内）',
    INDEX `idx_notif_type` (`notify_type`),
    INDEX `idx_notif_read` (`is_read`),
    INDEX `idx_notif_created` (`created_at`),
    INDEX `idx_notif_domain` (`domain`),
    INDEX `idx_notif_hash` (`item_hash`),
    INDEX `idx_notif_fresh` (`is_fresh`),
    INDEX `idx_notif_important` (`is_important`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='通知表（垂直领域增强版）';

-- ============================================================
-- 系统设置表
-- ============================================================
CREATE TABLE IF NOT EXISTS `system_settings` (
    `id` BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    `key` VARCHAR(128) NOT NULL UNIQUE COMMENT '设置键',
    `value` TEXT DEFAULT NULL COMMENT '设置值',
    `description` VARCHAR(256) DEFAULT NULL COMMENT '描述',
    `updated_by` VARCHAR(64) DEFAULT NULL COMMENT '最后修改人',
    `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='系统设置表';

-- ============================================================
-- 坐席会话分配表（用于分布式锁）
-- ============================================================
CREATE TABLE IF NOT EXISTS `agent_session_assignments` (
    `id` BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    `session_id` VARCHAR(128) NOT NULL UNIQUE COMMENT '会话ID',
    `agent_id` VARCHAR(64) NOT NULL COMMENT '坐席ID',
    `assigned_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `released_at` DATETIME DEFAULT NULL COMMENT '释放时间',
    `status` VARCHAR(32) DEFAULT 'active' COMMENT 'active/released',
    INDEX `idx_agent_assignments_agent` (`agent_id`),
    INDEX `idx_agent_assignments_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='坐席会话分配表';

-- ============================================================
-- 触发器：自动更新 updated_at（MySQL 事件调度器）
-- ============================================================
DELIMITER $$

DROP TRIGGER IF EXISTS `trg_customers_updated_at`$$
CREATE TRIGGER `trg_customers_updated_at`
BEFORE UPDATE ON `customers`
FOR EACH ROW
BEGIN
    SET NEW.updated_at = CURRENT_TIMESTAMP;
END$$

DROP TRIGGER IF EXISTS `trg_sessions_updated_at`$$
CREATE TRIGGER `trg_sessions_updated_at`
BEFORE UPDATE ON `sessions`
FOR EACH ROW
BEGIN
    SET NEW.updated_at = CURRENT_TIMESTAMP;
END$$

DROP TRIGGER IF EXISTS `trg_after_sales_updated_at`$$
CREATE TRIGGER `trg_after_sales_updated_at`
BEFORE UPDATE ON `after_sales`
FOR EACH ROW
BEGIN
    SET NEW.updated_at = CURRENT_TIMESTAMP;
END$$

DROP TRIGGER IF EXISTS `trg_reviews_updated_at`$$
CREATE TRIGGER `trg_reviews_updated_at`
BEFORE UPDATE ON `reviews`
FOR EACH ROW
BEGIN
    SET NEW.updated_at = CURRENT_TIMESTAMP;
END$$

DELIMITER ;


-- =====================================================
-- 消息中心服务表（message_center_service.py）
-- =====================================================

CREATE TABLE IF NOT EXISTS `quick_replies` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `category` VARCHAR(100) NOT NULL DEFAULT '通用',
    `title` VARCHAR(255) NOT NULL,
    `content` TEXT NOT NULL,
    `shortcut` VARCHAR(50),
    `is_active` TINYINT DEFAULT 1,
    `created_by` VARCHAR(100) DEFAULT 'admin',
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_quick_replies_category (`category`),
    INDEX idx_quick_replies_active (`is_active`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `reminders` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `title` VARCHAR(255) NOT NULL,
    `content` TEXT,
    `remind_type` VARCHAR(50) DEFAULT 'once',
    `remind_time` DATETIME NOT NULL,
    `is_repeat` TINYINT DEFAULT 0,
    `repeat_days` VARCHAR(100),
    `is_active` TINYINT DEFAULT 1,
    `is_triggered` TINYINT DEFAULT 0,
    `created_by` VARCHAR(100) DEFAULT 'admin',
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    `last_triggered` DATETIME,
    INDEX idx_reminders_time (`remind_time`),
    INDEX idx_reminders_active (`is_active`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `conversation_history` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `session_id` VARCHAR(100) UNIQUE NOT NULL,
    `platform` VARCHAR(50) NOT NULL,
    `customer_id` VARCHAR(100),
    `customer_name` VARCHAR(255),
    `is_human` TINYINT DEFAULT 0,
    `last_message` TEXT,
    `last_sender` VARCHAR(50),
    `message_count` INT DEFAULT 0,
    `status` VARCHAR(20) DEFAULT 'active',
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_conv_sid (`session_id`),
    INDEX idx_conv_platform (`platform`),
    INDEX idx_conv_updated (`updated_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""


# ============== 初始化默认数据 ==============

DEFAULT_DATA_SQL = """
USE `ruitalk`;

-- 默认回复模板
INSERT IGNORE INTO `reply_templates` (`name`, `content`, `category`, `is_default`, `created_by`) VALUES
('感谢支持', '感谢您的好评！您的满意是我们最大的动力。如有任何问题，欢迎随时联系我们。', '感谢', 1, 'system'),
('感谢5星', '非常感谢您的5星好评！期待下次为您服务。祝您生活愉快！', '感谢', 0, 'system'),
('抱歉差评', '非常抱歉给您带来不好的体验。我们非常重视您的反馈，请联系我们的客服，我们会尽快为您解决。', '道歉', 0, 'system'),
('已回复', '您好，我们已收到您的评价并进行了处理。感谢您的耐心等待。', '通用', 0, 'system'),
('欢迎下次', '感谢您的购买，欢迎下次再来。祝您购物愉快！', '感谢', 0, 'system');

-- 人工客服设置默认值
INSERT IGNORE INTO `human_settings` (`id`, `quick_phrases`, `timeout_seconds`, `timeout_presets`) VALUES
(1, '[]', 60, '[]');
"""


# ============== SQLite 兼容建表（回退用）=============

SQLITE_SCHEMA = """
-- SQLite 回退建表（与 MySQL 相同结构）
-- customers
CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id TEXT UNIQUE NOT NULL,
    phone TEXT,
    name TEXT,
    region TEXT,
    level TEXT DEFAULT '普通',
    m_value INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- sessions
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT UNIQUE NOT NULL,
    customer_id TEXT,
    status TEXT DEFAULT 'active',
    assign_to TEXT,
    is_ai INTEGER DEFAULT 1,
    language TEXT DEFAULT 'zh',
    system_source TEXT DEFAULT 'seller',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- messages
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- sellers
CREATE TABLE IF NOT EXISTS sellers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    name TEXT,
    role TEXT DEFAULT 'agent',
    is_online INTEGER DEFAULT 0,
    password_changed INTEGER DEFAULT 0,
    must_change_password INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    last_login TEXT
);

-- reviews
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
);

-- reply_templates
CREATE TABLE IF NOT EXISTS reply_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    content TEXT NOT NULL,
    category TEXT DEFAULT 'general',
    is_default INTEGER DEFAULT 0,
    created_by TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- auto_reply_rules
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
);

-- after_sales
CREATE TABLE IF NOT EXISTS after_sales (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    as_id TEXT UNIQUE NOT NULL,
    order_id TEXT,
    platform TEXT DEFAULT 'other',
    customer_id TEXT,
    customer_name TEXT,
    type TEXT DEFAULT '退货退款',
    reason_category TEXT,
    reason_detail TEXT,
    status TEXT DEFAULT '待审核',
    warehouse TEXT,
    return_address_type TEXT DEFAULT '国内',
    refund_product REAL DEFAULT 0,
    refund_shipping REAL DEFAULT 0,
    refund_subsidy REAL DEFAULT 0,
    refund_customs REAL DEFAULT 0,
    refund_commission REAL DEFAULT 0,
    refund_other REAL DEFAULT 0,
    refund_total REAL DEFAULT 0,
    refund_method TEXT DEFAULT '原路退回',
    return_tracking TEXT,
    return_carrier TEXT,
    return_shipping_cost REAL DEFAULT 0,
    qc_result TEXT,
    qc_note TEXT,
    exchange_product TEXT,
    exchange_qty INTEGER DEFAULT 1,
    internal_note TEXT,
    buyer_note TEXT,
    created_by TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT
);

-- pre_sale_notes
CREATE TABLE IF NOT EXISTS pre_sale_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    note_id TEXT UNIQUE NOT NULL,
    order_id TEXT,
    customer_id TEXT,
    customer_name TEXT,
    nickname TEXT,
    platform TEXT DEFAULT 'other',
    platform_id TEXT,
    country TEXT,
    region TEXT,
    language TEXT DEFAULT 'zh',
    is_old_customer INTEGER DEFAULT 0,
    repeat_purchase_count INTEGER DEFAULT 0,
    has_complaints INTEGER DEFAULT 0,
    has_disputes INTEGER DEFAULT 0,
    has_negative_reviews INTEGER DEFAULT 0,
    has_asked_shipping INTEGER DEFAULT 0,
    has_asked_logistics INTEGER DEFAULT 0,
    preference_style TEXT,
    preference_color TEXT,
    preference_size TEXT,
    price_sensitivity TEXT DEFAULT 'normal',
    needs_gift INTEGER DEFAULT 0,
    needs_card INTEGER DEFAULT 0,
    needs_privacy_packaging INTEGER DEFAULT 0,
    product_color TEXT,
    product_size TEXT,
    product_model TEXT,
    packaging_type TEXT DEFAULT 'normal',
    no_invoice INTEGER DEFAULT 0,
    no_price_list INTEGER DEFAULT 0,
    logistics_channel TEXT,
    must_combine INTEGER DEFAULT 1,
    urgent_shipping INTEGER DEFAULT 0,
    needs_gift_item INTEGER DEFAULT 0,
    needs_card_item INTEGER DEFAULT 0,
    customer_message_translation TEXT,
    fragile_need_extra_protection INTEGER DEFAULT 0,
    high_risk_area INTEGER DEFAULT 0,
    suspected_scammer INTEGER DEFAULT 0,
    price_modification TEXT,
    discount TEXT,
    free_shipping INTEGER DEFAULT 0,
    out_of_stock INTEGER DEFAULT 0,
    pre_order INTEGER DEFAULT 0,
    waiting_days INTEGER DEFAULT 0,
    internal_note TEXT,
    raw_note TEXT,
    created_by TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- human_settings
CREATE TABLE IF NOT EXISTS human_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    quick_phrases TEXT DEFAULT '[]',
    timeout_seconds INTEGER DEFAULT 60,
    timeout_presets TEXT DEFAULT '[]',
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- audit_logs
CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    operator TEXT,
    target_type TEXT,
    target_id TEXT,
    detail TEXT,
    ip_address TEXT,
    user_agent TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- notifications（增强版：支持垂直领域政策通知）
-- 新增字段：domain / data_source / item_hash / summary / target_audience
--               policy_type / key_benefit / timeliness_check / is_fresh
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    notification_type TEXT NOT NULL DEFAULT 'policy',
    title TEXT NOT NULL,
    content TEXT,
    source TEXT DEFAULT 'deepseek',
    url TEXT DEFAULT '',
    is_read INTEGER DEFAULT 0,
    is_important INTEGER DEFAULT 0,
    notify_type TEXT,
    priority TEXT DEFAULT 'normal',
    related_type TEXT,
    related_id TEXT,
    created_by TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    read_at TEXT,
    -- 垂直领域新增字段
    domain TEXT DEFAULT 'cross_border' COMMENT '内容领域：cross_border / government',
    data_source TEXT DEFAULT '' COMMENT '数据来源：customs / mofcom / amazon / tiktok / ln_gov / ln_rst / ln_bt',
    item_hash TEXT DEFAULT '' COMMENT '去重哈希 SHA256(title+url)',
    summary TEXT COMMENT 'AI生成的一句话摘要',
    target_audience TEXT COMMENT 'AI提取：政策涉及的人群/企业类型',
    policy_type TEXT DEFAULT '通知' COMMENT 'AI判断：利好 / 风险 / 通知 / 补贴',
    key_benefit TEXT COMMENT 'AI提取：核心利好或风险点',
    timeliness_check TEXT COMMENT 'AI核实：时效一致性',
    is_fresh INTEGER DEFAULT 0 COMMENT '是否新鲜（2小时内）'
);

-- system_settings
CREATE TABLE IF NOT EXISTS system_settings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT UNIQUE NOT NULL,
    value TEXT,
    description TEXT,
    updated_by TEXT,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- agent_session_assignments
CREATE TABLE IF NOT EXISTS agent_session_assignments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT UNIQUE NOT NULL,
    agent_id TEXT NOT NULL,
    assigned_at TEXT DEFAULT CURRENT_TIMESTAMP,
    released_at TEXT,
    status TEXT DEFAULT 'active'
);

-- SQLite 索引
CREATE INDEX IF NOT EXISTS idx_customers_phone ON customers(phone);
CREATE INDEX IF NOT EXISTS idx_sessions_customer ON sessions(customer_id);
CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
CREATE INDEX IF NOT EXISTS idx_reviews_order ON reviews(order_id);
CREATE INDEX IF NOT EXISTS idx_reviews_status ON reviews(status);
CREATE INDEX IF NOT EXISTS idx_after_sale_order ON after_sales(order_id);
CREATE INDEX IF NOT EXISTS idx_after_sale_status ON after_sales(status);
CREATE INDEX IF NOT EXISTS idx_pre_sale_order ON pre_sale_notes(order_id);
CREATE INDEX IF NOT EXISTS idx_pre_sale_customer ON pre_sale_notes(customer_id);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_notif_read ON notifications(is_read);
"""


def _split_sql_statements(sql: str) -> List[str]:
    """分割 SQL 语句（处理 DELIMITER 等 MySQL 特有语法）"""
    statements = []

    import re
    # 1. 提取所有 DELIMITER $$ ... $$ 块（触发器区域），先整体提取
    trigger_blocks = re.findall(r'\$\$[\s\S]*?\$\$', sql)
    rest = re.sub(r'\$\$[\s\S]*?\$\$', '', sql)

    # 2. 处理非触发器部分
    rest = re.sub(r'DELIMITER\s+\$\$\s*', '', rest)
    rest = re.sub(r'DELIMITER\s+;\s*', '', rest)

    for stmt in rest.split(';'):
        stmt = stmt.strip()
        if not stmt:
            continue
        lines = []
        in_block_comment = False
        for line in stmt.split('\n'):
            ls = line.strip()
            if ls.startswith('/*'):
                in_block_comment = True
            if not in_block_comment:
                if not ls.startswith('--'):
                    lines.append(line)
            if ls.endswith('*/'):
                in_block_comment = False
        cleaned = '\n'.join(lines).strip()
        if cleaned:
            statements.append(cleaned)

    # 3. 拆分触发器块：每个块内以 $$ 分割，得到各条触发器 DDL
    for block in trigger_blocks:
        inner = block.strip()
        # 去掉首尾 $$ 标记
        inner = re.sub(r'^\$\$', '', inner)
        inner = re.sub(r'\$\$$', '', inner)
        # 内部以 $$ 分割各触发器
        parts = inner.split('$$')
        for part in parts:
            part = part.strip()
            if part:
                statements.append(part + '$$')

    return statements


def init_mysql_schema() -> bool:
    """初始化 MySQL 表结构"""
    try:
        import pymysql
        config = _get_mysql_config()
        conn = pymysql.connect(
            host=config["host"],
            port=config["port"],
            user=config["user"],
            password=config["password"],
            charset=config["charset"],
            connect_timeout=10,
            read_timeout=30,
        )
        cursor = conn.cursor()

        # 分离建表语句和索引语句，先建表再创建索引
        all_stmts = _split_sql_statements(MYSQL_SCHEMA)
        table_stmts, index_stmts = [], []
        for s in all_stmts:
            s_upper = s.upper().strip()
            if s_upper.startswith("CREATE TABLE"):
                table_stmts.append(s)
            elif s_upper.startswith("CREATE INDEX") or s_upper.startswith("CREATE UNIQUE INDEX"):
                index_stmts.append(s)
            else:
                # 数据库/触发器等直接执行
                table_stmts.append(s)

        def _exec(stmts, label):
            for stmt in stmts:
                if not stmt.strip():
                    continue
                try:
                    cursor.execute(stmt)
                    conn.commit()
                except Exception as e:
                    if "already exists" not in str(e).lower() and "duplicate" not in str(e).lower():
                        logger.warning(f"[{label}] {stmt[:80]}...  -> {e}")

        _exec(table_stmts, "SQL")

        # 索引：使用 "CREATE INDEX IF NOT EXISTS"，MySQL 8.0.29+ 支持
        # 若不支持（老版本），忽略错误
        for idx_stmt in index_stmts:
            try:
                cursor.execute(idx_stmt)
                conn.commit()
            except Exception as e:
                if "already exists" not in str(e).lower() and "duplicate" not in str(e).lower():
                    logger.warning(f"[IDX] {idx_stmt[:80]}... -> {e}")

        for stmt in _split_sql_statements(DEFAULT_DATA_SQL):
            if stmt.strip():
                try:
                    cursor.execute(stmt)
                    conn.commit()
                except Exception as e:
                    if "duplicate" not in str(e).lower():
                        logger.warning(f"[DATA] {stmt[:80]}... -> {e}")
        # 补列：确保旧表有新字段（垂直领域增强）
        try:
            cursor.execute("DESCRIBE notifications")
            cols = {row[0] for row in cursor.fetchall()}

            new_columns = {
                "domain": ("VARCHAR(32) DEFAULT 'cross_border' COMMENT '内容领域：cross_border / government'", "cross_border"),
                "data_source": ("VARCHAR(32) DEFAULT '' COMMENT '数据来源：customs / mofcom / amazon / tiktok / ln_gov'", ""),
                "item_hash": ("VARCHAR(64) DEFAULT '' COMMENT '去重哈希 SHA256(title+url)'", ""),
                "summary": ("TEXT COMMENT 'AI生成的一句话摘要'", ""),
                "target_audience": ("VARCHAR(256) COMMENT 'AI提取：政策涉及的人群/企业类型'", ""),
                "policy_type": ("VARCHAR(32) DEFAULT '通知' COMMENT 'AI判断：利好 / 风险 / 通知 / 补贴'", "通知"),
                "key_benefit": ("VARCHAR(256) COMMENT 'AI提取：核心利好或风险点'", ""),
                "timeliness_check": ("VARCHAR(256) COMMENT 'AI核实：时效一致性'", ""),
                "is_fresh": ("TINYINT UNSIGNED DEFAULT 0 COMMENT '是否新鲜（2小时内）'", 0),
            }

            for col_name, (col_def, default_val) in new_columns.items():
                if col_name not in cols:
                    cursor.execute(f"ALTER TABLE notifications ADD COLUMN {col_name} {col_def}")
                    conn.commit()
                    logger.info(f"[MySQL] notifications 表已添加 {col_name} 列")
        except Exception as e:
            logger.warning(f"[MySQL] notifications 补列失败: {e}")
        cursor.close()
        conn.close()
        logger.info("[MySQL] 表结构初始化完成")
        return True
    except Exception as e:
        logger.error(f"[MySQL] 表结构初始化失败: {e}")
        return False


def _ensure_sqlite_notifications_columns(conn) -> None:
    """
    旧库仅有 notify_type，消息中心与政策搜索需要 notification_type / source / read_at 等列。
    CREATE TABLE IF NOT EXISTS 不会升级已存在表，因此在启动时补列。
    """
    try:
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='notifications'")
        if not cur.fetchone():
            return
        cur.execute("PRAGMA table_info(notifications)")
        cols = {row[1] for row in cur.fetchall()}
        if "notification_type" not in cols:
            cur.execute("ALTER TABLE notifications ADD COLUMN notification_type TEXT DEFAULT 'policy'")
        if "source" not in cols:
            cur.execute("ALTER TABLE notifications ADD COLUMN source TEXT DEFAULT 'deepseek'")
        if "is_important" not in cols:
            cur.execute("ALTER TABLE notifications ADD COLUMN is_important INTEGER DEFAULT 0")
        if "read_at" not in cols:
            cur.execute("ALTER TABLE notifications ADD COLUMN read_at TEXT")
        if "notify_type" not in cols:
            cur.execute("ALTER TABLE notifications ADD COLUMN notify_type TEXT")
        if "url" not in cols:
            cur.execute("ALTER TABLE notifications ADD COLUMN url TEXT DEFAULT ''")
        if "related_type" not in cols:
            cur.execute("ALTER TABLE notifications ADD COLUMN related_type TEXT")
        # 垂直领域增强字段
        if "domain" not in cols:
            cur.execute("ALTER TABLE notifications ADD COLUMN domain TEXT DEFAULT 'cross_border'")
        if "data_source" not in cols:
            cur.execute("ALTER TABLE notifications ADD COLUMN data_source TEXT DEFAULT ''")
        if "item_hash" not in cols:
            cur.execute("ALTER TABLE notifications ADD COLUMN item_hash TEXT DEFAULT ''")
        if "summary" not in cols:
            cur.execute("ALTER TABLE notifications ADD COLUMN summary TEXT")
        if "target_audience" not in cols:
            cur.execute("ALTER TABLE notifications ADD COLUMN target_audience TEXT")
        if "policy_type" not in cols:
            cur.execute("ALTER TABLE notifications ADD COLUMN policy_type TEXT DEFAULT '通知'")
        if "key_benefit" not in cols:
            cur.execute("ALTER TABLE notifications ADD COLUMN key_benefit TEXT")
        if "timeliness_check" not in cols:
            cur.execute("ALTER TABLE notifications ADD COLUMN timeliness_check TEXT")
        if "is_fresh" not in cols:
            cur.execute("ALTER TABLE notifications ADD COLUMN is_fresh INTEGER DEFAULT 0")
        conn.commit()
        cur.execute("PRAGMA table_info(notifications)")
        cols_after = {row[1] for row in cur.fetchall()}
        if "notify_type" in cols_after:
            cur.execute(
                """
                UPDATE notifications
                SET notification_type = notify_type
                WHERE notify_type IS NOT NULL AND TRIM(CAST(notify_type AS TEXT)) != ''
                """
            )
            conn.commit()
    except Exception as e:
        logger.warning(f"[SQLite] notifications 列补全失败: {e}")


def init_sqlite_schema() -> bool:
    """初始化 SQLite 表结构（回退用）"""
    try:
        from mysql_db import _get_sqlite_conn
        conn = _get_sqlite_conn()
        # 分离建表和索引语句，先建表后建索引
        all_stmts = _split_sql_statements(SQLITE_SCHEMA)
        table_stmts, index_stmts = [], []
        for s in all_stmts:
            s_upper = s.upper().strip()
            if s_upper.startswith("CREATE INDEX"):
                index_stmts.append(s)
            else:
                table_stmts.append(s)

        for stmt in table_stmts:
            if not stmt.strip():
                continue
            try:
                cursor = conn.cursor()
                cursor.execute(stmt)
                conn.commit()
            except Exception as e:
                if "already exists" not in str(e).lower():
                    logger.warning(f"[SQLite] {stmt[:80]}... -> {e}")

        for stmt in index_stmts:
            try:
                cursor = conn.cursor()
                cursor.execute(stmt)
                conn.commit()
            except Exception as e:
                if "already exists" not in str(e).lower():
                    logger.warning(f"[SQLite-IDX] {stmt[:80]}... -> {e}")

        _ensure_sqlite_notifications_columns(conn)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.commit()
        logger.info("[SQLite] 表结构初始化完成")
        return True
    except Exception as e:
        logger.error(f"[SQLite] 表结构初始化失败: {e}")
        return False


def main():
    import logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    parser = argparse.ArgumentParser(description="MySQL 数据库初始化工具")
    parser.add_argument("--mysql", action="store_true", help="强制使用 MySQL")
    parser.add_argument("--sqlite", action="store_true", help="强制使用 SQLite")
    parser.add_argument("--all", action="store_true", help="执行全部操作")
    args = parser.parse_args()

    if args.mysql or args.all:
        logger.info(">>> 初始化 MySQL 表结构...")
        init_mysql_schema()

    if args.sqlite or args.all:
        logger.info(">>> 初始化 SQLite 回退表结构...")
        init_sqlite_schema()

    if not any(vars(args).values()):
        # 默认：先尝试 MySQL，成功则跳过 SQLite
        logger.info(">>> 尝试 MySQL 表结构...")
        if not init_mysql_schema():
            logger.info(">>> MySQL 失败，尝试 SQLite 回退...")
            init_sqlite_schema()


if __name__ == "__main__":
    main()
