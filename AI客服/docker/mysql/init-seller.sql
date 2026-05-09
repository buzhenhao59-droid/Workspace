CREATE DATABASE IF NOT EXISTS `ruitalk`
    DEFAULT CHARACTER SET utf8mb4
    DEFAULT COLLATE utf8mb4_unicode_ci;

USE `ruitalk`;

-- 默认回复模板
INSERT IGNORE INTO `reply_templates` (`name`, `content`, `category`, `is_default`, `created_by`) VALUES
('感谢支持', '感谢您的好评！您的满意是我们最大的动力。如有任何问题，欢迎随时联系我们。', '感谢', 1, 'system'),
('感谢5星', '非常感谢您的5星好评！期待下次为您服务。祝您生活愉快！', '感谢', 0, 'system'),
('抱歉差评', '非常抱歉给您带来不好的体验。我们非常重视您的反馈，请联系我们的客服，我们会尽快为您解决。', '道歉', 0, 'system');

-- 人工客服设置默认值
INSERT IGNORE INTO `human_settings` (`id`, `quick_phrases`, `timeout_seconds`, `timeout_presets`) VALUES
(1, '[]', 60, '[]');
