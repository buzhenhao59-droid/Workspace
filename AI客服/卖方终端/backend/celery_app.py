# -*- coding: utf-8 -*-
"""
Celery 异步任务队列配置
支持：邮件发送 / 消息推送 / 定时备份 / AI 批量处理 / 平台数据同步

依赖：
    pip install celery redis

配置（环境变量）：
    CELERY_BROKER_URL=redis://127.0.0.1:6379/1   # Redis 作为 broker
    CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/2  # 结果存储
    CELERY_TASK_TRACK_STARTED=true
    CELERY_TASK_TIME_LIMIT=300  # 5分钟超时
    CELERY_WORKER_CONCURRENCY=4

用法：
    # 启动 worker
    celery -A celery_app worker --loglevel=info -Q default,ai_tasks,backup_tasks

    # 启动 beat（定时任务调度器）
    celery -A celery_app beat --loglevel=info

    # 调用任务
    from celery_tasks import send_email_task, sync_platform_task
    send_email_task.delay("user@example.com", "标题", "内容")
"""
import os
import sys
from pathlib import Path

# 添加项目路径
_project_root = Path(__file__).resolve().parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from celery import Celery
from celery.schedules import crontab

# ============== 配置加载 ==============

# 优先使用环境变量，兼容 Redis 配置
_broker_url = os.getenv("CELERY_BROKER_URL", "")
if not _broker_url:
    _host = os.getenv("REDIS_HOST", "127.0.0.1")
    _port = os.getenv("REDIS_PORT", "6379")
    _broker_db = int(os.getenv("CELERY_BROKER_DB", "1"))
    _broker_url = f"redis://{_host}:{_port}/{_broker_db}"

_result_url = os.getenv("CELERY_RESULT_BACKEND", "")
if not _result_url:
    _result_db = int(os.getenv("CELERY_RESULT_DB", "2"))
    _result_url = f"redis://{_host}:{_port}/{_result_db}"

# 创建 Celery 应用
celery_app = Celery(
    "ruitalk",
    broker=_broker_url,
    backend=_result_url,
    include=[
        "celery_tasks",
        "policy_crawl_tasks",   # 垂直领域政策爬虫任务
    ]
)

# Celery 配置
celery_app.conf.update(
    # 任务序列化
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Shanghai",
    enable_utc=True,

    # 任务追踪
    task_track_started=True,
    task_acks_late=True,          # 任务完成后才确认（防止丢任务）
    task_reject_on_worker_lost=True,
    task_time_limit=300,          # 5分钟硬超时
    task_soft_time_limit=240,     # 4分钟软超时

    # Worker 配置
    worker_prefetch_multiplier=4,
    worker_max_tasks_per_child=1000,  # 每个 worker 处理 1000 个任务后重启（防内存泄漏）

    # Beat 定时调度
    beat_schedule={
        # ---- 垂直领域政策爬虫（每日 8:00-20:00 每小时整点触发）----
        "vertical-policy-crawl": {
            "task": "policy_crawl_tasks.crawl_all_policies",
            "schedule": crontab(minute=0, hour="8-20"),
            "options": {"expires": 3600},
        },
        # 缓存预热（每小时第 30 分钟）
        "vertical-policy-cache-warm": {
            "task": "policy_crawl_tasks.warm_search_cache",
            "schedule": crontab(minute=30, hour="7-21"),
            "options": {"queue": "default"},
        },
        # 每日凌晨重建索引
        "vertical-policy-daily-reindex": {
            "task": "policy_crawl_tasks.reindex_all_to_meilisearch",
            "schedule": crontab(hour=6, minute=0),
            "options": {"queue": "default"},
        },

        # ---- 原有定时任务 ----
        # 数据库定时备份（每天凌晨 3:00）
        "backup-databases-daily": {
            "task": "celery_tasks.tasks.backup_all_databases",
            "schedule": crontab(hour=3, minute=0),
        },
        # 平台数据同步（每 6 小时）
        "sync-platforms-hourly": {
            "task": "celery_tasks.tasks.sync_all_platforms",
            "schedule": crontab(minute=0, hour="*/6"),
        },
        # 自动回复待评价（每 30 分钟）
        "auto-reply-reviews": {
            "task": "celery_tasks.tasks.auto_reply_pending_reviews",
            "schedule": crontab(minute="*/30"),
        },
        # 清理过期会话（每小时）
        "cleanup-expired-sessions": {
            "task": "celery_tasks.tasks.cleanup_expired_sessions",
            "schedule": crontab(minute=0),
        },
        # 统计报表生成（每天早上 9:00）
        "generate-daily-report": {
            "task": "celery_tasks.tasks.generate_daily_report",
            "schedule": crontab(hour=9, minute=0),
        },
    },
)

if __name__ == "__main__":
    celery_app.start()
