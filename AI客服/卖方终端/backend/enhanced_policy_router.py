# -*- coding: utf-8 -*-
"""
垂直领域政策 API 路由 - 精准数据版
核心改进：
  1. 每次手动搜索从9个权威来源实时抓取
  2. DeepSeek AI 生成一句话摘要
  3. 按发布时间倒序，最多返回10条
  4. 取消自动AI轮询，只保留手动触发
  5. 返回完整数据：原文链接、发布时间、来源名称、AI摘要
"""

import logging
import time
import json
import re
from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Query, Body
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/policy", tags=["垂直领域政策"])


# ============== 数据模型 ==============

class PolicySearchRequest(BaseModel):
    """政策搜索请求"""
    query: str = ""
    time_range: str = "all"
    domain: str = "all"
    page: int = 1
    page_size: int = 10
    include_read: bool = True


# ============== 核心搜索逻辑 ==============

def do_policy_search(
    query: str = "",
    time_range: str = "all",
    domain: str = "all",
    page: int = 1,
    page_size: int = 10,
) -> dict:
    """
    执行政策搜索：
      1. 从9个权威来源实时抓取
      2. 时间范围精确过滤（1天/3天/1周/1月）
      3. 关键词过滤（50+跨境电商关键词 + 用户自定义关键词）
      4. DeepSeek AI 生成一句话摘要（每条）
      5. 按关键词得分+发布时间排序
      6. 返回最多10条
    """
    start_time = time.time()

    try:
        from policy_scrapers_v2 import policy_aggregator

        # 实时抓取（带时间过滤和关键词过滤）
        items = policy_aggregator.scrape_all(
            domain=domain,
            time_range=time_range,
            keyword_filter=query,
            limit=page_size,
        )

        if not items:
            return {
                "success": True,
                "data": [],
                "total": 0,
                "page": page,
                "page_size": page_size,
                "search_time_ms": int((time.time() - start_time) * 1000),
                "source": "live_crawl",
                "message": "当前条件下暂无匹配的政策通知，请尝试扩大时间范围",
                "filters": {"time_range": time_range, "domain": domain, "keyword": query},
            }

        # DeepSeek AI 摘要（批量处理）
        items = _enrich_with_ai_summary(items)

        elapsed_ms = int((time.time() - start_time) * 1000)

        return {
            "success": True,
            "data": items,
            "total": len(items),
            "page": page,
            "page_size": page_size,
            "search_time_ms": elapsed_ms,
            "source": "live_crawl",
            "crawled_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "filters": {"time_range": time_range, "domain": domain, "keyword": query},
        }

    except ImportError as e:
        logger.warning(f"[Policy API] policy_scrapers_v2 未安装: {e}")
        return {
            "success": True,
            "data": [],
            "total": 0,
            "page": page,
            "page_size": page_size,
            "search_time_ms": int((time.time() - start_time) * 1000),
            "source": "fallback",
            "message": "爬虫模块未安装",
        }
    except Exception as e:
        logger.error(f"[Policy API] 搜索失败: {e}")
        return {
            "success": False,
            "data": [],
            "total": 0,
            "message": f"抓取失败: {str(e)}",
        }


def _enrich_with_ai_summary(items: List[dict]) -> List[dict]:
    """
    为政策条目批量生成 AI 摘要
    """
    try:
        import os
        api_key = os.getenv("DEEPSEEK_API_KEY", "")
        api_url = os.getenv(
            "DEEPSEEK_API_URL",
            "https://api.deepseek.com/v1/chat/completions"
        )
        if not api_key:
            for item in items:
                item["ai_summary"] = item.get("ai_summary", "") or ""
                item["target_audience"] = item.get("target_audience", "") or ""
            return items

        import requests

        for item in items:
            content = (item.get("content") or item.get("full_content") or "")[:1500]
            title = item.get("title", "")
            source = item.get("source_name", "")

            if not content or len(content) < 20:
                item["ai_summary"] = ""
                item["target_audience"] = ""
                continue

            prompt = f"""你是一名专业的政策分析师。请分析以下政策，生成简短解读。

【来源】{source}
【标题】{title}
【正文】{content[:800]}

请用JSON格式返回（只返回JSON，不要其他内容）：
{{
  "summary": "一句话总结政策核心（30字以内）",
  "target": "政策涉及的人群或企业类型（20字以内）"
}}"""

            try:
                resp = requests.post(
                    api_url,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {api_key}",
                    },
                    json={
                        "model": "deepseek-chat",
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.2,
                        "max_tokens": 200,
                    },
                    timeout=8,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    text = (data.get("choices", [{}])[0]
                            .get("message", {})
                            .get("content") or "").strip()
                    text = re.sub(r"^```json\s*", "", text, flags=re.IGNORECASE)
                    text = re.sub(r"^```\s*", "", text)
                    text = re.sub(r"\s*```$", "", text)
                    parsed = json.loads(text)
                    item["ai_summary"] = parsed.get("summary", "")
                    item["target_audience"] = parsed.get("target", "")
                else:
                    item["ai_summary"] = ""
                    item["target_audience"] = ""
            except Exception:
                item["ai_summary"] = ""
                item["target_audience"] = ""

    except Exception as e:
        logger.debug(f"[Policy API] AI摘要生成失败: {e}")

    return items


# ============== API 路由 ==============

@router.get("/search")
async def search_policies(
    query: str = Query("", description="搜索关键词"),
    time_range: str = Query("all", description="时间范围: 1d | 3d | 1w | 1m | all"),
    domain: str = Query("all", description="领域: cross_border | government | all"),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=20),
):
    """
    精准政策搜索（手动触发版）

    从9个权威来源实时抓取最新政策，DeepSeek AI 生成摘要，
    按发布时间倒序，最多返回10条。
    """
    result = do_policy_search(
        query=query,
        time_range=time_range,
        domain=domain,
        page=page,
        page_size=page_size,
    )
    return result


@router.post("/search")
async def search_policies_post(body: PolicySearchRequest):
    """POST 版政策搜索"""
    result = do_policy_search(
        query=body.query,
        time_range=body.time_range,
        domain=body.domain,
        page=body.page,
        page_size=body.page_size,
    )
    return result


# ============== 流式 SSE 端点 ==============

import asyncio
import json
from starlette.responses import StreamingResponse


@router.get("/stream")
async def stream_policies(
    query: str = Query("", description="搜索关键词"),
    time_range: str = Query("all", description="时间范围: 1d | 3d | 1w | 1m | all"),
    domain: str = Query("all", description="领域: cross_border | government | all"),
    limit: int = Query(10, ge=1, le=20),
):
    """
    流式政策搜索（SSE Server-Sent Events）

    前端 EventSource 接收，每个数据源爬完立即推送一条，
    实现实时渲染卡片效果。

    事件类型：
      - progress: 数据源抓取进度
      - item: 单条政策条目（可立即渲染）
      - error: 数据源抓取失败
      - done: 全部完成
    """
    async def event_stream():
        try:
            from policy_scrapers_v2 import policy_aggregator
            from policy_scrapers_v2 import CROSS_BORDER_KW, GOVERNMENT_KW

            # 先发送起始事件
            yield f"event: start\ndata: {json.dumps({'status': '开始抓取', 'time_range': time_range, 'domain': domain}, ensure_ascii=False)}\n\n"

            fetched_items = []

            # 流式迭代爬虫
            for event in policy_aggregator.scrape_stream(
                domain=domain,
                time_range=time_range,
                keyword_filter=query,
                limit=limit,
            ):
                evt_type = event.pop("_type", "item")

                if evt_type == "progress":
                    yield f"event: progress\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                elif evt_type == "error":
                    yield f"event: error\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                elif evt_type == "item":
                    fetched_items.append(event)
                    yield f"event: item\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                elif evt_type == "done":
                    # AI 摘要处理（批量）
                    if fetched_items:
                        enriched = _enrich_with_ai_summary(fetched_items)
                        yield f"event: enriched\ndata: {json.dumps({'items': enriched}, ensure_ascii=False)}\n\n"
                    yield f"event: done\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"

            # 确保发送 done
            if not fetched_items:
                yield f"event: done\ndata: {json.dumps({'total': 0, 'status': '无数据'}, ensure_ascii=False)}\n\n"

        except Exception as e:
            logger.error(f"[SSE] 流式搜索异常: {e}")
            yield f"event: error\ndata: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/sources")
async def get_policy_sources():
    """获取所有政策数据源"""
    try:
        from policy_scrapers_v2 import policy_aggregator
        sources = policy_aggregator.get_source_stats()
        return {"success": True, "data": sources, "total": len(sources)}
    except Exception as e:
        return {"success": False, "message": str(e)}


@router.get("/health")
async def search_health():
    """搜索服务健康状态"""
    try:
        from policy_scrapers_v2 import policy_aggregator
        sources = policy_aggregator.get_source_stats()
        return {
            "success": True,
            "scraper_available": True,
            "sources_count": len(sources),
            "total_sources": len(sources),
        }
    except Exception:
        return {
            "success": False,
            "scraper_available": False,
            "message": "爬虫模块不可用",
        }


@router.get("/domains")
async def get_available_domains():
    """获取可用领域"""
    return {
        "success": True,
        "data": [
            {"id": "all", "name": "全部领域", "count": 9},
            {"id": "cross_border", "name": "跨境电商", "count": 4},
            {"id": "government", "name": "政府公告", "count": 5},
        ],
    }
