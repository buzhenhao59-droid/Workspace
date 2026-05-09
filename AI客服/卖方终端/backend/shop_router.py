# -*- coding: utf-8 -*-
"""
店铺管理系统 API 路由
"""
import logging
from typing import Optional
from datetime import datetime
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from shop_api import (
    # 店铺
    create_shop, get_shops, get_shop_by_id, update_shop, delete_shop, test_shop_connection,
    # 商品
    create_product, get_products, get_product_by_id, update_product, delete_product,
    # SKU
    create_sku, update_sku, delete_sku,
    # 采集
    collect_product_from_source,
    # 刊登
    publish_products, get_shop_products,
    # 库存
    get_inventory, update_inventory, sync_inventory,
    # 定价
    create_pricing_rule, get_pricing_rules, calculate_price_by_rule, delete_pricing_rule,
    # 分类
    get_categories, create_category,
    # 统计
    get_dashboard_stats,
    PLATFORM_NAMES,
    ShopCreate, ShopUpdate, ProductCreate, ProductUpdate, SKUCreate, PricingRuleCreate, 
    PublishRequest, CollectRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/shop", tags=["店铺管理"])


# ============== 请求模型 ==============
class IdRequest(BaseModel):
    id: int


class BatchIdsRequest(BaseModel):
    ids: list[int]


# ============== 店铺接口 ==============
@router.post("/shops")
async def api_create_shop(data: ShopCreate):
    """创建店铺"""
    try:
        result = create_shop(data)
        return {"success": True, "data": result}
    except Exception as e:
        logger.error(f"创建店铺失败: {e}")
        return {"success": False, "message": str(e)}


@router.get("/shops")
async def api_get_shops(
    platform: str = Query(None, description="平台筛选"),
    status: str = Query(None, description="状态筛选"),
):
    """获取店铺列表"""
    try:
        shops = get_shops(platform=platform, status=status)
        return {"success": True, "data": shops}
    except Exception as e:
        logger.error(f"获取店铺列表失败: {e}")
        return {"success": False, "message": str(e)}


@router.get("/shops/{shop_id}")
async def api_get_shop(shop_id: int):
    """获取单个店铺"""
    try:
        shop = get_shop_by_id(shop_id)
        if not shop:
            raise HTTPException(status_code=404, detail="店铺不存在")
        return {"success": True, "data": shop}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取店铺失败: {e}")
        return {"success": False, "message": str(e)}


@router.put("/shops/{shop_id}")
async def api_update_shop(shop_id: int, data: ShopUpdate):
    """更新店铺"""
    try:
        result = update_shop(shop_id, data)
        return {"success": True, "data": result}
    except Exception as e:
        logger.error(f"更新店铺失败: {e}")
        return {"success": False, "message": str(e)}


@router.delete("/shops/{shop_id}")
async def api_delete_shop(shop_id: int):
    """删除店铺"""
    try:
        success = delete_shop(shop_id)
        return {"success": success, "message": "删除成功" if success else "删除失败"}
    except Exception as e:
        logger.error(f"删除店铺失败: {e}")
        return {"success": False, "message": str(e)}


@router.post("/shops/{shop_id}/test")
async def api_test_shop_connection(shop_id: int):
    """测试店铺连接"""
    try:
        result = test_shop_connection(shop_id)
        return {"success": result['success'], "message": result['message']}
    except Exception as e:
        logger.error(f"测试店铺连接失败: {e}")
        return {"success": False, "message": str(e)}


@router.get("/platforms")
async def api_get_platforms():
    """获取支持的平台列表"""
    platforms = []
    for code, name in PLATFORM_NAMES.items():
        platforms.append({"code": code, "name": name})
    return {"success": True, "data": platforms}


# ============== 商品接口 ==============
@router.post("/products")
async def api_create_product(data: ProductCreate):
    """创建商品"""
    try:
        result = create_product(data)
        return {"success": True, "data": result}
    except Exception as e:
        logger.error(f"创建商品失败: {e}")
        return {"success": False, "message": str(e)}


@router.get("/products")
async def api_get_products(
    status: str = Query(None, description="商品状态"),
    category_id: int = Query(None, description="分类ID"),
    source_platform: str = Query(None, description="货源平台"),
    page: int = Query(1, description="页码"),
    page_size: int = Query(20, description="每页数量"),
):
    """获取商品列表"""
    try:
        result = get_products(
            status=status,
            category_id=category_id,
            source_platform=source_platform,
            page=page,
            page_size=page_size
        )
        return {"success": True, "data": result}
    except Exception as e:
        logger.error(f"获取商品列表失败: {e}")
        return {"success": False, "message": str(e)}


@router.get("/products/{product_id}")
async def api_get_product(product_id: int):
    """获取单个商品（含SKU）"""
    try:
        product = get_product_by_id(product_id)
        if not product:
            raise HTTPException(status_code=404, detail="商品不存在")
        return {"success": True, "data": product}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取商品失败: {e}")
        return {"success": False, "message": str(e)}


@router.put("/products/{product_id}")
async def api_update_product(product_id: int, data: ProductUpdate):
    """更新商品"""
    try:
        result = update_product(product_id, data)
        return {"success": True, "data": result}
    except Exception as e:
        logger.error(f"更新商品失败: {e}")
        return {"success": False, "message": str(e)}


@router.delete("/products/{product_id}")
async def api_delete_product(product_id: int):
    """删除商品"""
    try:
        success = delete_product(product_id)
        return {"success": success, "message": "删除成功" if success else "删除失败"}
    except Exception as e:
        logger.error(f"删除商品失败: {e}")
        return {"success": False, "message": str(e)}


# ============== SKU接口 ==============
@router.post("/skus")
async def api_create_sku(data: SKUCreate):
    """创建SKU"""
    try:
        result = create_sku(data)
        return {"success": True, "data": result}
    except Exception as e:
        logger.error(f"创建SKU失败: {e}")
        return {"success": False, "message": str(e)}


@router.put("/skus/{sku_id}")
async def api_update_sku(sku_id: int, data: dict):
    """更新SKU"""
    try:
        result = update_sku(sku_id, data)
        return {"success": True, "data": result}
    except Exception as e:
        logger.error(f"更新SKU失败: {e}")
        return {"success": False, "message": str(e)}


@router.delete("/skus/{sku_id}")
async def api_delete_sku(sku_id: int):
    """删除SKU"""
    try:
        success = delete_sku(sku_id)
        return {"success": success, "message": "删除成功" if success else "删除失败"}
    except Exception as e:
        logger.error(f"删除SKU失败: {e}")
        return {"success": False, "message": str(e)}


# ============== 采集接口 ==============
@router.post("/collect")
async def api_collect_product(data: CollectRequest):
    """采集商品"""
    try:
        result = collect_product_from_source(data)
        return result
    except Exception as e:
        logger.error(f"采集商品失败: {e}")
        return {"success": False, "message": str(e)}


# ============== 刊登接口 ==============
@router.post("/publish")
async def api_publish_products(data: PublishRequest):
    """批量刊登商品"""
    try:
        result = publish_products(data)
        return result
    except Exception as e:
        logger.error(f"刊登商品失败: {e}")
        return {"success": False, "message": str(e)}


@router.get("/shop-products")
async def api_get_shop_products(
    shop_id: int = Query(None, description="店铺ID"),
    product_id: int = Query(None, description="商品ID"),
    publish_status: str = Query(None, description="刊登状态"),
    page: int = Query(1, description="页码"),
    page_size: int = Query(20, description="每页数量"),
):
    """获取店铺商品列表"""
    try:
        result = get_shop_products(
            shop_id=shop_id,
            product_id=product_id,
            publish_status=publish_status,
            page=page,
            page_size=page_size
        )
        return {"success": True, "data": result}
    except Exception as e:
        logger.error(f"获取店铺商品列表失败: {e}")
        return {"success": False, "message": str(e)}


# ============== 库存接口 ==============
@router.get("/inventory")
async def api_get_inventory(
    sku_id: int = Query(None, description="SKU ID"),
    shop_id: int = Query(None, description="店铺ID"),
):
    """获取库存"""
    try:
        result = get_inventory(sku_id=sku_id, shop_id=shop_id)
        return {"success": True, "data": result}
    except Exception as e:
        logger.error(f"获取库存失败: {e}")
        return {"success": False, "message": str(e)}


@router.put("/inventory")
async def api_update_inventory(
    sku_id: int,
    shop_id: int = None,
    available_stock: int = None,
    reserved_stock: int = None,
    total_stock: int = None,
):
    """更新库存"""
    try:
        result = update_inventory(sku_id, shop_id, available_stock, reserved_stock, total_stock)
        return result
    except Exception as e:
        logger.error(f"更新库存失败: {e}")
        return {"success": False, "message": str(e)}


@router.post("/inventory/{shop_id}/sync")
async def api_sync_inventory(shop_id: int):
    """同步店铺库存"""
    try:
        result = sync_inventory(shop_id)
        return result
    except Exception as e:
        logger.error(f"同步库存失败: {e}")
        return {"success": False, "message": str(e)}


# ============== 定价规则接口 ==============
@router.post("/pricing-rules")
async def api_create_pricing_rule(data: PricingRuleCreate):
    """创建定价规则"""
    try:
        result = create_pricing_rule(data)
        return {"success": True, "data": result}
    except Exception as e:
        logger.error(f"创建定价规则失败: {e}")
        return {"success": False, "message": str(e)}


@router.get("/pricing-rules")
async def api_get_pricing_rules(
    platform: str = Query(None, description="平台"),
    shop_id: int = Query(None, description="店铺ID"),
    rule_type: str = Query(None, description="规则类型"),
    is_active: bool = Query(None, description="是否启用"),
):
    """获取定价规则列表"""
    try:
        result = get_pricing_rules(
            platform=platform,
            shop_id=shop_id,
            rule_type=rule_type,
            is_active=is_active
        )
        return {"success": True, "data": result}
    except Exception as e:
        logger.error(f"获取定价规则列表失败: {e}")
        return {"success": False, "message": str(e)}


@router.delete("/pricing-rules/{rule_id}")
async def api_delete_pricing_rule(rule_id: int):
    """删除定价规则"""
    try:
        success = delete_pricing_rule(rule_id)
        return {"success": success, "message": "删除成功" if success else "删除失败"}
    except Exception as e:
        logger.error(f"删除定价规则失败: {e}")
        return {"success": False, "message": str(e)}


@router.get("/calculate-price/{sku_id}")
async def api_calculate_price(
    sku_id: int,
    shop_id: int = Query(None, description="店铺ID"),
    platform: str = Query(None, description="平台"),
):
    """计算价格"""
    try:
        result = calculate_price_by_rule(sku_id, shop_id, platform)
        return {"success": True, "data": result}
    except Exception as e:
        logger.error(f"计算价格失败: {e}")
        return {"success": False, "message": str(e)}


# ============== 分类接口 ==============
@router.get("/categories")
async def api_get_categories(
    parent_id: int = Query(None, description="父分类ID"),
    platform: str = Query(None, description="平台"),
):
    """获取分类列表"""
    try:
        result = get_categories(parent_id=parent_id, platform=platform)
        return {"success": True, "data": result}
    except Exception as e:
        logger.error(f"获取分类列表失败: {e}")
        return {"success": False, "message": str(e)}


@router.post("/categories")
async def api_create_category(name: str, name_en: str = None, parent_id: int = None, platform: str = None):
    """创建分类"""
    try:
        result = create_category(name, name_en, parent_id, platform)
        return {"success": True, "data": result}
    except Exception as e:
        logger.error(f"创建分类失败: {e}")
        return {"success": False, "message": str(e)}


# ============== 数据库初始化接口 ==============
@router.post("/init-database")
async def api_init_database():
    """初始化数据库表结构"""
    try:
        from shop_api import _init_sqlite_schema, _init_mysql_schema, _use_mysql
        if _use_mysql:
            _init_mysql_schema()
        else:
            _init_sqlite_schema()
        return {"success": True, "message": "数据库初始化成功"}
    except Exception as e:
        logger.error(f"数据库初始化失败: {e}")
        return {"success": False, "message": f"数据库初始化失败: {str(e)}"}


# ============== 仪表盘统计接口 ==============
@router.get("/stats")
async def api_get_stats():
    """获取仪表盘统计数据"""
    try:
        result = get_dashboard_stats()
        return {"success": True, "data": result}
    except Exception as e:
        logger.error(f"获取统计失败: {e}")
        return {"success": False, "message": str(e)}
