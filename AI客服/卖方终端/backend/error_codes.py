# -*- coding: utf-8 -*-
"""
API 统一错误码规范

所有 API 错误响应格式:
{
    "success": False,
    "error": {
        "code": "RTK_10001",
        "message": "人类可读的错误消息",
        "detail": "详细错误信息（可选，仅 DEBUG 模式暴露）",
        "field": "出错的字段名（可选，表单验证时使用）",
        "request_id": "请求追踪 ID"
    }
}

错误码格式: RTK_{Category}{Serial:05d}
  Category: 2-3 个字母
  Serial:   5 位数字（从 00001 开始）

| 类别   | 前缀   | 范围        | 说明                     |
|--------|--------|-------------|--------------------------|
| 通用   | GEN    | 00001-00099 | 通用错误                 |
| 认证   | AUTH   | 00101-00199 | 认证/鉴权错误            |
| 限流   | RATE   | 00201-00299 | 限流/配额错误            |
| 参数   | PARAM  | 00301-00399 | 参数校验错误              |
| 数据库 | DB     | 00401-00499 | 数据库操作错误           |
| 会话   | SESSION| 00501-00599 | 会话管理错误             |
| AI    | AI     | 00601-00699 | AI 服务错误              |
| 知识库 | KG     | 00701-00799 | 知识图谱/GraphRAG 错误   |
| 跨系统 | XFER   | 00801-00899 | 跨系统回调/通知错误       |
| 业务   | BIZ    | 00901-00999 | 业务逻辑错误             |
| 文件   | FILE   | 01001-01099 | 文件上传/下载错误         |
| 电商   | EC     | 01101-01199 | 电商平台集成错误          |
"""
from enum import Enum
from typing import Optional, Any, Dict
from dataclasses import dataclass, field, asdict


# ============== 错误码定义 ==============
class ErrorCode(Enum):
    # ---- 通用 (RTK_GENO0001 - RTK_GEN09999) ----
    INTERNAL_ERROR = ("RTK_GEN00001", "内部服务器错误", 500)
    SERVICE_UNAVAILABLE = ("RTK_GEN00002", "服务暂时不可用", 503)
    NOT_IMPLEMENTED = ("RTK_GEN00003", "功能暂未实现", 501)
    GATEWAY_TIMEOUT = ("RTK_GEN00004", "网关超时", 504)
    BAD_GATEWAY = ("RTK_GEN00005", "网关错误", 502)

    # ---- 认证/鉴权 (RTK_AUTH00101 - RTK_AUTH00199) ----
    AUTH_TOKEN_MISSING = ("RTK_AUTH00101", "未提供认证令牌", 401)
    AUTH_TOKEN_INVALID = ("RTK_AUTH00102", "认证令牌无效或已过期", 401)
    AUTH_TOKEN_EXPIRED = ("RTK_AUTH00103", "认证令牌已过期", 401)
    AUTH_INSUFFICIENT_PERMISSIONS = ("RTK_AUTH00104", "权限不足", 403)
    AUTH_ACCOUNT_LOCKED = ("RTK_AUTH00105", "账户已被锁定", 403)
    AUTH_WEAK_PASSWORD = ("RTK_AUTH00106", "密码强度不足", 400)
    AUTH_CREDENTIALS_INVALID = ("RTK_AUTH00107", "用户名或密码错误", 401)
    AUTH_REFRESH_TOKEN_INVALID = ("RTK_AUTH00108", "刷新令牌无效", 401)

    # ---- 限流 (RTK_RATE00201 - RTK_RATE00299) ----
    RATE_LIMIT_EXCEEDED = ("RTK_RATE00201", "请求过于频繁，请稍后再试", 429)
    RATE_LIMIT_QUOTA_EXCEEDED = ("RTK_RATE00202", "配额已用完", 429)
    RATE_LIMIT_BURST_EXCEEDED = ("RTK_RATE00203", "突发请求被限制", 429)

    # ---- 参数校验 (RTK_PARAM00301 - RTK_PARAM00399) ----
    PARAM_REQUIRED = ("RTK_PARAM00301", "缺少必需参数", 400)
    PARAM_INVALID = ("RTK_PARAM00302", "参数格式错误", 400)
    PARAM_TOO_LONG = ("RTK_PARAM00303", "参数值超出长度限制", 400)
    PARAM_OUT_OF_RANGE = ("RTK_PARAM00304", "参数值超出允许范围", 400)
    PARAM_UNSUPPORTED_VALUE = ("RTK_PARAM00305", "参数值不被支持", 400)
    PARAM_TYPE_MISMATCH = ("RTK_PARAM00306", "参数类型不匹配", 400)

    # ---- 数据库 (RTK_DB00401 - RTK_DB00499) ----
    DB_CONNECTION_FAILED = ("RTK_DB00401", "数据库连接失败", 503)
    DB_QUERY_FAILED = ("RTK_DB00402", "数据库查询失败", 500)
    DB_INSERT_FAILED = ("RTK_DB00403", "数据插入失败", 500)
    DB_UPDATE_FAILED = ("RTK_DB00404", "数据更新失败", 500)
    DB_DELETE_FAILED = ("RTK_DB00405", "数据删除失败", 500)
    DB_RECORD_NOT_FOUND = ("RTK_DB00406", "记录不存在", 404)
    DB_DUPLICATE_KEY = ("RTK_DB00407", "记录已存在（唯一键冲突）", 409)
    DB_CONSTRAINT_VIOLATION = ("RTK_DB00408", "数据完整性约束冲突", 400)

    # ---- 会话 (RTK_SESSION00501 - RTK_SESSION00599) ----
    SESSION_NOT_FOUND = ("RTK_SESSION00501", "会话不存在或已过期", 404)
    SESSION_EXPIRED = ("RTK_SESSION00502", "会话已过期，请重新开始", 401)
    SESSION_MAX_CREATED = ("RTK_SESSION00503", "会话创建数量已达上限", 400)
    SESSION_CUSTOMER_MISMATCH = ("RTK_SESSION00504", "会话与客户不匹配", 403)

    # ---- AI 服务 (RTK_AI00601 - RTK_AI00699) ----
    AI_SERVICE_UNAVAILABLE = ("RTK_AI00601", "AI 服务暂时不可用", 503)
    AI_MODEL_TIMEOUT = ("RTK_AI00602", "AI 模型响应超时", 504)
    AI_MODEL_ERROR = ("RTK_AI00603", "AI 模型返回错误", 500)
    AI_CIRCUIT_BREAKER_OPEN = ("RTK_AI00604", "AI 服务熔断中，请稍后再试", 503)
    AI_CONTENT_FILTERED = ("RTK_AI00605", "AI 内容被过滤", 400)
    AI_TOKEN_LIMIT_EXCEEDED = ("RTK_AI00606", "输入超出 AI 模型 Token 限制", 400)

    # ---- 知识图谱 (RTK_KG00701 - RTK_KG00799) ----
    KG_CONNECTION_FAILED = ("RTK_KG00701", "知识图谱服务连接失败", 503)
    KG_QUERY_FAILED = ("RTK_KG00702", "知识图谱查询失败", 500)
    KG_PROFILE_NOT_FOUND = ("RTK_KG00703", "客户档案不存在", 404)

    # ---- 跨系统 (RTK_XFER00801 - RTK_XFER00899) ----
    XFER_SELLER_UNREACHABLE = ("RTK_XFER00801", "无法连接卖方系统", 503)
    XFER_BUYER_UNREACHABLE = ("RTK_XFER00802", "无法连接买方系统", 503)
    XFER_SIGNATURE_INVALID = ("RTK_XFER00803", "回调签名验证失败", 401)
    XFER_TIMESTAMP_EXPIRED = ("RTK_XFER00804", "回调时间戳已过期（防重放）", 401)
    XFER_DELIVERY_FAILED = ("RTK_XFER00805", "消息投递失败", 500)

    # ---- 业务逻辑 (RTK_BIZ00901 - RTK_BIZ00999) ----
    BIZ_CUSTOMER_NOT_FOUND = ("RTK_BIZ00901", "客户不存在", 404)
    BIZ_ORDER_NOT_FOUND = ("RTK_BIZ00902", "订单不存在", 404)
    BIZ_REVIEW_NOT_FOUND = ("RTK_BIZ00903", "评价不存在", 404)
    BIZ_REFUND_NOT_ALLOWED = ("RTK_BIZ00904", "当前状态不允许退款", 400)
    BIZ_SESSION_NOT_IN_HUMAN_MODE = ("RTK_BIZ00905", "会话当前不在人工模式", 400)
    BIZ_TRANSFER_QUEUE_FULL = ("RTK_BIZ00906", "人工客服排队已满", 503)
    BIZ_AGENT_NOT_ONLINE = ("RTK_BIZ00907", "指定客服不在线", 400)

    # ---- 文件操作 (RTK_FILE01001 - RTK_FILE01099) ----
    FILE_TOO_LARGE = ("RTK_FILE01001", "文件大小超出限制", 413)
    FILE_TYPE_NOT_ALLOWED = ("RTK_FILE01002", "文件类型不允许", 400)
    FILE_UPLOAD_FAILED = ("RTK_FILE01003", "文件上传失败", 500)
    FILE_NOT_FOUND = ("RTK_FILE01004", "文件不存在", 404)
    FILE_MALWARE_DETECTED = ("RTK_FILE01005", "文件安全检查未通过", 400)

    # ---- 电商平台 (RTK_EC01101 - RTK_EC01199) ----
    EC_PLATFORM_UNAUTHORIZED = ("RTK_EC01101", "电商平台授权已过期", 401)
    EC_PLATFORM_API_ERROR = ("RTK_EC01102", "电商平台 API 调用失败", 502)
    EC_SYNC_CONFLICT = ("RTK_EC01103", "平台数据同步冲突", 409)
    EC_RATE_LIMIT_EXCEEDED = ("RTK_EC01104", "平台 API 限流", 429)

    def __init__(self, code: str, message: str, http_status: int):
        self.code = code
        self.message = message
        self.http_status = http_status

    @property
    def name(self) -> str:
        return self.value[0]

    @property
    def status(self) -> int:
        return self.value[2]


# ============== 错误响应构建器 ==============
@dataclass
class APIError:
    """标准 API 错误响应"""
    code: str
    message: str
    detail: Optional[str] = None
    field: Optional[str] = None
    request_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "code": self.code,
            "message": self.message,
        }
        if self.detail:
            result["detail"] = self.detail
        if self.field:
            result["field"] = self.field
        if self.request_id:
            result["request_id"] = self.request_id
        return result


def make_error(
    error_code: ErrorCode,
    detail: Optional[str] = None,
    field: Optional[str] = None,
    request_id: Optional[str] = None,
    **kwargs,
) -> Dict[str, Any]:
    """
    构建标准错误响应。

    Args:
        error_code: 错误码枚举值
        detail: 详细错误信息（DEBUG 模式暴露）
        field: 出错字段名（表单验证时）
        request_id: 请求追踪 ID

    Example:
        return JSONResponse(
            status_code=error.http_status,
            content={"success": False, "error": make_error(ErrorCode.AUTH_TOKEN_INVALID)}
        )
    """
    return {
        "success": False,
        "error": APIError(
            code=error_code.code,
            message=error_code.message,
            detail=detail,
            field=field,
            request_id=request_id,
            **kwargs
        ).to_dict()
    }


def make_success(data: Any = None, message: str = "") -> Dict[str, Any]:
    """构建标准成功响应"""
    result: Dict[str, Any] = {"success": True}
    if message:
        result["message"] = message
    if data is not None:
        result["data"] = data
    return result


# ============== FastAPI 异常类 ==============
class RuitalkHTTPException(Exception):
    """FastAPI HTTP 异常（用于路由中直接 raise）"""

    def __init__(
        self,
        error_code: ErrorCode,
        detail: Optional[str] = None,
        field: Optional[str] = None,
    ):
        self.error_code = error_code
        self.detail = detail
        self.field = field
        self.code = error_code.code
        self.message = error_code.message
        self.status_code = error_code.http_status

    def to_json_response(self, request_id: Optional[str] = None):
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=self.status_code,
            content=make_error(
                self.error_code,
                detail=self.detail,
                field=self.field,
                request_id=request_id,
            )
        )

    def __str__(self):
        return f"[{self.code}] {self.message}"


# ============== 常用快捷函数 ==============
def param_required(field: str, request_id: Optional[str] = None):
    return RuitalkHTTPException(ErrorCode.PARAM_REQUIRED, field=field, request_id=request_id)


def unauthorized(detail: Optional[str] = None, request_id: Optional[str] = None):
    return RuitalkHTTPException(ErrorCode.AUTH_TOKEN_INVALID, detail=detail, request_id=request_id)


def forbidden(detail: Optional[str] = None, request_id: Optional[str] = None):
    return RuitalkHTTPException(ErrorCode.AUTH_INSUFFICIENT_PERMISSIONS, detail=detail, request_id=request_id)


def not_found(resource: str, request_id: Optional[str] = None):
    return RuitalkHTTPException(ErrorCode.DB_RECORD_NOT_FOUND, detail=f"{resource} not found", request_id=request_id)


def rate_limited(retry_after: Optional[int] = None, request_id: Optional[str] = None):
    exc = RuitalkHTTPException(ErrorCode.RATE_LIMIT_EXCEEDED, request_id=request_id)
    exc.retry_after = retry_after
    return exc


def internal_error(detail: Optional[str] = None, request_id: Optional[str] = None):
    return RuitalkHTTPException(ErrorCode.INTERNAL_ERROR, detail=detail, request_id=request_id)


def ai_unavailable(detail: Optional[str] = None, request_id: Optional[str] = None):
    return RuitalkHTTPException(ErrorCode.AI_SERVICE_UNAVAILABLE, detail=detail, request_id=request_id)
