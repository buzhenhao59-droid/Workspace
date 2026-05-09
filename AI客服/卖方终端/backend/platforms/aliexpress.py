# -*- coding: utf-8 -*-
"""
AliExpress (速卖通) 开放平台 API 客户端
文档: https://open.aliexpress.com/
"""
import time
import requests
import hashlib
from typing import List
from . import BasePlatformClient


class AliExpressClient(BasePlatformClient):
    """AliExpress (速卖通) 开放平台"""

    def __init__(self, api_url: str = "", api_key: str = "", api_secret: str = "",
                 access_token: str = "", app_id: str = ""):
        super().__init__(api_url, api_key, api_secret, access_token, app_id)
        self._session = requests.Session()

    def _generate_signature(self, params: dict) -> str:
        """生成签名"""
        sorted_items = sorted(params.items())
        sign_str = "".join(f"{k}{v}" for k, v in sorted_items) + self.api_secret
        return hashlib.md5(sign_str.encode()).hexdigest().upper()

    def _request(self, endpoint: str, params: dict = None, method: str = "POST") -> dict:
        """发送请求"""
        if not self.is_configured:
            raise ConnectionError("AliExpress API 未配置")

        url = f"{self.api_url}/{endpoint.lstrip('/')}"
        params = params or {}
        params.update({
            "appKey": self.api_key,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
            "access_token": self.access_token,
        })
        params["sign"] = self._generate_signature(params)

        resp = self._session.request(method, url, json=params if method == "POST" else None,
                                     params=params if method == "GET" else None,
                                     timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if data.get("errorCode") or data.get("error_code"):
            raise ConnectionError(f"AliExpress API 错误: {data.get('errorMessage', data)}")
        return data.get("result", {})

    def get_orders(self, status: str = "", start_date: str = "", end_date: str = "",
                   page: int = 1, page_size: int = 50) -> List[dict]:
        """获取订单列表"""
        params = {
            "pageSize": min(page_size, 100),
            "currentPage": page,
        }
        if start_date:
            params["createDateStart"] = start_date
        if end_date:
            params["createDateEnd"] = end_date
        if status:
            params["orderStatus"] = status

        data = self._request("aliexpress.dataprovider.realtimeorderquery", params)
        orders = data.get("orderList", {}).get("orderList", [])
        return [self._normalize_order({
            **o,
            "order_id": o.get("orderId", ""),
            "customer_id": o.get("buyerId", ""),
            "customer_name": o.get("buyerLoginId", ""),
            "total_amount": float(o.get("totalAmount", 0)),
            "currency": o.get("currencyCode", "USD"),
            "created_at": o.get("gmtCreate", ""),
            "status": o.get("orderStatus", ""),
        }) for o in orders]

    def get_order_detail(self, order_id: str) -> dict:
        """获取订单详情"""
        data = self._request("aliexpress.logistics.realtimeorderquery", {"orderId": order_id})
        return self._normalize_order(data)

    def get_returns(self, status: str = "", page: int = 1, page_size: int = 50) -> List[dict]:
        """获取退货列表"""
        params = {"currentPage": page, "pageSize": min(page_size, 50)}
        if status:
            params["refundStatus"] = status
        data = self._request("aliexpress.refunds.realtimeorderquery", params)
        returns = data.get("refundList", [])
        return [self._normalize_return(r) for r in returns]

    def get_reviews(self, status: str = "", page: int = 1, page_size: int = 50) -> List[dict]:
        """获取评价列表"""
        params = {"currentPage": page, "pageSize": min(page_size, 50)}
        data = self._request("aliexpress.message.realtimeorderquery", params)
        return [self._normalize_review(r) for r in data.get("reviewList", [])]

    def reply_review(self, review_id: str, content: str) -> bool:
        """回复评价"""
        try:
            self._request("aliexpress.message.realtimeorderquery",
                         {"reviewId": review_id, "replyContent": content})
            return True
        except Exception:
            return False
