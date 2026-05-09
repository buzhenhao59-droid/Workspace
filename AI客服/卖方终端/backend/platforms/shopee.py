# -*- coding: utf-8 -*-
"""
Shopee 开放平台 API 客户端
文档: https://open.shopee.com/
"""
import hashlib
import hmac
import time
import requests
from typing import List, Dict
from . import BasePlatformClient


class ShopeeClient(BasePlatformClient):
    """Shopee 开放平台"""

    def __init__(self, api_url: str = "", api_key: str = "", api_secret: str = "",
                 access_token: str = "", shop_id: str = ""):
        super().__init__(api_url, api_key, api_secret, access_token, shop_id)
        self.partner_id = ""
        self._session = requests.Session()

    def _generate_signature(self, url: str, params: dict) -> str:
        """生成 Shopee 签名"""
        base_str = self.api_secret
        sorted_params = sorted(params.items())
        param_str = "&".join(f"{k}={v}" for k, v in sorted_params)
        sign_str = f"{url}\n{param_str}"
        return hmac.new(self.api_secret.encode(), sign_str.encode(), hashlib.sha256).hexdigest().upper()

    def _request(self, endpoint: str, params: dict = None, method: str = "POST") -> dict:
        """发送带签名的请求"""
        if not self.is_configured:
            raise ConnectionError("Shopee API 未配置")

        ts = int(time.time())
        params = params or {}
        params.update({
            "partner_id": int(self._extra.get("partner_id", 0)),
            "shopid": int(self.shop_id or 0),
            "timestamp": ts,
            "access_token": self.access_token,
        })

        url = f"{self.api_url}/{endpoint.lstrip('/')}"
        resp = self._session.request(method, url, json=params if method == "POST" else None,
                                      params=params if method == "GET" else None,
                                      timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if data.get("error"):
            raise ConnectionError(f"Shopee API 错误: {data.get('error_description', data['error'])}")
        return data

    def get_orders(self, status: str = "", start_date: str = "", end_date: str = "",
                   page: int = 1, page_size: int = 50) -> List[dict]:
        """获取订单列表"""
        status_map = {
            "pending": "unpaid", "paid": "paid", "shipped": "shipped",
            "completed": "completed", "cancelled": "cancelled",
            "": "all"
        }
        params = {
            "order_status": status_map.get(status.lower(), "all"),
            "page_size": min(page_size, 100),
            "cursor": (page - 1) * page_size,
            "create_time_from": int(time.mktime(time.strptime(start_date, "%Y-%m-%d"))) if start_date else 0,
            "create_time_to": int(time.mktime(time.strptime(end_date, "%Y-%m-%d"))) if end_date else int(time.time()),
        }
        data = self._request("/api/v2/order/get_orders", params)
        orders = data.get("order_list", [])
        return [self._normalize_order(o) for o in orders]

    def get_order_detail(self, order_id: str) -> dict:
        """获取订单详情"""
        data = self._request("/api/v2/order/get_order_detail", {"order_id": order_id})
        o = data.get("order", {})
        items = data.get("item_list", [])
        o["items_count"] = len(items)
        return self._normalize_order(o)

    def get_returns(self, status: str = "", page: int = 1, page_size: int = 50) -> List[dict]:
        """获取退货退款列表"""
        params = {"page_size": page_size, "cursor": (page - 1) * page_size}
        if status:
            params["status"] = status
        data = self._request("/api/v2/return/get_return_list", params)
        returns = data.get("return_list", [])
        return [self._normalize_return(r) for r in returns]

    def get_reviews(self, status: str = "", page: int = 1, page_size: int = 50) -> List[dict]:
        """获取商品评价"""
        params = {"page_size": page_size, "offset": (page - 1) * page_size}
        data = self._request("/api/v2/product/get_item_comment", params)
        reviews = data.get("comment_list", [])
        return [self._normalize_review(r) for r in reviews]

    def reply_review(self, review_id: str, content: str) -> bool:
        """回复评价"""
        try:
            self._request("/api/v2/product/add_item_comment", {
                "order_id": review_id, "comment_text": content, "rating": 5
            })
            return True
        except Exception:
            return False

    def get_shipments(self, order_id: str) -> List[dict]:
        """获取物流信息"""
        try:
            data = self._request("/api/v2/logistics/get_shipment_list", {"order_id": order_id})
            return data.get("shipment_list", [])
        except Exception:
            return []
