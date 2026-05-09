# Ruitalk - 卖方智能客服终端

AI 驱动的跨境电商多平台客服系统，支持 Amazon、eBay、Shopee、AliExpress、Lazada 等平台。

## 项目结构

```
Ruitalk/
├── 卖方终端/              # 卖方后台系统 (FastAPI, 端口8000)
│   ├── backend/          # FastAPI 后端 + GoldCS (Flask)
│   ├── frontend/         # 前端页面
│   └── data/            # SQLite 数据库
├── AI客服买方系统/        # 买方客服前端 (FastAPI, 端口8001)
├── ruitalk_config/      # 工具脚本 (备份、告警、定时任务)
├── diagnose/            # 诊断工具
├── docs/                # 文档
├── docker/              # Docker 配置
├── .env                 # 统一配置文件 (从 .env.example 复制)
├── .env.example         # 配置模板
├── login_backend.py     # 登录后端 (Flask, 端口5000)
├── login.html           # 登录页面
├── start_all.py         # 一键启动所有服务
├── 卖家系统启动.bat      # Windows 启动脚本
└── 启动_Redis.bat       # Redis 启动工具
```

## 快速启动（给对方后需执行的命令）

### 第 1 步：安装 Python（如未安装）

下载安装 Python 3.11+：https://www.python.org/downloads/
安装时勾选 **"Add Python to PATH"**

### 第 2 步：复制环境配置

```bash
# 在项目根目录执行
cp .env.example .env
```

然后编辑 `.env` 文件，填入你自己的 API Key 等配置。

> 💡 **快速体验**：不填任何值也能以演示模式启动（短信验证码会打印在控制台）。

### 第 3 步：安装 Python 依赖

```bash
# 在项目根目录执行
pip install -r "卖方终端/requirements.txt"
```

### 第 4 步：启动服务

**方法一（推荐）— 双击脚本：**

1. 双击 `卖家系统启动.bat` — 自动启动卖方系统（FastAPI 8000 端口 + GoldCS 5001 + GraphRAG 5050）
2. 双击 `AI客服买方系统\启动买方系统.bat` — 启动买方客服系统

**方法二 — 命令行一键启动：**

```bash
python start_all.py
```

**方法三 — 单独手动启动：**

```bash
# 启动卖方系统后端 (FastAPI)
cd "卖方终端/backend"
python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload

# 启动登录后端 (新开一个终端)
python login_backend.py
```

### 第 5 步：访问系统

| 服务 | 地址 |
|------|------|
| 卖方后台 | http://127.0.0.1:8000 |
| 买方前台 | http://127.0.0.1:8001 |
| 登录页面 | http://127.0.0.1:5000 |
| API 文档 | http://127.0.0.1:8000/docs |

## 环境变量配置

详见 `.env.example` 文件，关键配置项：

| 变量 | 说明 | 必填 |
|------|------|------|
| `DEEPSEEK_API_KEY` | DeepSeek AI 密钥 | ✗ (演示模式也🉑) |
| `JWT_SECRET_KEY` | JWT 签名密钥 | 推荐修改 |
| `MYSQL_PASSWORD` | 数据库密码 | ✗ (默认 SQLite) |
| `SMS_PROVIDER` | 短信服务商 | ✗ (默认演示模式) |

## 默认账户

首次启动后，可通过登录页面注册新用户。

## 技术栈

- **后端**: FastAPI, Flask, SQLAlchemy, Neo4j, Redis
- **AI**: DeepSeek API, GraphRAG
- **前端**: React, TypeScript, Vite
- **数据库**: SQLite (开发) / MySQL (生产)
- **缓存**: Redis / Memurai (Windows)
