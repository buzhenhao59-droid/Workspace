# -*- coding: utf-8 -*-
"""
垂直领域政策定时抓取任务 - v3
调度策略：每天早8点至晚8点，每2小时触发一次（8/10/12/14/16/18点，共6次）

每次触发：
  1. 从7个权威来源实时爬取最新政策（1天内）
  2. SHA256(title+url) 去重
  3. DeepSeek AI 预处理（摘要、人群、时效）
  4. 写入 notifications 表
  5. 清除相关缓存
"""

import logging
import json
import hashlib
import time
import os
from datetime import datetime, timedelta
from celery import Task
from celery_app import celery_app

logger = logging.getLogger("ruitalk.celery")

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_API_URL = os.getenv("DEEPSEEK_API_URL", "https://api.deepseek.com/v1/chat/completions")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")


class RetryTask(Task):
    autoretry_for = (Exception,)
    retry_kwargs = {"max_retries": 3}
    retry_backoff = True
    retry_backoff_max = 600
    retry_jitter = True


# ============== DeepSeek AI 预处理 ==============

def call_deepseek(content: str, domain: str = "cross_border") -> dict:
    """调用 DeepSeek API 生成政策分析"""
    if not DEEPSEEK_API_KEY or not content:
        return _fallback_analysis(content)

    prompt = f"""你是一名专业的政策分析师。请分析以下政策，生成结构化解读。

【政策正文】（前1500字）
{content[:1500]}

请用 JSON 格式返回（只返回JSON，不要其他内容）：
{{
  "summary": "一句话总结核心利好或风险（50字以内）",
  "target_audience": "适用人群或企业类型（20字以内）",
  "policy_type": "利好/风险/通知/补贴",
  "key_benefit": "最核心要点（30字以内）"
}}"""

    try:
        import requests
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        }
        resp = requests.post(
            DEEPSEEK_API_URL,
            headers=headers,
            json={
                "model": DEEPSEEK_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2,
                "max_tokens": 512,
            },
            timeout=30,
        )
        if resp.status_code != 200:
            logger.warning(f"[AI] DeepSeek {resp.status_code}")
            return _fallback_analysis(content)

        data = resp.json()
        text = (data.get("choices", [{}])[0].get("message", {}).get("content") or "").strip()
        import re
        text = re.sub(r"^```json\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"^```\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()
        return json.loads(text)
    except Exception as e:
        logger.warning(f"[AI] 调用失败: {e}")
        return _fallback_analysis(content)


def _fallback_analysis(content: str) -> dict:
    """AI 不可用时的兜底分析"""
    return {
        "summary": (content or "")[:100],
        "target_audience": "跨境电商从业者/企业",
        "policy_type": "通知",
        "key_benefit": "",
    }


def compute_dedup_hash(title: str, url: str) -> str:
    raw = (title + url).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:24]


# ============== Celery 定时任务（每2小时） ==============

@celery_app.task(
    bind=True,
    base=RetryTask,
    queue="ai_tasks",
    name="vertical_policy.crawl_all",
)
def crawl_all_policies(self) -> dict:
    """
    定时全量抓取任务
    由 Celery Beat 每2小时触发（8/10/12/14/16/18点）
    实时爬取7个权威来源，过滤24小时内新政策，写入通知表
    """
    start_time = time.time()
    logger.info(f"[Crawl] ========== 定时抓取开始 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ==========")

    try:
        from policy_scrapers_v2 import policy_aggregator, TimeRange

        now = datetime.now()
        logger.info(f"[Crawl] 系统时间: {now.strftime('%Y-%m-%d %H:%M:%S')}")

        # 抓取24小时内的所有政策（双领域）
        items = policy_aggregator.scrape_all(
            domain="all",
            time_range="1d",   # 只抓24小时内
            keyword_filter="",
            limit=20,
        )
        logger.info(f"[Crawl] 实时爬取完成: {len(items)} 条")

        if not items:
            logger.info("[Crawl] 无新数据")
            return {"success": True, "crawled": 0, "saved": 0, "skipped": 0, "elapsed_s": round(time.time() - start_time, 1)}

        # AI 预处理
        processed = []
        for item in items:
            content = (item.get("content") or "")[:1500]
            if not content:
                content = (item.get("full_content") or "")[:1500]
            analysis = call_deepseek(content, item.get("domain", "cross_border"))
            item["ai_summary"] = analysis.get("summary", "")
            item["target_audience"] = analysis.get("target_audience", "")
            item["policy_type"] = analysis.get("policy_type", "通知")
            item["key_benefit"] = analysis.get("key_benefit", "")
            item["published_date_str"] = item.get("published_date_str", "")
            item["published_date"] = item.get("published_date", "")
            item["is_important"] = 1 if item.get("keyword_score", 0) >= 3 else 0
            processed.append(item)

        logger.info(f"[Crawl] AI预处理完成: {len(processed)} 条")

        # 写入通知表
        saved = 0
        skipped = 0
        from message_center_service import message_center_service

        for item in processed:
            dedup_hash = compute_dedup_hash(item.get("title", ""), item.get("url", ""))

            # 去重：检查URL是否已存在
            is_dup = False
            try:
                existing = message_center_service.get_notifications(
                    notification_type="policy",
                    include_read=True,
                    limit=50,
                )
                url = item.get("url", "")
                is_dup = any(n.get("url") == url for n in existing if url)
            except Exception:
                pass

            if is_dup:
                skipped += 1
                continue

            try:
                message_center_service.add_notification(
                    notification_type="policy",
                    title=item.get("title", ""),
                    content=item.get("content", "")[:3000],
                    source=item.get("source_name", "政策爬虫"),
                    url=item.get("url", ""),
                    is_important=bool(item.get("is_important")),
                    # kwargs 字段（适配 message_center_service.add_notification）
                    domain=item.get("domain", ""),
                    data_source=item.get("source_id", ""),
                    item_hash=compute_dedup_hash(item.get("title", ""), item.get("url", "")),
                    summary=item.get("ai_summary", ""),
                    target_audience=item.get("target_audience", ""),
                    policy_type=item.get("policy_type", "通知"),
                    key_benefit=item.get("key_benefit", ""),
                    is_fresh=item.get("is_fresh", False),
                )
                saved += 1
            except Exception as e:
                logger.warning(f"[Crawl] 保存失败: {e}")

        elapsed = round(time.time() - start_time, 1)
        logger.info(f"[Crawl] 完成: 新增={saved}, 跳过={skipped}, 耗时={elapsed}s")

        return {
            "success": True,
            "crawled": len(items),
            "saved": saved,
            "skipped": skipped,
            "elapsed_s": elapsed,
            "crawled_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    except ImportError as e:
        logger.error(f"[Crawl] 导入失败: {e}")
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error(f"[Crawl] 任务异常: {e}")
        return {"success": False, "error": str(e)}


# ============== Celery Beat 调度配置（每2小时） ==============

from celery.schedules import crontab

celery_app.conf.beat_schedule = {
    # 定时抓取：每天早8点至晚8点，每2小时一次（8/10/12/14/16/18点）
    "vertical-policy-crawl-every-2h": {
        "task": "policy_crawl_tasks.crawl_all_policies",
        "schedule": crontab(minute=0, hour="8,10,12,14,16,18"),
        "options": {"expires": 3600, "queue": "ai_tasks"},
    },
}

logger.info("[CeleryBeat] 政策定时抓取已配置: 每天 8/10/12/14/16/18 点触发")
