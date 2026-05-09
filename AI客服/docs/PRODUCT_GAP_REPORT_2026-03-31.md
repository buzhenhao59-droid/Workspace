# Ruitalk 产品级系统差距报告
> 生成时间：2026-03-31
> 覆盖范围：卖方终端、AI客服买方系统、前端、Docker基础设施

---

## 一、总览

| 维度 | 当前状态 | 目标状态 | 差距等级 |
|------|---------|---------|---------|
| **代码质量** | 已建立基础架构 | 标准化、可维护 | 中 |
| **依赖管理** | 无依赖文件 | 完整 requirements.txt / pyproject.toml | 高 |
| **安全配置** | 有基础但有关键漏洞 | 生产级安全标准 | 极高 |
| **配置管理** | .env 部分配置 | 全配置、安全敏感项隔离 | 高 |
| **Docker 部署** | 多服务、healthcheck、CI/CD | K8s、生产可观测性 | 中 |
| **监控告警** | 有 Prometheus/Grafana | 完整 SLI/SLO + 告警 | 高 |
| **文档** | 有基础文档 | 完整产品文档体系 | 极高 |
| **认证授权** | JWT 有但 seller_login 无密码验证 | 完整认证授权体系 | 极高 |
| **容错降级** | 部分有降级 | 全链路容错 | 高 |
| **API 生态** | 有路由但无文档 | OpenAPI 3.0 + SDK | 极高 |

**综合差距分：6.2 / 10**（基础框架完善，关键安全和文档缺口大）

---

## 二、安全与认证 —— 差距等级：极高 🔴

### 2.1 硬编码密钥 [CRITICAL]

| 位置 | 配置项 | 默认值 | 风险 |
|------|--------|--------|------|
| `config.py:167` | `SECRET_KEY` | `"dev-secret-key-change-in-production"` | 会话签名可被伪造 |
| `config.py:230` | `JWT_SECRET_KEY` | `"dev-jwt-secret-change-in-production-please"` | JWT token 可被伪造 |
| `config.py:168` | `ADMIN_PASSWORD` | `"123456"` | 管理后台直接沦陷 |
| `config.py:246` | `ADMIN_PASSWORD_SALT` | `"ruitalk-dev-salt-2026"` | 密码哈希可被碰撞 |
| `config.py:295` | `INTERNAL_API_SECRET` | `"buyer-seller-internal-secret-2026"` | 内部API可被未授权调用 |

**建议**：
```bash
# 生产环境必须设置
export SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")
export JWT_SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")
# ADMIN_PASSWORD 必须强制首次登录修改
```

### 2.2 坐席登录无密码验证 [CRITICAL]

**问题**：`POST /api/seller/login` → `agent_service.login()` 无密码校验

```python
# 当前代码 (main.py:1525)
if agent_service and hasattr(agent_service, 'login'):
    agent_info = agent_service.login(request.username, request.password)
    # ⚠️ agent_service.login() 只做内存注册，不校验密码
```

**后果**：任何人都能用任意用户名+密码登录 seller 端

**修复建议**：
```python
# 在 db.py 中添加 seller_auth(username, password_hash) 函数
def seller_auth(username: str, password: str) -> Optional[dict]:
    seller = db_fetchone("SELECT * FROM sellers WHERE username=?", (username,))
    if not seller: return None
    if not verify_hash(password, seller['password_hash']): return None
    return seller
```

### 2.3 缺失防护措施

| 防护项 | 当前状态 | 修复方式 |
|--------|---------|---------|
| CSRF | ❌ 完全缺失 | 添加 `csrf` 中间件，所有 POST/PUT/DELETE 要求 `X-CSRF-Token` |
| CORS | ⚠️ 有但配置宽松 | 生产环境必须限制 `ALLOWED_ORIGINS` |
| 敏感数据日志 | ⚠️ 有但不严格 | 审计日志需脱敏（手机号、邮箱、密码） |
| 密码强度 | ❌ 无 | 登录密码至少8位，含大小写+数字 |
| 登录失败限制 | ❌ 无 | 同一IP/账号 5分钟内失败5次，封禁30分钟 |
| 会话并发控制 | ❌ 无 | 同一账号只允许一个有效 token |
| API 鉴权 | ⚠️ 部分有 | 所有 `/api/*` 端点必须强制鉴权 |

### 2.4 认证测试结果

| 接口 | 预期 | 实际 | 结果 |
|------|------|------|------|
| `POST /api/seller/login` | 验证密码返回token | 跳过密码验证 | ❌ |
| `POST /api/admin/login` | 验证密码返回token | 凭据错误 | ⚠️ |
| 已认证接口 | 带Bearer token可访问 | 无有效token | ❌ |
| JWT 有效期 | ACCESS 30min / REFRESH 7d | 合理 | ✅ |
| JWT 算法 | HS256 | HS256（生产建议 EdDSA/RSA） | ⚠️ |

---

## 三、依赖管理 —— 差距等级：高 🟠

### 3.1 无依赖清单文件

**问题**：`d:/Ruitalk1/卖方终端/backend/` 下既无 `requirements.txt` 也无 `pyproject.toml`

**影响**：
- 新环境部署需要手动逐个安装
- 无法用 `pip freeze` 固定版本
- CI/CD 无法缓存依赖层

**建议**：
```bash
# 在 seller/.venv 中导出
pip freeze > requirements.txt
# 或使用 pyproject.toml
```

### 3.2 建议的依赖结构

```toml
# pyproject.toml（推荐）
[project]
name = "ruitalk-seller"
version = "1.0.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.30.0",
    "pyjwt>=2.12.0",
    "sqlalchemy>=2.0.0",
    "pymysql>=1.1.0",
    "redis>=5.0.0",
    # ... 完整依赖
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "ruff>=0.6"]
prod = ["gunicorn>=22.0"]
```

---

## 四、文档生态 —— 差距等级：极高 🔴

### 4.1 现有文档

| 文档 | 位置 | 内容质量 |
|------|------|---------|
| `README.md` | 根目录 | 基础项目说明 |
| `docs/PRODUCTION_READY_REPORT.md` | docs/ | 生产就绪检查 |
| `docs/RuiTalk整合报告与生产级差距清单.md` | docs/ | 整合报告 |
| `docs/GitHub_CI_CD部署指南.md` | docs/ | CI/CD 指南 |
| `docs/generate_openapi_docs.py` | docs/ | OpenAPI生成脚本 |

### 4.2 缺失文档

| 文档类型 | 优先级 | 说明 |
|---------|--------|------|
| **OpenAPI 完整文档** | 极高 | 应生成 `openapi.json` 并发布到 docs/API.md |
| **部署文档** | 极高 | Docker Compose 完整部署步骤 |
| **API 接口文档** | 极高 | 每个接口的请求/响应示例 |
| **监控文档** | 高 | Prometheus + Grafana 集成指南 |
| **数据库迁移文档** | 高 | Schema 变更流程 |
| **备份恢复文档** | 高 | MySQL / Redis / Neo4j 备份策略 |
| **安全配置文档** | 高 | 安全加固清单 |
| **故障排查指南** | 中 | 常见错误处理 |
| **用户使用手册** | 中 | 操作指南 |
| **SDK 文档** | 低 | Python / JavaScript SDK |

---

## 五、Docker 与基础设施 —— 差距等级：中 🟡

### 5.1 已完善项

| 特性 | 状态 | 详情 |
|------|------|------|
| 多阶段构建 | ✅ | seller / buyer 各4阶段：base → deps → builder → prod |
| 非 root 用户 | ✅ | 用户 `ruitalk` (uid 1000) |
| healthcheck | ✅ | seller/buyer/graphrag 均有 |
| restart 策略 | ✅ | unless-stopped / always |
| 资源限制 | ✅ | CPU + memory limits in compose |
| CI/CD | ✅ | GitHub Actions: lint + test + build + deploy |

### 5.2 缺失/待完善项

| 问题 | 影响 | 建议 |
|------|------|------|
| `docker-compose.yml` 端口全暴露 | 安全风险 | 加 `127.0.0.1:` 前缀 |
| 基础版/staging 无 logging 配置 | 无法收集日志 | 添加 json-file driver + 日志轮转 |
| 基础版/staging 无 ulimits | Neo4j 等可能占满 fd | 添加 `nofile: {soft: 65536, hard: 65536}` |
| 无 Docker Scout/Trivy 安全扫描 | 镜像漏洞未知 | CI 中加 `docker scout cves` |
| 无 healthcheck for MySQL/Redis | 无法感知依赖就绪 | 添加 `healthcheck` |
| 8个平台API密钥全部为空 | 平台集成不可用 | 按需配置 |

### 5.3 端口暴露对比

| compose 文件 | seller:8000 | buyer:8001 | neo4j:7474 | prometheus:9090 | grafana:3000 |
|-------------|------------|-----------|-----------|---------------|-------------|
| `docker-compose.yml` | 0.0.0.0:8000 | 0.0.0.0:8001 | 0.0.0.0:7474 | 0.0.0.0:9090 | 0.0.0.0:3000 |
| `docker-compose.prod.yml` | 127.0.0.1:8000 | 127.0.0.1:8001 | 无暴露 | 无暴露 | 无暴露 |
| `docker-compose.staging.yml` | 0.0.0.0:8000 | 0.0.0.0:8001 | 无暴露 | 无暴露 | 无暴露 |

---

## 六、监控与可观测性 —— 差距等级：高 🟠

### 6.1 已有的可观测性能力

| 组件 | 状态 | 说明 |
|------|------|------|
| Prometheus | ✅ 已有 | `metrics/` 端点暴露业务指标 |
| Grafana | ✅ 已有 | 预置 dashboard |
| 日志 | ⚠️ 部分 | 生产版有 json 日志 |
| 健康检查 | ✅ `/health` `/live` `/ready` | 三个独立端点 |
| 链路追踪 | ❌ 无 | 未集成 OpenTelemetry |

### 6.2 缺失的监控能力

| 缺失项 | 优先级 | 说明 |
|--------|--------|------|
| **OpenTelemetry 链路追踪** | 高 | 请求全链路 trace |
| **结构化日志规范** | 高 | JSON + trace_id + request_id |
| **SLO/SLI 定义** | 高 | 无服务等级目标 |
| **业务告警规则** | 高 | 错误率、延迟、队列积压 |
| **健康检查集成** | 中 | 写入 Prometheus |
| **Grafana 告警** | 中 | 无人值守告警 |

### 6.3 建议的监控矩阵

| 指标 | 类型 | 告警阈值 |
|------|------|---------|
| API 错误率 | SLI | > 1% 持续5分钟 |
| API P99 延迟 | SLI | > 2000ms |
| seller /health | 探测 | 连续失败3次 |
| seller CPU 使用率 | 资源 | > 80% |
| MySQL 连接数 | 资源 | > 80% max_connections |
| Neo4j 可用性 | 探测 | 无法连接 |
| Celery 队列积压 | 业务 | > 1000 任务 |
| JWT token 刷新失败率 | 安全 | > 5% |

---

## 七、认证与授权体系 —— 差距等级：极高 🔴

### 7.1 当前认证架构

```
无密码验证注册
       ↓
POST /api/seller/login → agent_service.login() → 内存注册 → 返回JWT
       ↓
POST /api/admin/login → db查询密码 → 验证JWT
```

### 7.2 问题清单

| 问题 | 位置 | 严重性 |
|------|------|--------|
| seller_login 无密码验证 | `main.py:1525` | 极高 |
| agent_service.login 只做内存注册 | `agent_service.py:63` | 极高 |
| sellers 表有密码哈希但从不校验 | `db.py` / `main.py` | 极高 |
| 无 refresh token 续期机制 | `jwt_auth.py` | 高 |
| 无登出机制（token 撤销） | 缺失 | 高 |
| 无角色权限控制 (RBAC) | 缺失 | 高 |
| 无 API key 认证（内部服务） | 缺失 | 中 |
| Keycloak 配置存在但未使用 | `keycloak_auth.py` | 中 |

### 7.3 修复优先级

```
P0 (立即修复):
├── 在 db.py 中实现 seller_auth(username, password) → seller_info
├── 在 main.py:seller_login() 中调用 db.seller_auth()
└── 添加登录失败计数与封禁

P1 (本周完成):
├── 实现 token 撤销（Redis 黑名单）
├── 实现 refresh token 自动续期
└── 添加 ADMIN_PASSWORD 强制首次修改

P2 (计划中):
├── 实现 RBAC 权限体系
├── 集成 Keycloak（可选）
└── API Key 认证（内部服务）
```

---

## 八、模块化与可维护性 —— 差距等级：中 🟡

### 8.1 当前模块评分

| 模块 | 质量 | 说明 |
|------|------|------|
| agent_service | 良好 | 清晰的类结构 |
| jwt_auth | 良好 | 函数式，职责单一 |
| db.py | 良好 | MySQL/SQLite 双引擎兼容 |
| services.py | 中等 | 多个 API 混在一起，缺少 Service Object 模式 |
| main.py | 较差 | **4100+ 行单文件**，路由/业务/工具混在一起 |
| config.py | 中等 | 配置加载逻辑清晰，但有硬编码 |

### 8.2 main.py 膨胀问题

**问题**：`main.py` 4100+ 行，是所有路由、生命周期、异常处理的唯一入口

**建议拆分**：
```
backend/
├── routers/              # 路由拆分
│   ├── __init__.py
│   ├── admin.py          # /api/admin/* 路由
│   ├── seller.py         # /api/seller/* 路由
│   ├── message_center.py # /api/message-center/* 路由
│   └── shop.py           # /api/v1/shop/* 路由
├── lifecycle/            # 生命周期拆分
│   ├── startup.py        # lifespan startup
│   └── shutdown.py       # lifespan shutdown
├── middleware/            # 中间件拆分
│   ├── security.py       # CORS / CSRF / RateLimit
│   └── tracing.py        # OpenTelemetry
└── main.py              # 只做 app 创建和 include_router
```

---

## 九、测试覆盖 —— 差距等级：高 🟠

### 9.1 当前测试状态

| 测试类型 | 状态 | 文件 |
|---------|------|------|
| 单元测试 | ⚠️ 有框架 | `tests/test_*.py` |
| 集成测试 | ⚠️ 有框架 | `tests/full_integration_test.py` |
| E2E 测试 | ⚠️ 有框架 | `tests/full_buyer_e2e_test.py` |
| 压力测试 | ⚠️ 有脚本 | `stress_test.py` |
| 测试数据生成 | ✅ 完善 | `_create_test_data.py` |
| pytest 配置 | ⚠️ 有但不完整 | `conftest.py` |

### 9.2 测试缺口

| 缺口 | 影响 | 建议覆盖率 |
|------|------|---------|
| JWT 认证安全测试 | 高 | 100% |
| SQL 注入防护测试 | 高 | 100% |
| Rate Limiting 边界测试 | 高 | 100% |
| 数据库迁移测试 | 中 | 每条迁移必须有回滚测试 |
| Celery 异步任务测试 | 中 | 80% |
| WebSocket 消息测试 | 中 | 80% |
| 平台 API mock 测试 | 低 | 60% |

---

## 十、平台集成与业务完整性 —— 差距等级：高 🟠

### 10.1 已实现 vs 待配置

| 平台 | API Key | 已集成代码 | 可用状态 |
|------|---------|-----------|---------|
| TikTok Shop | ❌ 空 | ✅ `platforms/tiktok.py` | 待配置 |
| Shopee | ❌ 空 | ✅ `platforms/shopee.py` | 待配置 |
| Lazada | ❌ 空 | ✅ `platforms/lazada.py` | 待配置 |
| Amazon | ❌ 空 | ✅ `platforms/amazon.py` | 待配置 |
| AliExpress | ❌ 空 | ✅ `platforms/aliexpress.py` | 待配置 |
| eBay | ❌ 空 | ✅ `platforms/ebay.py` | 待配置 |
| Shopify | ❌ 空 | ✅ `platforms/shopify.py` | 待配置 |
| Neo4j | ⚠️ 有密码 | ✅ `database.py` | ✅ 可用 |
| MySQL | ❌ 空密码 | ✅ `mysql_db.py` | 待配置 |
| Redis | ⚠️ 无密码 | ✅ `redis_store.py` | ✅ 可用 |
| DeepSeek API | ⚠️ 有Key | ✅ `services.py` | ✅ 可用 |
| GraphRAG | ✅ | ✅ `graphrag_proxy.py` | ✅ 可用 |

### 10.2 物流 API

| 物流商 | API Key | 状态 |
|--------|---------|------|
| DHL | ❌ 空 | 未配置 |
| FedEx | ❌ 空 | 未配置 |
| UPS | ❌ 空 | 未配置 |
| 燕文 | ❌ 空 | 未配置 |
| 4PX | ❌ 空 | 未配置 |
| 顺丰 | ❌ 空 | 未配置 |

---

## 十一、总结与优先级

### 按优先级排序的改进清单

| 优先级 | 任务 | 工作量 | 风险 |
|--------|------|--------|------|
| 🔴 P0 | 修复 seller_login 无密码验证漏洞 | 1天 | 高 |
| 🔴 P0 | 修改所有硬编码 SECRET/JWT 密钥 | 1小时 | 中 |
| 🔴 P0 | 生成 requirements.txt / pyproject.toml | 2小时 | 低 |
| 🟠 P1 | 生成 OpenAPI 文档并发布 | 1天 | 低 |
| 🟠 P1 | 添加登录失败封禁机制 | 1天 | 中 |
| 🟠 P1 | 添加 CSRF 防护 | 1天 | 中 |
| 🟠 P1 | 添加 API token 撤销机制 | 1天 | 中 |
| 🟠 P1 | 补充 docker-compose.yml 端口绑定和logging | 2小时 | 低 |
| 🟡 P2 | 拆分 main.py（4100行 → 多文件路由） | 2天 | 高 |
| 🟡 P2 | 添加 OpenTelemetry 链路追踪 | 2天 | 中 |
| 🟡 P2 | 补充缺失文档（部署/监控/安全） | 2天 | 低 |
| 🟡 P2 | 配置至少一个平台API验证完整性 | 1天 | 中 |
| 🟡 P2 | 补充测试覆盖（认证/安全/SQL注入） | 2天 | 低 |
| ⚪ P3 | 集成 Keycloak SSO | 3天 | 中 |
| ⚪ P3 | 添加 Grafana 告警规则 | 1天 | 低 |

### 预计工作量

| 阶段 | 时间 | 覆盖范围 |
|------|------|---------|
| P0 紧急修复 | 1-2天 | 安全漏洞堵住 |
| P1 基础完善 | 5-7天 | 认证/文档/基础设施 |
| P2 系统优化 | 5-7天 | 重构/监控/测试 |
| P3 高级特性 | 3-5天 | SSO/高级集成 |

---

*报告生成工具：Ruitalk 自检脚本*
*下次自检建议时间：P0/P1 完成后一周内*
