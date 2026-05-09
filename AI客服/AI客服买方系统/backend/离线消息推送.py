# -*- coding: utf-8 -*-
"""
离线消息推送模块 (Notification Service)

功能：
- 转人工超时自动通知卖家管理员
- 支持多种通知渠道：Webhook、邮件、短信
- 通知内容包含客户ID和问题摘要
- 可配置超时时间（默认60秒）

触发场景：
- 客户点击"转人工"后超过60秒无坐席接起
- 系统自动发送提醒通知给卖家管理员

配置项（.env）：
- NOTIFICATION_ENABLED=1
- NOTIFICATION_TIMEOUT=60 (秒)
- NOTIFICATION_WEBHOOK_URL= (钉钉/飞书Webhook)
- NOTIFICATION_EMAIL= (管理员邮箱)
- NOTIFICATION_SMS_ENABLED=0
- NOTIFICATION_SMS_API= (短信API)
- NOTIFICATION_SMS_KEY= (短信API密钥)
"""
import json
import logging
import os
import time
import asyncio
import hashlib
from datetime import datetime
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, asdict
from enum import Enum

import requests

logger = logging.getLogger(__name__)

# ============== 配置 ==============
NOTIFICATION_ENABLED = os.getenv("NOTIFICATION_ENABLED", "1") == "1"
NOTIFICATION_TIMEOUT = int(os.getenv("NOTIFICATION_TIMEOUT", "60"))  # 60秒无坐席接起则通知
NOTIFICATION_WEBHOOK_URL = os.getenv("NOTIFICATION_WEBHOOK_URL", "")
NOTIFICATION_EMAIL = os.getenv("NOTIFICATION_EMAIL", "")
NOTIFICATION_SMS_ENABLED = os.getenv("NOTIFICATION_SMS_ENABLED", "0") == "1"
NOTIFICATION_SMS_API = os.getenv("NOTIFICATION_SMS_API", "")
NOTIFICATION_SMS_KEY = os.getenv("NOTIFICATION_SMS_KEY", "")

# 通知级别
class NotificationLevel(Enum):
    INFO = "info"
    WARNING = "warning"
    URGENT = "urgent"
    CRITICAL = "critical"


# ============== 数据结构 ==============
@dataclass
class NotificationPayload:
    """通知载荷"""
    event_type: str  # transfer_to_human_timeout
    session_id: str
    customer_id: str
    customer_name: str
    customer_phone: Optional[str]
    language: str
    question_summary: str  # 问题摘要（取前100字）
    wait_time: int  # 等待时长（秒）
    timestamp: float
    level: str
    priority: int  # 1-5，越高越紧急


@dataclass
class NotificationResult:
    """通知结果"""
    success: bool
    channel: str
    message: str
    sent_at: Optional[float] = None
    error: Optional[str] = None


# ============== 通知渠道基类 ==============
class NotificationChannel:
    """通知渠道基类"""
    
    name: str = "base"
    
    def __init__(self):
        self.enabled = False
    
    async def send(self, payload: NotificationPayload) -> NotificationResult:
        """发送通知"""
        raise NotImplementedError
    
    def _build_message(self, payload: NotificationPayload) -> str:
        """构建通知消息"""
        return f"[{payload.level.upper()}] {payload.event_type}\n客户: {payload.customer_name}\n问题: {payload.question_summary}"


class WebhookChannel(NotificationChannel):
    """Webhook通知渠道
    
    支持钉钉群机器人和飞书群机器人
    """
    
    name = "webhook"
    
    def __init__(self, webhook_url: str):
        super().__init__()
        self.webhook_url = webhook_url
        self.enabled = bool(webhook_url)
    
    async def send(self, payload: NotificationPayload) -> NotificationResult:
        """发送Webhook通知"""
        if not self.enabled:
            return NotificationResult(False, self.name, "未启用")
        
        try:
            # 钉钉/飞书格式
            message = self._build_dingtalk_message(payload)
            
            response = requests.post(
                self.webhook_url,
                json=message,
                timeout=10
            )
            
            if response.status_code == 200:
                result = response.json()
                if result.get("errcode") == 0:
                    logger.info(f"[Notification] Webhook通知发送成功: session={payload.session_id}")
                    return NotificationResult(True, self.name, "发送成功", time.time())
                else:
                    return NotificationResult(False, self.name, f"错误码: {result.get('errmsg')}")
            else:
                return NotificationResult(False, self.name, f"HTTP {response.status_code}")
                
        except requests.exceptions.Timeout:
            return NotificationResult(False, self.name, "请求超时")
        except Exception as e:
            logger.error(f"[Notification] Webhook通知失败: {e}")
            return NotificationResult(False, self.name, str(e))
    
    def _build_dingtalk_message(self, payload: NotificationPayload) -> dict:
        """构建钉钉/飞书格式消息"""
        # 根据等待时长设置颜色
        if payload.wait_time >= 180:  # 3分钟以上
            color = "red"
            emoji = "🔴"
        elif payload.wait_time >= 120:  # 2分钟以上
            color = "orange"
            emoji = "🟠"
        else:
            color = "yellow"
            emoji = "🟡"
        
        # Markdown格式
        content = f"""## {emoji} 紧急：客户等待超时

**事件**: 客户请求人工服务超时
**客户**: {payload.customer_name}
**语言**: {payload.language}
**等待时长**: {payload.wait_time}秒

### 问题摘要
{payload.question_summary[:100]}...

### 会话信息
- Session ID: `{payload.session_id}`
- Customer ID: `{payload.customer_id}`
- 时间: {datetime.fromtimestamp(payload.timestamp).strftime('%Y-%m-%d %H:%M:%S')}

> 请尽快分配坐席处理！"""

        return {
            "msgtype": "markdown",
            "markdown": {
                "title": f"客户等待超时 [{payload.wait_time}s]",
                "text": content
            }
        }


class EmailChannel(NotificationChannel):
    """邮件通知渠道"""
    
    name = "email"
    
    def __init__(self, smtp_host: str, smtp_port: int, smtp_user: str, smtp_pass: str,
                 from_email: str = None, use_tls: bool = True):
        super().__init__()
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.smtp_user = smtp_user
        self.smtp_pass = smtp_pass
        self.from_email = from_email or smtp_user
        self.use_tls = use_tls
        self.enabled = bool(smtp_host and smtp_user and smtp_pass)
    
    async def send(self, payload: NotificationPayload) -> NotificationResult:
        """发送邮件通知"""
        if not self.enabled:
            return NotificationResult(False, self.name, "未启用")
        
        try:
            import smtplib
            from email.mime.text import MIMEText
            from email.header import Header
            
            # 构建邮件内容
            subject = f"[紧急] 客户等待超时 - {payload.customer_name}"
            html_content = self._build_html_email(payload)
            
            msg = MIMEText(html_content, 'html', 'utf-8')
            msg['Subject'] = Header(subject, 'utf-8')
            msg['From'] = self.from_email
            
            # 发送
            server = smtplib.SMTP(self.smtp_host, self.smtp_port)
            if self.use_tls:
                server.starttls()
            server.login(self.smtp_user, self.smtp_pass)
            server.sendmail(self.from_email, [NOTIFICATION_EMAIL], msg.as_string())
            server.quit()
            
            logger.info(f"[Notification] 邮件通知发送成功: {payload.session_id}")
            return NotificationResult(True, self.name, "发送成功", time.time())
            
        except smtplib.SMTPException as e:
            logger.error(f"[Notification] 邮件发送失败: {e}")
            return NotificationResult(False, self.name, str(e))
        except Exception as e:
            logger.error(f"[Notification] 邮件通知失败: {e}")
            return NotificationResult(False, self.name, str(e))
    
    def _build_html_email(self, payload: NotificationPayload) -> str:
        """构建HTML邮件"""
        urgency_color = "#ff0000" if payload.wait_time >= 120 else "#ff9900"
        
        return f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: Arial, sans-serif; line-height: 1.6; }}
        .header {{ background: {urgency_color}; color: white; padding: 20px; }}
        .content {{ padding: 20px; }}
        .urgent {{ color: {urgency_color}; font-weight: bold; }}
        .info-table {{ width: 100%; border-collapse: collapse; }}
        .info-table td {{ padding: 8px; border-bottom: 1px solid #ddd; }}
        .info-table td:first-child {{ font-weight: bold; width: 120px; }}
    </style>
</head>
<body>
    <div class="header">
        <h2>🚨 客户等待超时提醒</h2>
    </div>
    <div class="content">
        <p class="urgent">客户已等待 <strong>{payload.wait_time}秒</strong>，请尽快处理！</p>
        
        <table class="info-table">
            <tr><td>客户名称</td><td>{payload.customer_name}</td></tr>
            <tr><td>客户ID</td><td>{payload.customer_id}</td></tr>
            <tr><td>手机号</td><td>{payload.customer_phone or '未提供'}</td></tr>
            <tr><td>语言</td><td>{payload.language}</td></tr>
            <tr><td>等待时长</td><td>{payload.wait_time}秒</td></tr>
            <tr><td>时间</td><td>{datetime.fromtimestamp(payload.timestamp).strftime('%Y-%m-%d %H:%M:%S')}</td></tr>
            <tr><td>Session ID</td><td>{payload.session_id}</td></tr>
        </table>
        
        <h3>问题摘要</h3>
        <p>{payload.question_summary[:200]}</p>
    </div>
</body>
</html>
"""


class SMSChannel(NotificationChannel):
    """短信通知渠道"""
    
    name = "sms"
    
    def __init__(self, api_url: str, api_key: str):
        super().__init__()
        self.api_url = api_url
        self.api_key = api_key
        self.enabled = bool(api_url and api_key)
    
    async def send(self, payload: NotificationPayload) -> NotificationResult:
        """发送短信通知"""
        if not self.enabled:
            return NotificationResult(False, self.name, "未启用")
        
        try:
            # 短信内容（限制70字）
            content = f"【客服系统】客户{payload.customer_name}等待人工服务{payload.wait_time}秒，请及时处理。Session: {payload.session_id[:8]}..."
            
            # 调用短信API（这里使用通用格式，具体API需要适配）
            response = requests.post(
                self.api_url,
                json={
                    "apikey": self.api_key,
                    "mobile": NOTIFICATION_EMAIL,  # 短信通知时使用邮箱作为手机号占位
                    "text": content
                },
                timeout=10
            )
            
            if response.status_code == 200:
                result = response.json()
                if result.get("code") == 0:
                    logger.info(f"[Notification] 短信通知发送成功")
                    return NotificationResult(True, self.name, "发送成功", time.time())
                else:
                    return NotificationResult(False, self.name, result.get("msg", "发送失败"))
            else:
                return NotificationResult(False, self.name, f"HTTP {response.status_code}")
                
        except Exception as e:
            logger.error(f"[Notification] 短信通知失败: {e}")
            return NotificationResult(False, self.name, str(e))


# ============== 通知服务 ==============
class NotificationService:
    """
    通知服务管理器
    
    统一管理多种通知渠道，支持Webhook、邮件、短信。
    """
    
    def __init__(self):
        self.channels: List[NotificationChannel] = []
        self._init_channels()
    
    def _init_channels(self):
        """初始化通知渠道"""
        # Webhook
        if NOTIFICATION_WEBHOOK_URL:
            self.channels.append(WebhookChannel(NOTIFICATION_WEBHOOK_URL))
            logger.info(f"[Notification] Webhook渠道已启用: {NOTIFICATION_WEBHOOK_URL[:50]}...")
        
        # 邮件
        smtp_host = os.getenv("SMTP_HOST", "")
        smtp_port = int(os.getenv("SMTP_PORT", "587"))
        smtp_user = os.getenv("SMTP_USER", "")
        smtp_pass = os.getenv("SMTP_PASS", "")
        if smtp_host and smtp_user and smtp_pass:
            self.channels.append(EmailChannel(
                smtp_host, smtp_port, smtp_user, smtp_pass,
                use_tls=os.getenv("SMTP_TLS", "true") == "true"
            ))
            logger.info("[Notification] 邮件渠道已启用")
        
        # 短信
        if NOTIFICATION_SMS_ENABLED and NOTIFICATION_SMS_API:
            self.channels.append(SMSChannel(NOTIFICATION_SMS_API, NOTIFICATION_SMS_KEY))
            logger.info("[Notification] 短信渠道已启用")
    
    async def send(self, payload: NotificationPayload) -> List[NotificationResult]:
        """
        发送通知到所有已启用的渠道
        
        Args:
            payload: 通知载荷
            
        Returns:
            各渠道的发送结果列表
        """
        if not NOTIFICATION_ENABLED:
            logger.debug("[Notification] 通知功能未启用")
            return []
        
        if not self.channels:
            logger.warning("[Notification] 没有已启用的通知渠道")
            return []
        
        # 并发发送到所有渠道
        tasks = [channel.send(payload) for channel in self.channels]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 处理异常
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                channel_name = self.channels[i].name if i < len(self.channels) else "unknown"
                processed_results.append(NotificationResult(False, channel_name, str(result)))
            else:
                processed_results.append(result)
        
        return processed_results
    
    async def notify_transfer_timeout(
        self,
        session_id: str,
        customer_id: str,
        customer_name: str,
        customer_phone: Optional[str],
        language: str,
        question_summary: str,
        wait_time: int
    ) -> List[NotificationResult]:
        """
        发送转人工超时通知
        
        Args:
            session_id: 会话ID
            customer_id: 客户ID
            customer_name: 客户名称
            customer_phone: 客户电话
            language: 语言
            question_summary: 问题摘要
            wait_time: 等待时长（秒）
            
        Returns:
            各渠道的发送结果
        """
        # 计算优先级
        if wait_time >= 180:
            level = NotificationLevel.CRITICAL.value
            priority = 5
        elif wait_time >= 120:
            level = NotificationLevel.URGENT.value
            priority = 4
        elif wait_time >= 90:
            level = NotificationLevel.WARNING.value
            priority = 3
        else:
            level = NotificationLevel.INFO.value
            priority = 2
        
        payload = NotificationPayload(
            event_type="transfer_to_human_timeout",
            session_id=session_id,
            customer_id=customer_id,
            customer_name=customer_name,
            customer_phone=customer_phone,
            language=language,
            question_summary=question_summary,
            wait_time=wait_time,
            timestamp=time.time(),
            level=level,
            priority=priority
        )
        
        logger.warning(
            f"[Notification] 转人工超时通知: customer={customer_name} "
            f"wait={wait_time}s session={session_id}"
        )
        
        return await self.send(payload)
    
    def get_status(self) -> Dict[str, Any]:
        """获取通知服务状态"""
        return {
            "enabled": NOTIFICATION_ENABLED,
            "channels": [
                {"name": ch.name, "enabled": ch.enabled}
                for ch in self.channels
            ]
        }


# ============== 等待监控器 ==============
class WaitingMonitor:
    """
    转人工等待监控器
    
    监控已转人工但未分配坐席的会话，
    超过超时时间后自动触发通知。
    """
    
    def __init__(self, notification_service: NotificationService):
        self.notification_service = notification_service
        self._waiting_sessions: Dict[str, Dict] = {}  # session_id -> {start_time, customer_info, ...}
        self._lock = asyncio.Lock()
    
    async def start_tracking(
        self,
        session_id: str,
        customer_id: str,
        customer_name: str,
        customer_phone: Optional[str],
        language: str,
        question_summary: str
    ):
        """开始跟踪一个等待中的会话"""
        async with self._lock:
            self._waiting_sessions[session_id] = {
                "start_time": time.time(),
                "customer_id": customer_id,
                "customer_name": customer_name,
                "customer_phone": customer_phone,
                "language": language,
                "question_summary": question_summary,
                "notified": False
            }
            logger.info(f"[WaitingMonitor] 开始跟踪: session={session_id}")
    
    async def stop_tracking(self, session_id: str):
        """停止跟踪一个会话（已分配坐席）"""
        async with self._lock:
            if session_id in self._waiting_sessions:
                del self._waiting_sessions[session_id]
                logger.info(f"[WaitingMonitor] 停止跟踪: session={session_id}")
    
    async def check_timeouts(self) -> List[NotificationResult]:
        """
        检查所有等待中的会话是否超时
        
        Returns:
            超时通知的发送结果
        """
        results = []
        now = time.time()
        
        async with self._lock:
            timed_out = [
                (sid, data) for sid, data in self._waiting_sessions.items()
                if not data["notified"] and (now - data["start_time"]) >= NOTIFICATION_TIMEOUT
            ]
        
        for session_id, data in timed_out:
            wait_time = int(now - data["start_time"])
            
            result = await self.notification_service.notify_transfer_timeout(
                session_id=session_id,
                customer_id=data["customer_id"],
                customer_name=data["customer_name"],
                customer_phone=data["customer_phone"],
                language=data["language"],
                question_summary=data["question_summary"],
                wait_time=wait_time
            )
            results.extend(result)
            
            # 标记为已通知
            async with self._lock:
                if session_id in self._waiting_sessions:
                    self._waiting_sessions[session_id]["notified"] = True
        
        return results
    
    def get_pending_count(self) -> int:
        """获取当前等待中的会话数"""
        return len(self._waiting_sessions)
    
    def get_pending_sessions(self) -> List[Dict]:
        """获取所有等待中的会话"""
        now = time.time()
        return [
            {
                "session_id": sid,
                "wait_time": int(now - data["start_time"]),
                "notified": data["notified"]
            }
            for sid, data in self._waiting_sessions.items()
        ]


# ============== 全局实例 ==============
_notification_service: Optional[NotificationService] = None
_waiting_monitor: Optional[WaitingMonitor] = None


def get_notification_service() -> NotificationService:
    """获取通知服务实例"""
    global _notification_service
    if _notification_service is None:
        _notification_service = NotificationService()
    return _notification_service


def get_waiting_monitor() -> WaitingMonitor:
    """获取等待监控器实例"""
    global _waiting_monitor
    if _waiting_monitor is None:
        _waiting_monitor = WaitingMonitor(get_notification_service())
    return _waiting_monitor


async def notify_transfer_timeout(**kwargs) -> List[NotificationResult]:
    """快捷函数：发送转人工超时通知"""
    return await get_notification_service().notify_transfer_timeout(**kwargs)


# ============== 导出 ==============
__all__ = [
    'NotificationService',
    'NotificationChannel',
    'WebhookChannel',
    'EmailChannel',
    'SMSChannel',
    'WaitingMonitor',
    'NotificationPayload',
    'NotificationResult',
    'NotificationLevel',
    'get_notification_service',
    'get_waiting_monitor',
    'notify_transfer_timeout',
]
