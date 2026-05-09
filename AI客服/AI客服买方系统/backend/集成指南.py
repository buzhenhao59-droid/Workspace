# -*- coding: utf-8 -*-
"""
Ruitalk 增强模块集成指南

本文档说明如何在现有项目中集成新增的5个功能模块。

## 一、模块概览

新增模块位于 `AI客服买方系统/backend/` 目录：

1. **语义缓存.py** - 语义缓存层（Semantic Cache）
2. **离线消息推送.py** - 离线消息推送（Notification Service）
3. **AI提示词版本控制.py** - AI提示词版本管理
4. **翻译术语库.py** - 翻译术语库（Glossary）
5. **熔断降级机制.py** - 熔断降级（Circuit Breaker & Fallback）
6. **增强聊天模块.py** - 集成以上所有功能的增强模块

配置文件位于 `ruitalk_config/` 目录：
- `ai_prompts.yaml` - AI提示词配置
- `translation_glossary.yaml` - 翻译术语库配置

## 二、快速集成

### 2.1 导入增强模块

在 main_buyer.py 中添加：

```python
from 增强聊天模块 import (
    enhanced_customer_chat,
    enhanced_translate,
    enhanced_transfer_to_human,
    check_waiting_sessions,
)
```

### 2.2 替换聊天API

找到 customer_chat 函数，替换为使用 enhanced_customer_chat

### 2.3 替换翻译API

找到 translate 函数，替换为使用 enhanced_translate

### 2.4 添加等待监控定时任务

在 FastAPI 的 lifespan 中添加后台任务

## 三、独立使用各模块

详见 docs/集成指南.md

## 四、配置说明

所有配置在 .env 文件中，详细说明见各模块注释

## 五、依赖安装

pip install redis fakeredis pyyaml numpy

## 六、注意事项

1. Redis依赖: 语义缓存和翻译缓存依赖Redis
2. YAML依赖: 提示词和术语库使用YAML存储
3. 异步处理: 部分模块需要异步支持
4. 热更新: 修改配置文件后会自动在TTL后生效
"""
