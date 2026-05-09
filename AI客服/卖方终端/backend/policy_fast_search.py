# -*- coding: utf-8 -*-
"""
垂直领域政策秒级搜索 - Meilisearch + Redis 缓存
替代传统 LIKE 查询，实现毫秒级全文检索

功能：
  1. Meilisearch 全文搜索引擎（支持中文分词）
  2. Redis 多级缓存（1天内/3天内/1周内热点数据）
  3. 搜索结果实时索引
  4. 缓存自动失效与预热
"""

import os
import re
import time
import json
import logging
import threading
import hashlib
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass
from enum import Enum

import redis

logger = logging.getLogger("ruitalk.search")

# ============== 配置 ==============

# Meilisearch 配置
MEILISEARCH_HOST = os.getenv("MEILISEARCH_HOST", os.getenv("MEILISEARCH_URL", "http://localhost:7700"))
MEILISEARCH_KEY = os.getenv("MEILISEARCH_KEY", "")
INDEX_NAME = "ruitalk_policies"

# Redis 配置
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("REDIS_DB", "0"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "") or None

# 缓存 TTL（秒）
CACHE_TTL_1D = 3600       # 1天内数据：1小时
CACHE_TTL_3D = 7200       # 3天内数据：2小时
CACHE_TTL_1W = 14400      # 1周内数据：4小时
CACHE_TTL_DEFAULT = 10800 # 默认：3小时

# 搜索超时（毫秒）
SEARCH_TIMEOUT_MS = 500    # 500ms 内必须返回


# ============== 搜索请求模型 ==============

class TimeRange(Enum):
    DAY_1 = "1d"      # 1天内
    DAY_3 = "3d"      # 3天内
    WEEK_1 = "1w"     # 1周内
    MONTH_1 = "1m"    # 1月内
    ALL = "all"       # 全部


class SearchDomain(Enum):
    CROSS_BORDER = "cross_border"   # 跨境电商
    GOVERNMENT = "government"        # 政务
    ALL = "all"                     # 全部


@dataclass
class SearchRequest:
    """搜索请求"""
    query: str = ""                        # 搜索关键词
    time_range: TimeRange = TimeRange.ALL  # 时间范围
    domain: SearchDomain = SearchDomain.ALL # 内容领域
    page: int = 1                         # 页码
    page_size: int = 20                   # 每页条数
    include_read: bool = True            # 是否包含已读
    sort_by_importance: bool = True      # 是否按重要性排序


@dataclass
class SearchResult:
    """搜索结果"""
    items: List[Dict] = None               # 搜索结果列表
    total: int = 0                        # 总数
    page: int = 1                         # 当前页
    page_size: int = 20                   # 每页条数
    total_pages: int = 0                   # 总页数
    search_time_ms: float = 0.0           # 搜索耗时
    source: str = "cache"                 # 数据来源：cache / meilisearch / db
    cached: bool = False                   # 是否来自缓存


# ============== Meilisearch 客户端封装 ==============

class MeilisearchClient:
    """
    Meilisearch 客户端封装
    自动处理连接失败，优雅降级到 DB 搜索
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
        self._client = None
        self._available = False
        self._init_client()

    def _init_client(self):
        """初始化 Meilisearch 客户端"""
        try:
            import meilisearch
            self._client = meilisearch.Client(MEILISEARCH_HOST, MEILISEARCH_KEY)
            # 健康检查
            health = self._client.health()
            if health.get("status") == "available":
                self._available = True
                self._ensure_index()
                logger.info("[Meilisearch] 连接成功，索引已就绪")
            else:
                self._available = False
                logger.warning("[Meilisearch] 服务不可用，降级到 DB 搜索")
        except ImportError:
            logger.warning("[Meilisearch] meilisearch 库未安装，将使用 DB 搜索")
            self._available = False
        except Exception as e:
            logger.warning(f"[Meilisearch] 连接失败: {e}，降级到 DB 搜索")
            self._available = False

    def _ensure_index(self):
        """确保索引存在并配置正确"""
        if not self._client:
            return
        try:
            # 创建或获取索引
            try:
                self._client.create_index(INDEX_NAME, {"primaryKey": "id"})
            except Exception:
                pass  # 索引可能已存在

            index = self._client.index(INDEX_NAME)

            # 配置中文分词（使用 chinese_char_opt 普通分词）
            try:
                index.update_searchable_attributes([
                    "title",
                    "content",
                    "summary",
                    "source_name",
                    "target_audience",
                ])
                index.update_filterable_attributes([
                    "domain",
                    "data_source",
                    "time_range_key",
                    "is_important",
                    "is_read",
                ])
                index.update_sortable_attributes([
                    "published_date",
                    "crawled_date",
                    "is_important",
                ])
                index.update_ranking_rules([
                    "words",
                    "typo",
                    "proximity",
                    "attribute",
                    "sort",
                    "exactness",
                    "is_important:desc",
                    "published_date:desc",
                ])
            except Exception as e:
                logger.debug(f"[Meilisearch] 索引配置: {e}")
        except Exception as e:
            logger.warning(f"[Meilisearch] 索引初始化失败: {e}")

    @property
    def is_available(self) -> bool:
        return self._available and self._client is not None

    def add_documents(self, documents: List[Dict]) -> bool:
        """添加文档到索引"""
        if not self.is_available:
            return False
        try:
            index = self._client.index(INDEX_NAME)
            # 为每条文档生成 ID
            for i, doc in enumerate(documents):
                doc["id"] = doc.get("id") or doc.get("item_hash") or f"doc_{i}_{int(time.time())}"
                # 生成 time_range_key（用于过滤）
                pub_date = doc.get("published_date")
                if pub_date:
                    try:
                        pub_dt = datetime.fromisoformat(pub_date.replace("Z", "+00:00"))
                        days_ago = (datetime.now() - pub_dt).days
                        if days_ago <= 1:
                            doc["time_range_key"] = "1d"
                        elif days_ago <= 3:
                            doc["time_range_key"] = "3d"
                        elif days_ago <= 7:
                            doc["time_range_key"] = "1w"
                        elif days_ago <= 30:
                            doc["time_range_key"] = "1m"
                        else:
                            doc["time_range_key"] = "older"
                    except Exception:
                        doc["time_range_key"] = "unknown"
                else:
                    doc["time_range_key"] = "unknown"
            index.add_documents(documents)
            return True
        except Exception as e:
            logger.warning(f"[Meilisearch] 添加文档失败: {e}")
            return False

    def search(self, req: SearchRequest) -> Optional[Dict]:
        """
        执行 Meilisearch 搜索

        Args:
            req: SearchRequest 对象

        Returns:
            Meilisearch 搜索结果 dict，或 None（不可用时）
        """
        if not self.is_available:
            return None

        try:
            index = self._client.index(INDEX_NAME)

            # 构建过滤条件
            filters = []
            if not req.include_read:
                filters.append("is_read = 0")
            if req.domain != SearchDomain.ALL:
                filters.append(f"domain = '{req.domain.value}'")
            if req.time_range != TimeRange.ALL:
                filters.append(f"time_range_key = '{req.time_range.value}'")

            filter_str = " AND ".join(filters) if filters else None

            # 排序
            sort = []
            if req.sort_by_importance:
                sort.append("is_important:desc")
            sort.append("published_date:desc")

            offset = (req.page - 1) * req.page_size

            result = index.search(
                req.query,
                {
                    "filter": filter_str,
                    "sort": sort,
                    "offset": offset,
                    "limit": req.page_size,
                    "attributesToRetrieve": ["*"],
                    "showMatchesPosition": True,
                    "matchingStrategy": "all",
                },
            )

            return {
                "hits": result.get("hits", []),
                "estimatedTotalHits": result.get("estimatedTotalHits", 0),
                "processingTimeMs": result.get("processingTimeMs", 0),
                "query": result.get("query", ""),
            }
        except Exception as e:
            logger.warning(f"[Meilisearch] 搜索失败: {e}")
            return None

    def delete_document(self, doc_id: str) -> bool:
        """删除文档"""
        if not self.is_available:
            return False
        try:
            index = self._client.index(INDEX_NAME)
            index.delete_document(doc_id)
            return True
        except Exception as e:
            logger.warning(f"[Meilisearch] 删除文档失败: {e}")
            return False


# ============== Redis 缓存层 ==============

class SearchCache:
    """
    Redis 多级缓存
    按时间范围分层缓存，实现极速响应
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
        self._client: Optional[redis.Redis] = None
        self._available = False
        self._init_redis()

    def _init_redis(self):
        """初始化 Redis 连接"""
        try:
            self._client = redis.Redis(
                host=REDIS_HOST,
                port=REDIS_PORT,
                db=REDIS_DB,
                password=REDIS_PASSWORD,
                decode_responses=True,
                socket_connect_timeout=3,
                socket_timeout=3,
                retry_on_timeout=True,
            )
            # 测试连接
            self._client.ping()
            self._available = True
            logger.info("[SearchCache] Redis 连接成功")
        except redis.exceptions.ConnectionError as e:
            logger.warning(f"[SearchCache] Redis 连接失败: {e}，降级到内存缓存")
            self._available = False
        except Exception as e:
            logger.warning(f"[SearchCache] Redis 初始化失败: {e}")
            self._available = False

    @property
    def is_available(self) -> bool:
        return self._available and self._client is not None

    def _make_cache_key(self, req: SearchRequest) -> str:
        """生成缓存键"""
        raw = (
            f"search:{req.query}:{req.time_range.value}:{req.domain.value}:"
            f"{req.page}:{req.page_size}:{req.include_read}:{req.sort_by_importance}"
        )
        return f"rtk:{hashlib.md5(raw.encode()).hexdigest()}"

    def get(self, req: SearchRequest) -> Optional[Dict]:
        """从缓存获取搜索结果"""
        if not self.is_available:
            return None
        try:
            key = self._make_cache_key(req)
            data = self._client.get(key)
            if data:
                return json.loads(data)
        except Exception as e:
            logger.debug(f"[SearchCache] 读取缓存失败: {e}")
        return None

    def set(self, req: SearchRequest, result: Dict) -> bool:
        """写入缓存"""
        if not self.is_available:
            return False
        try:
            key = self._make_cache_key(req)
            # 根据时间范围选择 TTL
            ttl_map = {
                TimeRange.DAY_1: CACHE_TTL_1D,
                TimeRange.DAY_3: CACHE_TTL_3D,
                TimeRange.WEEK_1: CACHE_TTL_1W,
            }
            ttl = ttl_map.get(req.time_range, CACHE_TTL_DEFAULT)
            self._client.setex(key, ttl, json.dumps(result, ensure_ascii=False, default=str))
            return True
        except Exception as e:
            logger.debug(f"[SearchCache] 写入缓存失败: {e}")
            return False

    def invalidate(self, pattern: str = "rtk:search:*") -> int:
        """清除缓存（支持通配符）"""
        if not self.is_available:
            return 0
        try:
            keys = self._client.keys(pattern)
            if keys:
                return self._client.delete(*keys)
        except Exception as e:
            logger.warning(f"[SearchCache] 清除缓存失败: {e}")
        return 0

    def invalidate_all(self) -> int:
        """清除所有搜索缓存"""
        return self.invalidate("rtk:search:*")

    def warm_cache(self, items: List[Dict]) -> int:
        """预热缓存：将热门数据预先写入"""
        if not self.is_available or not items:
            return 0
        count = 0
        try:
            pipe = self._client.pipeline()
            for item in items[:100]:  # 最多预热 100 条
                pub_date = item.get("published_date")
                if pub_date:
                    try:
                        pub_dt = datetime.fromisoformat(str(pub_date).replace("Z", "+00:00"))
                        days_ago = (datetime.now() - pub_dt).days
                        if days_ago <= 1:
                            tr = TimeRange.DAY_1
                        elif days_ago <= 3:
                            tr = TimeRange.DAY_3
                        elif days_ago <= 7:
                            tr = TimeRange.WEEK_1
                        else:
                            tr = TimeRange.MONTH_1
                    except Exception:
                        tr = TimeRange.MONTH_1
                else:
                    tr = TimeRange.ALL

                for domain in [SearchDomain.ALL, SearchDomain(item.get("domain", "all"))]:
                    for include_read in [True, False]:
                        req = SearchRequest(
                            query="",
                            time_range=tr,
                            domain=domain,
                            include_read=include_read,
                        )
                        key = self._make_cache_key(req)
                        result = {
                            "items": [item] if item.get("id") == item.get("item_hash") else [],
                            "total": 1,
                            "page": 1,
                            "page_size": 20,
                            "total_pages": 1,
                            "source": "cache",
                            "cached": True,
                        }
                        ttl = CACHE_TTL_1W
                        pipe.setex(key, ttl, json.dumps(result, ensure_ascii=False, default=str))
                        count += 1
            pipe.execute()
        except Exception as e:
            logger.warning(f"[SearchCache] 预热失败: {e}")
        return count


# ============== 秒级搜索服务 ==============

class FastSearchService:
    """
    秒级政策搜索服务
    三级降级策略：Cache → Meilisearch → DB
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
        self._meilisearch = MeilisearchClient()
        self._cache = SearchCache()
        logger.info("[FastSearch] 秒级搜索服务初始化完成")

    def search(self, req: SearchRequest) -> SearchResult:
        """
        执行秒级搜索

        搜索优先级：
        1. Redis 缓存 → 毫秒级响应
        2. Meilisearch → <500ms 响应
        3. DB LIKE 查询 → 最后兜底
        """
        start_time = time.time()

        # === 层级 1：缓存命中 ===
        cached = self._cache.get(req)
        if cached:
            elapsed = (time.time() - start_time) * 1000
            return SearchResult(
                items=cached.get("items", []),
                total=cached.get("total", 0),
                page=req.page,
                page_size=req.page_size,
                total_pages=cached.get("total_pages", 1),
                search_time_ms=elapsed,
                source="cache",
                cached=True,
            )

        # === 层级 2：Meilisearch 搜索 ===
        if self._meilisearch.is_available:
            result = self._meilisearch.search(req)
            if result:
                hits = result.get("hits", [])
                total = result.get("estimatedTotalHits", len(hits))
                total_pages = max(1, (total + req.page_size - 1) // req.page_size)

                search_result = SearchResult(
                    items=hits,
                    total=total,
                    page=req.page,
                    page_size=req.page_size,
                    total_pages=total_pages,
                    search_time_ms=result.get("processingTimeMs", 0),
                    source="meilisearch",
                    cached=False,
                )

                # 异步写入缓存（不阻塞响应）
                self._async_cache_write(req, search_result)

                return search_result

        # === 层级 3：DB 回退搜索 ===
        db_result = self._db_fallback_search(req)
        elapsed = (time.time() - start_time) * 1000
        return SearchResult(
            items=db_result.get("items", []),
            total=db_result.get("total", 0),
            page=req.page,
            page_size=req.page_size,
            total_pages=db_result.get("total_pages", 1),
            search_time_ms=elapsed,
            source="db",
            cached=False,
        )

    def _async_cache_write(self, req: SearchRequest, result: SearchResult):
        """异步写入缓存（不阻塞搜索响应）"""
        def _write():
            try:
                cache_data = {
                    "items": result.items,
                    "total": result.total,
                    "page": result.page,
                    "page_size": result.page_size,
                    "total_pages": result.total_pages,
                }
                self._cache.set(req, cache_data)
            except Exception as e:
                logger.debug(f"[FastSearch] 缓存写入失败: {e}")
        threading.Thread(target=_write, daemon=True).start()

    def _db_fallback_search(self, req: SearchRequest) -> Dict:
        """DB 回退搜索（传统 LIKE 查询兜底）"""
        try:
            from message_center_service import message_center_service

            # 根据时间范围计算日期阈值
            days_map = {
                TimeRange.DAY_1: 1,
                TimeRange.DAY_3: 3,
                TimeRange.WEEK_1: 7,
                TimeRange.MONTH_1: 30,
                TimeRange.ALL: None,
            }
            days = days_map.get(req.time_range)

            # 映射 domain 到 notification_type
            type_map = {
                SearchDomain.CROSS_BORDER: ["policy"],
                SearchDomain.GOVERNMENT: ["policy", "market"],
                SearchDomain.ALL: None,
            }
            include_types = type_map.get(req.domain)

            # 构建搜索请求
            limit = req.page_size * req.page
            notifications = message_center_service.get_notifications(
                notification_type=None,
                include_read=req.include_read,
                limit=limit,
                include_types=include_types,
                days=days,
            )

            # 关键词过滤
            if req.query:
                q = req.query.lower()
                notifications = [
                    n for n in notifications
                    if q in (n.get("title") or "").lower()
                    or q in (n.get("content") or "").lower()
                    or q in (n.get("source") or "").lower()
                ]

            # 分页
            start = (req.page - 1) * req.page_size
            end = start + req.page_size
            page_items = notifications[start:end]

            # 按重要性排序
            if req.sort_by_importance:
                page_items = sorted(
                    page_items,
                    key=lambda x: (x.get("is_important", 0), x.get("created_at", "")),
                    reverse=True,
                )

            return {
                "items": page_items,
                "total": len(notifications),
                "total_pages": max(1, (len(notifications) + req.page_size - 1) // req.page_size),
            }
        except Exception as e:
            logger.error(f"[FastSearch] DB 回退搜索失败: {e}")
            return {"items": [], "total": 0, "total_pages": 1}

    def index_documents(self, items: List[Dict]) -> Tuple[int, int]:
        """
        将数据索引到 Meilisearch

        Returns:
            (成功数, 失败数)
        """
        if not items:
            return 0, 0
        success = 0
        failed = 0
        for item in items:
            if self._meilisearch.add_documents([item]):
                success += 1
            else:
                failed += 1
        return success, failed

    def invalidate_cache(self) -> int:
        """清除所有缓存"""
        return self._cache.invalidate_all()

    def warm_cache_from_db(self) -> int:
        """从数据库预热缓存"""
        try:
            from message_center_service import message_center_service
            # 获取最近一周的重要通知
            notifications = message_center_service.get_notifications(
                notification_type=None,
                include_read=True,
                limit=200,
                days=7,
            )
            # 只索引重要或新鲜的
            hot_items = [
                n for n in notifications
                if n.get("is_important") or self._is_fresh(n)
            ]
            return self._cache.warm_cache(hot_items)
        except Exception as e:
            logger.warning(f"[FastSearch] 缓存预热失败: {e}")
            return 0

    @staticmethod
    def _is_fresh(item: Dict) -> bool:
        """判断是否新鲜（24h内）"""
        created = item.get("created_at")
        if not created:
            return False
        try:
            created_dt = datetime.fromisoformat(str(created).replace("Z", "+00:00"))
            return (datetime.now() - created_dt).total_seconds() < 86400
        except Exception:
            return False


# ============== 便捷搜索函数 ==============

def fast_search(
    query: str = "",
    time_range: str = "all",
    domain: str = "all",
    page: int = 1,
    page_size: int = 20,
) -> SearchResult:
    """
    便捷搜索函数

    用法:
        result = fast_search("TikTok 政策", time_range="1d", domain="cross_border")
    """
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
    )

    service = FastSearchService()
    return service.search(req)


# 单例导出
fast_search_service = FastSearchService()
meilisearch_client = MeilisearchClient()
search_cache = SearchCache()
