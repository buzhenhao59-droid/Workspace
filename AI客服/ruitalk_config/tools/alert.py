# -*- coding: utf-8 -*-
"""
Ruitalk 统一告警通知工具
支持: 钉钉群机器人 / 飞书群机器人 / 企业微信 / 邮件

用法:
    python alert.py --level error --title "服务宕机" --content "Redis 连接失败"
    python alert.py --level warning --title "备份失败" --content "gold_customer.db 备份失败"
    python alert.py --level info --title "系统上线" --content "新版本已部署"

配置 (.env.master):
    DINGTALK_WEBHOOK=    # 钉钉群机器人 Webhook URL
    DINGTALK_SECRET=      # 钉钉加签密钥（可选）
    FEISHU_WEBHOOK=      # 飞书群机器人 Webhook URL
    ALERT_LEVEL=error    # 最低告警级别: debug/info/warning/error/critical
"""
from __future__ import annotations

import os
import sys
import json
import hmac
import hashlib
import base64
import time
import argparse
import logging
import smtplib
from pathlib import Path
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ===== 自动计算项目根目录 =====
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent.parent    # 项目根目录
_UNIFIED_CONFIG = _SCRIPT_DIR.parent / ".env.master"  # ruitalk_config/.env.master
_env_cache: dict[str, str] = {}

if _UNIFIED_CONFIG.exists():
    for line in _UNIFIED_CONFIG.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        key = k.strip()
        val = v.strip().strip('"').strip("'")
        _env_cache[key] = val
        os.environ.setdefault(key, val)


def _e(key: str, default: str = "") -> str:
    return _env_cache.get(key, os.getenv(key, default))


# ===== 日志 =====
_log = logging.getLogger("ruitalk.alert")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


# ===== 告警级别 =====
LEVEL_PRIORITY = {"debug": 0, "info": 1, "warning": 2, "error": 3, "critical": 4}

LEVEL_ICONS = {
    "debug": "🔹",
    "info": "ℹ️ ",
    "warning": "⚠️ ",
    "error": "🚨",
    "critical": "🔴",
}


class AlertMessage:
    """告警消息构造器"""

    def __init__(
        self,
        level: str = "info",
        title: str = "",
        content: str = "",
        source: str = "Ruitalk",
        extra: dict | None = None,
    ):
        self.level = level.lower()
        self.title = title
        self.content = content
        self.source = source
        self.extra = extra or {}
        self._ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ── 钉钉格式 ──────────────────────────────────────────
    def to_dingtalk(self) -> dict:
        icon = LEVEL_ICONS.get(self.level, "ℹ️")
        text = f"{icon} **{self.title}**\n" \
               f"> 来源: `{self.source}`  时间: `{self._ts}`\n" \
               f"> 级别: `{self.level.upper()}`\n\n{self.content}"
        if self.extra:
            text += "\n\n**详情:**\n"
            for k, v in self.extra.items():
                text += f"- **{k}**: `{v}`\n"
        return {"msgtype": "markdown", "markdown": {"title": self.title, "text": text}}

    # ── 飞书格式 ─────────────────────────────────────────
    def to_feishu(self) -> dict:
        icon = LEVEL_ICONS.get(self.level, "ℹ️")
        elements = [
            {
                "tag": "markdown",
                "content": (
                    f"**{icon} {self.title}**\n"
                    f"**来源:** {self.source}  |  **时间:** {self._ts}  |  **级别:** {self.level.upper()}\n\n"
                    f"{self.content}"
                ),
            }
        ]
        if self.extra:
            rows = "".join(f"| **{k}** | `{v}` |" + "\n" for k, v in self.extra.items())
            elements.append({"tag": "markdown", "content": f"\n**详情:**\n| 字段 | 值 |\n|---|---|\n{rows}"})
        return {"msg_type": "post", "content": {"post": {"zh_cn": {"title": self.title, "content": elements}}}}

    # ── 企业微信格式 ─────────────────────────────────────
    def to_wecom(self) -> dict:
        icon = LEVEL_ICONS.get(self.level, "")
        text = f"{icon} **{self.title}**\n" \
               f"来源: {self.source}  时间: {self._ts}\n级别: {self.level.upper()}\n\n{self.content}"
        if self.extra:
            text += "\n\n详情:\n" + "\n".join(f"- {k}: {v}" for k, v in self.extra.items())
        return {"msgtype": "text", "text": {"content": text}}

    # ── 邮件格式 ─────────────────────────────────────────
    def to_email(self) -> tuple[str, str]:
        icon = LEVEL_ICONS.get(self.level, "")
        body = f"""
<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
  <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; border-radius: 8px 8px 0 0;">
    <h2 style="margin:0;">{icon} {self.title}</h2>
    <p style="margin:5px 0 0; opacity: 0.9;">{self.source} · {self.level.upper()} · {self._ts}</p>
  </div>
  <div style="border: 1px solid #e0e0e0; border-top: none; padding: 20px; border-radius: 0 0 8px 8px;">
    <p style="font-size: 14px; color: #333;">{self.content.replace(chr(10), '<br>')}</p>
    {"".join(f'<p><strong>{k}:</strong> <code>{v}</code></p>' for k, v in self.extra.items())}
    <hr style="border: none; border-top: 1px solid #eee; margin: 15px 0;">
    <p style="color: #888; font-size: 12px;">此邮件由 Ruitalk 告警系统自动发送</p>
  </div>
</div>
        """.strip()
        return self.title, body


# ── 发送器 ──────────────────────────────────────────────────────────

def _dingtalk_sign(secret: str) -> str:
    """生成钉钉加签"""
    timestamp = str(int(time.time() * 1000))
    sign_str = f"{timestamp}\n{secret}"
    sign = base64.b64encode(
        hmac.new(sign_str.encode(), sign_str.encode(), hashlib.sha256).digest()
    ).decode()
    return timestamp, sign


def send_dingtalk(msg: AlertMessage) -> bool:
    webhook = _e("DINGTALK_WEBHOOK", "").strip()
    secret = _e("DINGTALK_SECRET", "").strip()
    if not webhook:
        return False

    url = webhook
    if secret:
        ts, sign = _dingtalk_sign(secret)
        url = f"{webhook}&timestamp={ts}&sign={sign}"

    body = msg.to_dingtalk()
    try:
        import urllib.request
        req = urllib.request.Request(
            url,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
        if result.get("errcode") == 0:
            _log.info("钉钉告警发送成功")
            return True
        _log.error("钉钉告警失败: %s", result.get("errmsg"))
        return False
    except Exception as e:
        _log.error("钉钉告警异常: %s", e)
        return False


def send_feishu(msg: AlertMessage) -> bool:
    webhook = _e("FEISHU_WEBHOOK", "").strip()
    if not webhook:
        return False

    body = msg.to_feishu()
    try:
        import urllib.request
        req = urllib.request.Request(
            webhook,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
        if result.get("code") == 0 or result.get("StatusCode") == 0:
            _log.info("飞书告警发送成功")
            return True
        _log.error("飞书告警失败: %s", result.get("msg"))
        return False
    except Exception as e:
        _log.error("飞书告警异常: %s", e)
        return False


def send_wecom(msg: AlertMessage) -> bool:
    webhook = _e("WECOM_WEBHOOK", "").strip()
    if not webhook:
        return False

    body = msg.to_wecom()
    try:
        import urllib.request
        req = urllib.request.Request(
            webhook,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
        if result.get("errcode") == 0:
            _log.info("企业微信告警发送成功")
            return True
        _log.error("企业微信告警失败: %s", result.get("errmsg"))
        return False
    except Exception as e:
        _log.error("企业微信告警异常: %s", e)
        return False


def send_email(msg: AlertMessage) -> bool:
    smtp_host = _e("SMTP_HOST", "").strip()
    if not smtp_host:
        return False

    smtp_user = _e("SMTP_USER", "")
    smtp_pass = _e("SMTP_PASS", "")
    smtp_port = int(_e("SMTP_PORT", "587"))
    smtp_tls = _e("SMTP_TLS", "true").lower() in ("1", "true", "yes")
    notify_to = _e("ALERT_NOTIFY_EMAIL", "").strip() or _e("BACKUP_NOTIFY_EMAIL", "").strip()
    notify_from = _e("SMTP_FROM", smtp_user).strip()

    if not notify_to:
        return False

    subject, body_html = msg.to_email()
    subject = f"[Ruitalk-{msg.level.upper()}] {subject}"

    try:
        msg_obj = MIMEMultipart("alternative")
        msg_obj["From"] = notify_from
        msg_obj["To"] = notify_to
        msg_obj["Subject"] = subject
        msg_obj.attach(MIMEText(body_html, "html", "utf-8"))

        with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
            if smtp_tls:
                server.starttls()
            if smtp_user and smtp_pass:
                server.login(smtp_user, smtp_pass)
            server.send_message(msg_obj)
        _log.info("邮件告警发送成功 -> %s", notify_to)
        return True
    except Exception as e:
        _log.error("邮件告警异常: %s", e)
        return False


def send(msg: AlertMessage, min_level: str = "warning") -> bool:
    """发送告警到所有已配置渠道"""
    if LEVEL_PRIORITY.get(msg.level, 0) < LEVEL_PRIORITY.get(min_level, 0):
        _log.debug("跳过 %s 级别告警（低于阈值 %s）", msg.level, min_level)
        return True

    sent = []
    sent.append(("钉钉", send_dingtalk(msg)))
    sent.append(("飞书", send_feishu(msg)))
    sent.append(("企业微信", send_wecom(msg)))
    sent.append(("邮件", send_email(msg)))

    success = [name for name, ok in sent if ok]
    if success:
        _log.info("告警已发送至: %s", ", ".join(success))
    return bool(success)


# ── 快捷函数 ─────────────────────────────────────────────────────────

def alert_error(title: str, content: str, **kw):
    send(AlertMessage(level="error", title=title, content=content, **kw))

def alert_warning(title: str, content: str, **kw):
    send(AlertMessage(level="warning", title=title, content=content, **kw))

def alert_info(title: str, content: str, **kw):
    send(AlertMessage(level="info", title=title, content=content, **kw))

def alert_critical(title: str, content: str, **kw):
    send(AlertMessage(level="critical", title=title, content=content, **kw))


# ── CLI ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Ruitalk 告警通知工具")
    parser.add_argument("--level", "-l", default="info",
                        choices=["debug","info","warning","error","critical"],
                        help="告警级别（默认 info）")
    parser.add_argument("--title", "-t", required=True, help="告警标题")
    parser.add_argument("--content", "-c", required=True, help="告警内容")
    parser.add_argument("--source", "-s", default="Ruitalk", help="来源（默认 Ruitalk）")
    parser.add_argument("--extra", "-e", nargs="*", help="额外字段，格式: key=value key2=value2")
    parser.add_argument("--min-level", default=None,
                        help="最低告警级别（低于此级别不发送）")
    args = parser.parse_args()

    extra = {}
    if args.extra:
        for item in args.extra:
            if "=" in item:
                k, _, v = item.partition("=")
                extra[k.strip()] = v.strip()

    msg = AlertMessage(
        level=args.level,
        title=args.title,
        content=args.content,
        source=args.source,
        extra=extra,
    )
    min_lvl = args.min_level or _e("ALERT_LEVEL", "warning")
    ok = send(msg, min_level=min_lvl)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
