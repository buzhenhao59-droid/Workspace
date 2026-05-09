# -*- coding: utf-8 -*-
"""
店铺管理 API 路由 - 对应前端 shop-manager.html
提供店铺、商品、库存、定价规则、批量刊登等完整后端接口
"""
import json
import math
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Query, Body

from pydantic import BaseModel
from . import shop_db as db

router = APIRouter(prefix="/api/v1/shop", tags=["店铺管理"])

# ============== 请求/响应模型 ==============
class ShopCreateModel(BaseModel):
    shop_name: str
    platform: str
    shop_id: Optional[str] = None
    app_key: Optional[str] = None
    app_secret: Optional[str] = None
    access_token: Optional[str] = None
    country: Optional[str] = None
    currency: Optional[str] = "USD"
    is_default: bool = False


class ProductCreateModel(BaseModel):
    title: str
    title_en: Optional[str] = None
    description: Optional[str] = None
    source_platform: Optional[str] = None
    brand: Optional[str] = None
    material: Optional[str] = None
    weight: Optional[float] = None
    images: Optional[List[str]] = []
    status: Optional[str] = "draft"


class PricingRuleCreateModel(BaseModel):
    rule_name: str
    rule_type: str
    platform: Optional[str] = None
    margin_percent: Optional[float] = 30
    platform_fee_percent: Optional[float] = 10
    shipping_cost: Optional[float] = 0
    payment_fee_percent: Optional[float] = 2
    round_mode: Optional[str] = "ceil"
    priority: Optional[int] = 0
    is_active: bool = True


class CollectModel(BaseModel):
    platform: str
    url: str
    auto_create_sku: bool = True


class PublishModel(BaseModel):
    product_ids: List[int]
    shop_ids: List[int]
    price_type: str = "cost_plus"
    price_adjustment: float = 0
    stock_sync: bool = True


# ============== 工具函数 ==============
def success(data=None, message="操作成功"):
    return {"success": True, "message": message, "data": data}


def error(message="操作失败"):
    return {"success": False, "message": message}


def calculate_price(cost: float, rule: dict, adjustment: float = 0) -> float:
    """根据定价规则计算售价"""
    if not rule:
        return round(cost * (1 + adjustment / 100), 2)

    rule_type = rule.get("rule_type", "margin")
    margin = rule.get("margin_percent", 30) / 100
    platform_fee = rule.get("platform_fee_percent", 10) / 100
    shipping = rule.get("shipping_cost", 0)
    payment_fee = rule.get("payment_fee_percent", 2) / 100
    round_mode = rule.get("round_mode", "ceil")

    if rule_type == "margin":
        base = cost * (1 + margin + platform_fee + payment_fee) + shipping
    elif rule_type == "fixed":
        base = cost + rule.get("margin_percent", 0) + shipping
    else:
        base = cost * (1 + margin + platform_fee + payment_fee) + shipping

    price = base * (1 + adjustment / 100)

    if round_mode == "ceil":
        return math.ceil(price * 100) / 100
    elif round_mode == "floor":
        return math.floor(price * 100) / 100
    else:
        return round(price, 2)


# ============== 数据库初始化 ==============
@router.post("/init-database")
async def init_database():
    """初始化店铺管理数据库表"""
    try:
        result = db.init_database()
        return success(message=result["message"])
    except Exception as e:
        return error(f"初始化失败: {str(e)}")


# ============== 仪表盘 ==============
@router.get("/stats")
async def get_stats():
    """获取仪表盘统计数据"""
    try:
        stats = db.get_dashboard_stats()
        return success(stats)
    except Exception as e:
        return error(f"获取统计数据失败: {str(e)}")


# ============== 店铺管理 ==============
@router.get("/shops")
async def list_shops(
    platform: Optional[str] = Query(None),
    status: Optional[str] = Query(None)
):
    """获取店铺列表"""
    try:
        shops = db.get_shops(platform=platform, status=status)
        return success(shops)
    except Exception as e:
        return error(f"获取店铺列表失败: {str(e)}")


@router.post("/shops")
async def create_shop(shop: ShopCreateModel):
    """创建店铺"""
    try:
        shop_id = db.create_shop(shop.model_dump())
        if shop_id <= 0:
            return error("创建店铺失败")
        new_shop = db.get_shop(shop_id)
        return success(new_shop, "店铺创建成功")
    except Exception as e:
        return error(f"创建店铺失败: {str(e)}")


@router.get("/shops/{shop_id}")
async def get_shop(shop_id: int):
    """获取单个店铺"""
    try:
        shop = db.get_shop(shop_id)
        if not shop:
            return error("店铺不存在")
        return success(shop)
    except Exception as e:
        return error(f"获取店铺失败: {str(e)}")


@router.put("/shops/{shop_id}")
async def update_shop(shop_id: int, shop: ShopCreateModel):
    """更新店铺"""
    try:
        ok = db.update_shop(shop_id, shop.model_dump(exclude_unset=True))
        if not ok:
            return error("更新店铺失败")
        updated = db.get_shop(shop_id)
        return success(updated, "店铺更新成功")
    except Exception as e:
        return error(f"更新店铺失败: {str(e)}")


@router.delete("/shops/{shop_id}")
async def delete_shop(shop_id: int):
    """删除店铺"""
    try:
        ok = db.delete_shop(shop_id)
        if not ok:
            return error("删除店铺失败")
        return success(message="店铺已删除")
    except Exception as e:
        return error(f"删除店铺失败: {str(e)}")


@router.post("/shops/{shop_id}/test")
async def test_shop_connection(shop_id: int):
    """测试店铺 API 连接"""
    try:
        result = db.test_shop_connection(shop_id)
        return result
    except Exception as e:
        return error(f"连接测试失败: {str(e)}")


# ============== 商品管理 ==============
@router.get("/products")
async def list_products(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    status: Optional[str] = Query(None),
    source_platform: Optional[str] = Query(None),
    keyword: Optional[str] = Query(None)
):
    """分页获取商品列表"""
    try:
        result = db.get_products(
            page=page, page_size=page_size,
            status=status, source_platform=source_platform, keyword=keyword
        )
        return success(result)
    except Exception as e:
        return error(f"获取商品列表失败: {str(e)}")


@router.post("/products")
async def create_product(product: ProductCreateModel):
    """创建商品"""
    try:
        product_id = db.create_product(product.model_dump(exclude_unset=True))
        if product_id <= 0:
            return error("创建商品失败")
        new_product = db.get_product(product_id)
        return success(new_product, "商品创建成功")
    except Exception as e:
        return error(f"创建商品失败: {str(e)}")


@router.get("/products/{product_id}")
async def get_product(product_id: int):
    """获取单个商品（含 SKU）"""
    try:
        product = db.get_product_with_skus(product_id)
        if not product:
            return error("商品不存在")
        return success(product)
    except Exception as e:
        return error(f"获取商品失败: {str(e)}")


@router.put("/products/{product_id}")
async def update_product(product_id: int, product: ProductCreateModel):
    """更新商品"""
    try:
        ok = db.update_product(product_id, product.model_dump(exclude_unset=True))
        if not ok:
            return error("更新商品失败")
        updated = db.get_product(product_id)
        return success(updated, "商品更新成功")
    except Exception as e:
        return error(f"更新商品失败: {str(e)}")


@router.delete("/products/{product_id}")
async def delete_product(product_id: int):
    """删除商品"""
    try:
        ok = db.delete_product(product_id)
        if not ok:
            return error("删除商品失败")
        return success(message="商品已删除")
    except Exception as e:
        return error(f"删除商品失败: {str(e)}")


# ============== 商品采集 ==============
@router.post("/collect")
async def collect_product(data: CollectModel):
    """采集商品（从各平台）"""
    try:
        # 实际项目中这里会调用对应平台的爬虫/API
        # 当前实现：演示模式，创建一条草稿商品记录
        if data.platform == "1688":
            product_data = {
                "title": f"【1688采集】{data.url.split('/')[-1] if '/' in data.url else '商品'}",
                "source_platform": "1688",
                "status": "draft",
                "images": [],
            }
        elif data.platform == "amazon":
            product_data = {
                "title": f"【Amazon采集】{data.url}",
                "source_platform": "amazon",
                "status": "draft",
                "images": [],
            }
        elif data.platform == "aliexpress":
            product_data = {
                "title": f"【AliExpress采集】{data.url}",
                "source_platform": "aliexpress",
                "status": "draft",
                "images": [],
            }
        elif data.platform == "shopee":
            product_data = {
                "title": f"【Shopee采集】{data.url}",
                "source_platform": "shopee",
                "status": "draft",
                "images": [],
            }
        elif data.platform == "temu":
            product_data = {
                "title": f"【Temu采集】{data.url}",
                "source_platform": "temu",
                "status": "draft",
                "images": [],
            }
        else:
            product_data = {
                "title": f"【{data.platform}采集】{data.url}",
                "source_platform": data.platform,
                "status": "draft",
                "images": [],
            }

        product_id = db.create_product(product_data)

        # 如果需要自动创建 SKU
        if data.auto_create_sku:
            sku_data = {
                "sku_code": None,
                "sku_name": "默认SKU",
                "source_price": 0,
                "attributes": {},
                "images": [],
            }
            db.create_sku(product_id, sku_data)

        db.add_collect_history({
            "platform": data.platform,
            "source_url": data.url,
            "title": product_data["title"],
            "status": "success",
            "product_id": product_id,
        })

        return success({"product_id": product_id}, f"{data.platform} 商品采集成功")
    except Exception as e:
        db.add_collect_history({
            "platform": data.platform,
            "source_url": data.url,
            "title": "",
            "status": "failed",
            "error_message": str(e),
        })
        return error(f"采集失败: {str(e)}")


# ============== 批量刊登 ==============
@router.get("/shop-products")
async def list_shop_products(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    shop_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None)
):
    """获取已刊登商品列表"""
    try:
        result = db.get_shop_products(
            page=page, page_size=page_size,
            shop_id=shop_id, status=status
        )
        return success(result)
    except Exception as e:
        return error(f"获取刊登列表失败: {str(e)}")


@router.post("/publish")
async def publish_products(data: PublishModel):
    """批量刊登商品到店铺"""
    try:
        published = []
        for product_id in data.product_ids:
            product = db.get_product(product_id)
            if not product:
                continue

            # 获取商品 SKU
            skus = db.get_skus_by_product(product_id)
            if not skus:
                # 没有 SKU 时直接创建刊登记录
                for shop_id in data.shop_ids:
                    shop = db.get_shop(shop_id)
                    if not shop:
                        continue
                    rule = db.get_active_pricing_rule(shop["platform"], shop_id)
                    price = calculate_price(0, rule, data.price_adjustment)
                    sp_id = db.create_shop_product({
                        "product_id": product_id,
                        "shop_id": shop_id,
                        "sku_id": None,
                        "price": price,
                        "stock": 0,
                        "publish_status": "published",
                    })
                    published.append(sp_id)
            else:
                # 有 SKU，为每个店铺每个 SKU 创建刊登记录
                for shop_id in data.shop_ids:
                    shop = db.get_shop(shop_id)
                    if not shop:
                        continue
                    rule = db.get_active_pricing_rule(shop["platform"], shop_id)
                    for sku in skus:
                        cost = sku.get("source_price", 0) or 0
                        price = calculate_price(cost, rule, data.price_adjustment)

                        # 获取库存
                        stock = 0
                        if data.stock_sync:
                            invs = db.get_inventory(sku_id=sku["id"])
                            for inv in invs:
                                if inv.get("sku_id") == sku["id"]:
                                    stock = inv.get("available_stock", 0)
                                    break

                        sp_id = db.create_shop_product({
                            "product_id": product_id,
                            "shop_id": shop_id,
                            "sku_id": sku["id"],
                            "price": price,
                            "stock": stock,
                            "publish_status": "published",
                        })
                        published.append(sp_id)

            # 更新商品状态为已发布
            db.update_product(product_id, {"status": "published"})

        return success({
            "published_count": len(published),
            "published_ids": published
        }, f"成功刊登 {len(published)} 个商品")
    except Exception as e:
        return error(f"刊登失败: {str(e)}")


@router.post("/shop-products/{sp_id}/offline")
async def offline_product(sp_id: int):
    """下架商品"""
    try:
        ok = db.offline_shop_product(sp_id)
        if not ok:
            return error("下架失败")
        return success(message="商品已下架")
    except Exception as e:
        return error(f"下架失败: {str(e)}")


# ============== 库存管理 ==============
@router.get("/inventory")
async def list_inventory(
    sku_id: Optional[int] = Query(None),
    shop_id: Optional[int] = Query(None)
):
    """获取库存列表（支持按 SKU / 店铺筛选）"""
    try:
        inventory = db.get_inventory(sku_id=sku_id, shop_id=shop_id)
        return success(inventory)
    except Exception as e:
        return error(f"获取库存失败: {str(e)}")


@router.post("/inventory")
async def create_inventory_record(
    sku_id: int = Body(...),
    shop_id: Optional[int] = Body(None),
    available_stock: int = Body(0),
    reserved_stock: int = Body(0),
    low_stock_threshold: int = Body(10)
):
    """创建库存记录"""
    try:
        inv_id = db.create_inventory({
            "sku_id": sku_id,
            "shop_id": shop_id,
            "available_stock": available_stock,
            "reserved_stock": reserved_stock,
            "low_stock_threshold": low_stock_threshold,
        })
        if inv_id <= 0:
            return error("创建库存记录失败")
        return success({"id": inv_id}, "库存记录创建成功")
    except Exception as e:
        return error(f"创建库存记录失败: {str(e)}")


@router.put("/inventory/{inv_id}")
async def update_inventory_record(
    inv_id: int,
    available_stock: Optional[int] = None,
    reserved_stock: Optional[int] = None,
    low_stock_threshold: Optional[int] = None
):
    """更新库存"""
    try:
        data = {}
        if available_stock is not None:
            data["available_stock"] = available_stock
        if reserved_stock is not None:
            data["reserved_stock"] = reserved_stock
        if low_stock_threshold is not None:
            data["low_stock_threshold"] = low_stock_threshold
        if not data:
            return error("没有需要更新的字段")
        ok = db.update_inventory(inv_id, data)
        if not ok:
            return error("更新库存失败")
        return success(message="库存更新成功")
    except Exception as e:
        return error(f"更新库存失败: {str(e)}")


@router.post("/inventory/sync-all")
async def sync_all_inventory():
    """同步全店库存（模拟实现）"""
    try:
        # 实际项目中这里会调用各平台 API 获取实时库存
        inventory = db.get_inventory()
        return success({
            "synced_count": len(inventory),
            "message": "库存同步完成（模拟模式）"
        }, "全店库存同步完成")
    except Exception as e:
        return error(f"库存同步失败: {str(e)}")


# ============== 定价规则 ==============
@router.get("/pricing-rules")
async def list_pricing_rules():
    """获取定价规则列表"""
    try:
        rules = db.get_pricing_rules()
        return success(rules)
    except Exception as e:
        return error(f"获取定价规则失败: {str(e)}")


@router.post("/pricing-rules")
async def create_pricing_rule(rule: PricingRuleCreateModel):
    """创建定价规则"""
    try:
        rule_id = db.create_pricing_rule(rule.model_dump())
        if rule_id <= 0:
            return error("创建规则失败")
        return success({"id": rule_id}, "定价规则创建成功")
    except Exception as e:
        return error(f"创建规则失败: {str(e)}")


@router.delete("/pricing-rules/{rule_id}")
async def delete_pricing_rule(rule_id: int):
    """删除定价规则"""
    try:
        ok = db.delete_pricing_rule(rule_id)
        if not ok:
            return error("删除规则失败")
        return success(message="规则已删除")
    except Exception as e:
        return error(f"删除规则失败: {str(e)}")


# ============== SKU 管理 ==============
@router.get("/products/{product_id}/skus")
async def list_product_skus(product_id: int):
    """获取商品的所有 SKU"""
    try:
        skus = db.get_skus_by_product(product_id)
        return success(skus)
    except Exception as e:
        return error(f"获取 SKU 失败: {str(e)}")


@router.put("/skus/{sku_id}")
async def update_sku_route(sku_id: int):
    """更新 SKU（支持 attributes / images / source_price 等字段）"""
    from fastapi import Request
    try:
        req = await Request.json()
        ok = db.update_sku(sku_id, req)
        if not ok:
            return error("更新 SKU 失败")
        return success(message="SKU 更新成功")
    except Exception as e:
        return error(f"更新 SKU 失败: {str(e)}")


@router.delete("/skus/{sku_id}")
async def delete_sku_route(sku_id: int):
    """删除 SKU"""
    try:
        ok = db.delete_sku(sku_id)
        if not ok:
            return error("删除 SKU 失败")
        return success(message="SKU 已删除")
    except Exception as e:
        return error(f"删除 SKU 失败: {str(e)}")


# ============== 平台列表 ==============
PLATFORM_NAMES = {
    "aliexpress": "速卖通",
    "amazon": "亚马逊",
    "shopee": "Shopee",
    "temu": "Temu",
    "tiktok": "TikTok Shop",
    "lazada": "Lazada",
    "ebay": "eBay",
    "shopify": "Shopify",
    "1688": "1688",
}


@router.get("/platforms")
async def list_platforms():
    """获取支持的平台列表"""
    return success([{"code": k, "name": v} for k, v in PLATFORM_NAMES.items()])


# ============== 采集历史 ==============
@router.get("/collect-history")
async def list_collect_history(limit: int = Query(50, ge=1, le=200)):
    """获取采集历史"""
    try:
        history = db.get_collect_history(limit=limit)
        return success(history)
    except Exception as e:
        return error(f"获取采集历史失败: {str(e)}")
