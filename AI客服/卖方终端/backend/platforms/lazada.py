# -*- coding: utf-8 -*-
"""
Lazada 开放平台 API 客户端
文档: https://open.lazada.com/
"""
import time
import requests
import hmac
import hashlib
from typing import List
from . import BasePlatformClient


class LazadaClient(BasePlatformClient):
    """Lazada 开放平台"""

    def __init__(self, api_url: str = "", api_key: str = "", api_secret: str = "",
                 access_token: str = "", shop_id: str = ""):
        super().__init__(api_url, api_key, api_secret, access_token, shop_id)
        self._session = requests.Session()

    def _sign_params(self, params: dict) -> dict:
        """生成 Lazada 签名"""
        params["app_key"] = self.api_key
        params["timestamp"] = str(int(time.time() * 1000))
        params["access_token"] = self.access_token
        sorted_keys = sorted(params.keys())
        pairs = "".join(f"{k}{params[k]}" for k in sorted_keys)
        sign = hmac.new(self.api_secret.encode(), pairs.encode(), hashlib.sha256).hexdigest().upper()
        params["sign"] = sign
        return params

    def _request(self, endpoint: str, params: dict = None, method: str = "POST") -> dict:
        """发送请求"""
        if not self.is_configured:
            raise ConnectionError("Lazada API 未配置")

        url = f"{self.api_url}/{endpoint.lstrip('/')}"
        params = params or {}
        params = self._sign_params(params)
        resp = self._session.request(method, url, data=params if method == "POST" else None,
                                     params=params if method == "GET" else None,
                                     timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != "0":
            raise ConnectionError(f"Lazada API 错误: {data.get('message', data.get('code', ''))}")
        return data.get("data", {})

    def get_orders(self, status: str = "", start_date: str = "", end_date: str = "",
                   page: int = 1, page_size: int = 50) -> List[dict]:
        """获取订单列表"""
        params = {
            "sort_by": "created_at",
            "sort_direction": "DESC",
            "page_no": page,
            "page_size": min(page_size, 100),
        }
        if status:
            params["status"] = status
        if start_date:
            params["create_after"] = start_date
        if end_date:
            params["create_before"] = end_date

        data = self._request("orders/get", params)
        orders = data.get("orders", [])
        return [self._normalize_order({
            **o,
            "order_id": o.get("order_id", ""),
            "customer_id": o.get("buyer_id", ""),
            "customer_name": o.get("customer_first_name", "") + o.get("customer_last_name", ""),
            "total_amount": float(o.get("price", 0)),
            "currency": o.get("currency", "USD"),
            "created_at": o.get("created_at", ""),
            "status": o.get("status", ""),
        }) for o in orders]

    def get_order_detail(self, order_id: str) -> dict:
        """获取订单详情"""
        data = self._request("orders/items/get", {"order_id": order_id})
        items = data.get("order_items", {}).get("order_item", [])
        return {
            "order_id": order_id,
            "platform": "lazada",
            "items": items,
            "items_count": len(items),
        }

    def get_returns(self, status: str = "", page: int = 1, page_size: int = 50) -> List[dict]:
        """获取退货列表"""
        params = {"page_no": page, "page_size": min(page_size, 100)}
        if status:
            params["status"] = status
        data = self._request("returns/get", params)
        returns = data.get("result", {}).get("return_list", [])
        return [self._normalize_return(r) for r in returns]

    def get_reviews(self, status: str = "", page: int = 1, page_size: int = 50) -> List[dict]:
        """获取评价列表"""
        params = {"page_no": page, "page_size": min(page_size, 100)}
        data = self._request("rater/list", params)
        reviews = data.get("rater_list", [])
        return [self._normalize_review({
            **r,
            "review_id": r.get("id", ""),
            "order_id": r.get("order_id", ""),
            "star_rating": r.get("rating", 5),
            "content": r.get("review", ""),
            "customer_name": r.get("display_name", "匿名"),
            "product_name": r.get("item_name", ""),
        }) for r in reviews]

    def reply_review(self, review_id: str, content: str) -> bool:
        """回复评价"""
        try:
            self._request("order/rating/reply", {"rating_id": review_id, "reply_content": content})
            return True
        except Exception:
            return False
