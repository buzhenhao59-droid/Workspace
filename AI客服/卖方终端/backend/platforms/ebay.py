# -*- coding: utf-8 -*-
"""
eBay 开放平台 API 客户端
文档: https://developer.ebay.com/
"""
import time
import requests
import base64
from typing import List
from . import BasePlatformClient


class EbayClient(BasePlatformClient):
    """eBay 开放平台"""

    def __init__(self, api_url: str = "", api_key: str = "", api_secret: str = "",
                 access_token: str = "", seller_id: str = ""):
        super().__init__(api_url, api_key, api_secret, access_token, seller_id)
        self._session = requests.Session()

    def _get_headers(self) -> dict:
        """生成请求头"""
        credentials = base64.b64encode(f"{self.api_key}:{self.api_secret}".encode()).decode()
        return {
            "Authorization": f"Basic {credentials}",
            "X-EBAY-SOA-SECURITY-TOKEN": self.access_token,
            "X-EBAY-SOA-CONSUMER-ID": self.api_key,
            "Content-Type": "application/json",
        }

    def _request(self, endpoint: str, params: dict = None, method: str = "GET") -> dict:
        """发送请求"""
        if not self.is_configured:
            raise ConnectionError("eBay API 未配置")

        url = f"{self.api_url}/{endpoint.lstrip('/')}"
        headers = self._get_headers()
        resp = self._session.request(method, url, json=params if method == "POST" else None,
                                     params=params if method == "GET" else None,
                                     headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if data.get("errorMessage"):
            raise ConnectionError(f"eBay API 错误: {data['errorMessage']}")
        return data

    def get_orders(self, status: str = "", start_date: str = "", end_date: str = "",
                   page: int = 1, page_size: int = 50) -> List[dict]:
        """获取订单列表"""
        params = {
            "Pagination": {"pageNumber": page, "entriesPerPage": min(page_size, 100)},
            "Sorting": [{"SortAttribute": "CreationDate", "SortOrder": "Descending"}],
        }
        if start_date:
            params["CreateTimeFrom"] = start_date
        if end_date:
            params["CreateTimeTo"] = end_date
        if status:
            params["OrderStatus"] = status.upper()

        data = self._request("buy/order/v1/order", params, method="POST")
        orders = data.get("orders", [])
        return [self._normalize_order({
            **o,
            "order_id": o.get("orderId", ""),
            "customer_id": o.get("buyer", {}).get("buyerId", ""),
            "customer_name": o.get("buyer", {}).get("fullName", ""),
            "total_amount": float(o.get("total", {}).get("value", 0)),
            "currency": o.get("total", {}).get("currency", "USD"),
            "created_at": o.get("creationDate", ""),
            "status": o.get("orderPaymentStatus", ""),
        }) for o in orders]

    def get_order_detail(self, order_id: str) -> dict:
        """获取订单详情"""
        data = self._request(f"buy/order/v1/order/{order_id}")
        return self._normalize_order(data)

    def get_returns(self, status: str = "", page: int = 1, page_size: int = 50) -> List[dict]:
        """获取退货列表"""
        params = {"offset": (page - 1) * page_size, "limit": min(page_size, 50)}
        if status:
            params["state"] = status
        data = self._request("post-order/v2/return", params)
        returns = data.get("members", [])
        return [self._normalize_return({
            **r,
            "return_id": r.get("returnId", ""),
            "order_id": r.get("item", {}).get("lineItemId", ""),
            "status": r.get("state", ""),
            "reason": r.get("reasonForUser", ""),
        }) for r in returns]

    def get_reviews(self, status: str = "", page: int = 1, page_size: int = 50) -> List[dict]:
        """eBay 评价 API 需单独申请，返回空"""
        return []

    def reply_review(self, review_id: str, content: str) -> bool:
        """eBay 不支持 API 回复评价"""
        return False
