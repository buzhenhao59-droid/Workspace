# Ruitalk Windows 本地开发 / 交付准备指南

面向：**演示 / 开发原型 → 稳定、安全、可交付的生产候选**，并兼顾 Windows 路径、端口与依赖差异。

---

## 1. 环境与依赖

| 项 | 建议 |
|----|------|
| Python | **3.11+**，安装时勾选 **Add Python to PATH** |
| 虚拟环境 | 在项目根目录：`python -m venv .venv`，激活：`.venv\Scripts\activate` |
| 依赖 | `pip install -r "卖方终端/requirements.txt"`；买方如需单独环境可参考 `AI客服买方系统/requirements.txt` |
| 配置 | **唯一推荐**：项目根目录 `.env`（由 `.env.example` 复制），`start_all.py` 与卖方 `config.py` 均优先读取此处 |

### 随机密钥（不要用示例默认值上线）

```powershell
# PowerShell：生成 32 字节 hex（示例）
-join ((1..32) | ForEach-Object { '{0:x2}' -f (Get-Random -Max 256) })
```

或使用 Git Bash / WSL：`openssl rand -hex 32`

---

## 2. 启动方式

```powershell
cd <项目根目录>
python start_all.py
```

- 卖方端口：`FASTAPI_PORT`（默认 8000），买方端口：`BUYER_PORT`（默认 8001），均在根目录 `.env` 配置。
- 端口被占用时，控制台会提示使用 `Get-NetTCPConnection -LocalPort <端口>` 排查，或修改 `.env` 中端口号。
- 买方 **工作目录** 必须为 `AI客服买方系统/backend`（`start_all.py` 已固定 `cwd`，勿单独改命令行路径）。

---

## 3. 生产安全门禁（卖方服务）

当 **`RUITALK_ENV=production`**（或 **`ENV=production`**）时，卖方 FastAPI 启动前会校验：

- `SECRET_KEY`、`JWT_SECRET_KEY`、`ADMIN_PASSWORD`、`INTERNAL_API_SECRET`、`ADMIN_PASSWORD_SALT` 不得仍为开发默认值；
- `ALLOWED_ORIGINS` 不得包含 `*`。

不满足则**进程退出**。开发环境保留默认值时仅打印 **`[SECURITY]`** 警告，不中断。

实现位置：`卖方终端/backend/config.py` → `enforce_production_security_or_exit()`，由 `main.py` 的 lifespan 调用。

---

## 4. Redis / MySQL / Neo4j（可选）

| 组件 | Windows 常见做法 |
|------|------------------|
| Redis | **Memurai**、或 WSL2 内 `redis-server`、或 `.env` 中 `REDIS_USE_FAKE=true`（仅开发） |
| MySQL | 安装 MySQL 8 / MariaDB，或使用 **SQLite 回退**（`USE_SQLITE_FALLBACK=true`）；并发高时优先上 MySQL + 连接池 |
| Neo4j / GraphRAG | 不需要图谱时可不装；未部署时部分接口可能降级或超时，见技术总结文档 |

Docker Desktop 建议开启 **WSL2 后端**，否则 Compose 性能较差；资源紧张时可不用 Docker，仅用 `start_all.py` + 本机 Redis。

---

## 5. 前端与脚本（PowerShell）

若日后引入 **Node.js + Vite**，首次可在 PowerShell 执行：

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

---

## 6. 开机自启（可选）

可使用 **NSSM**、**任务计划程序**将 `python start_all.py` 配置为登录或开机运行（注意以固定用户身份运行以便读取用户目录下 `.env`）。

---

## 7. 推荐阅读

- 根目录：`Ruitalk_技术总结与路线图.md`
- 差距与安全背景：`docs/PRODUCT_GAP_REPORT_2026-03-31.md`（部分内容可能随代码迭代过时，以实机为准）

---

**文档版本**：2026-05-05
