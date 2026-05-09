# -*- coding: utf-8 -*-
"""
Shopify 开放平台 API 客户端
文档: https://shopify.dev/docs/api/admin-rest
"""
import time
import requests
from typing import List
from . import BasePlatformClient


class ShopifyClient(BasePlatformClient):
    """Shopify 开放平台"""

    def __init__(self, api_url: str = "", api_key: str = "", api_secret: str = "",
                 access_token: str = "", shop_domain: str = ""):
        super().__init__(api_url, api_key, api_secret, access_token, shop_domain)
        self._session = requests.Session()

    def _get_headers(self) -> dict:
        return {
            "X-Shopify-Access-Token": self.access_token,
            "Content-Type": "application/json",
        }

    def _request(self, endpoint: str, params: dict = None, method: str = "GET") -> dict:
        """发送请求"""
        if not self.is_configured:
            raise ConnectionError("Shopify API 未配置")

        url = f"https://{self.shop_domain}/admin/api/2024-01/{endpoint.lstrip('/')}"
        querystring = ""
        if params and method == "GET":
            querystring = "&".join(f"{k}={v}" for k, v in params.items() if v)
            url = f"{url}?{querystring}"
        resp = self._session.request(method, url, json=params if method != "GET" else None,
                                     headers=self._get_headers(), timeout=30)
        resp.raise_for_status()
        return resp.json()

    def get_orders(self, status: str = "", start_date: str = "", end_date: str = "",
                   page: int = 1, page_size: int = 50) -> List[dict]:
        """获取订单列表"""
        status_map = {"pending": "any", "paid": "paid", "shipped": "fulfilled",
                      "completed": "closed", "cancelled": "cancelled"}
        params = {
            "status": status_map.get(status.lower(), "any"),
            "limit": min(page_size, 250),
            "page": page,
        }
        if start_date:
            params["created_at_min"] = start_date
        if end_date:
            params["created_at_max"] = end_date

        data = self._request("orders.json", params)
        orders = data.get("orders", [])
        return [self._normalize_order({
            **o,
            "order_id": str(o.get("id", "")),
            "customer_id": str(o.get("customer", {}).get("id", "")),
            "customer_name": f"{o.get('customer', {}).get('first_name', '')} {o.get('customer', {}).get('last_name', '')}".strip(),
            "total_amount": float(o.get("total_price", 0)),
            "currency": o.get("currency", "USD"),
            "created_at": o.get("created_at", ""),
            "status": o.get("financial_status", ""),
            "shipping_address": f"{o.get('shipping_address', {}).get('address1', '')} "
                                f"{o.get('shipping_address', {}).get('city', '')} "
                                f"{o.get('shipping_address', {}).get('country', '')}",
        }) for o in orders]

    def get_order_detail(self, order_id: str) -> dict:
        """获取订单详情"""
        data = self._request(f"orders/{order_id}.json")
        o = data.get("order", {})
        return self._normalize_order(o)

    def get_returns(self, status: str = "", page: int = 1, page_size: int = 50) -> List[dict]:
        """Shopify 退货用 Refund API 代替"""
        params = {"limit": min(page_size, 100), "page": page}
        data = self._request("refunds.json", params)
        refunds = data.get("refunds", [])
        return [self._normalize_return({
            **r,
            "return_id": str(r.get("id", "")),
            "order_id": str(r.get("order_id", "")),
            "created_at": r.get("created_at", ""),
        }) for r in refunds]

    def get_reviews(self, status: str = "", page: int = 1, page_size: int = 50) -> List[dict]:
        """Shopify 原生无评价 API（需用 Yotpo / Judge.me 等插件），返回空"""
        return []

    def reply_review(self, review_id: str, content: str) -> bool:
        """需通过第三方插件 API，这里不支持"""
        return False

    def get_shipments(self, order_id: str) -> List[dict]:
        """获取物流信息"""
        try:
            data = self._request(f"orders/{order_id}/fulfillments.json")
            return data.get("fulfillments", [])
        except Exception:
            return []
