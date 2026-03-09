# 拓岳科技跨境电商管理系统 - 后端

## 快速启动

### 1. 安装依赖
```bash
cd backend
npm install
```

### 2. 启动服务
```bash
npm start
# 或开发模式（自动重启）
npm run dev
```

### 3. 访问
- 服务地址: http://localhost:3000
- API文档: http://localhost:3000/api/docs

## 默认账号
- 管理员: admin / admin123
- 销售经理: sales / sales123

## API 接口列表

### 认证接口
- POST /api/auth/login - 登录
- POST /api/auth/register - 注册
- GET /api/auth/profile - 获取用户信息

### 销售管理
- GET /api/sales/orders - 订单列表
- POST /api/sales/orders - 创建订单
- POST /api/sales/orders/:id/audit - 订单审核
- POST /api/sales/orders/:id/split - 订单拆分
- POST /api/sales/orders/merge - 订单合并
- POST /api/sales/orders/:id/mark-exception - 异常标记
- GET /api/sales/listings - Listing列表
- PUT /api/sales/listings/:id/price - 调价
- POST /api/sales/listings/:id/publish - 刊登
- GET /api/sales/aftersales - 售后列表
- GET /api/sales/aftersales/analytics - 售后分析

### 产品与库存
- GET /api/products - 产品列表
- POST /api/products - 创建产品
- POST /api/products/:id/link-source - 货源配对
- GET /api/inventory - 库存列表
- GET /api/inventory/summary - 库存汇总
- POST /api/inventory/transactions - 出入库

### FBA仓储与补货
- GET /api/fba/replenishment/suggestions - 补货建议
- POST /api/fba/replenishment/calculate - 计算补货
- GET /api/fba/shipments - 货件列表
- POST /api/fba/shipments - 创建货件
- POST /api/fba/shipments/:id/boxing - 装箱
- POST /api/fba/shipments/:id/tracking - 跟踪号

### 物流与供应链
- GET /api/logistics/channels - 物流渠道
- POST /api/logistics/calculate-freight - 运费试算
- POST /api/logistics/print-label - 面单打印
- GET /api/logistics/tracking/:trackingNumber - 物流轨迹
- GET /api/purchases - 采购单
- POST /api/purchases - 创建采购单
- PUT /api/purchases/:id/stage/:stage - 更新阶段

### 财务管理
- GET /api/finance/profit-report - 利润报表
- GET /api/finance/profit-summary - 利润汇总
- GET /api/finance/accounts-payable - 应付账款
- GET /api/finance/platform-revenue - 平台收款
- GET /api/finance/expenses - 费用报销

### AI辅助
- POST /api/ai/generate-description - 生成商品描述
- POST /api/ai/translate - 多语言翻译
- POST /api/ai/analyze-reviews - 差评分析

## 技术栈
- Node.js
- Express
- JWT 认证
- 文件存储（可升级为数据库）

## 生产环境建议
1. 使用 MySQL/PostgreSQL 替换文件存储
2. 添加 Redis 缓存
3. 配置 HTTPS
4. 添加日志系统
5. 接入真实的AI服务（如OpenAI）
6. 对接真实物流API
