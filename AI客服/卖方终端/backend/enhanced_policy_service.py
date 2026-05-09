# -*- coding: utf-8 -*-
"""
垂直领域政策服务 - Enhanced Policy Service
整合爬虫 + AI 预处理 + Meilisearch 秒级搜索 + Redis 缓存

对外暴露统一接口，同时支持：
  - 新版快速搜索（Meilisearch + Redis）
  - 旧版数据库查询（向后兼容）
  - 手动触发爬取
  - 领域过滤（跨境电商 / 政务）
"""

import logging
import json
import threading
import time
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple

logger = logging.getLogger("ruitalk.policy_service")


# ============== 通知类型映射 ==============

NOTIFICATION_TYPE_MAP = {
    "cross_border": ["policy"],
    "government": ["policy", "market"],
    "all": None,
}


class EnhancedPolicyService:
    """
    增强版政策服务
    同时管理：爬虫、搜索、数据库操作
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, "_initialized") and self._initialized:
            return
        self._initialized = True
        self._search_available = False
        self._meilisearch_available = False
        self._cache_available = False
        self._init_components()

    def _init_components(self):
        """初始化各组件"""
        try:
            from policy_fast_search import fast_search_service, SearchRequest, SearchDomain, TimeRange
            self._search = fast_search_service
            self._search_available = True
            logger.info("[PolicyService] 快速搜索服务已就绪")
        except ImportError:
            logger.warning("[PolicyService] policy_fast_search 未安装，降级到数据库查询")
            self._search = None

        try:
            from policy_crawl_tasks import crawl_all_policies
            self._crawl_task = crawl_all_policies
        except ImportError:
            self._crawl_task = None

    # ============== 搜索接口（统一入口） ==============

    def search(
        self,
        query: str = "",
        time_range: str = "all",
        domain: str = "all",
        page: int = 1,
        page_size: int = 20,
        include_read: bool = True,
    ) -> Dict:
        """
        统一搜索接口

        Args:
            query: 搜索关键词
            time_range: 时间范围 1d / 3d / 1w / 1m / all
            domain: 内容领域 cross_border / government / all
            page: 页码
            page_size: 每页数量
            include_read: 是否包含已读

        Returns:
            统一的搜索结果 dict
        """
        from policy_fast_search import fast_search_service, SearchRequest, SearchDomain, TimeRange

        tr_map = {
            "1d": TimeRange.DAY_1,
            "3d": TimeRange.DAY_3,
            "1w": TimeRange.WEEK_1,
            "1m": TimeRange.MONTH_1,
            "all": TimeRange.ALL,
        }
        dm_map = {
            "cross_border": SearchDomain.CROSS_BORDER,
            "government": SearchDomain.GOVERNMENT,
            "all": SearchDomain.ALL,
        }

        req = SearchRequest(
            query=query,
            time_range=tr_map.get(time_range, TimeRange.ALL),
            domain=dm_map.get(domain, SearchDomain.ALL),
            page=page,
            page_size=page_size,
            include_read=include_read,
        )

        result = fast_search_service.search(req)

        # 标准化返回格式
        return {
            "success": True,
            "data": result.items,
            "total": result.total,
            "page": result.page,
            "page_size": result.page_size,
            "total_pages": result.total_pages,
            "search_time_ms": round(result.search_time_ms, 1),
            "source": result.source,
            "cached": result.cached,
            "domain": domain,
            "time_range": time_range,
            "query": query,
        }

    # ============== 通知管理接口 ==============

    def get_notifications(
        self,
        notification_type: Optional[str] = None,
        include_read: bool = True,
        limit: int = 50,
        exclude_types: Optional[List[str]] = None,
        include_types: Optional[List[str]] = None,
        days: Optional[int] = None,
        domain: Optional[str] = None,
    ) -> List[Dict]:
        """获取通知列表（向后兼容 message_center_service）"""
        try:
            from message_center_service import message_center_service
        except ImportError:
            return []

        # 领域过滤
        if domain and domain != "all":
            include_types = NOTIFICATION_TYPE_MAP.get(domain)

        notifications = message_center_service.get_notifications(
            notification_type=notification_type,
            include_read=include_read,
            limit=limit,
            exclude_types=exclude_types,
            include_types=include_types,
            days=days,
        )

        # 补充前端所需字段
        for n in notifications:
            # 确保有 domain 字段
            if "domain" not in n:
                n["domain"] = self._infer_domain(n.get("source", ""))
            # 确保有时效性标记
            if "is_fresh" not in n:
                n["is_fresh"] = self._is_fresh(n)
            # 添加标签
            if "tags" not in n:
                n["tags"] = self._generate_tags(n)

        return notifications

    def _infer_domain(self, source: str) -> str:
        """从来源推断领域"""
        government_sources = ["辽宁省", "人社厅", "商务厅", "gov.cn", "人民政府"]
        for kw in government_sources:
            if kw in source:
                return "government"
        return "cross_border"

    def _is_fresh(self, item: Dict) -> bool:
        """判断是否新鲜（2小时内）"""
        created = item.get("created_at")
        if not created:
            return False
        try:
            created_str = str(created)
            # 支持多种日期格式
            for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"]:
                try:
                    created_dt = datetime.strptime(created_str[:19], fmt)
                    diff_hours = (datetime.now() - created_dt).total_seconds() / 3600
                    return diff_hours <= 2
                except ValueError:
                    continue
        except Exception:
            pass
        return False

    def _generate_tags(self, item: Dict) -> List[str]:
        """生成标签"""
        tags = []
        domain = item.get("domain", "")
        source = item.get("source", "")
        is_important = item.get("is_important", 0)
        is_fresh = item.get("is_fresh", False)

        # 领域标签
        if domain == "government":
            tags.append({"label": "政府公告", "color": "#7c3aed", "bg": "#f3e8ff"})
        else:
            tags.append({"label": "跨境电商", "color": "#0891b2", "bg": "#ecfeff"})

        # 重要标记
        if is_important:
            tags.append({"label": "重要", "color": "#dc2626", "bg": "#fee2e2"})

        # 最新标记
        if is_fresh:
            tags.append({"label": "最新", "color": "#16a34a", "bg": "#dcfce7", "blink": True})

        return tags

    # ============== 统计接口 ==============

    def get_stats(self, domain: str = "all") -> Dict:
        """获取政策统计"""
        try:
            from message_center_service import message_center_service
        except ImportError:
            return {}

        # 各领域未读数
        stats = {
            "cross_border": {"total": 0, "unread": 0},
            "government": {"total": 0, "unread": 0},
            "all": {"total": 0, "unread": 0},
        }

        for dom in ["cross_border", "government"]:
            incl_types = NOTIFICATION_TYPE_MAP.get(dom)
            total = len(message_center_service.get_notifications(
                include_read=True, limit=1000, include_types=incl_types
            ))
            unread = message_center_service.get_unread_notification_count(
                include_types=incl_types
            )
            stats[dom] = {"total": total, "unread": unread}

        stats["all"]["total"] = sum(s["total"] for s in stats.values())
        stats["all"]["unread"] = sum(s["unread"] for s in stats.values())

        # 搜索引擎状态
        try:
            from policy_fast_search import fast_search_service
            stats["search_engine"] = {
                "cache_available": fast_search_service._cache.is_available if hasattr(fast_search_service, "_cache") else False,
                "meilisearch_available": fast_search_service._meilisearch.is_available if hasattr(fast_search_service, "_meilisearch") else False,
            }
        except Exception:
            stats["search_engine"] = {"cache_available": False, "meilisearch_available": False}

        # 爬虫状态
        try:
            from policy_scrapers import vertical_scraper
            stats["scrapers"] = vertical_scraper.get_scraper_stats()
        except Exception:
            stats["scrapers"] = {}

        return stats

    # ============== 手动触发 ==============

    def trigger_crawl(self, sync: bool = False) -> Dict:
        """手动触发爬取"""
        try:
            from policy_crawl_tasks import crawl_all_policies
            if sync:
                result = crawl_all_policies.apply_async().get(timeout=300)
                return {"success": True, "sync": True, "result": result}
            else:
                task = crawl_all_policies.delay()
                return {"success": True, "sync": False, "task_id": task.id}
        except ImportError:
            return {"success": False, "message": "celery 未安装，无法触发任务"}
        except Exception as e:
            logger.error(f"[PolicyService] 触发爬取失败: {e}")
            return {"success": False, "message": str(e)}

    def trigger_reindex(self) -> Dict:
        """触发 Meilisearch 重建索引"""
        try:
            from policy_crawl_tasks import reindex_all_to_meilisearch
            task = reindex_all_to_meilisearch.delay()
            return {"success": True, "task_id": task.id}
        except ImportError:
            return {"success": False, "message": "celery 未安装"}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def clear_cache(self) -> Dict:
        """清除搜索缓存"""
        try:
            from policy_fast_search import fast_search_service
            count = fast_search_service.invalidate_cache()
            return {"success": True, "invalidated": count}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def warm_cache(self) -> Dict:
        """预热缓存"""
        try:
            from policy_fast_search import fast_search_service
            count = fast_search_service.warm_cache_from_db()
            return {"success": True, "warmed": count}
        except Exception as e:
            return {"success": False, "message": str(e)}


# 单例
enhanced_policy_service = EnhancedPolicyService()
