# -*- coding: utf-8 -*-
"""
Celery 异步任务定义
与 celery_app.py 同目录，由 celery_app.conf.include 引用

队列说明：
  - default: 默认队列（通用任务）
  - ai_tasks: AI 处理任务（耗时较长，独立队列避免阻塞）
  - backup_tasks: 备份任务（定时调度，不需要立即响应）
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from celery import Task
from celery_app import celery_app

logger = logging.getLogger("ruitalk.celery")


# ============== 基础任务类 ==============

class RetryTask(Task):
    """支持重试的任务基类"""
    autoretry_for = (Exception,)
    retry_kwargs = {"max_retries": 3}
    retry_backoff = True
    retry_backoff_max = 600
    retry_jitter = True


# ============== 通知类任务 ==============

@celery_app.task(bind=True, base=RetryTask, queue="default", rate_limit="100/m")
def send_email_task(self, to_email: str, subject: str, content: str,
                    smtp_host: str = "", smtp_port: int = 587,
                    smtp_user: str = "", smtp_pass: str = "") -> dict:
    """
    异步发送邮件
    用法: send_email_task.delay("user@example.com", "标题", "内容")
    """
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    try:
        msg = MIMEMultipart("alternative")
        msg["From"] = smtp_user
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(content.replace("\n", "<br>"), "html", "utf-8"))

        with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
            server.ehlo()
            server.starttls()
            if smtp_user and smtp_pass:
                server.login(smtp_user, smtp_pass)
            server.send_message(msg)

        logger.info(f"[Celery] 邮件发送成功: {to_email}")
        return {"success": True, "to": to_email, "sent_at": datetime.now().isoformat()}
    except Exception as e:
        logger.error(f"[Celery] 邮件发送失败: {e}")
        raise


@celery_app.task(bind=True, base=RetryTask, queue="default")
def send_dingtalk_alert_task(self, webhook_url: str, secret: str,
                              level: str, title: str, content: str) -> dict:
    """异步发送钉钉告警"""
    import json
    import time
    import hmac
    import hashlib
    import base64
    import urllib.request

    try:
        url = webhook_url
        if secret:
            timestamp = str(int(time.time() * 1000))
            sign_str = f"{timestamp}\n{secret}"
            sign = base64.b64encode(
                hmac.new(sign_str.encode(), sign_str.encode(), hashlib.sha256).digest()
            ).decode()
            url = f"{webhook_url}&timestamp={timestamp}&sign={sign}"

        body = {
            "msgtype": "markdown",
            "markdown": {
                "title": title,
                "text": f"**{title}**\n\n{content}\n\n> 来源: Ruitalk\n> 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            }
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
        if result.get("errcode") == 0:
            logger.info(f"[Celery] 钉钉告警发送成功: {title}")
            return {"success": True, "title": title}
        return {"success": False, "error": result.get("errmsg")}
    except Exception as e:
        logger.error(f"[Celery] 钉钉告警失败: {e}")
        raise


# ============== 备份类任务 ==============

@celery_app.task(bind=True, base=RetryTask, queue="backup_tasks", max_retries=2)
def backup_all_databases(self) -> dict:
    """
    定时备份所有数据库（每天凌晨 3:00 由 Celery Beat 触发）
    用法: backup_all_databases.delay()
    """
    import subprocess
    import sys

    try:
        # 调用 backup_db.py 执行备份
        _CELERY_DIR = Path(__file__).resolve().parent
        _BACKUP_SCRIPT = str(_CELERY_DIR.parent.parent / "ruitalk_config" / "tools" / "backup_db.py")
        result = subprocess.run(
            [sys.executable, _BACKUP_SCRIPT,
             "--seller", "--buyer", "--compress", "--retention", "30"],
            capture_output=True,
            text=True,
            timeout=300,
        )
        logger.info(f"[Celery] 数据库备份完成: exit={result.returncode}")
        if result.returncode != 0:
            logger.error(f"[Celery] 备份失败: {result.stderr}")
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout[-500:],
            "stderr": result.stderr[-500:],
            "completed_at": datetime.now().isoformat(),
        }
    except Exception as e:
        logger.error(f"[Celery] 备份任务异常: {e}")
        raise


@celery_app.task(bind=True, queue="backup_tasks")
def backup_specific_database(self, db_name: str, db_type: str = "mysql") -> dict:
    """备份指定数据库"""
    import subprocess
    import sys

    try:
        _CELERY_DIR = Path(__file__).resolve().parent
        _BACKUP_SCRIPT = str(_CELERY_DIR.parent.parent / "ruitalk_config" / "tools" / "backup_db.py")
        result = subprocess.run(
            [sys.executable, _BACKUP_SCRIPT,
             "--compress", "--retention", "7"],
            capture_output=True, text=True, timeout=300
        )
        return {
            "success": result.returncode == 0,
            "db": db_name,
            "completed_at": datetime.now().isoformat(),
        }
    except Exception as e:
        logger.error(f"[Celery] 数据库 {db_name} 备份失败: {e}")
        return {"success": False, "db": db_name, "error": str(e)}


# ============== AI 批量处理任务 ==============

@celery_app.task(bind=True, base=RetryTask, queue="ai_tasks",
                 time_limit=600, soft_time_limit=540)
def batch_translate_task(self, texts: list, target_lang: str = "en") -> dict:
    """
    批量翻译文本（AI 加速，避免 API 限流）
    """
    import sys as _sys
    import time as _time
    from pathlib import Path
    _proj = Path(__file__).resolve().parent
    sys_path_added = str(_proj) not in _sys.path
    if sys_path_added:
        _sys.path.insert(0, str(_proj))

    try:
        from services import translate_text

        results = []
        for i, text in enumerate(texts):
            try:
                translated = translate_text(text, target_lang)
                results.append({"original": text[:50], "translated": translated, "success": True})
            except Exception as ex:
                results.append({"original": text[:50], "translated": "", "success": False, "error": str(ex)})
            # 每条间隔 0.5s，避免 API 限流
            _time.sleep(0.5)

        if sys_path_added:
            _sys.path.remove(str(_proj))

        return {
            "total": len(texts),
            "success_count": sum(1 for r in results if r["success"]),
            "results": results,
            "completed_at": datetime.now().isoformat(),
        }
    except Exception as e:
        logger.error(f"[Celery] 批量翻译失败: {e}")
        raise


@celery_app.task(bind=True, base=RetryTask, queue="ai_tasks", time_limit=900)
def auto_reply_pending_reviews_task(self) -> dict:
    """自动回复待处理评价"""
    try:
        import sys as _sys
        from pathlib import Path
        _proj = Path("d:/Ruitalk1/卖方终端/backend")
        if str(_proj) not in _sys.path:
            _sys.path.insert(0, str(_proj))
        from db import auto_reply_pending_reviews
        count = auto_reply_pending_reviews()
        logger.info(f"[Celery] 自动回复评价完成: {count} 条")
        return {"count": count, "completed_at": datetime.now().isoformat()}
    except Exception as e:
        logger.error(f"[Celery] 自动回复评价失败: {e}")
        raise


# ============== 平台同步任务 ==============

@celery_app.task(bind=True, queue="ai_tasks", rate_limit="10/h")
def sync_platform_task(self, platform: str) -> dict:
    """同步指定电商平台数据"""
    try:
        logger.info(f"[Celery] 开始同步平台数据: {platform}")
        # TODO: 各平台 API 实际对接后实现
        # from api_clients import TikTokClient, ShopeeClient
        # client = {"tiktok": TikTokClient, "shopee": ShopeeClient}.get(platform)
        # if client:
        #     client.sync_orders()
        return {
            "platform": platform,
            "synced_at": datetime.now().isoformat(),
            "success": True,
        }
    except Exception as e:
        logger.error(f"[Celery] 平台 {platform} 同步失败: {e}")
        raise


@celery_app.task(bind=True, queue="ai_tasks")
def sync_all_platforms(self) -> dict:
    """同步所有已配置平台"""
    platforms = []
    try:
        import os
        for p in ["tiktok", "shopee", "lazada", "amazon"]:
            key = f"{p.upper()}_ACCESS_TOKEN"
            if os.getenv(key):
                sync_platform_task.delay(p)
                platforms.append(p)
        return {"synced_platforms": platforms, "completed_at": datetime.now().isoformat()}
    except Exception as e:
        logger.error(f"[Celery] 批量平台同步失败: {e}")
        raise


# ============== 清理任务 ==============

@celery_app.task(bind=True, queue="default")
def cleanup_expired_sessions(self) -> dict:
    """清理过期会话数据"""
    try:
        import sys as _sys
        from pathlib import Path
        _proj = Path("d:/Ruitalk1/卖方终端/backend")
        if str(_proj) not in _sys.path:
            _sys.path.insert(0, str(_proj))
        from db import get_db
        from mysql_db import is_mysql

        cleaned = 0
        with get_db() as (conn, cursor):
            if is_mysql():
                cursor.execute("DELETE FROM sessions WHERE updated_at < DATE_SUB(NOW(), INTERVAL 7 DAY) AND status = 'closed'")
            else:
                cursor.execute("DELETE FROM sessions WHERE updated_at < datetime('now', '-7 days') AND status = 'closed'")
            cleaned = cursor.rowcount
            conn.commit()

        logger.info(f"[Celery] 清理过期会话: {cleaned} 条")
        return {"cleaned": cleaned, "completed_at": datetime.now().isoformat()}
    except Exception as e:
        logger.error(f"[Celery] 清理会话失败: {e}")
        return {"cleaned": 0, "error": str(e)}


# ============== 统计报表任务 ==============

@celery_app.task(bind=True, queue="ai_tasks", time_limit=300)
def generate_daily_report_task(self) -> dict:
    """生成每日统计报表"""
    try:
        import sys as _sys
        from pathlib import Path
        _proj = Path("d:/Ruitalk1/卖方终端/backend")
        if str(_proj) not in _sys.path:
            _sys.path.insert(0, str(_proj))
        from db import get_advanced_stats, create_notification

        stats = get_advanced_stats()
        # 生成报表摘要
        report = f"""每日统计报表 - {datetime.now().strftime('%Y-%m-%d')}

会话统计:
  - 活跃会话: {stats.get('active_sessions', 0)}
  - 今日会话: {stats.get('today_sessions', 0)}
  - 在线坐席: {stats.get('online_agents', 0)} / {stats.get('total_agents', 0)}

评价统计:
  - 待回复评价: {stats.get('pending_reviews', 0)}
  - 差评待处理: {stats.get('negative_pending_reviews', 0)}
  - 平均评分: {stats.get('avg_rating', 0)}

售后统计:
  - 待处理售后: {stats.get('pending_after_sales', 0)}
  - 已完成售后: {stats.get('completed_after_sales', 0)}
  - 总退款金额: ¥{stats.get('total_refund_amount', 0):.2f}
"""

        # 创建系统通知
        create_notification(
            notify_type="report",
            title=f"每日统计报表 - {datetime.now().strftime('%Y-%m-%d')}",
            content=report,
            priority="low",
        )

        logger.info(f"[Celery] 每日报表生成完成")
        return {"stats": stats, "completed_at": datetime.now().isoformat()}
    except Exception as e:
        logger.error(f"[Celery] 生成报表失败: {e}")
        raise
