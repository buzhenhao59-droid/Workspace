# -*- coding: utf-8 -*-
"""
物流渠道统一 API 客户端
支持 DHL / FedEx / UPS / 燕文 / 4PX
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Optional
import requests
import logging

logger = logging.getLogger(__name__)


class BaseLogisticsClient(ABC):
    """物流 API 基类"""

    def __init__(self, api_url: str = "", api_key: str = "", api_secret: str = ""):
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        self.api_secret = api_secret
        self._session = requests.Session()

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    @property
    def platform_name(self) -> str:
        return self.__class__.__name__.replace("Client", "")

    @abstractmethod
    def query_tracking(self, tracking_number: str, carrier_code: str = "") -> dict:
        """查询物流轨迹"""
        pass

    @abstractmethod
    def create_return_label(self, order_id: str, address: dict) -> dict:
        """创建退货面单"""
        pass

    def health_check(self) -> dict:
        if not self.is_configured:
            return {"ok": False, "message": "未配置 API 凭证"}
        try:
            return {"ok": True, "message": "连接正常"}
        except Exception as e:
            return {"ok": False, "message": str(e)}


class DHLClient(BaseLogisticsClient):
    """DHL 物流"""

    def query_tracking(self, tracking_number: str, carrier_code: str = "DHL") -> dict:
        if not self.is_configured:
            return {"ok": False, "message": "未配置"}
        try:
            resp = self._session.get(
                f"{self.api_url}/track/shipments?trackingNumber={tracking_number}",
                headers={"DHL-API-Key": self.api_key},
                timeout=15
            )
            data = resp.json()
            events = data.get("shipments", [{}])[0].get("events", [])
            return {
                "ok": True,
                "tracking_number": tracking_number,
                "status": data.get("shipments", [{}])[0].get("status", {}).get("statusCode", ""),
                "events": [{"timestamp": e.get("timestamp"), "location": e.get("location"), "description": e.get("description")} for e in events]
            }
        except Exception as e:
            return {"ok": False, "message": str(e)}

    def create_return_label(self, order_id: str, address: dict) -> dict:
        if not self.is_configured:
            return {"ok": False, "message": "未配置"}
        try:
            resp = self._session.post(
                f"{self.api_url}/shipments",
                json={"plannedShippingDateAndTime": "", "pickup": {"isRequested": False}, "customerDetails": {"shipperDetails": address}},
                headers={"DHL-API-Key": self.api_key, "Content-Type": "application/json"},
                timeout=20
            )
            return {"ok": True, "label_url": resp.json().get("documents", [{}])[0].get("url", "")}
        except Exception as e:
            return {"ok": False, "message": str(e)}


class FedExClient(BaseLogisticsClient):
    """FedEx 物流"""

    def query_tracking(self, tracking_number: str, carrier_code: str = "FEDEX") -> dict:
        if not self.is_configured:
            return {"ok": False, "message": "未配置"}
        try:
            resp = self._session.post(
                f"{self.api_url}/track/v1/trackingnumbers",
                json={"trackingInfo": [{"trackingNumberInfo": {"trackingNumber": tracking_number}}]},
                headers={"X-locale": "en_US", "Content-Type": "application/json"},
                timeout=15
            )
            data = resp.json()
            events = (data.get("completeTrackResults", [{}])[0].get("trackResults", [{}])
                      .get("scanEvents", []))
            return {
                "ok": True,
                "tracking_number": tracking_number,
                "status": data.get("completeTrackResults", [{}])[0].get("trackResults", [{}]).get("latestStatusDetail", {}).get("code", ""),
                "events": [{"timestamp": e.get("date"), "location": str(e.get("scanLocation", {})), "description": e.get("eventDescription", "")} for e in events]
            }
        except Exception as e:
            return {"ok": False, "message": str(e)}

    def create_return_label(self, order_id: str, address: dict) -> dict:
        if not self.is_configured:
            return {"ok": False, "message": "未配置"}
        return {"ok": False, "message": "FedEx 退货标签需单独申请接口权限"}


class UPSClient(BaseLogisticsClient):
    """UPS 物流"""

    def query_tracking(self, tracking_number: str, carrier_code: str = "UPS") -> dict:
        if not self.is_configured:
            return {"ok": False, "message": "未配置"}
        try:
            resp = self._session.get(
                f"{self.api_url}/api/v1/tracking?locate=zh_CN",
                params={"trackingNumber": tracking_number},
                headers={"AccessLicenseNumber": self.api_key, "Content-Type": "application/json"},
                timeout=15
            )
            data = resp.json()
            events = (data.get("trackResponse", {}).get("shipment", [{}])[0]
                      .get("package", [{}]).get("activity", []))
            return {
                "ok": True,
                "tracking_number": tracking_number,
                "status": events[0].get("status", {}).get("type", "") if events else "",
                "events": [{"timestamp": e.get("date") + " " + e.get("time", ""), "location": str(e.get("location", {})), "description": e.get("status", {}).get("description", "")} for e in events]
            }
        except Exception as e:
            return {"ok": False, "message": str(e)}

    def create_return_label(self, order_id: str, address: dict) -> dict:
        if not self.is_configured:
            return {"ok": False, "message": "未配置"}
        return {"ok": False, "message": "UPS 退货标签需申请 Returns API"}


class YanwenClient(BaseLogisticsClient):
    """燕文物流"""

    def query_tracking(self, tracking_number: str, carrier_code: str = "") -> dict:
        if not self.is_configured:
            return {"ok": False, "message": "未配置"}
        try:
            resp = self._session.get(
                f"{self.api_url}/open/api/track",
                params={"billcode": tracking_number, "api_key": self.api_key},
                timeout=15
            )
            data = resp.json()
            tracks = data.get("data", {}).get("traces", [])
            return {
                "ok": True,
                "tracking_number": tracking_number,
                "status": tracks[0].get("status", "") if tracks else "",
                "events": [{"timestamp": t.get("accept_time", ""), "location": t.get("accept_address", ""), "description": t.get("remark", "")} for t in tracks]
            }
        except Exception as e:
            return {"ok": False, "message": str(e)}

    def create_return_label(self, order_id: str, address: dict) -> dict:
        if not self.is_configured:
            return {"ok": False, "message": "未配置"}
        return {"ok": False, "message": "燕文退货标签需联系燕文客服申请"}


class FPXClient(BaseLogisticsClient):
    """4PX (递四方) 物流"""

    def query_tracking(self, tracking_number: str, carrier_code: str = "") -> dict:
        if not self.is_configured:
            return {"ok": False, "message": "未配置"}
        try:
            resp = self._session.post(
                f"{self.api_url}/open/api/track",
                json={"trackingNo": tracking_number, "apiKey": self.api_key},
                headers={"Content-Type": "application/json"},
                timeout=15
            )
            data = resp.json()
            traces = data.get("data", {}).get("traceList", [])
            return {
                "ok": True,
                "tracking_number": tracking_number,
                "status": traces[0].get("status", "") if traces else "",
                "events": [{"timestamp": t.get("opTime", ""), "location": t.get("opLocation", ""), "description": t.get("opDesc", "")} for t in traces]
            }
        except Exception as e:
            return {"ok": False, "message": str(e)}

    def create_return_label(self, order_id: str, address: dict) -> dict:
        if not self.is_configured:
            return {"ok": False, "message": "未配置"}
        return {"ok": False, "message": "4PX 退货标签需申请 ERP 接口"}
