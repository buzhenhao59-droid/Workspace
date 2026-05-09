# ============================================================
# GitHub 上传与 CI/CD 激活指南
# ============================================================
# 本指南将引导你完成以下步骤：
#   1. 创建 GitHub 仓库
#   2. 配置 GitHub Secrets（CI/CD 凭证）
#   3. 本地初始化 Git 并推送
#   4. 验证 CI/CD 流水线运行
#   5. 配置分支保护规则
# ============================================================

## 第一步：创建 GitHub 仓库

1. 访问 https://github.com/new 创建新仓库
2. 仓库名称：`ruitalk`
3. 描述：`金牌客服系统 - RuiTalk`
4. 选择 Private（私有）或 Public（公开）
5. **不要勾选** "Add a README file"（项目已有）
6. **不要勾选** ".gitignore"（项目已有）
7. 点击 "Create repository"

---

## 第二步：本地初始化 Git 并推送

打开 PowerShell 或 Git Bash，运行以下命令：

```bash
# 进入项目目录
cd D:\Ruitalk1

# 初始化 Git 仓库
git init

# 配置 Git 用户（请替换为你的信息）
git config user.name "你的GitHub用户名"
git config user.email "your@email.com"

# 添加所有文件（排除敏感文件）
# 创建 .gitignore（如果不存在）
git add .

# 或者逐个添加主要目录（排除敏感文件）
git add 卖方终端/backend/
git add 卖方终端/frontend/
git add 买方系统/backend/
git add 买方系统/frontend/
git add ruitalk_config/
git add nginx/
git add docker-compose.yml
git add README.md

# 首次提交
git commit -m "feat: initial commit - RuiTalk 客服系统"

# 添加远程仓库（请替换 YOUR_USERNAME 为你的 GitHub 用户名）
git remote add origin https://github.com/YOUR_USERNAME/ruitalk.git

# 推送到 GitHub
git branch -M main
git push -u origin main
```

---

## 第三步：配置 GitHub Secrets

访问你的仓库 → Settings → Secrets and variables → Actions

点击 "New repository secret"，添加以下 Secrets：

### Docker Hub（推送镜像用）

| Secret 名称 | 值 | 说明 |
|-------------|-----|------|
| `DOCKER_USERNAME` | `your_dockerhub_username` | Docker Hub 用户名 |
| `DOCKER_PASSWORD` | `your_dockerhub_token` | **建议使用 Access Token**，不要用密码 |

> 获取 Docker Access Token：
> Docker Hub → Account Settings → Security → New Access Token

### Staging 环境（部署用）

| Secret 名称 | 值 | 说明 |
|-------------|-----|------|
| `STAGING_HOST` | `123.456.789.012` | Staging 服务器 IP 地址 |
| `STAGING_USER` | `root` | SSH 登录用户名 |
| `STAGING_SSH_KEY` | `-----BEGIN OPENSSH PRIVATE KEY-----\n...\n-----END OPENSSH PRIVATE KEY-----` | **完整的私钥内容**（包含换行的完整内容） |

> 生成 SSH 密钥对：
> ```bash
> ssh-keygen -t ed25519 -C "your@email.com"
> # 私钥：~/.ssh/id_ed25519
> # 公钥：~/.ssh/id_ed25519.pub（复制到服务器的 ~/.ssh/authorized_keys）
> ```

### Production 环境（部署用）

| Secret 名称 | 值 | 说明 |
|-------------|-----|------|
| `PRODUCTION_HOST` | `987.654.321.098` | Production 服务器 IP |
| `PRODUCTION_USER` | `root` | SSH 用户名 |
| `PRODUCTION_SSH_KEY` | `-----BEGIN OPENSSH PRIVATE KEY-----\n...\n-----END OPENSSH PRIVATE KEY-----` | 完整私钥内容 |

### 其他 Secrets（可选）

| Secret 名称 | 值 | 说明 |
|-------------|-----|------|
| `SENTRY_DSN` | `https://...@...ingest.sentry.io/...` | Sentry 错误追踪 DSN |
| `DEEPSEEK_API_KEY` | `sk-...` | DeepSeek API 密钥 |

---

## 第四步：验证 CI/CD 流水线

1. 推送代码后，访问仓库 → Actions 页面
2. 应该能看到 "CI/CD Pipeline" 工作流正在运行
3. 点击工作流查看各 Job 状态：

```
Job 执行顺序：
  ✅ lint（代码质量） → 并行运行 →
  ✅ test-seller ──┐
  ✅ test-buyer   ├──→ ✅ docker → ✅ deploy-staging / deploy-production
  ✅ test-tools   ──┘
  ✅ security
```

4. 如有失败，点击 Job 查看日志
5. 常见失败原因：
   - `pip install` 超时 → 重试即可
   - Redis 连接失败 → GitHub Actions 已提供 Redis 服务
   - 权限不足 → 检查 Secrets 配置

---

## 第五步：配置分支保护规则（可选但强烈推荐）

访问仓库 → Settings → Branches → Branch protection rules

点击 "Add rule"：

### 主分支保护（main）

| 设置 | 值 |
|------|-----|
| Branch name pattern | `main` |
| ✅ Require a pull request before merging | 启用 |
| ✅ Require status checks to pass before merging | 启用 |
|   Status checks | 勾选 `lint`, `test-seller`, `test-buyer`, `test-tools`, `docker` |
| ✅ Require branches to be up to date before merging | 启用 |
| ✅ Do not allow bypassing the above settings | 启用 |

### 生产分支保护（master）

| 设置 | 值 |
|------|-----|
| Branch name pattern | `master` |
| ✅ Require a pull request before merging | 启用 |
| ✅ Require status checks to pass before merging | 启用 |
|   Status checks | 勾选所有 status checks |
| ✅ Require 2 approvals | 启用 |

---

## 第六步：自动部署配置

### 服务器准备（Staging/Production）

在目标服务器上执行：

```bash
# 1. 安装必要软件
apt update && apt install -y docker.io docker-compose

# 2. 创建应用目录
mkdir -p /app/ruitalk && cd /app/ruitalk

# 3. 克隆仓库（首次）
git clone https://github.com/YOUR_USERNAME/ruitalk.git .

# 4. 配置环境变量
cp .env.docker .env
nano .env  # 填写实际配置

# 5. 拉取最新代码
git pull origin main

# 6. 启动服务
docker-compose --profile production up -d
```

### 苹果boy SSH 部署说明

CI/CD 使用 `appleboy/ssh-action@v1` 进行 SSH 部署，需要服务器满足：

1. SSH 公钥已添加到服务器
2. SSH 私钥已配置为 GitHub Secret
3. 服务器已安装 Docker 和 docker-compose

---

## 工作流说明

| 分支 | 触发条件 | 动作 |
|------|----------|------|
| `main` | push / PR | 运行测试 + 构建镜像 |
| `main` | push 完成 | 自动部署到 Staging |
| `master` | push 完成 | 自动部署到 Production |
| 任意 | 手动触发 | 可选择环境部署 |

---

## 常见问题

**Q: CI/CD 运行失败怎么办？**
A: 点击失败的 Job → 查看日志，通常是网络超时或依赖问题，重试即可。

**Q: Docker 镜像推送到哪里？**
A: 推送到 GitHub Container Registry (ghcr.io)，不是 Docker Hub。
如需推送到 Docker Hub，请修改 `.github/workflows/ci-cd.yml` 中的镜像地址。

**Q: 如何跳过某些 Job？**
A: 在 commit message 中添加 `[skip ci]` 即可跳过 CI。

**Q: 生产环境需要什么配置？**
A: 参见 `docker-compose.yml` 和 `nginx/HTTPS部署指南.md`
