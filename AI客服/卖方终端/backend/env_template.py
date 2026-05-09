# -*- coding: utf-8 -*-
"""
.env 配置模板说明文件
= 所有可以配置的平台 API 及对应获取方式
= 填写完 .env 后，这些字段就会自动生效
"""
ENV_TEMPLATE = """
# ============== Neo4j 图数据库 ==============
# 必填：客服对话历史 + 客户档案存储
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=你的Neo4j密码

# ============== DeepSeek AI ==============
# 必填：AI 客服大模型（免费注册获取：https://platform.deepseek.com/）
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxx
DEEPSEEK_API_URL=https://api.deepseek.com/v1/chat/completions

# ============== 跨境电商平台 API ==============
# ─── Shopee 开放平台 ───
# 申请地址：https://open.shopee.com/
# 凭证获取：开发者后台 → 应用管理 → 创建应用 → 获取 App Key + App Secret
# OAuth 授权后获取 Access Token
SHOPEE_API_URL=https://partner.shopeemobile.com
SHOPEE_API_KEY=你的Partner ID
SHOPEE_API_SECRET=你的App Secret
SHOPEE_ACCESS_TOKEN=你的Access Token（OAuth获取）
SHOPEE_SHOP_ID=你的店铺ID

# ─── TikTok Shop 开放平台 ───
# 申请地址：https://partner.tiktok.com/
# 凭证获取：开发者后台 → 创建应用 → 获取 Client Key + Client Secret
# 完成 OAuth 授权后获取 Access Token
TIKTOK_API_URL=https://open.tiktokapis.com
TIKTOK_API_KEY=你的Client Key
TIKTOK_API_SECRET=你的Client Secret
TIKTOK_ACCESS_TOKEN=你的Access Token（OAuth获取）
TIKTOK_SHOP_ID=你的店铺ID

# ─── Amazon Selling Partner API ───
# 申请地址：https://developer.amazonservices.com/
# 需先注册卖家开发账号，申请 SP API 访问权限
# AWS 账号注册：https://aws.amazon.com/
# 生成 LWA Access Token：https://sellercentral.amazon.com/apps/manage
AMAZON_API_URL=https://sellingpartnerapi.amazon.com
AMAZON_API_KEY=你的Client ID（LWA）
AMAZON_API_SECRET=你的Client Secret（LWA）
AMAZON_ACCESS_TOKEN=你的Refresh Token（LWA OAuth）
AMAZON_SELLER_ID=你的Seller ID
AMAZON_MARKETPLACE_ID=你的Marketplace ID（如 ATVPDKIKX0DER）

# ─── Lazada 开放平台 ───
# 申请地址：https://open.lazada.com/
# 开发者后台创建应用后获取 App Key + App Secret
# 完成 OAuth 授权获取 Access Token
LAZADA_API_URL=https://api.lazada.com/rest
LAZADA_API_KEY=你的App Key
LAZADA_API_SECRET=你的App Secret
LAZADA_ACCESS_TOKEN=你的Access Token（OAuth获取）
LAZADA_SHOP_ID=你的店铺ID

# ─── AliExpress (速卖通) 开放平台 ───
# 申请地址：https://open.aliexpress.com/
# 开发者后台创建应用，获取 App Key + App Secret
ALIEXPRESS_API_URL=https://eco.alibaba.com
ALIEXPRESS_API_KEY=你的App Key
ALIEXPRESS_API_SECRET=你的App Secret
ALIEXPRESS_ACCESS_TOKEN=你的Access Token
ALIEXPRESS_APP_ID=你的App ID

# ─── eBay 开放平台 ───
# 申请地址：https://developer.ebay.com/
# 创建应用后获取 App ID (Client ID) + Cert ID (Client Secret)
# 在 Developer Dashboard 完成 OAuth 授权
EBAY_API_URL=https://api.ebay.com
EBAY_API_KEY=你的App ID (Client ID)
EBAY_API_SECRET=你的Cert ID (Client Secret)
EBAY_ACCESS_TOKEN=你的Access Token（OAuth获取）
EBAY_SELLER_ID=你的Seller ID

# ─── Shopify 开放平台 ───
# 申请地址：https://shopify.dev/
# 在 Shopify 后台 → 应用管理 → 开发应用 → 获取 API Key + API Secret
# 安装应用后获取 Access Token
SHOPIFY_API_URL=https://your-store.myshopify.com/admin/api/2024-01
SHOPIFY_API_KEY=你的API Key
SHOPIFY_API_SECRET=你的API Secret
SHOPIFY_ACCESS_TOKEN=你的Admin API Access Token
SHOPIFY_SHOP_DOMAIN=你的店铺域名（如 my-store.myshopify.com）

# ============== 物流渠道 API ==============
# ─── DHL ───
# 申请地址：https://developer.dhl.com/
# 注册开发者账号，创建应用获取 API Key
DHL_API_URL=https://api-eu.dhl.com
DHL_API_KEY=你的API Key
DHL_API_SECRET=你的API Secret（部分接口需要）

# ─── FedEx ───
# 申请地址：https://developer.fedex.com/
# 注册开发者账号，获取 API Key + Secret
FEDEX_API_URL=https://apis.fedex.com
FEDEX_API_KEY=你的API Key
FEDEX_API_SECRET=你的API Secret

# ─── UPS ───
# 申请地址：https://www.ups.com/upsdeveloperkit
# 注册开发者账号，申请 OAuth 客户端凭据
UPS_API_URL=https://onlinetools.ups.com
UPS_API_KEY=你的Client ID（Access License Number）
UPS_API_SECRET=你的Client Secret

# ─── 燕文物流 ───
# 申请地址：联系燕文物流客服开通 API 接口
YANWEN_API_URL=https://api.yanwen物流.com
YANWEN_API_KEY=你的API Key
YANWEN_API_SECRET=你的API Secret

# ─── 4PX (递四方) ───
# 申请地址：联系4PX客服开通 ERP 接口
FPX_API_URL=https://open.4px.com
FPX_API_KEY=你的API Key
FPX_API_SECRET=你的API Secret

# ============== 业务系统对接 API ==============
# 如果你有 ERP / WMS / OMS 系统，在此填入接口地址
# 售后单
AFTER_SALES_LIST_API=
AFTER_SALES_CREATE_API=
AFTER_SALES_DETAIL_API=
AFTER_SALES_UPDATE_API=
AFTER_SALES_STATUS_API=
AFTER_SALES_STATS_API=

# 售前处理
PRESALE_LIST_API=
PRESALE_CREATE_API=
PRESALE_UPDATE_API=
PRESALE_ORDER_API=

# 评价管理
EVALUATION_LIST_API=
EVALUATION_DETAIL_API=
EVALUATION_REPLY_API=
EVALUATION_STATS_API=

# 物流 & 支付
LOGISTICS_API=
RETURN_LABEL_API=
REFUND_API=
PAYMENT_QUERY_API=

# ============== 1688 货源平台 ==============
# 申请地址：https://gw.open.1688.com/
ALIBABA_API_URL=https://gw.open.1688.com/openapi/
ALIBABA_APP_KEY=你的App Key
ALIBABA_APP_SECRET=你的App Secret

# ============== 汇率服务 ==============
# 推荐：exchangerate-api.com（免费注册获取 API Key）
EXCHANGE_RATE_API_URL=https://api.exchangerate-api.com/v4/latest/
EXCHANGE_RATE_API_KEY=你的API Key

# ============== 商品采集 / 爬虫 API ==============
# 推荐：店小秘 / 马帮 ERP（已接好各平台，可直接使用）
SCRAPER_API_URL=
SCRAPER_API_KEY=

# ============== 本地数据库配置 ==============
# MySQL（店铺管理系统数据）
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=你的MySQL密码
MYSQL_DATABASE=shop_manager

# ============== 系统配置 ==============
SECRET_KEY=请修改为随机字符串
ADMIN_PASSWORD=你的管理后台密码
"""
