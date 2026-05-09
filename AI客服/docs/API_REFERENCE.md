# Ruitalk Seller Terminal API Reference

> **Generated**: 2026-03-31 15:01  | **Base URL**: `http://127.0.0.1:8000`  | **Version**: 1.0.0

## Table of Contents

- [Admin](#admin)
- [Agent](#agent)
- [Documentation](#documentation)
- [Message Center](#message-center)
- [Monitoring](#monitoring)
- [Platform](#platform)
- [Seller](#seller)
- [Shop](#shop)
- [System](#system)

---

## Admin

### `GET /api/admin/advanced-stats`

**Summary**: 高级统计数据

---

### `GET /api/admin/after-sales`

**Summary**: 获取售后列表

---

### `POST /api/admin/after-sales`

**Summary**: 创建售后单

---

### `POST /api/admin/after-sales/batch`

**Summary**: 批量处理售后

---

### `GET /api/admin/after-sales/stats`

**Summary**: 售后统计

---

### `GET /api/admin/after-sales/{as_id}`

**Summary**: 获取售后详情

**Path Parameters**:

| Name | Type | Required | Description |
|------|------|---------|-------------|
| `as_id` | string | Yes | 路径参数: as_id |

---

### `PUT /api/admin/after-sales/{as_id}`

**Summary**: 更新售后单

**Path Parameters**:

| Name | Type | Required | Description |
|------|------|---------|-------------|
| `as_id` | string | Yes | 路径参数: as_id |

---

### `POST /api/admin/after-sales/{as_id}/status`

**Summary**: 更新售后状态

**Path Parameters**:

| Name | Type | Required | Description |
|------|------|---------|-------------|
| `as_id` | string | Yes | 路径参数: as_id |

---

### `GET /api/admin/audit-logs`

**Summary**: 获取审计日志

---

### `GET /api/admin/auto-reply-rules`

**Summary**: 获取自动回复规则

---

### `POST /api/admin/auto-reply-rules`

**Summary**: 创建自动回复规则

---

### `DELETE /api/admin/auto-reply-rules/{rule_id}`

**Summary**: 删除自动回复规则

**Path Parameters**:

| Name | Type | Required | Description |
|------|------|---------|-------------|
| `rule_id` | string | Yes | 路径参数: rule_id |

---

### `PUT /api/admin/auto-reply-rules/{rule_id}`

**Summary**: 更新自动回复规则

**Path Parameters**:

| Name | Type | Required | Description |
|------|------|---------|-------------|
| `rule_id` | string | Yes | 路径参数: rule_id |

---

### `POST /api/admin/change-password`

**Summary**: 修改管理员密码

---

### `GET /api/admin/conversation/{session_id}`

**Summary**: 获取单个会话详情

**Path Parameters**:

| Name | Type | Required | Description |
|------|------|---------|-------------|
| `session_id` | string | Yes | 路径参数: session_id |

---

### `POST /api/admin/conversation/{session_id}/rate`

**Summary**: 评价会话

**Path Parameters**:

| Name | Type | Required | Description |
|------|------|---------|-------------|
| `session_id` | string | Yes | 路径参数: session_id |

---

### `GET /api/admin/conversations`

**Summary**: 获取会话列表（分页）

---

### `GET /api/admin/customer/{customer_id}`

**Summary**: 管理后台查询客户（Neo4j失效时回退SQLite）

**Path Parameters**:

| Name | Type | Required | Description |
|------|------|---------|-------------|
| `customer_id` | string | Yes | 路径参数: customer_id |

---

### `POST /api/admin/login`

**Summary**: 管理员登录 — 签发 JWT

---

### `POST /api/admin/logout`

**Summary**: 管理员登出

---

### `GET /api/admin/me`

**Summary**: 获取当前登录管理员信息

---

### `GET /api/admin/notifications`

**Summary**: 获取通知列表

---

### `GET /api/admin/notifications/unread-count`

**Summary**: 获取未读通知数量

---

### `POST /api/admin/notifications/{notify_id}/read`

**Summary**: 标记通知已读

**Path Parameters**:

| Name | Type | Required | Description |
|------|------|---------|-------------|
| `notify_id` | string | Yes | 路径参数: notify_id |

---

### `GET /api/admin/orders`

**Summary**: 获取订单列表

---

### `GET /api/admin/quick-replies`

**Summary**: 获取快捷回复列表

---

### `POST /api/admin/quick-replies`

**Summary**: 创建快捷回复

---

### `DELETE /api/admin/quick-replies/{category}/{reply_id}`

**Summary**: 删除快捷回复

**Path Parameters**:

| Name | Type | Required | Description |
|------|------|---------|-------------|
| `category` | string | Yes | 路径参数: category |
| `reply_id` | string | Yes | 路径参数: reply_id |

---

### `POST /api/admin/refresh`

**Summary**: 用 refresh token 刷新 access token

---

### `GET /api/admin/reply-templates`

**Summary**: 获取回复模板

---

### `POST /api/admin/reply-templates`

**Summary**: 创建回复模板

---

### `DELETE /api/admin/reply-templates/{template_id}`

**Summary**: 删除回复模板

**Path Parameters**:

| Name | Type | Required | Description |
|------|------|---------|-------------|
| `template_id` | string | Yes | 路径参数: template_id |

---

### `PUT /api/admin/reply-templates/{template_id}`

**Summary**: 更新回复模板

**Path Parameters**:

| Name | Type | Required | Description |
|------|------|---------|-------------|
| `template_id` | string | Yes | 路径参数: template_id |

---

### `GET /api/admin/reviews`

**Summary**: 获取评价列表

---

### `POST /api/admin/reviews/auto-reply`

**Summary**: 自动回复评价

---

### `GET /api/admin/reviews/export`

**Summary**: 导出评价

---

### `POST /api/admin/reviews/generate-sample`

**Summary**: 生成示例评价

---

### `POST /api/admin/reviews/import`

**Summary**: 导入评价数据

---

### `POST /api/admin/reviews/quick-reply`

**Summary**: 快捷回复评价

---

### `POST /api/admin/reviews/reply`

**Summary**: 回复评价

---

### `GET /api/admin/reviews/stats`

**Summary**: 评价统计

---

### `GET /api/admin/sessions`

**Summary**: 获取所有会话列表

---

### `GET /api/admin/stats`

**Summary**: 管理后台统计数据

---

### `GET /api/admin/system-settings`

**Summary**: 获取系统设置

---

### `POST /api/admin/system-settings`

**Summary**: 更新系统设置

---

### `GET /api/admin/users`

**Summary**: 列出所有管理员用户

---

### `POST /api/admin/users`

**Summary**: 创建管理员用户或坐席

---

## Agent

### `POST /api/agent/assign`

**Summary**: 分配会话给坐席

---

### `GET /api/agent/sessions/{agent_id}`

**Summary**: 获取坐席的会话列表

**Path Parameters**:

| Name | Type | Required | Description |
|------|------|---------|-------------|
| `agent_id` | string | Yes | 路径参数: agent_id |

---

### `GET /api/agent/status`

**Summary**: 坐席状态

---

## Documentation

### `GET /docs`

**Summary**: GET /docs

---

### `GET /docs/oauth2-redirect`

**Summary**: GET /docs/oauth2-redirect

---

### `GET /openapi.json`

**Summary**: GET /openapi.json

---

### `GET /redoc`

**Summary**: GET /redoc

---

## Message Center

### `GET /api/message-center/conversations`

**Summary**: 获取会话列表（按平台分组，显示最近72小时内的人工会话）

---

### `POST /api/message-center/conversations/sync`

**Summary**: 同步会话列表（从sessions表同步到conversation_history表）

---

### `GET /api/message-center/health`

**Summary**: 消息中心健康检查

---

### `POST /api/message-center/init`

**Summary**: 初始化消息中心数据库表

---

### `GET /api/message-center/notifications`

**Summary**: 获取消息通知列表

---

### `POST /api/message-center/notifications/manual-search`

**Summary**: 手动触发政策搜索

---

### `POST /api/message-center/notifications/mark-all-read`

**Summary**: 标记所有通知为已读

---

### `GET /api/message-center/notifications/search-status`

**Summary**: 获取政策搜索状态

---

### `GET /api/message-center/notifications/unread-count`

**Summary**: 获取未读通知数量

---

### `POST /api/message-center/notifications/{notification_id}/read`

**Summary**: 标记通知为已读

**Path Parameters**:

| Name | Type | Required | Description |
|------|------|---------|-------------|
| `notification_id` | string | Yes | 路径参数: notification_id |

---

### `GET /api/message-center/platforms`

**Summary**: 获取所有平台及其会话统计

---

### `GET /api/message-center/quick-replies`

**Summary**: 获取快捷回复列表

---

### `POST /api/message-center/quick-replies`

**Summary**: 创建快捷回复

---

### `GET /api/message-center/quick-replies/categories`

**Summary**: 获取快捷回复分类列表

---

### `DELETE /api/message-center/quick-replies/{reply_id}`

**Summary**: 删除快捷回复

**Path Parameters**:

| Name | Type | Required | Description |
|------|------|---------|-------------|
| `reply_id` | string | Yes | 路径参数: reply_id |

---

### `PUT /api/message-center/quick-replies/{reply_id}`

**Summary**: 更新快捷回复

**Path Parameters**:

| Name | Type | Required | Description |
|------|------|---------|-------------|
| `reply_id` | string | Yes | 路径参数: reply_id |

---

### `GET /api/message-center/reminders`

**Summary**: 获取提醒列表

---

### `POST /api/message-center/reminders`

**Summary**: 创建新提醒

---

### `GET /api/message-center/reminders/due`

**Summary**: 获取到期提醒（需要触发的）

---

### `DELETE /api/message-center/reminders/{reminder_id}`

**Summary**: 删除提醒

**Path Parameters**:

| Name | Type | Required | Description |
|------|------|---------|-------------|
| `reminder_id` | string | Yes | 路径参数: reminder_id |

---

### `PUT /api/message-center/reminders/{reminder_id}`

**Summary**: 更新提醒

**Path Parameters**:

| Name | Type | Required | Description |
|------|------|---------|-------------|
| `reminder_id` | string | Yes | 路径参数: reminder_id |

---

### `POST /api/message-center/reminders/{reminder_id}/reset`

**Summary**: 重置提醒（用于重复提醒）

**Path Parameters**:

| Name | Type | Required | Description |
|------|------|---------|-------------|
| `reminder_id` | string | Yes | 路径参数: reminder_id |

---

### `POST /api/message-center/reminders/{reminder_id}/trigger`

**Summary**: 触发提醒（标记为已触发）

**Path Parameters**:

| Name | Type | Required | Description |
|------|------|---------|-------------|
| `reminder_id` | string | Yes | 路径参数: reminder_id |

---

## Monitoring

### `GET /metrics`

**Summary**: Prometheus 指标端点

---

## Platform

### `GET /api/v1/dashboard/stats`

**Summary**: 获取仪表盘统计数据

---

### `GET /api/v1/logistics/{tracking_number}`

**Summary**: 查询物流轨迹

**Path Parameters**:

| Name | Type | Required | Description |
|------|------|---------|-------------|
| `tracking_number` | string | Yes | 路径参数: tracking_number |

---

### `GET /api/v1/orders`

**Summary**: 获取订单列表（优先读本地同步缓存）

---

### `GET /api/v1/orders/{order_id}`

**Summary**: 获取订单详情

**Path Parameters**:

| Name | Type | Required | Description |
|------|------|---------|-------------|
| `order_id` | string | Yes | 路径参数: order_id |

---

### `GET /api/v1/platforms`

**Summary**: 获取平台配置状态

---

### `GET /api/v1/returns`

**Summary**: 获取退换货列表

---

### `POST /api/v1/returns`

**Summary**: 创建售后单（写入本地库 + 调用外部API）

---

### `GET /api/v1/reviews`

**Summary**: 获取评价列表

---

### `POST /api/v1/reviews/reply`

**Summary**: 回复评价

---

### `POST /api/v1/sync`

**Summary**: 手动触发平台同步

---

### `GET /api/v1/sync/status`

**Summary**: 获取同步状态

---

## Seller

### `POST /api/seller/change-password`

**Summary**: 卖家修改密码

---

### `POST /api/seller/clear-messages`

**Summary**: 清空会话消息

---

### `POST /api/seller/close-session`

**Summary**: 卖家关闭会话

---

### `GET /api/seller/customers`

**Summary**: 卖家获取分配的客户列表

---

### `GET /api/seller/human-settings`

**Summary**: 获取人工客服设置

---

### `PUT /api/seller/human-settings`

**Summary**: 更新人工客服设置

---

### `POST /api/seller/login`

**Summary**: 卖家登录

---

### `POST /api/seller/logout`

**Summary**: 卖家登出

---

### `GET /api/seller/messages/{session_id}`

**Summary**: 卖家获取会话消息

**Path Parameters**:

| Name | Type | Required | Description |
|------|------|---------|-------------|
| `session_id` | string | Yes | 路径参数: session_id |

---

### `POST /api/seller/send`

**Summary**: 卖家发送消息

---

### `POST /api/seller/transfer-to-ai`

**Summary**: 卖家将会话转回 AI

---

### `POST /api/seller/upload`

**Summary**: 卖家上传文件

---

## Shop

### `GET /api/v1/shop/calculate-price/{sku_id}`

**Summary**: 计算价格

**Path Parameters**:

| Name | Type | Required | Description |
|------|------|---------|-------------|
| `sku_id` | string | Yes | 路径参数: sku_id |

---

### `GET /api/v1/shop/categories`

**Summary**: 获取分类列表

---

### `POST /api/v1/shop/categories`

**Summary**: 创建分类

---

### `POST /api/v1/shop/collect`

**Summary**: 采集商品

---

### `POST /api/v1/shop/init-database`

**Summary**: 初始化数据库表结构

---

### `GET /api/v1/shop/inventory`

**Summary**: 获取库存

---

### `PUT /api/v1/shop/inventory`

**Summary**: 更新库存

---

### `POST /api/v1/shop/inventory/{shop_id}/sync`

**Summary**: 同步店铺库存

**Path Parameters**:

| Name | Type | Required | Description |
|------|------|---------|-------------|
| `shop_id` | string | Yes | 路径参数: shop_id |

---

### `GET /api/v1/shop/platforms`

**Summary**: 获取支持的平台列表

---

### `GET /api/v1/shop/pricing-rules`

**Summary**: 获取定价规则列表

---

### `POST /api/v1/shop/pricing-rules`

**Summary**: 创建定价规则

---

### `DELETE /api/v1/shop/pricing-rules/{rule_id}`

**Summary**: 删除定价规则

**Path Parameters**:

| Name | Type | Required | Description |
|------|------|---------|-------------|
| `rule_id` | string | Yes | 路径参数: rule_id |

---

### `GET /api/v1/shop/products`

**Summary**: 获取商品列表

---

### `POST /api/v1/shop/products`

**Summary**: 创建商品

---

### `DELETE /api/v1/shop/products/{product_id}`

**Summary**: 删除商品

**Path Parameters**:

| Name | Type | Required | Description |
|------|------|---------|-------------|
| `product_id` | string | Yes | 路径参数: product_id |

---

### `GET /api/v1/shop/products/{product_id}`

**Summary**: 获取单个商品（含SKU）

**Path Parameters**:

| Name | Type | Required | Description |
|------|------|---------|-------------|
| `product_id` | string | Yes | 路径参数: product_id |

---

### `PUT /api/v1/shop/products/{product_id}`

**Summary**: 更新商品

**Path Parameters**:

| Name | Type | Required | Description |
|------|------|---------|-------------|
| `product_id` | string | Yes | 路径参数: product_id |

---

### `POST /api/v1/shop/publish`

**Summary**: 批量刊登商品

---

### `GET /api/v1/shop/shop-products`

**Summary**: 获取店铺商品列表

---

### `GET /api/v1/shop/shops`

**Summary**: 获取店铺列表

---

### `POST /api/v1/shop/shops`

**Summary**: 创建店铺

---

### `DELETE /api/v1/shop/shops/{shop_id}`

**Summary**: 删除店铺

**Path Parameters**:

| Name | Type | Required | Description |
|------|------|---------|-------------|
| `shop_id` | string | Yes | 路径参数: shop_id |

---

### `GET /api/v1/shop/shops/{shop_id}`

**Summary**: 获取单个店铺

**Path Parameters**:

| Name | Type | Required | Description |
|------|------|---------|-------------|
| `shop_id` | string | Yes | 路径参数: shop_id |

---

### `PUT /api/v1/shop/shops/{shop_id}`

**Summary**: 更新店铺

**Path Parameters**:

| Name | Type | Required | Description |
|------|------|---------|-------------|
| `shop_id` | string | Yes | 路径参数: shop_id |

---

### `POST /api/v1/shop/shops/{shop_id}/test`

**Summary**: 测试店铺连接

**Path Parameters**:

| Name | Type | Required | Description |
|------|------|---------|-------------|
| `shop_id` | string | Yes | 路径参数: shop_id |

---

### `POST /api/v1/shop/skus`

**Summary**: 创建SKU

---

### `DELETE /api/v1/shop/skus/{sku_id}`

**Summary**: 删除SKU

**Path Parameters**:

| Name | Type | Required | Description |
|------|------|---------|-------------|
| `sku_id` | string | Yes | 路径参数: sku_id |

---

### `PUT /api/v1/shop/skus/{sku_id}`

**Summary**: 更新SKU

**Path Parameters**:

| Name | Type | Required | Description |
|------|------|---------|-------------|
| `sku_id` | string | Yes | 路径参数: sku_id |

---

### `GET /api/v1/shop/stats`

**Summary**: 获取仪表盘统计数据

---

## System

### `GET /`

**Summary**: 首页：卖方运营管理门户（frontend/home.html）；文件缺失时回退骨架页。

---

### `GET /admin/after-sales.html`

**Summary**: 售后管理

---

### `GET /admin/agent_console.html`

**Summary**: 坐席控制台

---

### `GET /admin/audit-logs.html`

**Summary**: 审计日志

---

### `GET /admin/console.html`

**Summary**: 管理控制台

---

### `GET /admin/customer-query`

**Summary**: 客户查询

---

### `GET /admin/dashboard`

**Summary**: 管理员仪表盘

---

### `GET /admin/dashboard-overview`

**Summary**: 数据看板 / 工具集成入口（与「客户档案检索」/dashboard 区分）

---

### `GET /admin/dashboard-overview.html`

**Summary**: 数据看板 / 工具集成入口（与「客户档案检索」/dashboard 区分）

---

### `GET /admin/dashboard.html`

**Summary**: 管理员仪表盘

---

### `GET /admin/evaluation.html`

**Summary**: 评价管理

---

### `GET /admin/login`

**Summary**: 管理员登录页

---

### `GET /admin/login.html`

**Summary**: 管理员登录页

---

### `GET /admin/logout`

**Summary**: 登出

---

### `GET /admin/message-center`

**Summary**: 消息中心

---

### `GET /admin/message-center.html`

**Summary**: 消息中心

---

### `GET /admin/orders`

**Summary**: 订单管理

---

### `GET /admin/orders.html`

**Summary**: 订单管理

---

### `GET /admin/pre-sale-notes.html`

**Summary**: 售前备注

---

### `GET /admin/shop-manager.html`

**Summary**: 店铺管理

---

### `GET /agent-console`

**Summary**: 坐席控制台

---

### `GET /api/circuit-breakers`

**Summary**: 获取所有熔断器状态

---

### `POST /api/customer/start`

**Summary**: 门户首页「开始咨询」→ 转发到金牌客服 Flask（5000），保持 8000 同域调用。

---

### `POST /api/internal/buyer-back-to-ai`

**Summary**: 买方回调：客户选择返回 AI（HMAC 保护）

---

### `POST /api/internal/buyer-message`

**Summary**: 买方回调：买方有新消息（HMAC 保护）

---

### `POST /api/internal/buyer-transfer`

**Summary**: 买方回调：客户发起转人工请求（HMAC 保护）

---

### `GET /api/metrics/business`

**Summary**: 业务指标详情（JSON 格式）

---

### `GET /api/metrics/summary`

**Summary**: 指标摘要（JSON 格式，供前端展示）

---

### `GET /api/port-check`

**Summary**: 检查所有服务端口状态

---

### `GET /api/pre-sale-notes`

**Summary**: 获取售前备注列表

---

### `POST /api/pre-sale-notes`

**Summary**: 创建售前备注

---

### `GET /api/pre-sale-notes/stats/summary`

**Summary**: 售前备注统计摘要

---

### `DELETE /api/pre-sale-notes/{note_id}`

**Summary**: 删除售前备注

**Path Parameters**:

| Name | Type | Required | Description |
|------|------|---------|-------------|
| `note_id` | string | Yes | 路径参数: note_id |

---

### `GET /api/pre-sale-notes/{note_id}`

**Summary**: 获取售前备注详情

**Path Parameters**:

| Name | Type | Required | Description |
|------|------|---------|-------------|
| `note_id` | string | Yes | 路径参数: note_id |

---

### `PUT /api/pre-sale-notes/{note_id}`

**Summary**: 更新售前备注

**Path Parameters**:

| Name | Type | Required | Description |
|------|------|---------|-------------|
| `note_id` | string | Yes | 路径参数: note_id |

---

### `GET /api/realtime/stats`

**Summary**: 实时统计

---

### `GET /api/redis-status`

**Summary**: 获取 Redis 连接状态

---

### `GET /api/services-status`

**Summary**: 获取所有服务状态（综合信息）

---

### `GET /api/status`

**Summary**: API 状态检查（含 Neo4j、GraphRAG），供前端状态栏显示

---

### `GET /api/system-check`

**Summary**: 完整系统自检（全面检查所有依赖项）

**Description**: 检查端口、数据库、AI服务、安全配置等

---

### `GET /api/system-check/buyer`

**Summary**: 检查买方系统状态

---

### `GET /api/system-check/quick`

**Summary**: 快速健康检查（仅核心服务），用于前端状态指示器

---

### `GET /api/system-check/report`

**Summary**: 生成专业 HTML 自检报告单页面

**Description**: 页面内通过 JavaScript 异步加载检查数据并渲染

---

### `GET /api/system-check/report/download`

**Summary**: 下载 JSON 格式的完整系统检查报告

**Description**: 响应 Content-Disposition 头，支持直接下载

---

### `POST /api/system-check/trigger`

**Summary**: 手动触发系统自检（POST）

---

### `GET /chat`

**Summary**: 聊天页面

---

### `GET /console`

**Summary**: 客服工作台

---

### `GET /console/{page}`

**Summary**: 客服子页面

**Path Parameters**:

| Name | Type | Required | Description |
|------|------|---------|-------------|
| `page` | string | Yes | 路径参数: page |

---

### `GET /customer`

**Summary**: 客户聊天页：直接返回买方系统的 chat.html（无需 Flask 代理）。

---

### `GET /entry`

**Summary**: 入口页面

---

### `GET /health`

**Summary**: 基础健康检查

---

### `GET /home`

**Summary**: 运营控制台首页

---

### `GET /live`

**Summary**: 存活探针（K8s liveness）

---

### `GET /ready`

**Summary**: 就绪检查

---

## Quick Reference

| Method | Path | Tag | Summary |
|--------|------|-----|---------|
| GET | `/api/admin/advanced-stats` | Admin | 高级统计数据 |
| GET | `/api/admin/after-sales` | Admin | 获取售后列表 |
| POST | `/api/admin/after-sales` | Admin | 创建售后单 |
| POST | `/api/admin/after-sales/batch` | Admin | 批量处理售后 |
| GET | `/api/admin/after-sales/stats` | Admin | 售后统计 |
| GET | `/api/admin/after-sales/{as_id}` | Admin | 获取售后详情 |
| PUT | `/api/admin/after-sales/{as_id}` | Admin | 更新售后单 |
| POST | `/api/admin/after-sales/{as_id}/status` | Admin | 更新售后状态 |
| GET | `/api/admin/audit-logs` | Admin | 获取审计日志 |
| GET | `/api/admin/auto-reply-rules` | Admin | 获取自动回复规则 |
| POST | `/api/admin/auto-reply-rules` | Admin | 创建自动回复规则 |
| PUT | `/api/admin/auto-reply-rules/{rule_id}` | Admin | 更新自动回复规则 |
| DELETE | `/api/admin/auto-reply-rules/{rule_id}` | Admin | 删除自动回复规则 |
| POST | `/api/admin/change-password` | Admin | 修改管理员密码 |
| GET | `/api/admin/conversation/{session_id}` | Admin | 获取单个会话详情 |
| POST | `/api/admin/conversation/{session_id}/rate` | Admin | 评价会话 |
| GET | `/api/admin/conversations` | Admin | 获取会话列表（分页） |
| GET | `/api/admin/customer/{customer_id}` | Admin | 管理后台查询客户（Neo4j失效时回退SQLite） |
| POST | `/api/admin/login` | Admin | 管理员登录 — 签发 JWT |
| POST | `/api/admin/logout` | Admin | 管理员登出 |
| GET | `/api/admin/me` | Admin | 获取当前登录管理员信息 |
| GET | `/api/admin/notifications` | Admin | 获取通知列表 |
| GET | `/api/admin/notifications/unread-count` | Admin | 获取未读通知数量 |
| POST | `/api/admin/notifications/{notify_id}/read` | Admin | 标记通知已读 |
| GET | `/api/admin/orders` | Admin | 获取订单列表 |
| GET | `/api/admin/quick-replies` | Admin | 获取快捷回复列表 |
| POST | `/api/admin/quick-replies` | Admin | 创建快捷回复 |
| DELETE | `/api/admin/quick-replies/{category}/{reply_id}` | Admin | 删除快捷回复 |
| POST | `/api/admin/refresh` | Admin | 用 refresh token 刷新 access token |
| GET | `/api/admin/reply-templates` | Admin | 获取回复模板 |
| POST | `/api/admin/reply-templates` | Admin | 创建回复模板 |
| PUT | `/api/admin/reply-templates/{template_id}` | Admin | 更新回复模板 |
| DELETE | `/api/admin/reply-templates/{template_id}` | Admin | 删除回复模板 |
| GET | `/api/admin/reviews` | Admin | 获取评价列表 |
| POST | `/api/admin/reviews/auto-reply` | Admin | 自动回复评价 |
| GET | `/api/admin/reviews/export` | Admin | 导出评价 |
| POST | `/api/admin/reviews/generate-sample` | Admin | 生成示例评价 |
| POST | `/api/admin/reviews/import` | Admin | 导入评价数据 |
| POST | `/api/admin/reviews/quick-reply` | Admin | 快捷回复评价 |
| POST | `/api/admin/reviews/reply` | Admin | 回复评价 |
| GET | `/api/admin/reviews/stats` | Admin | 评价统计 |
| GET | `/api/admin/sessions` | Admin | 获取所有会话列表 |
| GET | `/api/admin/stats` | Admin | 管理后台统计数据 |
| GET | `/api/admin/system-settings` | Admin | 获取系统设置 |
| POST | `/api/admin/system-settings` | Admin | 更新系统设置 |
| POST | `/api/admin/users` | Admin | 创建管理员用户或坐席 |
| GET | `/api/admin/users` | Admin | 列出所有管理员用户 |
| POST | `/api/agent/assign` | Agent | 分配会话给坐席 |
| GET | `/api/agent/sessions/{agent_id}` | Agent | 获取坐席的会话列表 |
| GET | `/api/agent/status` | Agent | 坐席状态 |
| GET | `/docs` | Documentation | GET /docs |
| GET | `/docs/oauth2-redirect` | Documentation | GET /docs/oauth2-redirect |
| GET | `/openapi.json` | Documentation | GET /openapi.json |
| GET | `/redoc` | Documentation | GET /redoc |
| GET | `/api/message-center/conversations` | Message Center | 获取会话列表（按平台分组，显示最近72小时内的人工会话） |
| POST | `/api/message-center/conversations/sync` | Message Center | 同步会话列表（从sessions表同步到conversation_history表） |
| GET | `/api/message-center/health` | Message Center | 消息中心健康检查 |
| POST | `/api/message-center/init` | Message Center | 初始化消息中心数据库表 |
| GET | `/api/message-center/notifications` | Message Center | 获取消息通知列表 |
| POST | `/api/message-center/notifications/manual-search` | Message Center | 手动触发政策搜索 |
| POST | `/api/message-center/notifications/mark-all-read` | Message Center | 标记所有通知为已读 |
| GET | `/api/message-center/notifications/search-status` | Message Center | 获取政策搜索状态 |
| GET | `/api/message-center/notifications/unread-count` | Message Center | 获取未读通知数量 |
| POST | `/api/message-center/notifications/{notification_id}/read` | Message Center | 标记通知为已读 |
| GET | `/api/message-center/platforms` | Message Center | 获取所有平台及其会话统计 |
| GET | `/api/message-center/quick-replies` | Message Center | 获取快捷回复列表 |
| POST | `/api/message-center/quick-replies` | Message Center | 创建快捷回复 |
| GET | `/api/message-center/quick-replies/categories` | Message Center | 获取快捷回复分类列表 |
| PUT | `/api/message-center/quick-replies/{reply_id}` | Message Center | 更新快捷回复 |
| DELETE | `/api/message-center/quick-replies/{reply_id}` | Message Center | 删除快捷回复 |
| GET | `/api/message-center/reminders` | Message Center | 获取提醒列表 |
| POST | `/api/message-center/reminders` | Message Center | 创建新提醒 |
| GET | `/api/message-center/reminders/due` | Message Center | 获取到期提醒（需要触发的） |
| PUT | `/api/message-center/reminders/{reminder_id}` | Message Center | 更新提醒 |
| DELETE | `/api/message-center/reminders/{reminder_id}` | Message Center | 删除提醒 |
| POST | `/api/message-center/reminders/{reminder_id}/reset` | Message Center | 重置提醒（用于重复提醒） |
| POST | `/api/message-center/reminders/{reminder_id}/trigger` | Message Center | 触发提醒（标记为已触发） |
| GET | `/metrics` | Monitoring | Prometheus 指标端点 |
| GET | `/api/v1/dashboard/stats` | Platform | 获取仪表盘统计数据 |
| GET | `/api/v1/logistics/{tracking_number}` | Platform | 查询物流轨迹 |
| GET | `/api/v1/orders` | Platform | 获取订单列表（优先读本地同步缓存） |
| GET | `/api/v1/orders/{order_id}` | Platform | 获取订单详情 |
| GET | `/api/v1/platforms` | Platform | 获取平台配置状态 |
| GET | `/api/v1/returns` | Platform | 获取退换货列表 |
| POST | `/api/v1/returns` | Platform | 创建售后单（写入本地库 + 调用外部API） |
| GET | `/api/v1/reviews` | Platform | 获取评价列表 |
| POST | `/api/v1/reviews/reply` | Platform | 回复评价 |
| POST | `/api/v1/sync` | Platform | 手动触发平台同步 |
| GET | `/api/v1/sync/status` | Platform | 获取同步状态 |
| POST | `/api/seller/change-password` | Seller | 卖家修改密码 |
| POST | `/api/seller/clear-messages` | Seller | 清空会话消息 |
| POST | `/api/seller/close-session` | Seller | 卖家关闭会话 |
| GET | `/api/seller/customers` | Seller | 卖家获取分配的客户列表 |
| GET | `/api/seller/human-settings` | Seller | 获取人工客服设置 |
| PUT | `/api/seller/human-settings` | Seller | 更新人工客服设置 |
| POST | `/api/seller/login` | Seller | 卖家登录 |
| POST | `/api/seller/logout` | Seller | 卖家登出 |
| GET | `/api/seller/messages/{session_id}` | Seller | 卖家获取会话消息 |
| POST | `/api/seller/send` | Seller | 卖家发送消息 |
| POST | `/api/seller/transfer-to-ai` | Seller | 卖家将会话转回 AI |
| POST | `/api/seller/upload` | Seller | 卖家上传文件 |
| GET | `/api/v1/shop/calculate-price/{sku_id}` | Shop | 计算价格 |
| GET | `/api/v1/shop/categories` | Shop | 获取分类列表 |
| POST | `/api/v1/shop/categories` | Shop | 创建分类 |
| POST | `/api/v1/shop/collect` | Shop | 采集商品 |
| POST | `/api/v1/shop/init-database` | Shop | 初始化数据库表结构 |
| GET | `/api/v1/shop/inventory` | Shop | 获取库存 |
| PUT | `/api/v1/shop/inventory` | Shop | 更新库存 |
| POST | `/api/v1/shop/inventory/{shop_id}/sync` | Shop | 同步店铺库存 |
| GET | `/api/v1/shop/platforms` | Shop | 获取支持的平台列表 |
| POST | `/api/v1/shop/pricing-rules` | Shop | 创建定价规则 |
| GET | `/api/v1/shop/pricing-rules` | Shop | 获取定价规则列表 |
| DELETE | `/api/v1/shop/pricing-rules/{rule_id}` | Shop | 删除定价规则 |
| POST | `/api/v1/shop/products` | Shop | 创建商品 |
| GET | `/api/v1/shop/products` | Shop | 获取商品列表 |
| GET | `/api/v1/shop/products/{product_id}` | Shop | 获取单个商品（含SKU） |
| PUT | `/api/v1/shop/products/{product_id}` | Shop | 更新商品 |
| DELETE | `/api/v1/shop/products/{product_id}` | Shop | 删除商品 |
| POST | `/api/v1/shop/publish` | Shop | 批量刊登商品 |
| GET | `/api/v1/shop/shop-products` | Shop | 获取店铺商品列表 |
| POST | `/api/v1/shop/shops` | Shop | 创建店铺 |
| GET | `/api/v1/shop/shops` | Shop | 获取店铺列表 |
| GET | `/api/v1/shop/shops/{shop_id}` | Shop | 获取单个店铺 |
| PUT | `/api/v1/shop/shops/{shop_id}` | Shop | 更新店铺 |
| DELETE | `/api/v1/shop/shops/{shop_id}` | Shop | 删除店铺 |
| POST | `/api/v1/shop/shops/{shop_id}/test` | Shop | 测试店铺连接 |
| POST | `/api/v1/shop/skus` | Shop | 创建SKU |
| PUT | `/api/v1/shop/skus/{sku_id}` | Shop | 更新SKU |
| DELETE | `/api/v1/shop/skus/{sku_id}` | Shop | 删除SKU |
| GET | `/api/v1/shop/stats` | Shop | 获取仪表盘统计数据 |
| GET | `/` | System | 首页：卖方运营管理门户（frontend/home.html）；文件缺失时回退骨架页。 |
| GET | `/admin/after-sales.html` | System | 售后管理 |
| GET | `/admin/agent_console.html` | System | 坐席控制台 |
| GET | `/admin/audit-logs.html` | System | 审计日志 |
| GET | `/admin/console.html` | System | 管理控制台 |
| GET | `/admin/customer-query` | System | 客户查询 |
| GET | `/admin/dashboard` | System | 管理员仪表盘 |
| GET | `/admin/dashboard-overview` | System | 数据看板 / 工具集成入口（与「客户档案检索」/dashboard 区分） |
| GET | `/admin/dashboard-overview.html` | System | 数据看板 / 工具集成入口（与「客户档案检索」/dashboard 区分） |
| GET | `/admin/dashboard.html` | System | 管理员仪表盘 |
| GET | `/admin/evaluation.html` | System | 评价管理 |
| GET | `/admin/login` | System | 管理员登录页 |
| GET | `/admin/login.html` | System | 管理员登录页 |
| GET | `/admin/logout` | System | 登出 |
| GET | `/admin/message-center` | System | 消息中心 |
| GET | `/admin/message-center.html` | System | 消息中心 |
| GET | `/admin/orders` | System | 订单管理 |
| GET | `/admin/orders.html` | System | 订单管理 |
| GET | `/admin/pre-sale-notes.html` | System | 售前备注 |
| GET | `/admin/shop-manager.html` | System | 店铺管理 |
| GET | `/agent-console` | System | 坐席控制台 |
| GET | `/api/circuit-breakers` | System | 获取所有熔断器状态 |
| POST | `/api/customer/start` | System | 门户首页「开始咨询」→ 转发到金牌客服 Flask（5000），保持 8000 同域调用。 |
| POST | `/api/internal/buyer-back-to-ai` | System | 买方回调：客户选择返回 AI（HMAC 保护） |
| POST | `/api/internal/buyer-message` | System | 买方回调：买方有新消息（HMAC 保护） |
| POST | `/api/internal/buyer-transfer` | System | 买方回调：客户发起转人工请求（HMAC 保护） |
| GET | `/api/metrics/business` | System | 业务指标详情（JSON 格式） |
| GET | `/api/metrics/summary` | System | 指标摘要（JSON 格式，供前端展示） |
| GET | `/api/port-check` | System | 检查所有服务端口状态 |
| GET | `/api/pre-sale-notes` | System | 获取售前备注列表 |
| POST | `/api/pre-sale-notes` | System | 创建售前备注 |
| GET | `/api/pre-sale-notes/stats/summary` | System | 售前备注统计摘要 |
| GET | `/api/pre-sale-notes/{note_id}` | System | 获取售前备注详情 |
| PUT | `/api/pre-sale-notes/{note_id}` | System | 更新售前备注 |
| DELETE | `/api/pre-sale-notes/{note_id}` | System | 删除售前备注 |
| GET | `/api/realtime/stats` | System | 实时统计 |
| GET | `/api/redis-status` | System | 获取 Redis 连接状态 |
| GET | `/api/services-status` | System | 获取所有服务状态（综合信息） |
| GET | `/api/status` | System | API 状态检查（含 Neo4j、GraphRAG），供前端状态栏显示 |
| GET | `/api/system-check` | System | 完整系统自检（全面检查所有依赖项） |
| GET | `/api/system-check/buyer` | System | 检查买方系统状态 |
| GET | `/api/system-check/quick` | System | 快速健康检查（仅核心服务），用于前端状态指示器 |
| GET | `/api/system-check/report` | System | 生成专业 HTML 自检报告单页面 |
| GET | `/api/system-check/report/download` | System | 下载 JSON 格式的完整系统检查报告 |
| POST | `/api/system-check/trigger` | System | 手动触发系统自检（POST） |
| GET | `/chat` | System | 聊天页面 |
| GET | `/console` | System | 客服工作台 |
| GET | `/console/{page}` | System | 客服子页面 |
| GET | `/customer` | System | 客户聊天页：直接返回买方系统的 chat.html（无需 Flask 代理）。 |
| GET | `/entry` | System | 入口页面 |
| GET | `/health` | System | 基础健康检查 |
| GET | `/home` | System | 运营控制台首页 |
| GET | `/live` | System | 存活探针（K8s liveness） |
| GET | `/ready` | System | 就绪检查 |

## Authentication

Most endpoints require a Bearer token in the `Authorization` header:

```
Authorization: Bearer <your_access_token>
```

### Endpoints that do NOT require authentication:

- `GET /`
- `GET /admin/after-sales.html`
- `GET /admin/agent_console.html`
- `GET /admin/audit-logs.html`
- `GET /admin/console.html`
- `GET /admin/customer-query`
- `GET /admin/dashboard`
- `GET /admin/dashboard-overview`
- `GET /admin/dashboard-overview.html`
- `GET /admin/dashboard.html`
- `GET /admin/evaluation.html`
- `GET /admin/login`
- `GET /admin/login.html`
- `GET /admin/logout`
- `GET /admin/message-center`
- `GET /admin/message-center.html`
- `GET /admin/orders`
- `GET /admin/orders.html`
- `GET /admin/pre-sale-notes.html`
- `GET /admin/shop-manager.html`
- `GET /agent-console`
- `GET /api/admin/advanced-stats`
- `GET /api/admin/after-sales`
- `GET /api/admin/after-sales/stats`
- `GET /api/admin/after-sales/{as_id}`
- `GET /api/admin/audit-logs`
- `GET /api/admin/auto-reply-rules`
- `GET /api/admin/conversation/{session_id}`
- `GET /api/admin/conversations`
- `GET /api/admin/customer/{customer_id}`
- `POST /api/admin/login`
- `GET /api/admin/me`
- `GET /api/admin/notifications`
- `GET /api/admin/notifications/unread-count`
- `GET /api/admin/orders`
- `GET /api/admin/quick-replies`
- `GET /api/admin/reply-templates`
- `GET /api/admin/reviews`
- `GET /api/admin/reviews/export`
- `GET /api/admin/reviews/stats`
- `GET /api/admin/sessions`
- `GET /api/admin/stats`
- `GET /api/admin/system-settings`
- `GET /api/admin/users`
- `GET /api/agent/sessions/{agent_id}`
- `GET /api/agent/status`
- `GET /api/circuit-breakers`
- `GET /api/message-center/conversations`
- `GET /api/message-center/health`
- `GET /api/message-center/notifications`
- `GET /api/message-center/notifications/search-status`
- `GET /api/message-center/notifications/unread-count`
- `GET /api/message-center/platforms`
- `GET /api/message-center/quick-replies`
- `GET /api/message-center/quick-replies/categories`
- `GET /api/message-center/reminders`
- `GET /api/message-center/reminders/due`
- `GET /api/metrics/business`
- `GET /api/metrics/summary`
- `GET /api/port-check`
- `GET /api/pre-sale-notes`
- `GET /api/pre-sale-notes/stats/summary`
- `GET /api/pre-sale-notes/{note_id}`
- `GET /api/realtime/stats`
- `GET /api/redis-status`
- `GET /api/seller/customers`
- `GET /api/seller/human-settings`
- `POST /api/seller/login`
- `GET /api/seller/messages/{session_id}`
- `GET /api/services-status`
- `GET /api/status`
- `GET /api/system-check`
- `GET /api/system-check/buyer`
- `GET /api/system-check/quick`
- `GET /api/system-check/report`
- `GET /api/system-check/report/download`
- `GET /api/v1/dashboard/stats`
- `GET /api/v1/logistics/{tracking_number}`
- `GET /api/v1/orders`
- `GET /api/v1/orders/{order_id}`
- `GET /api/v1/platforms`
- `GET /api/v1/returns`
- `GET /api/v1/reviews`
- `GET /api/v1/shop/calculate-price/{sku_id}`
- `GET /api/v1/shop/categories`
- `GET /api/v1/shop/inventory`
- `GET /api/v1/shop/platforms`
- `GET /api/v1/shop/pricing-rules`
- `GET /api/v1/shop/products`
- `GET /api/v1/shop/products/{product_id}`
- `GET /api/v1/shop/shop-products`
- `GET /api/v1/shop/shops`
- `GET /api/v1/shop/shops/{shop_id}`
- `GET /api/v1/shop/stats`
- `GET /api/v1/sync/status`
- `GET /chat`
- `GET /console`
- `GET /console/{page}`
- `GET /customer`
- `GET /docs`
- `GET /docs/oauth2-redirect`
- `GET /entry`
- `GET /health`
- `GET /home`
- `GET /live`
- `GET /metrics`
- `GET /openapi.json`
- `GET /ready`
- `GET /redoc`

## Error Codes

| Code | Meaning |
|------|---------|
| 200 | OK |
| 400 | Bad Request - Invalid parameters |
| 401 | Unauthorized - Invalid or missing token |
| 403 | Forbidden - Insufficient permissions |
| 404 | Not Found |
| 429 | Too Many Requests - Rate limit exceeded |
| 500 | Internal Server Error |

---
*Generated by OpenAPI Generator - 2026-03-31T15:01:05.882375*