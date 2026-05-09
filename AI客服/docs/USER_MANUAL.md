# Ruitalk 智能客服系统说明书

> **版本**：v2.0
> **更新日期**：2026-04-02
> **项目类型**：AI 驱动的跨境电商多平台客服系统

---

## 目录

1. [系统概述](#一系统概述)
2. [系统架构](#二系统架构)
3. [目录结构](#三目录结构)
4. [核心功能模块](#四核心功能模块)
5. [快速开始](#五快速开始)
6. [部署指南](#六部署指南)
7. [API 参考](#七api-参考)
8. [用户指南](#八用户指南)
9. [运维监控](#九运维监控)
10. [安全配置](#十安全配置)
11. [故障排查](#十一故障排查)
12. [常见问题](#十二常见问题)

---

## 一、系统概述

### 1.1 项目简介

Ruitalk 是一款**AI 驱动的跨境电商多平台智能客服系统**，专为处理来自 Amazon、eBay、Shopee、AliExpress、Lazada、TikTok Shop 等主流跨境电商平台的客户服务需求而设计。

系统采用双端架构：

| 端 | 名称 | 端口 | 主要用户 |
|----|------|------|---------|
| **卖方终端** | Seller Terminal | 8000 | 客服坐席、店铺管理员 |
| **买方系统** | Buyer AI System | 8001 | 平台买家（AI客服对话） |

### 1.2 核心能力

- **多平台统一接入**：支持 8+ 主流跨境电商平台订单、客户、售后数据的统一管理
- **AI 智能客服**：基于 DeepSeek 大语言模型的自动回复，支持多语言（中/英/阿/俄/泰/越南/印尼/马来/菲律宾）
- **金牌客服工作台**：坐席实时聊天、快捷回复、订单查询、评价管理、售后处理
- **消息中心**：跨平台消息统一收发，支持 Webhook 回调
- **GraphRAG 知识图谱**：基于 Neo4j 的客服知识图谱检索，增强 AI 回复准确性
- **异步任务队列**：Celery + Redis 实现定时备份、批量通知、AI 翻译等后台任务

### 1.3 技术栈

| 层级 | 技术选型 |
|------|---------|
| **后端框架** | FastAPI (Python 3.11+) |
| **前端框架** | React 18 + TypeScript + Vite |
| **数据库** | MySQL 8.0 (卖家/买家各一) |
| **缓存/消息队列** | Redis (Memurai on Windows) |
| **知识图谱** | Neo4j |
| **任务队列** | Celery + Celery Beat |
| **监控** | Prometheus + Grafana |
| **容器化** | Docker + Docker Compose |
| **AI 能力** | DeepSeek API (兼容 OpenAI 接口) |

---

## 二、系统架构

### 2.1 整体架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                      Docker Compose (ruitalk-net)                │
│                        11 服务容器化编排                          │
├──────────────┬───────────────┬─────────────┬────────────────────┤
│   MySQL      │    Redis      │   Neo4j     │   Prometheus        │
│   Seller     │  (Session +   │ (知识图谱)  │   (监控指标)        │
│   Port 3306  │   Queue)      │  Port 7687  │                    │
│              │   Port 6379   │             │                    │
├──────────────┴───────────────┴─────────────┴────────────────────┤
│             MySQL Buyer        │  Grafana (可视化)              │
│             Port 3307          │  Port 3000                     │
├────────────────────────────┬────────────────────────────────────┤
│  Seller (卖方终端)           │  Buyer (买方AI客服)               │
│  FastAPI :8000              │  FastAPI :8001                    │
│  /api/* (92个端点)           │  /api/v1/* (多语言)                │
│                             │                                   │
│  功能模块:                   │  功能模块:                        │
│  - 金牌客服工作台              │  - AI 聊天 (AI/人工模式)           │
│  - 订单/客户/售后管理          │  - 多语言支持 (9种语言)            │
│  - 评价管理                   │  - 转人工触发卖方通知              │
│  - 消息中心                   │  - 独立买家数据库                  │
│  - 多平台数据同步              │                                   │
├────────────────────────────┴────────────────────────────────────┤
│                      Celery Worker / Beat                        │
│                    (异步任务: 备份/翻译/通知/报表)               │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 数据流向

```
[电商平台 Webhook]
       │
       ▼
[平台同步服务 platform_sync.py]
       │
       ▼
[MySQL Seller DB] ◀─────────────────── [AI客服买方系统]
       │                                      │
       ▼                                      ▼
[卖方终端 API (FastAPI :8000)] ◀──────── [Webhook 回调]
       │                                      │
       ▼                                      ▼
[React 前端]                          [买家聊天界面]
```

### 2.3 认证体系

- **JWT Token 认证**：统一的访问令牌机制
- **坐席登录**：`/api/seller/login`（用户名 + 密码）
- **管理员登录**：`/api/admin/login`（支持多因素）
- **内部 API 认证**：`INTERNAL_API_SECRET` 用于卖方/买方系统间通信

---

## 三、目录结构

```
Ruitalk/
│
├── 卖方终端/                          # 卖方客服终端（主系统）
│   ├── backend/                       # FastAPI 后端
│   │   ├── main.py                   # 主应用入口 (92个API端点)
│   │   ├── mysql_db.py               # MySQL 连接池 (pymysql + DBUtils)
│   │   ├── celery_app.py             # Celery 应用配置
│   │   ├── celery_tasks.py           # 异步任务 (7个任务)
│   │   ├── config.py                 # 配置管理
│   │   ├── rate_limiter.py           # 限流中间件
│   │   ├── error_codes.py            # 统一错误码 (RTK_*)
│   │   ├── webhook_client.py         # Webhook 客户端 (重试+签名)
│   │   ├── platform_sync.py          # 多平台数据同步
│   │   ├── agent_service.py          # 坐席服务
│   │   ├── message_center_router.py  # 消息中心路由
│   │   ├── shop_router.py            # 店铺管理路由
│   │   ├── platforms/                # 平台适配器
│   │   │   ├── amazon.py             # Amazon 适配
│   │   │   ├── ebay.py               # eBay 适配
│   │   │   ├── shopee.py             # Shopee 适配
│   │   │   ├── aliexpress.py         # AliExpress 适配
│   │   │   ├── lazada.py             # Lazada 适配
│   │   │   ├── tiktok.py             # TikTok Shop 适配
│   │   │   └── shopify.py            # Shopify 适配
│   │   ├── logistics/                # 物流服务商适配
│   │   │   └── __init__.py
│   │   ├── migrations/               # Flyway 数据库迁移
│   │   │   └── V001__init_schema.sql
│   │   └── tests/                    # 单元测试
│   ├── frontend/                     # 旧版 HTML 前端
│   │   └── admin/
│   │       ├── dashboard.html        # 仪表盘
│   │       ├── orders.html           # 订单管理
│   │       ├── customers.html        # 客户管理
│   │       ├── after-sales.html      # 售后管理
│   │       ├── reviews.html          # 评价管理
│   │       ├── message_center.html   # 消息中心
│   │       └── agent_console.html    # 坐席工作台
│   └── requirements.txt
│
├── frontend/                          # 新版 React 前端 (主用)
│   ├── src/
│   │   ├── App.tsx                  # 应用入口 + 路由配置
│   │   ├── main.tsx                 # React 渲染入口
│   │   ├── index.css                # 全局样式 (Tailwind CSS)
│   │   ├── pages/                   # 页面组件
│   │   │   ├── LoginPage.tsx         # 登录页
│   │   │   ├── DashboardPage.tsx    # 仪表盘
│   │   │   ├── CustomersPage.tsx     # 客户管理
│   │   │   ├── OrdersPage.tsx        # 订单管理
│   │   │   ├── ReviewsPage.tsx       # 评价管理
│   │   │   ├── AfterSalesPage.tsx    # 售后管理
│   │   │   ├── AgentConsolePage.tsx  # 坐席工作台
│   │   │   ├── SettingsPage.tsx      # 系统设置
│   │   │   └── SystemHealthPage.tsx  # 系统健康监控
│   │   ├── components/              # 公共组件
│   │   │   ├── layout/
│   │   │   │   ├── Sidebar.tsx      # 侧边导航栏
│   │   │   │   └── TopBar.tsx       # 顶部栏
│   │   │   └── ui/                  # UI 组件库
│   │   ├── hooks/                   # React Query Hooks
│   │   │   └── useApi.ts
│   │   ├── stores/                  # Zustand 状态管理
│   │   │   └── index.ts             # 认证状态存储
│   │   ├── providers/               # React Provider
│   │   │   └── ReactQueryProvider.tsx
│   │   └── utils/                   # 工具函数
│   │       ├── api-helpers.ts       # API 辅助函数
│   │       ├── helpers.ts            # 通用工具
│   │       ├── validation.ts         # 表单验证
│   │       └── cn.ts                 # 工具类
│   ├── package.json                  # 依赖管理
│   ├── vite.config.ts               # Vite 构建配置
│   ├── tailwind.config.ts           # Tailwind CSS 配置
│   ├── playwright.config.ts          # E2E 测试配置
│   ├── tests/                       # E2E 测试
│   │   └── e2e/
│   │       ├── buyer-landing.spec.ts
│   │       └── buyer-chat.spec.ts
│   ├── Dockerfile                    # 前端 Docker 镜像
│   └── nginx.conf                   # Nginx 反向代理配置
│
├── AI客服买方系统/                    # 买方 AI 客服（独立系统）
│   ├── backend/
│   │   ├── main_buyer.py           # 主应用 (FastAPI)
│   │   ├── mysql_db_buyer.py        # MySQL 连接池
│   │   ├── init_mysql_schema_buyer.py # 买方数据库初始化
│   │   ├── system_checker.py        # 系统检查器
│   │   └── requirements.txt
│   ├── frontend/
│   │   ├── customer/
│   │   │   ├── chat.html           # 买家 AI 聊天界面
│   │   │   └── human_chat.html      # 人工客服转接界面
│   │   └── index.html
│   ├── tests/
│   │   └── test_buyer.py
│   └── 启动买方系统.bat
│
├── docker/                          # Docker 配置
│   ├── mysql/
│   │   ├── init-seller.sql         # 卖家数据库初始化脚本
│   │   ├── init-buyer.sql           # 买家数据库初始化脚本
│   │   ├── seller.cnf               # MySQL 卖家配置
│   │   └── buyer.cnf                # MySQL 买家配置
│   ├── redis/
│   │   └── redis.conf               # Redis 配置
│   ├── prometheus/
│   │   └── prometheus.yml           # Prometheus 配置
│   └── grafana/
│       └── provisioning/            # Grafana 自动配置
│
├── docs/                             # 文档目录
│   ├── API_REFERENCE.md             # API 参考文档
│   ├── DEPLOYMENT.md                # 部署指南
│   ├── MONITORING.md                # 监控运维文档
│   ├── PRODUCTION_READY_REPORT.md   # 生产就绪报告
│   ├── PRODUCT_GAP_REPORT_*.md      # 产品差距报告
│   └── IMPROVEMENTS.md             # 改进记录
│
├── ruitalk_config/                  # Ruitalk 配置
│   └── tools/
│       ├── alert.py                 # 钉钉/飞书告警工具
│       ├── backup_db.py            # 数据库备份工具
│       └── setup_cron.py           # Cron 定时任务配置
│
├── chaos/                            # 混沌工程实验
│   ├── experiments.py              # 实验脚本
│   └── README.md
│
├── shuju/                            # 数据工具
│
├── 虚拟库/                           # 虚拟库相关 (Neo4j Demo)
│   └── neo4j_demo/
│       └── docker-compose.yml
│
├── docker-compose.yml               # Docker 编排（基础/开发版）
├── docker-compose.prod.yml         # Docker 编排（生产版）
├── docker-compose.staging.yml       # Docker 编排（预发布版）
├── Dockerfile.seller               # 卖方后端镜像
├── Dockerfile.buyer                 # 买方后端镜像
├── Dockerfile.graphrag              # GraphRAG 镜像
├── .env                             # 环境变量
├── .env.production                  # 生产环境变量模板
├── .env.example                     # 环境变量示例
├── .gitignore
├── README.md                        # 项目说明
└── start_all.py                    # 一键启动脚本
```

---

## 四、核心功能模块

### 4.1 卖方终端 (Seller Terminal)

#### 4.1.1 金牌客服工作台

坐席统一工作台，支持：

- **实时聊天**：与买家进行 WebSocket 实时对话
- **快捷回复**：预置常用回复模板
- **会话切换**：快速切换不同客户会话
- **AI 辅助**：AI 推荐回复、自动翻译

#### 4.1.2 订单管理

- 跨平台订单列表（支持 Amazon、eBay、Shopee 等）
- 订单状态筛选与搜索
- 订单详情查看（含物流信息）
- 批量操作（发货、退款等）

#### 4.1.3 客户管理

- 客户信息统一视图
- 购买历史查询
- 客户标签与分级
- 联系记录管理

#### 4.1.4 售后管理

- 售后工单创建与跟踪
- 退款/退货/换货处理
- 售后状态流转
- 批量售后处理

#### 4.1.5 评价管理

- 跨平台评价汇总
- 负面评价预警
- 回复评价
- 评价分析报表

#### 4.1.6 消息中心

- 统一消息收发
- 消息模板管理
- Webhook 回调配置
- 消息归档与搜索

### 4.2 AI 客服买方系统 (Buyer AI System)

#### 4.2.1 AI 聊天机器人

- **多语言支持**：中/英/阿/俄/泰/越南/印尼/马来/菲律宾
- **智能意图识别**：自动识别买家意图
- **知识库检索**：基于 GraphRAG 的知识图谱问答
- **多轮对话**：支持上下文理解的连续对话

#### 4.2.2 转人工服务

- AI 无法解答时自动转人工
- 通知卖方坐席系统
- 保持对话历史连贯性

#### 4.2.3 人工客服模式

- 客服接管对话
- 与卖方系统同步客户信息

### 4.3 多平台适配

| 平台 | 适配器文件 | 支持功能 |
|------|----------|---------|
| Amazon | `platforms/amazon.py` | 订单、客户、退款 |
| eBay | `platforms/ebay.py` | 订单、消息、退货 |
| Shopee | `platforms/shopee.py` | 订单、聊天、售后 |
| AliExpress | `platforms/aliexpress.py` | 订单、评价 |
| Lazada | `platforms/lazada.py` | 订单、退款 |
| TikTok Shop | `platforms/tiktok.py` | 订单、售后 |
| Shopify | `platforms/shopify.py` | 订单、客户 |

### 4.4 异步任务 (Celery)

| 任务名称 | 队列 | 功能描述 |
|---------|------|---------|
| `send_email_task` | default | 发送邮件通知 |
| `send_dingtalk_task` | default | 钉钉告警通知 |
| `backup_database_task` | backup_tasks | 数据库备份 |
| `sync_platform_data_task` | default | 同步平台数据 |
| `translate_message_task` | ai_tasks | AI 翻译 |
| `generate_report_task` | ai_tasks | 生成数据报表 |
| `cleanup_old_logs_task` | backup_tasks | 清理旧日志 |

---

## 五、快速开始

### 5.1 环境要求

| 组件 | 最低版本 | 推荐版本 |
|------|---------|---------|
| Python | 3.11 | 3.11+ |
| Node.js | 18 | 20+ |
| pnpm | 8 | 8+ |
| Docker | 20.10 | 24.0 |
| Docker Compose | 2.0 | 2.20+ |
| MySQL | 8.0 | 8.0 |
| Redis | 6.0 | 7.0 |

### 5.2 Docker 快速启动（推荐）

```bash
# 1. 克隆项目
git clone <repo-url>
cd Ruitalk

# 2. 配置环境变量
cp .env.production .env
# 编辑 .env 填入必填项

# 3. 启动所有服务
docker-compose up -d

# 4. 查看服务状态
docker-compose ps

# 5. 访问系统
# 卖方终端: http://localhost:8000
# 买方系统:  http://localhost:8001
# Grafana:   http://localhost:3000
```

### 5.3 本地开发启动

#### 后端启动

```bash
cd 卖方终端/backend

# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
# 编辑 .env 设置 JWT_SECRET_KEY 和 DEEPSEEK_API_KEY

# 初始化数据库
python init_mysql_schema.py

# 启动服务
python main.py
# 或
uvicorn main:app --reload --port 8000
```

#### 前端启动

```bash
cd frontend

# 安装依赖
pnpm install

# 启动开发服务器
pnpm dev

# 访问 http://localhost:5173
```

#### 买方系统启动

```bash
cd AI客服买方系统

# 安装依赖
pip install -r backend/requirements.txt

# 启动
python backend/main_buyer.py
# 或
cd AI客服买方系统 && 启动买方系统.bat
```

### 5.4 默认账户

| 系统 | 用户名 | 密码 | 角色 |
|------|-------|------|------|
| 卖方终端 | admin | 123456 | 管理员 |
| 买方系统 | buyer_admin | 123456 | 管理员 |

---

## 六、部署指南

> 详细部署步骤请参阅 [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)

### 6.1 环境配置

必须配置的环境变量：

```bash
# 认证相关（必须修改）
JWT_SECRET_KEY=<生成32位随机密钥>
SECRET_KEY=<生成32位随机密钥>
ADMIN_PASSWORD=<强密码>

# AI 能力
DEEPSEEK_API_KEY=<DeepSeek API Key>
DEEPSEEK_API_URL=<DeepSeek API 地址>

# 数据库
MYSQL_ROOT_PASSWORD=<MySQL Root 密码>
MYSQL_PASSWORD=<MySQL 应用密码>

# Redis
REDIS_PASSWORD=<Redis 密码>

# 监控（可选）
SENTRY_DSN=<Sentry DSN>

# 告警（可选）
DINGTALK_WEBHOOK=<钉钉群机器人地址>
FEISHU_WEBHOOK=<飞书群机器人地址>
```

### 6.2 生产环境部署

```bash
# 使用生产配置启动
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# 检查服务健康
curl http://localhost:8000/health
curl http://localhost:8001/health
```

### 6.3 备份策略

| 类型 | 频率 | 保留时间 | 存储位置 |
|------|------|---------|---------|
| MySQL 全量备份 | 每日 | 30 天 | 本地 + OSS |
| MySQL 增量备份 | 每小时 | 7 天 | 本地 |
| Redis 快照 | 每6小时 | 7 天 | 本地 |
| 日志归档 | 每日 | 90 天 | 日志服务器 |

---

## 七、API 参考

完整 API 文档请参阅 [docs/API_REFERENCE.md](docs/API_REFERENCE.md)

### 7.1 卖方终端 API

| 分类 | 前缀 | 端点数量 |
|------|------|---------|
| Admin | `/api/admin/*` | 20+ |
| Agent | `/api/agent/*` | 10+ |
| Message Center | `/api/message/*` | 10+ |
| Platform | `/api/platform/*` | 15+ |
| Seller | `/api/seller/*` | 15+ |
| Shop | `/api/shop/*` | 10+ |
| System | `/api/system/*` | 5+ |

### 7.2 买方系统 API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v1/chat` | POST | 发送聊天消息 |
| `/api/v1/conversations` | GET | 获取会话列表 |
| `/api/v1/transfer-to-human` | POST | 转人工服务 |
| `/api/v1/webhook/agent-response` | POST | 接收坐席回复 |

---

## 八、用户指南

### 8.1 坐席工作台使用

1. **登录系统**：访问 `/admin/login`，输入用户名密码
2. **查看待处理**：仪表盘显示待回复消息、待处理订单、待跟进售后
3. **处理会话**：点击会话卡片进入聊天界面
4. **使用快捷回复**：输入 `/` 触发快捷回复菜单
5. **AI 辅助**：启用 AI 推荐获得回复建议

### 8.2 订单处理流程

```
新订单 → 确认付款 → 安排发货 → 更新物流 → 完成配送
         ↓
      异常订单 → 联系客户 → 退款/退货处理
```

### 8.3 售后处理流程

```
收到售后申请 → 审核申请 → 做出决定 → 执行操作 → 通知客户
                               ↓
                         同意/拒绝/部分退款
```

---

## 九、运维监控

> 详细监控配置请参阅 [docs/MONITORING.md](docs/MONITORING.md)

### 9.1 监控端点

| 端点 | 说明 | 认证 |
|------|------|------|
| `GET /metrics` | Prometheus 格式指标 | 无 |
| `GET /health` | 健康检查 | 无 |
| `GET /live` | 存活探针 | 无 |
| `GET /ready` | 就绪探针 | 无 |

### 9.2 Grafana 看板

- 访问地址：`http://localhost:3000`
- 默认账户：`admin` / `admin`
- 预置看板：**Ruitalk Overview**

### 9.3 关键监控指标

| 指标 | 告警阈值 | 说明 |
|------|---------|------|
| HTTP 请求延迟 P99 | > 2s | API 响应时间 |
| 错误率 | > 1% | 5xx 错误占比 |
| Celery 队列积压 | > 1000 | 待处理任务数 |
| MySQL 连接数 | > 80% | 连接池使用率 |
| 磁盘使用率 | > 85% | 存储空间 |

---

## 十、安全配置

### 10.1 必做安全加固

- [ ] 修改所有默认密码
- [ ] 生成新的 JWT_SECRET_KEY 和 SECRET_KEY
- [ ] 配置 HTTPS（通过 Nginx）
- [ ] 限制 MySQL/Redis 端口仅本地访问
- [ ] 配置防火墙规则
- [ ] 启用 Sentry APM 错误追踪

### 10.2 敏感信息管理

生产环境敏感配置建议使用环境变量或密钥管理服务：

```bash
# 禁止提交到 Git
echo ".env" >> .gitignore
echo "*.pem" >> .gitignore
```

---

## 十一、故障排查

### 11.1 常见问题

| 问题 | 可能原因 | 解决方案 |
|------|---------|---------|
| 服务无法启动 | 端口被占用 | `netstat -ano \| findstr :8000`，杀掉占用进程 |
| 数据库连接失败 | MySQL 未启动 | `docker-compose up -d mysql-seller` |
| AI 回复慢 | DeepSeek API 限流 | 检查 API 配额，启用降级回复 |
| Webhook 不生效 | 回调地址不可达 | 确认公网可访问，使用 ngrok 测试 |

### 11.2 日志查看

```bash
# 查看所有服务日志
docker-compose logs -f

# 查看特定服务日志
docker-compose logs -f seller
docker-compose logs -f buyer

# 查看后端日志
tail -f 卖方终端/backend/logs/app.log
```

### 11.3 健康检查

```bash
# 卖方终端
curl http://localhost:8000/health

# 买方系统
curl http://localhost:8001/health

# 检查数据库连接
docker-compose exec mysql-seller mysqladmin ping -u root -p
```

---

## 十二、常见问题

### Q1: 如何添加新的电商平台？

在 `卖方终端/backend/platforms/` 目录下创建新的适配器文件，实现平台 API 的接入。

### Q2: 如何扩展 AI 模型？

修改 `config.py` 中的 AI 配置，切换到其他 OpenAI 兼容的 API 提供商。

### Q3: 支持私有化部署吗？

支持，提供完整的 Docker Compose 部署包，可在任何支持 Docker 的环境中部署。

### Q4: 如何联系技术支持？

如需技术支持，请提交 Issue 或联系开发团队。

---

## 附录

### A. 错误码说明

系统使用 `RTK_{Category}{Serial}` 格式的错误码：

| 前缀 | 分类 | 示例 |
|------|------|------|
| RTK_AUTH | 认证授权 | RTK_AUTH_001 |
| RTK_DB | 数据库 | RTK_DB_001 |
| RTK_API | API 调用 | RTK_API_001 |
| RTK_PLATFORM | 平台同步 | RTK_PLATFORM_001 |

### B. 版本历史

| 版本 | 日期 | 主要变更 |
|------|------|---------|
| v1.0 | 2025-xx | 初始版本 |
| v2.0 | 2026-03 | MySQL + Neo4j + Redis + Celery 全量升级 |

---

*本文档最后更新于 2026-04-02*
