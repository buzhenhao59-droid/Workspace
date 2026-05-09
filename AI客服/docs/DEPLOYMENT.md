# Ruitalk 部署文档

> 版本：1.0.0 | 更新：2026-03-31

---

## 目录

- [环境要求](#环境要求)
- [快速部署（Docker）](#快速部署docker)
- [本地开发部署](#本地开发部署)
- [环境变量配置](#环境变量配置)
- [验证部署](#验证部署)
- [反向代理配置（Nginx）](#反向代理配置nginx)
- [备份策略](#备份策略)
- [故障排查](#故障排查)

---

## 环境要求

| 组件 | 最低 | 推荐 | 说明 |
|------|------|------|------|
| CPU | 4 核 | 8 核 | AI 推理需要更多计算 |
| 内存 | 8 GB | 16 GB | Neo4j 占 2GB+ |
| 磁盘 | 50 GB | 200 GB SSD | 数据库 + 日志 |
| Docker | 20.10 | 24.0 | 支持 compose v2 |
| Docker Compose | 2.0 | 2.20+ | YAML version 3.9 |

---

## 快速部署（Docker）

### 1. 克隆项目

```bash
git clone https://github.com/ruitalk/ruitalk.git
cd ruitalk
```

### 2. 配置环境变量

```bash
cp .env.production .env
# 编辑 .env，填入所有必填项（参考下方环境变量配置）
```

### 3. 启动所有服务

```bash
# 基础/开发环境
docker-compose up -d

# 生产环境（推荐）
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# 预发布环境
docker-compose -f docker-compose.staging.yml up -d
```

### 4. 验证服务状态

```bash
docker-compose ps
```

所有服务应为 `healthy` 状态（Neo4j 启动较慢，首次约需 60 秒）。

---

## 本地开发部署

### 前置条件

- Python 3.11+
- Node.js 18+
- Redis（本地或 Docker）
- MySQL（本地或 Docker）

### 后端

```bash
cd 卖方终端

# 安装依赖
pip install -r requirements.txt

# 或使用 pyproject.toml
pip install -e ".[dev]"

# 初始化数据库
cd backend
python init_seller_db.py

# 启动开发服务器（热重载）
cd backend
uvicorn main:app --host 127.0.0.1 --port 8000 --reload

# 或使用 pytest 运行测试
pytest tests/ -v
```

### 前端

```bash
cd frontend

# 安装依赖
npm install

# 启动开发服务器
npm run dev

# 生产构建
npm run build
```

---

## 环境变量配置

> **注意**：所有敏感值（密码、API Key、密钥）必须通过环境变量传入，勿硬编码。

### 必填项

| 变量名 | 说明 | 示例值 |
|--------|------|--------|
| `MYSQL_PASSWORD` | 卖方 MySQL 密码 | `YourStrongPassword123!` |
| `MYSQL_ROOT_PASSWORD` | MySQL root 密码 | `YourRootPassword123!` |
| `MYSQL_PASSWORD_BUYER` | 买方 MySQL 密码 | `BuyerStrongPass456!` |
| `NEO4J_PASSWORD` | Neo4j 密码 | `Neo4jSecurePass789!` |
| `REDIS_PASSWORD` | Redis 密码（可选） | `RedisSecurePass!` |

### 密钥（生产必改）

| 变量名 | 说明 | 建议生成 |
|--------|------|---------|
| `SECRET_KEY` | FastAPI 会话签名密钥 | `python -c "import secrets; print(secrets.token_hex(32))"` |
| `JWT_SECRET_KEY` | JWT token 签名密钥 | `python -c "import secrets; print(secrets.token_hex(32))"` |
| `INTERNAL_API_SECRET` | 内部 API 调用密钥 | `python -c "import secrets; print(secrets.token_hex(16))"` |

### 平台 API（按需配置）

| 平台 | 变量名 | 获取地址 |
|------|--------|---------|
| DeepSeek AI | `DEEPSEEK_API_KEY` | https://platform.deepseek.com/api_keys |
| TikTok Shop | `TIKTOK_APP_KEY` / `TIKTOK_APP_SECRET` | TikTok Shop Partner Portal |
| Shopee | `SHOPEE_PARTNER_ID` / `SHOPEE_SHOP_ID` / `SHOPEE_API_KEY` | Shopee Open Platform |
| Lazada | `LAZADA_APP_KEY` / `LAZADA_APP_SECRET` | Lazada Open Platform |
| AliExpress | `ALIEXPRESS_APP_KEY` / `ALIEXPRESS_APP_SECRET` | AliExpress Open Platform |
| Amazon | `AMAZON_CLIENT_ID` / `AMAZON_CLIENT_SECRET` | Amazon Seller Central |
| eBay | `EBAY_APP_ID` / `EBAY_CERT_ID` | eBay Developer Program |

### 通知（可选）

| 变量名 | 说明 |
|--------|------|
| `SENTRY_DSN` | Sentry APM（生产推荐） |
| `SMTP_HOST` / `SMTP_USER` / `SMTP_PASS` | 邮件通知 |
| `DINGTALK_WEBHOOK` | 钉钉告警机器人 |
| `FEISHU_WEBHOOK` | 飞书告警机器人 |

---

## 验证部署

### 后端 API

```bash
# 健康检查
curl http://127.0.0.1:8000/health
# 期望: {"status":"ok","database":"connected","redis":"connected"}

# 就绪检查
curl http://127.0.0.1:8000/live
# 期望: {"status":"alive"}

# API 文档
curl http://127.0.0.1:8000/openapi.json | python -m json.tool | head -30
```

### 前端

```bash
# 开发模式
# 访问 http://localhost:5173

# 生产模式（通过 Nginx）
# 访问 http://your-domain.com
```

### 数据库

```bash
# MySQL 连接
docker exec -it ruitalk-mysql-seller mysql -u root -p -e "SHOW DATABASES;"

# Neo4j 连接（通过浏览器）
# 访问 http://127.0.0.1:7474

# Redis
docker exec -it ruitalk-redis redis-cli ping
# 期望: PONG
```

### 监控

| 工具 | 地址 | 默认凭据 |
|------|------|---------|
| Prometheus | http://127.0.0.1:9090 | - |
| Grafana | http://127.0.0.1:3000 | admin / `GRAFANA_PASSWORD` |
| API 指标 | http://127.0.0.1:8000/metrics | 无需认证 |
| API Docs | http://127.0.0.1:8000/docs | 无需认证 |

---

## 反向代理配置（Nginx）

### 生产推荐配置

```nginx
# /etc/nginx/sites-available/ruitalk

server {
    listen 443 ssl http2;
    server_name your-domain.com;

    ssl_certificate /path/to/fullchain.pem;
    ssl_certificate_key /path/to/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256;
    ssl_prefer_server_ciphers off;
    add_header Strict-Transport-Security "max-age=63072000" always;

    # 卖方 API
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
        proxy_connect_timeout 75s;
    }

    # WebSocket
    location /ws/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 86400s;
    }

    # 前端静态文件
    location / {
        root /var/www/ruitalk/frontend/dist;
        try_files $uri $uri/ /index.html;
        expires 1y;
        add_header Cache-Control "public, immutable";
    }

    # 监控（限内部网络访问）
    location /monitor/ {
        proxy_pass http://127.0.0.1:9090;
        allow 10.0.0.0/8;
        allow 172.16.0.0/12;
        allow 192.168.0.0/16;
        deny all;
    }
}

server {
    listen 80;
    server_name your-domain.com;
    return 301 https://$server_name$request_uri;
}
```

---

## 备份策略

### 数据库备份脚本

```bash
#!/bin/bash
# backup.sh - 每日备份（建议通过 cron 执行）

BACKUP_DIR="/backups/ruitalk"
DATE=$(date +%Y%m%d_%H%M%S)
mkdir -p "$BACKUP_DIR"

# MySQL 备份
docker exec ruitalk-mysql-seller mysqldump \
    -u root -p"$MYSQL_ROOT_PASSWORD" \
    --single-transaction --quick ruitalk \
    | gzip > "$BACKUP_DIR/mysql_seller_${DATE}.sql.gz"

docker exec ruitalk-mysql-buyer mysqldump \
    -u root -p"$MYSQL_ROOT_PASSWORD_BUYER" \
    --single-transaction --quick ruitalk_buyer \
    | gzip > "$BACKUP_DIR/mysql_buyer_${DATE}.sql.gz"

# Neo4j 备份
docker exec ruitalk-neo4j neo4j-admin backup \
    --from=localhost:6362 \
    --backup-dir=/backups/neo4j_${DATE} \
    --database=neo4j

# 保留最近 30 天
find "$BACKUP_DIR" -name "*.gz" -mtime +30 -delete
find "$BACKUP_DIR" -type d -name "neo4j_*" -mtime +30 -exec rm -rf {} +

echo "[$(date)] Backup completed" >> /var/log/ruitalk_backup.log
```

### Cron 配置（每日凌晨 2 点）

```cron
0 2 * * * /opt/ruitalk/backup.sh >> /var/log/ruitalk_backup.log 2>&1
```

---

## 故障排查

### 服务无法启动

```bash
# 查看所有日志
docker-compose logs -f

# 查看特定服务
docker-compose logs -f seller
docker-compose logs -f neo4j

# 检查端口占用
netstat -tlnp | grep -E '3306|6379|7474|8000|9090|3000'
```

### 数据库连接失败

```bash
# MySQL 健康检查
docker exec ruitalk-mysql-seller mysqladmin ping -h localhost -u root -p

# 等待 MySQL 就绪
docker-compose exec mysql-seller mysql -u root -p -e "SELECT 1"
```

### Neo4j 启动缓慢

Neo4j 首次启动需要 60 秒以上进行初始化。查看日志：

```bash
docker-compose logs -f neo4j
```

### API 返回 502

通常是上游服务未就绪，检查依赖顺序：

```bash
docker-compose ps
docker-compose logs seller | grep -E "ConnectionError|mysql|redis|neo4j"
```

### 性能问题

```bash
# 查看资源使用
docker stats

# 查看慢查询
docker exec ruitalk-mysql-seller mysql -u root -p -e \
    "SHOW FULL PROCESSLIST;" 2>/dev/null
```

---

*文档版本：1.0.0 | 维护：Ruitalk Team*
