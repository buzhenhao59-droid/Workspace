# -*- coding: utf-8 -*-
"""
TikTok Shop 开放平台 API 客户端
文档: https://partner.tiktok.com/
"""
import time
import requests
import hmac
import hashlib
from typing import List, Dict
from . import BasePlatformClient


class TikTokClient(BasePlatformClient):
    """TikTok Shop 开放平台"""

    def __init__(self, api_url: str = "", api_key: str = "", api_secret: str = "",
                 access_token: str = "", shop_id: str = ""):
        super().__init__(api_url, api_key, api_secret, access_token, shop_id)
        self._session = requests.Session()

    def _get_headers(self) -> dict:
        """生成请求头"""
        ts = str(int(time.time()))
        sign = hmac.new(
            self.api_secret.encode(),
            f"{self.api_key}{ts}".encode(),
            hashlib.sha256
        ).hexdigest()
        return {
            "Content-Type": "application/json",
            "x-tbh-access-token": self.access_token,
            "x-tbh-app-key": self.api_key,
            "x-tbh-timestamp": ts,
            "x-tbh-signature": sign,
        }

    def _request(self, endpoint: str, params: dict = None, method: str = "GET") -> dict:
        """发送请求"""
        if not self.is_configured:
            raise ConnectionError("TikTok API 未配置")

        url = f"{self.api_url}/{endpoint.lstrip('/')}"
        headers = self._get_headers()
        resp = self._session.request(method, url, json=params if method == "POST" else None,
                                     params=params if method == "GET" else None,
                                     headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        code = data.get("code", 0)
        if code != 0:
            raise ConnectionError(f"TikTok API 错误 [{code}]: {data.get('message', '')}")
        return data.get("data", {})

    def get_orders(self, status: str = "", start_date: str = "", end_date: str = "",
                   page: int = 1, page_size: int = 50) -> List[dict]:
        """获取订单列表"""
        params = {
            "shop_id": self.shop_id,
            "page_size": min(page_size, 50),
            "cursor": (page - 1) * page_size,
            "create_time_to": end_date or "",
            "create_time_from": start_date or "",
        }
        if status:
            params["order_status"] = status
        data = self._request("api/orders/search", params, method="POST")
        orders = data.get("orders", [])
        return [self._normalize_order(o) for o in orders]

    def get_order_detail(self, order_id: str) -> dict:
        """获取订单详情"""
        data = self._request("api/orders/detail", {"order_id": order_id, "shop_id": self.shop_id})
        o = data.get("order_info", {})
        return self._normalize_order(o)

    def get_returns(self, status: str = "", page: int = 1, page_size: int = 50) -> List[dict]:
        """获取退货列表"""
        params = {"shop_id": self.shop_id, "page_size": page_size, "cursor": (page - 1) * page_size}
        if status:
            params["status"] = status
        data = self._request("api/aftersale/search", params, method="POST")
        returns = data.get("aftersale_records", [])
        return [self._normalize_return(r) for r in returns]

    def get_reviews(self, status: str = "", page: int = 1, page_size: int = 50) -> List[dict]:
        """获取评价列表"""
        params = {"shop_id": self.shop_id, "page_size": page_size, "cursor": (page - 1) * page_size}
        data = self._request("api/reviews/list", params, method="POST")
        reviews = data.get("review_list", [])
        return [self._normalize_review(r) for r in reviews]

    def reply_review(self, review_id: str, content: str) -> bool:
        """回复评价"""
        try:
            self._request("api/reviews/reply", {
                "review_id": review_id, "content": content
            }, method="POST")
            return True
        except Exception:
            return False
