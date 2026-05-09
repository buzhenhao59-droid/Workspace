# Ruitalk 监控与可观测性文档

> 版本：1.0.0 | 更新：2026-03-31

---

## 目录

- [架构概览](#架构概览)
- [指标端点](#指标端点)
- [Prometheus 配置](#prometheus-配置)
- [Grafana 看板](#grafana-看板)
- [告警规则](#告警规则)
- [SLO/SLI 定义](#slosli-定义)

---

## 架构概览

```
+-------------+     +-----------+     +------------+
|   Seller    | --> |  Redis    | <-- |  Celery    |
|  (FastAPI)  | --> |  (Cache)  |     |  (Worker)  |
+-------------+     +-----------+     +------------+
       |                                     |
       v                                     v
+-------------+     +------------+     +--------+
| Prometheus  | <-- |  Neo4j     |     | MySQL  |
|  (Metrics)  |     | (GraphDB)  |     |        |
+-------------+     +------------+     +--------+
       |
       v
+--------------+
|   Grafana    |
|  (Dashboard) |
+--------------+
```

---

## 指标端点

### FastAPI 指标

| 端点 | 说明 | 认证 |
|------|------|------|
| `GET /metrics` | Prometheus 格式指标 | 无需 |
| `GET /health` | 健康检查 | 无需 |
| `GET /live` | 存活探针 | 无需 |
| `GET /ready` | 就绪探针 | 无需 |

### 指标类型

**请求指标**（来自 `prometheus_client`）：

| 指标名 | 类型 | 说明 |
|--------|------|------|
| `http_requests_total` | Counter | HTTP 请求总数，按 method/endpoint/status 标签 |
| `http_request_duration_seconds` | Histogram | 请求延迟分布 |
| `http_requests_in_progress` | Gauge | 当前处理中请求数 |

**业务指标**：

| 指标名 | 类型 | 说明 |
|--------|------|------|
| `active_sessions_total` | Gauge | 当前活跃会话数 |
| `active_agents_online` | Gauge | 在线坐席数 |
| `ai_handled_sessions_total` | Counter | AI 处理会话总数 |
| `human_handled_sessions_total` | Counter | 人工处理会话总数 |
| `messages_sent_total` | Counter | 发送消息数，按 direction（in/out）标签 |
| `transfer_to_agent_total` | Counter | 转人工次数 |
| `transfer_to_ai_total` | Counter | 转 AI 次数 |
| `db_operation_duration_seconds` | Histogram | 数据库操作延迟 |
| `redis_operation_duration_seconds` | Histogram | Redis 操作延迟 |

---

## Prometheus 配置

### prometheus.yml（参考）

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

alerting:
  alertmanagers:
    - static_configs:
        - targets: []

rule_files:
  - "alert_rules.yml"

scrape_configs:
  - job_name: "ruitalk-seller"
    static_configs:
      - targets: ["seller:8000"]
    metrics_path: "/metrics"
    scrape_interval: 15s

  - job_name: "ruitalk-buyer"
    static_configs:
      - targets: ["buyer:8001"]
    metrics_path: "/metrics"
    scrape_interval: 15s

  - job_name: "redis"
    static_configs:
      - targets: ["redis:6379"]
    scrape_interval: 30s

  - job_name: "prometheus"
    static_configs:
      - targets: ["localhost:9090"]
```

### 指标抓取验证

```bash
# 查看已抓取的指标
curl -s http://localhost:9090/api/v1/query?query=http_requests_total

# 实时查看特定指标
curl -s http://localhost:8000/metrics | grep http_requests_total | head -10
```

---

## Grafana 看板

### 访问

```
URL: http://127.0.0.1:3000
用户名: admin
密码: （GRAFANA_PASSWORD 环境变量）
```

### 推荐看板面板

| 面板名称 | 数据源 | 说明 |
|---------|--------|------|
| **系统总览** | Prometheus | 请求量、延迟、错误率 |
| **Seller API** | Prometheus | 按路由分组 |
| **数据库状态** | Prometheus | MySQL/Redis 连接数 |
| **会话活跃度** | Prometheus | 实时会话数 |
| **AI vs 人工** | Prometheus | 会话分流比例 |
| **告警历史** | Alertmanager | 所有触发过的告警 |

### 添加数据源

1. 访问 http://127.0.0.1:3000/datasources
2. 点击 "Add data source"
3. 选择 "Prometheus"
4. URL: `http://prometheus:9090`（Docker 内部网络）
5. 点击 "Save & Test"

---

## 告警规则

### alert_rules.yml

```yaml
groups:
  - name: ruitalk
    rules:
      # API 错误率
      - alert: HighErrorRate
        expr: |
          sum(rate(http_requests_total{status=~"5.."}[5m]))
          / sum(rate(http_requests_total[5m])) > 0.01
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "API 错误率超过 1%"
          description: "5分钟内错误率为 {{ $value | humanizePercentage }}"

      # API 延迟过高
      - alert: HighLatency
        expr: |
          histogram_quantile(0.99,
            sum(rate(http_request_duration_seconds_bucket[5m])) by (le)
          ) > 2
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "P99 延迟超过 2 秒"
          description: "当前 P99 = {{ $value | humanizeDuration }}"

      # 服务不可用
      - alert: SellerDown
        expr: up{job="ruitalk-seller"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Seller 服务宕机"

      # Redis 不可用
      - alert: RedisDown
        expr: redis_connected_clients == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Redis 连接数为 0"

      # 会话队列积压
      - alert: SessionQueueBacklog
        expr: active_sessions_total > 1000
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "会话队列积压过多"

      # AI 处理率低
      - alert: LowAIHandlingRate
        expr: |
          sum(rate(ai_handled_sessions_total[1h]))
          / sum(rate(ai_handled_sessions_total[1h]) + rate(human_handled_sessions_total[1h])) < 0.3
        for: 30m
        labels:
          severity: warning
        annotations:
          summary: "AI 处理率低于 30%"

      # MySQL 连接数过高
      - alert: HighMySQLConnections
        expr: mysql_max_connections / 100 < 0.8
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "MySQL 连接数超过 80%"
```

### 告警通知配置

支持多种通知渠道（通过 Grafana 或 Alertmanager）：

| 渠道 | 配置 |
|------|------|
| 钉钉 | 在 Grafana Notification channels 添加 DingTalk webhook |
| 飞书 | 在 Grafana Notification channels 添加 Custom HTTP |
| 邮件 | SMTP 配置 |
| Slack | Slack webhook |

---

## SLO/SLI 定义

### 服务等级目标

| 服务 | SLO | SLI | 测量窗口 |
|------|-----|-----|---------|
| Seller API 可用性 | 99.5% | `up{job="ruitalk-seller"}` | 30 天滚动 |
| API 延迟 P99 | < 2s | `histogram_quantile(0.99, ...)` | 5 分钟滚动 |
| API 错误率 | < 0.5% | `rate(5xx) / rate(total)` | 5 分钟滚动 |
| 坐席分配延迟 | < 30s | `transfer_to_agent latency` | 5 分钟滚动 |

### 错误预算

```
月度错误预算 = (1 - SLO) × 30天 × 24小时 × 60分钟
对于 99.5% SLO：0.5% × 43,200 分钟 = 216 分钟/月

当错误预算消耗超过 50% 时，降低变更频率
当错误预算消耗超过 100% 时，暂停非紧急变更
```

---

*文档版本：1.0.0 | 维护：Ruitalk Team*
