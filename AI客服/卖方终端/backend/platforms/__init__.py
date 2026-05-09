# -*- coding: utf-8 -*-
"""
跨境电商平台统一抽象层
所有平台（Shopee / Amazon / TikTok / Lazada / AliExpress / eBay / Shopify）
均实现此接口，保证后端业务逻辑与具体平台解耦

接口规范：
- get_orders(status, start_date, end_date, page, page_size) -> list[dict]
- get_order_detail(order_id) -> dict
- get_returns(status, page, page_size) -> list[dict]
- get_reviews(status, page, page_size) -> list[dict]
- reply_review(review_id, content) -> bool
- get_shipments(order_id) -> list[dict]
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Optional, Any
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class BasePlatformClient(ABC):
    """平台 API 客户端基类"""

    def __init__(self, api_url: str = "", api_key: str = "", api_secret: str = "",
                 access_token: str = "", shop_id: str = "", **kwargs):
        self.api_url = api_url.rstrip("/") if api_url else ""
        self.api_key = api_key
        self.api_secret = api_secret
        self.access_token = access_token
        self.shop_id = shop_id
        self._extra = kwargs

    @property
    def platform_name(self) -> str:
        return self.__class__.__name__.replace("Client", "")

    @property
    def is_configured(self) -> bool:
        """判断是否已配置必要的凭证"""
        return bool(self.api_key or self.access_token)

    def _fmt_date(self, dt) -> str:
        """统一日期格式"""
        if isinstance(dt, datetime):
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        if isinstance(dt, str):
            return dt
        return ""

    def _normalize_order(self, raw: dict) -> dict:
        """将各平台原始订单数据格式化为统一结构"""
        return {
            "order_id": str(raw.get("order_id", raw.get("order_sn", raw.get("id", "")))),
            "platform": self.platform_name.lower(),
            "customer_id": str(raw.get("customer_id", raw.get("buyer_id", raw.get("user_id", "")))),
            "customer_name": raw.get("customer_name", raw.get("buyer_name", "")),
            "status": raw.get("status", raw.get("order_status", "")),
            "total_amount": float(raw.get("total_amount", raw.get("total_price", raw.get("amount", 0)))),
            "currency": raw.get("currency", "USD"),
            "items_count": raw.get("items_count", raw.get("product_count", 1)),
            "payment_method": raw.get("payment_method", ""),
            "shipping_address": raw.get("shipping_address", ""),
            "created_at": self._fmt_date(raw.get("created_at", raw.get("create_time", raw.get("date_added", "")))),
            "updated_at": self._fmt_date(raw.get("updated_at", raw.get("update_time", ""))),
            "notes": raw.get("notes", ""),
        }

    def _normalize_review(self, raw: dict) -> dict:
        """将各平台原始评价数据格式化为统一结构"""
        return {
            "review_id": str(raw.get("review_id", raw.get("id", ""))),
            "order_id": str(raw.get("order_id", raw.get("order_sn", ""))),
            "customer_id": str(raw.get("customer_id", raw.get("user_id", ""))),
            "customer_name": raw.get("customer_name", raw.get("user_name", "匿名用户")),
            "star_rating": int(raw.get("star_rating", raw.get("rating", raw.get("stars", 5)))),
            "content": raw.get("content", raw.get("comment", raw.get("review_content", ""))),
            "platform": self.platform_name.lower(),
            "product_name": raw.get("product_name", raw.get("item_name", "")),
            "product_image": raw.get("product_image", raw.get("image_url", "")),
            "reply_content": raw.get("reply_content", ""),
            "status": raw.get("status", "pending"),
            "review_date": self._fmt_date(raw.get("review_date", raw.get("create_time", ""))),
            "replied_at": self._fmt_date(raw.get("replied_at", "")),
        }

    def _normalize_return(self, raw: dict) -> dict:
        """将各平台原始退换货数据格式化为统一结构"""
        return {
            "return_id": str(raw.get("return_id", raw.get("id", ""))),
            "order_id": str(raw.get("order_id", raw.get("order_sn", ""))),
            "customer_id": str(raw.get("customer_id", raw.get("user_id", ""))),
            "customer_name": raw.get("customer_name", ""),
            "type": raw.get("type", raw.get("return_type", "退货退款")),
            "reason": raw.get("reason", ""),
            "status": raw.get("status", "pending"),
            "amount": float(raw.get("amount", 0)),
            "currency": raw.get("currency", "USD"),
            "created_at": self._fmt_date(raw.get("created_at", raw.get("create_time", ""))),
            "updated_at": self._fmt_date(raw.get("updated_at", "")),
            "description": raw.get("description", ""),
            "platform": self.platform_name.lower(),
        }

    # === 以下方法由子类实现 ===

    @abstractmethod
    def get_orders(self, status: str = "", start_date: str = "", end_date: str = "",
                   page: int = 1, page_size: int = 50) -> List[dict]:
        """获取订单列表"""
        pass

    @abstractmethod
    def get_order_detail(self, order_id: str) -> dict:
        """获取订单详情"""
        pass

    def get_returns(self, status: str = "", page: int = 1, page_size: int = 50) -> List[dict]:
        """获取退换货列表（默认返回空，子类可覆盖）"""
        return []

    def get_reviews(self, status: str = "", page: int = 1, page_size: int = 50) -> List[dict]:
        """获取评价列表（默认返回空，子类可覆盖）"""
        return []

    def reply_review(self, review_id: str, content: str) -> bool:
        """回复评价（默认不支持）"""
        return False

    def get_shipments(self, order_id: str) -> List[dict]:
        """获取物流信息（默认返回空，子类可覆盖）"""
        return []

    def health_check(self) -> dict:
        """平台连接健康检查"""
        if not self.is_configured:
            return {"ok": False, "message": "未配置 API 凭证"}
        try:
            orders = self.get_orders(page=1, page_size=1)
            return {"ok": True, "message": "连接正常", "order_count_hint": len(orders)}
        except Exception as e:
            return {"ok": False, "message": str(e)}
