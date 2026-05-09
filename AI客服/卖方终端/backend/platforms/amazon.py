# -*- coding: utf-8 -*-
"""
Amazon Selling Partner API 客户端
文档: https://developer-docs.amazon.com/sp-api/
"""
import base64
import time
import requests
import hmac
import hashlib
import urllib.parse
from typing import List, Dict
from . import BasePlatformClient


class AmazonClient(BasePlatformClient):
    """Amazon Selling Partner API"""

    def __init__(self, api_url: str = "", api_key: str = "", api_secret: str = "",
                 access_token: str = "", seller_id: str = "", marketplace_id: str = ""):
        super().__init__(api_url, api_key, api_secret, access_token, seller_id)
        self.marketplace_id = marketplace_id
        self._session = requests.Session()

    def _get_aws_sig(self, method: str, url: str, body: str = "") -> dict:
        """生成 AWS Signature V4"""
        service = "execute-api"
        region = self._extra.get("region", "us-east-1")
        t = time.gmtime()
        amz_date = time.strftime("%Y%m%dT%H%M%SZ", t)
        date_stamp = time.strftime("%Y%m%d", t)

        # Canonical request
        canonical_uri = urllib.parse.urlparse(url).path
        canonical_querystring = urllib.parse.urlparse(url).query
        payload_hash = hashlib.sha256(body.encode()).hexdigest()
        canonical_headers = f"host:{urllib.parse.urlparse(url).netloc}\nx-amz-date:{amz_date}\n"
        signed_headers = "host;x-amz-date"
        canonical_request = f"{method}\n{canonical_uri}\n{canonical_querystring}\n{canonical_headers}\n{signed_headers}\n{payload_hash}"
        alg = "AWS4-HMAC-SHA256"
        credential_scope = f"{date_stamp}/{region}/{service}/aws4_request"
        string_to_sign = f"{alg}\n{amz_date}\n{credential_scope}\n{hashlib.sha256(canonical_request.encode()).hexdigest()}"
        k_date = hmac.new(("AWS4" + self.api_secret).encode(), date_stamp.encode(), hashlib.sha256).digest()
        k_region = hmac.new(k_date, region.encode(), hashlib.sha256).digest()
        k_service = hmac.new(k_region, service.encode(), hashlib.sha256).digest()
        k_signing = hmac.new(k_service, "aws4_request".encode(), hashlib.sha256).digest()
        signature = hmac.new(k_signing, string_to_sign.encode(), hashlib.sha256).hexdigest()
        auth_header = (f"{alg} Credential={self.api_key}/{credential_scope}, "
                       f"SignedHeaders={signed_headers}, Signature={signature}")
        return {
            "x-amz-date": amz_date,
            "Authorization": auth_header,
        }

    def _request(self, endpoint: str, params: dict = None, method: str = "GET") -> dict:
        """发送请求"""
        if not self.is_configured:
            raise ConnectionError("Amazon API 未配置")

        url = f"{self.api_url}/{endpoint.lstrip('/')}"
        headers = {
            "Content-Type": "application/json",
            "x-amz-access-token": self.access_token,
        }
        body = ""
        if method == "POST":
            body = requests.json.dumps(params or {})
            headers["x-amz-date"] = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        elif params:
            url = f"{url}?{urllib.parse.urlencode(params)}"

        resp = self._session.request(method, url, data=body if method == "POST" else None,
                                     headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if "errors" in data and data["errors"]:
            raise ConnectionError(f"Amazon API 错误: {data['errors']}")
        return data

    def get_orders(self, status: str = "", start_date: str = "", end_date: str = "",
                   page: int = 1, page_size: int = 50) -> List[dict]:
        """获取订单列表 (Orders API v0)"""
        params = {
            "MarketplaceId": self.marketplace_id,
            "MaxResultsPerPage": str(min(page_size, 100)),
        }
        if start_date:
            params["CreatedAfter"] = f"{start_date}T00:00:00Z"
        if end_date:
            params["CreatedBefore"] = f"{end_date}T23:59:59Z"
        if status:
            params["OrderStatus"] = status

        data = self._request("orders/0/orders", params)
        orders = data.get("Orders", [])
        return [self._normalize_order({
            **o,
            "order_id": o.get("AmazonOrderId", ""),
            "customer_id": o.get("BuyerInfo", {}).get("CustomerId", ""),
            "customer_name": o.get("BuyerInfo", {}).get("Name", ""),
            "total_amount": float(o.get("OrderTotal", {}).get("Amount", 0)),
            "currency": o.get("OrderTotal", {}).get("CurrencyCode", "USD"),
            "created_at": o.get("PurchaseDate", ""),
            "status": o.get("OrderStatus", ""),
            "shipping_address": str(o.get("ShippingAddress", {})),
        }) for o in orders]

    def get_order_detail(self, order_id: str) -> dict:
        """获取订单详情"""
        data = self._request(f"orders/0/orders/{order_id}")
        o = data.get("Orders", [{}])[0]
        return self._normalize_order({
            **o,
            "order_id": o.get("AmazonOrderId", ""),
            "total_amount": float(o.get("OrderTotal", {}).get("Amount", 0)),
            "currency": o.get("OrderTotal", {}).get("CurrencyCode", "USD"),
        })

    def get_returns(self, status: str = "", page: int = 1, page_size: int = 50) -> List[dict]:
        """获取退货列表"""
        params = {"MarketplaceId": self.marketplace_id, "PageSize": str(min(page_size, 100))}
        if status:
            params["Status"] = status
        data = self._request("fba/outbound/bopis/orders/v0/sellerOrders", params)
        return [self._normalize_return(r) for r in data.get("payload", {}).get("orders", [])]

    def get_reviews(self, status: str = "", page: int = 1, page_size: int = 50) -> List[dict]:
        """Amazon 没有公共评价列表 API（需要 Brand Registry），这里返回空"""
        return []

    def reply_review(self, review_id: str, content: str) -> bool:
        """Amazon 不支持通过 API 公开回复评价"""
        return False
