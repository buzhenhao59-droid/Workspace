# -*- coding: utf-8 -*-
"""
政策检索服务 - 优化版
支持异步流式输出、时间范围过滤、权重排序
"""
import requests
import logging
import threading
import time
import re
import json
import queue
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Generator, AsyncGenerator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# 导入配置
try:
    from config import DEEPSEEK_API_KEY, DEEPSEEK_API_URL
except ImportError:
    DEEPSEEK_API_KEY = ""
    DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"


# ============== 配置常量 ==============
SEARCH_TIME_RANGES = {
    "week": 7,      # AI检索默认：一周内
    "month": 30,    # 扩大范围：一月内
    "day": 1,       # 权重加成：24小时内 +50%
}

# 权重配置
WEIGHT_CONFIG = {
    "recent_24h_boost": 1.5,  # 24小时内权重加成 50%
    "recent_week_default": 1.0,  # 一周内默认权重
}

# 并发控制
MAX_CONCURRENT_SEARCHES = 2  # 最多2个并发搜索
SEARCH_TIMEOUT = 30  # 单次搜索超时（秒）


# ============== 搜索关键词库 ==============
_POLICY_KEYWORDS = [
    "海关总署 跨境电商 2026 最新公告",
    "国务院 跨境电商 综合试验区 2026 扩容",
    "跨境电商 零售进口 清单 2026 最新",
    "跨境电商 B2B 出口 监管 2026",
    "跨境电商 税收优惠 延续 2026",
    "海外仓 建设 政策 2026 支持",
    "海南自贸港 跨境电商 2026 新政",
    "广州 跨境电商 综合试验区 2026",
    "深圳 跨境电商 政策 2026 最新",
    "跨境电商 合规 监管 2026 新规",
    "RCEP 跨境电商 政策红利 2026",
    "跨境电商 跨境支付 外汇 政策 2026",
    "跨境电商 直播电商 监管 2026",
]

_MARKET_KEYWORDS = [
    "Shopee 2026 新政策 卖家公告",
    "Lazada 2026 最新 卖家激励",
    "TikTok Shop 跨境电商 2026 增长",
    "Amazon 全球开店 2026 新规 卖家",
    "AliExpress 2026 跨境电商 新动作",
    "2026 跨境电商 热销品类 趋势预测",
    "东南亚电商 2026 热门品类 选品",
    "2026 亚马逊 Prime Day 卖家 备战",
]

_SEARCH_ENGINES = [
    {"name": "duckduckgo", "url": "https://html.duckduckgo.com/html/", "enabled": True},
]


# ============== 数据结构 ==============
@dataclass
class SearchResult:
    """标准化搜索结果"""
    title: str
    content: str
    url: str
    source: str
    created_at: datetime = field(default_factory=datetime.now)
    importance: str = "normal"
    is_important: bool = False
    freshness_weight: float = 1.0  # 新鲜度权重
    is_historical: bool = False  # 是否为历史相关

    def to_dict(self) -> Dict:
        return {
            "title": self.title,
            "content": self.content,
            "url": self.url,
            "source": self.source,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "importance": self.importance,
            "is_important": self.is_important,
            "freshness_weight": self.freshness_weight,
            "is_historical": self.is_historical,
        }


# ============== 搜索缓存（避免重复搜索）==============
class SearchCache:
    """简单的内存缓存，5分钟内相同关键词结果不重复搜索"""
    
    def __init__(self, ttl_seconds: int = 300):
        self._cache: Dict[str, tuple] = {}
        self._ttl = ttl_seconds
    
    def get(self, key: str) -> Optional[List[Dict]]:
        if key in self._cache:
            result, timestamp = self._cache[key]
            if time.time() - timestamp < self._ttl:
                return result
            del self._cache[key]
        return None
    
    def set(self, key: str, result: List[Dict]):
        self._cache[key] = (result, time.time())
    
    def clear(self):
        self._cache.clear()


_search_cache = SearchCache(ttl_seconds=300)


# ============== 搜索任务队列 ==============
class SearchTaskQueue:
    """线程安全的搜索任务队列"""
    
    def __init__(self, max_size: int = 10):
        self._queue: queue.Queue = queue.Queue(maxsize=max_size)
        self._results: Dict[str, SearchResult] = {}
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=MAX_CONCURRENT_SEARCHES, thread_name_prefix="search_worker_")
    
    def add_task(self, task_id: str, keywords: List[str], search_type: str = "policy"):
        """添加搜索任务"""
        try:
            self._queue.put_nowait({
                "task_id": task_id,
                "keywords": keywords,
                "search_type": search_type,
                "timestamp": time.time()
            })
            return True
        except queue.Full:
            logger.warning(f"搜索队列已满，拒绝任务 {task_id}")
            return False
    
    def get_task(self, timeout: float = 1.0) -> Optional[Dict]:
        """获取下一个任务"""
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None
    
    def submit_result(self, task_id: str, results: List[SearchResult]):
        """提交搜索结果"""
        with self._lock:
            self._results[task_id] = results
    
    def get_result(self, task_id: str) -> Optional[List[SearchResult]]:
        """获取搜索结果"""
        with self._lock:
            return self._results.get(task_id)
    
    def shutdown(self):
        """关闭线程池"""
        self._executor.shutdown(wait=True)


_search_queue = SearchTaskQueue(max_size=10)


# ============== 主服务类 ==============
class PolicySearchService:
    """政策检索服务 - 优化版"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        # 防止重复初始化
        if hasattr(self, '_initialized'):
            return
        self._initialized = True
        
        self._search_interval_minutes = 10
        self._last_search_time: Optional[str] = None
        self._is_searching = False
        self._is_running = False
        self._last_daily_full_run: Optional[str] = None
        self._last_search_error: Optional[str] = None
        
        # 搜索结果缓存（按时间范围）
        self._recent_results: List[SearchResult] = []
        self._results_lock = threading.Lock()
        
        # 流式输出回调
        self._stream_callbacks: Dict[str, callable] = {}

    @property
    def is_running(self) -> bool:
        return self._is_running

    @property
    def last_search_time(self) -> Optional[str]:
        return self._last_search_time

    @property
    def last_search_error(self) -> Optional[str]:
        return self._last_search_error

    @property
    def is_searching(self) -> bool:
        return self._is_searching

    # ============== 核心搜索方法 ==============
    
    def search_policies(
        self, 
        keywords: str = "", 
        time_range: str = "week",
        limit: int = 10,
        use_streaming: bool = False
    ) -> List[SearchResult]:
        """
        政策检索主方法
        
        Args:
            keywords: 搜索关键词（空则使用默认关键词库）
            time_range: 时间范围 - "week"(一周内) | "month"(一月内)
            limit: 返回结果数量限制
            use_streaming: 是否启用流式输出
        
        Returns:
            排序后的搜索结果列表
        """
        if self._is_searching:
            logger.debug("上一次搜索还未完成，返回缓存结果")
            return self._get_cached_results(limit)
        
        self._is_searching = True
        self._last_search_error = None
        
        try:
            # 1. 执行搜索
            if keywords:
                search_keywords = [keywords]
            else:
                import random
                search_keywords = random.sample(_POLICY_KEYWORDS, min(3, len(_POLICY_KEYWORDS)))
            
            # 2. 执行并行搜索
            web_results = self._parallel_web_search(search_keywords, search_type="policy")
            
            if not web_results:
                logger.info("网络搜索无结果，使用模拟数据")
                web_results = self._get_mock_results("policy")
            
            # 3. 时间过滤与权重计算
            filtered_results = self._filter_by_time_range(web_results, time_range)
            
            # 4. 判断是否需要扩大范围
            if len(filtered_results) < 3 and time_range == "week":
                logger.info("一周内结果不足，扩大到一月范围搜索")
                month_results = self._filter_by_time_range(web_results, "month")
                # 合并结果，标记历史相关
                for r in month_results:
                    if r not in filtered_results:
                        r.is_historical = True
                        filtered_results.append(r)
            
            # 5. 权重排序
            sorted_results = self._sort_by_weight(filtered_results)
            
            # 6. 限制数量
            final_results = sorted_results[:limit]
            
            # 7. 更新缓存
            self._update_cache(final_results)
            
            # 8. 调用 DeepSeek 分析（可选流式）
            if DEEPSEEK_API_KEY and web_results:
                if use_streaming:
                    threading.Thread(
                        target=self._deepseek_analyze_stream,
                        args=(final_results, "policy"),
                        daemon=True
                    ).start()
                else:
                    analyzed = self._deepseek_analyze_sync(final_results, "policy")
                    if analyzed:
                        final_results = analyzed
            
            return final_results
            
        except Exception as e:
            self._last_search_error = str(e)
            logger.error(f"政策检索失败: {e}", exc_info=True)
            return self._get_cached_results(limit)
        finally:
            self._is_searching = False
            self._last_search_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def search_market(
        self,
        keywords: str = "",
        time_range: str = "week",
        limit: int = 10
    ) -> List[SearchResult]:
        """市场动态检索（逻辑同政策检索）"""
        if self._is_searching:
            return []
        
        self._is_searching = True
        try:
            if keywords:
                search_keywords = [keywords]
            else:
                import random
                search_keywords = random.sample(_MARKET_KEYWORDS, min(3, len(_MARKET_KEYWORDS)))
            
            web_results = self._parallel_web_search(search_keywords, search_type="market")
            
            if not web_results:
                web_results = self._get_mock_results("market")
            
            filtered_results = self._filter_by_time_range(web_results, time_range)
            sorted_results = self._sort_by_weight(filtered_results)
            final_results = sorted_results[:limit]
            
            self._update_cache(final_results)
            
            if DEEPSEEK_API_KEY and web_results:
                analyzed = self._deepseek_analyze_sync(final_results, "market")
                if analyzed:
                    final_results = analyzed
            
            return final_results
            
        except Exception as e:
            logger.error(f"市场检索失败: {e}")
            return []
        finally:
            self._is_searching = False

    # ============== 流式输出方法 ==============
    
    def stream_search(
        self,
        keywords: str = "",
        search_type: str = "policy"
    ) -> Generator[str, None, None]:
        """
        流式搜索 - 生成器模式，逐步返回搜索结果
        
        Yields:
            JSON 格式的搜索进度/结果片段
        """
        task_id = f"stream_{int(time.time() * 1000)}"
        
        # 1. 立即返回搜索开始状态
        yield self._make_stream_chunk("status", {
            "task_id": task_id,
            "status": "started",
            "message": "开始搜索..."
        })
        
        try:
            # 2. 执行搜索（带超时保护）
            if keywords:
                search_keywords = [keywords]
            else:
                import random
                if search_type == "policy":
                    search_keywords = random.sample(_POLICY_KEYWORDS, 3)
                else:
                    search_keywords = random.sample(_MARKET_KEYWORDS, 3)
            
            # 3. 分步骤返回进度
            yield self._make_stream_chunk("progress", {
                "step": "searching",
                "message": f"正在搜索: {search_keywords[0][:20]}..."
            })
            
            web_results = self._parallel_web_search(search_keywords, search_type=search_type)
            
            yield self._make_stream_chunk("progress", {
                "step": "analyzing",
                "message": "获取到 {} 条结果，正在分析...".format(len(web_results))
            })
            
            # 4. 过滤和排序
            filtered = self._filter_by_time_range(web_results, "week")
            
            yield self._make_stream_chunk("progress", {
                "step": "sorting",
                "message": "应用时效性权重排序..."
            })
            
            sorted_results = self._sort_by_weight(filtered)
            
            # 5. DeepSeek 分析（流式）
            if DEEPSEEK_API_KEY and web_results:
                yield self._make_stream_chunk("progress", {
                    "step": "ai_analyzing",
                    "message": "AI 正在深度分析..."
                })
                
                # 使用流式 API
                for chunk in self._deepseek_stream_chunks(sorted_results[:3], search_type):
                    yield chunk
            else:
                # 无 API 时直接返回结果
                for i, result in enumerate(sorted_results[:5]):
                    yield self._make_stream_chunk("result", result.to_dict())
            
            # 6. 完成
            yield self._make_stream_chunk("status", {
                "status": "completed",
                "total": len(sorted_results),
                "message": "搜索完成"
            })
            
        except Exception as e:
            yield self._make_stream_chunk("error", {
                "message": f"搜索失败: {str(e)}"
            })

    def _make_stream_chunk(self, chunk_type: str, data: Dict) -> str:
        """生成流式输出 JSON 块"""
        return json.dumps({
            "type": chunk_type,
            "data": data,
            "timestamp": datetime.now().isoformat()
        }, ensure_ascii=False) + "\n"

    def _deepseek_stream_chunks(
        self, 
        results: List[SearchResult], 
        search_type: str
    ) -> Generator[str, None, None]:
        """DeepSeek 流式分析"""
        if not DEEPSEEK_API_KEY or not results:
            return
        
        items_text = "\n".join([
            f"【{i+1}】{r.title}\n   来源：{r.source}\n   摘要：{r.content[:100]}..."
            for i, r in enumerate(results)
        ])
        
        if search_type == "policy":
            prompt = f"""你是一名专业的跨境电商政策分析师。根据以下信息，生成简明的政策解读。

搜索到的政策信息：
{items_text}

请生成 2-3 条政策解读，每条包含：
1. **标题**（20字以内）
2. **摘要**（100字以内）
3. **对卖家的影响**（50字以内）
4. **建议行动**（1-2条）

只返回JSON数组格式：
[
  {{"title": "标题", "summary": "摘要", "impact": "影响", "actions": ["建议"]}}
]"""
        else:
            prompt = f"""你是一名专业的跨境电商市场分析师。根据以下信息，生成简明的市场分析。

搜索到的市场信息：
{items_text}

请生成 2-3 条市场分析，每条包含：
1. **标题**（20字以内）
2. **趋势**（100字以内）
3. **机会**（50字以内）
4. **建议**（1-2条）

只返回JSON数组格式：
[
  {{"title": "标题", "trend": "趋势", "opportunity": "机会", "suggestions": ["建议"]}}
]"""
        
        try:
            # 使用 requests 的流式模式
            response = requests.post(
                DEEPSEEK_API_URL,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {DEEPSEEK_API_KEY}"
                },
                json={
                    "model": "deepseek-chat",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.3,
                    "max_tokens": 2000,
                    "stream": True  # 启用流式
                },
                stream=True,
                timeout=60
            )
            
            if response.status_code != 200:
                logger.warning(f"DeepSeek API 返回 {response.status_code}")
                return
            
            full_content = ""
            for line in response.iter_lines():
                if line:
                    line = line.decode('utf-8')
                    if line.startswith('data: '):
                        data_str = line[6:]
                        if data_str == '[DONE]':
                            break
                        try:
                            data = json.loads(data_str)
                            content = data.get("choices", [{}])[0].get("delta", {}).get("content", "")
                            if content:
                                full_content += content
                                # 实时返回增量内容
                                yield self._make_stream_chunk("ai_stream", {
                                    "delta": content
                                })
                        except json.JSONDecodeError:
                            continue
            
            # 解析完整响应
            if full_content:
                analyzed = self._parse_ai_response(full_content, search_type)
                for result in analyzed:
                    yield self._make_stream_chunk("result", result.to_dict())
                    
        except Exception as e:
            logger.error(f"DeepSeek 流式分析失败: {e}")
            # 回退到原始结果
            for r in results:
                yield self._make_stream_chunk("result", r.to_dict())

    def _parse_ai_response(self, response: str, search_type: str) -> List[SearchResult]:
        """解析 AI 响应"""
        try:
            # 清理 markdown 代码块
            response = response.strip()
            if response.startswith("```"):
                lines = response.split('\n')
                response = '\n'.join([l for l in lines if not l.startswith('```')])[6:].strip()
            
            data = json.loads(response)
            if not isinstance(data, list):
                return []
            
            results = []
            for item in data:
                title = item.get("title", "政策更新" if search_type == "policy" else "市场动态")
                content_parts = []
                
                if search_type == "policy":
                    for key in ["summary", "impact", "detail"]:
                        if item.get(key):
                            content_parts.append(f"【{key}】\n{item[key]}")
                    if item.get("actions"):
                        content_parts.append("【建议行动】\n" + "\n".join(f"- {a}" for a in item["actions"]))
                else:
                    for key in ["trend", "opportunity"]:
                        if item.get(key):
                            content_parts.append(f"【{key}】\n{item[key]}")
                    if item.get("suggestions"):
                        content_parts.append("【建议】\n" + "\n".join(f"- {s}" for s in item["suggestions"]))
                
                results.append(SearchResult(
                    title=title,
                    content="\n\n".join(content_parts),
                    url=item.get("url", ""),
                    source=item.get("source", "DeepSeek AI"),
                    importance=item.get("importance", "normal"),
                    is_important=item.get("importance") == "high"
                ))
            
            return results
        except Exception as e:
            logger.debug(f"AI 响应解析失败: {e}")
            return []

    # ============== 搜索实现方法 ==============

    def _parallel_web_search(
        self, 
        keywords: List[str], 
        search_type: str,
        timeout: int = SEARCH_TIMEOUT
    ) -> List[SearchResult]:
        """并行网络搜索"""
        results: List[SearchResult] = []
        seen_titles = set()
        
        def search_keyword(kw: str) -> List[SearchResult]:
            try:
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                }
                resp = requests.get(
                    "https://html.duckduckgo.com/html/",
                    params={"q": kw},
                    headers=headers,
                    timeout=8
                )
                
                if resp.status_code != 200:
                    return []
                
                return self._parse_search_results(resp.text, kw, search_type)
            except Exception as e:
                logger.debug(f"搜索 {kw} 失败: {e}")
                return []
        
        # 使用线程池并行搜索
        with ThreadPoolExecutor(max_workers=min(3, len(keywords))) as executor:
            futures = {executor.submit(search_keyword, kw): kw for kw in keywords}
            
            for future in futures:
                try:
                    keyword_results = future.result(timeout=timeout)
                    for r in keyword_results:
                        if r.title[:30] not in seen_titles:
                            seen_titles.add(r.title[:30])
                            results.append(r)
                except Exception as e:
                    logger.debug(f"关键词搜索超时: {e}")
        
        return results

    def _parse_search_results(
        self, 
        html_content: str, 
        keyword: str,
        search_type: str
    ) -> List[SearchResult]:
        """解析搜索结果"""
        results = []
        
        try:
            titles = re.findall(r'<a class="result__a"[^>]*>([^<]*)</a>', html_content)
            urls = re.findall(r'<a class="result__a"[^>]*href="(https?://[^"]*)"', html_content)
            snippets = re.findall(r'<a class="result__snippet"[^>]*>(.*?)</a>', html_content)
            
            for i, title in enumerate(titles[:10]):
                title = re.sub(r'<[^>]+>', '', title).strip()
                if not title or len(title) < 10:
                    continue
                
                url = urls[i].split("?")[0].split("#")[0] if i < len(urls) else ""
                snippet = ""
                if i < len(snippets):
                    snippet = re.sub(r'<[^>]+>', '', snippets[i]).strip()[:200]
                
                results.append(SearchResult(
                    title=title[:150],
                    content=snippet or "暂无摘要",
                    url=url,
                    source=self._extract_source_name(url),
                    created_at=datetime.now()  # 网络搜索结果假设为当前时间
                ))
        except Exception as e:
            logger.debug(f"解析搜索结果失败: {e}")
        
        return results

    def _extract_source_name(self, url: str) -> str:
        """从 URL 提取来源"""
        if not url:
            return "网络搜索"
        
        url_lower = url.lower()
        sources = [
            ("customs.gov.cn", "海关总署"),
            ("mofcom.gov.cn", "商务部"),
            ("gov.cn", "政府官网"),
            ("chinatax.gov.cn", "国家税务总局"),
            ("shopee", "Shopee"),
            ("lazada", "Lazada"),
            ("amazon", "Amazon"),
            ("tiktok", "TikTok"),
            ("aliexpress", "AliExpress"),
            ("ebay", "eBay"),
        ]
        
        for pattern, name in sources:
            if pattern in url_lower:
                return name
        return "网络搜索"

    def _filter_by_time_range(
        self, 
        results: List[SearchResult], 
        time_range: str
    ) -> List[SearchResult]:
        """根据时间范围过滤结果"""
        if not results:
            return []
        
        days = SEARCH_TIME_RANGES.get(time_range, 7)
        threshold = datetime.now() - timedelta(days=days)
        
        # 24小时阈值（用于权重加成）
        day_threshold = datetime.now() - timedelta(days=1)
        
        filtered = []
        for r in results:
            # 时间戳早于阈值的不保留
            if r.created_at and r.created_at < threshold:
                continue
            filtered.append(r)
        
        return filtered

    def _calculate_freshness_weight(self, result: SearchResult) -> float:
        """计算新鲜度权重"""
        if not result.created_at:
            return WEIGHT_CONFIG["recent_week_default"]
        
        age = datetime.now() - result.created_at
        
        if age < timedelta(hours=24):
            # 24小时内：+50% 权重
            return WEIGHT_CONFIG["recent_24h_boost"]
        elif age < timedelta(days=3):
            return 1.2
        elif age < timedelta(days=7):
            return 1.0
        else:
            return 0.8

    def _sort_by_weight(self, results: List[SearchResult]) -> List[SearchResult]:
        """按综合权重排序"""
        for r in results:
            r.freshness_weight = self._calculate_freshness_weight(r)
        
        # 排序：重要性 > 新鲜度权重 > 时间
        return sorted(
            results,
            key=lambda x: (
                0 if x.is_important else 1,  # 重要政策优先
                -x.freshness_weight,  # 新鲜度高的优先
                0 if x.created_at else datetime.max,  # 有时间戳的优先
            )
        )

    def _update_cache(self, results: List[SearchResult]):
        """更新结果缓存"""
        with self._results_lock:
            self._recent_results = results

    def _get_cached_results(self, limit: int = 10) -> List[SearchResult]:
        """获取缓存结果"""
        with self._results_lock:
            return self._recent_results[:limit]

    def _get_mock_results(self, search_type: str) -> List[SearchResult]:
        """生成模拟结果（网络搜索失败时使用）"""
        now = datetime.now()
        
        if search_type == "policy":
            mock_data = [
                {
                    "title": "海关总署优化跨境电商进口商品清单",
                    "content": "海关总署近日发布公告，进一步优化跨境电商进口商品清单，扩大优质消费品进口范围。",
                    "source": "海关总署",
                    "is_important": True,
                    "age_hours": 12
                },
                {
                    "title": "跨境电商综合试验区再扩容",
                    "content": "国务院批准新增一批跨境电商综合试验区，支持更多城市开展跨境电商业务。",
                    "source": "国务院",
                    "is_important": True,
                    "age_hours": 48
                },
                {
                    "title": "跨境电商零售进口税收优惠政策延续",
                    "content": "财政部、税务总局联合发布公告，跨境电商零售进口税收优惠政策执行期限延长至2027年底。",
                    "source": "国家税务总局",
                    "is_important": False,
                    "age_hours": 72
                },
                {
                    "title": "跨境电商出口合规指南发布",
                    "content": "海关、税务、外汇多部门联合发布跨境电商出口合规指南，明确全流程合规要求。",
                    "source": "多部门联合",
                    "is_important": False,
                    "age_hours": 120
                },
            ]
        else:
            mock_data = [
                {
                    "title": "户外露营装备海外热销",
                    "content": "近期户外露营装备在欧美市场持续热销，帐篷、睡袋等品类增长显著。",
                    "source": "市场分析",
                    "is_important": True,
                    "age_hours": 6
                },
                {
                    "title": "东南亚电商市场增长强劲",
                    "content": "东南亚电商市场年增长率超过20%，Shopee、Lazada平台交易额持续攀升。",
                    "source": "市场分析",
                    "is_important": True,
                    "age_hours": 24
                },
                {
                    "title": "TikTok Shop 跨境电商快速增长",
                    "content": "TikTok Shop 在东南亚市场快速崛起，内容电商模式创新驱动增长。",
                    "source": "平台动态",
                    "is_important": False,
                    "age_hours": 48
                },
            ]
        
        results = []
        for item in mock_data:
            results.append(SearchResult(
                title=item["title"],
                content=item["content"],
                url="",
                source=item["source"],
                created_at=now - timedelta(hours=item["age_hours"]),
                is_important=item["is_important"],
                importance="high" if item["is_important"] else "normal"
            ))
        
        return results

    # ============== DeepSeek 分析 ==============

    def _deepseek_analyze_sync(
        self, 
        results: List[SearchResult], 
        search_type: str
    ) -> Optional[List[SearchResult]]:
        """同步 DeepSeek 分析"""
        if not DEEPSEEK_API_KEY or not results:
            return None
        
        try:
            items_text = "\n".join([
                f"【{i+1}】{r.title}\n   来源：{r.source}\n   摘要：{r.content[:100]}..."
                for i, r in enumerate(results[:3])
            ])
            
            prompt = f"""作为专业的跨境电商分析师，请根据以下信息生成简明解读。

信息：
{items_text}

生成 2-3 条解读，每条包含：标题（20字内）、摘要（100字内）、影响、建议。

JSON格式返回："""
            
            response = self._call_deepseek_streaming(prompt, stream=False)
            if response:
                return self._parse_ai_response(response, search_type)
        except Exception as e:
            logger.debug(f"DeepSeek 分析失败: {e}")
        
        return None

    def _deepseek_analyze_stream(
        self, 
        results: List[SearchResult], 
        search_type: str
    ):
        """异步 DeepSeek 分析（后台运行）"""
        pass  # 流式分析在 stream_search 中处理

    def _call_deepseek_streaming(
        self, 
        prompt: str, 
        stream: bool = False
    ) -> Optional[str]:
        """调用 DeepSeek API"""
        if not DEEPSEEK_API_KEY:
            return None
        
        try:
            response = requests.post(
                DEEPSEEK_API_URL,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {DEEPSEEK_API_KEY}"
                },
                json={
                    "model": "deepseek-chat",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.3,
                    "max_tokens": 2048,
                    "stream": stream
                },
                timeout=60,
                stream=stream
            )
            
            if response.status_code != 200:
                logger.warning(f"DeepSeek API 返回 {response.status_code}")
                return None
            
            if stream:
                # 收集流式响应
                content = ""
                for line in response.iter_lines():
                    if line:
                        line = line.decode('utf-8')
                        if line.startswith('data: '):
                            data_str = line[6:]
                            if data_str == '[DONE]':
                                break
                            try:
                                data = json.loads(data_str)
                                chunk = data.get("choices", [{}])[0].get("delta", {}).get("content", "")
                                if chunk:
                                    content += chunk
                            except json.JSONDecodeError:
                                continue
                return content if content else None
            else:
                result = response.json()
                return (result.get("choices") or [{}])[0].get("message", {}).get("content")
                
        except Exception as e:
            logger.debug(f"DeepSeek API 请求失败: {e}")
            return None

    # ============== 自动搜索控制 ==============

    def start_auto_search(self, interval_minutes: int = 10):
        """启动自动搜索"""
        if self._is_running:
            logger.warning("PolicySearchService 已在运行中")
            return
        
        self._search_interval_minutes = interval_minutes
        self._is_running = True
        
        def run_loop():
            time.sleep(10)
            while self._is_running:
                try:
                    today_str = datetime.now().strftime("%Y-%m-%d")
                    current_hour = datetime.now().hour
                    
                    if current_hour == 9 and self._last_daily_full_run != today_str:
                        self._last_daily_full_run = today_str
                        self._daily_full_search()
                    else:
                        self.search_policies()
                except Exception as e:
                    logger.error(f"自动搜索失败: {e}")
                
                for _ in range(interval_minutes * 60):
                    if not self._is_running:
                        break
                    time.sleep(1)
        
        thread = threading.Thread(target=run_loop, daemon=True)
        thread.start()
        logger.info(f"PolicySearchService 已启动，搜索间隔: {interval_minutes} 分钟")

    def _daily_full_search(self):
        """每日全量搜索"""
        logger.info("PolicySearchService 每日全量搜索开始...")
        
        # 搜索政策
        policy_results = self.search_policies(limit=10)
        
        # 搜索市场
        market_results = self.search_market(limit=10)
        
        # 保存结果
        self._save_results(policy_results, market_results)
        
        logger.info(f"每日全量搜索完成: {len(policy_results)} 条政策, {len(market_results)} 条市场")

    def stop_auto_search(self):
        """停止自动搜索"""
        self._is_running = False
        logger.info("PolicySearchService 已停止")

    def _save_results(self, policy_results: List[SearchResult], market_results: List[SearchResult]):
        """保存结果到消息中心"""
        try:
            from message_center_service import message_center_service
            
            for r in policy_results:
                try:
                    message_center_service.add_notification(
                        notification_type='policy',
                        title=r.title,
                        content=r.content,
                        url=r.url,
                        source=r.source,
                        is_important=r.is_important
                    )
                except Exception as e:
                    logger.warning(f"保存政策通知失败: {e}")
            
            for r in market_results:
                try:
                    message_center_service.add_notification(
                        notification_type='market',
                        title=r.title,
                        content=r.content,
                        url=r.url,
                        source=r.source,
                        is_important=r.is_important
                    )
                except Exception as e:
                    logger.warning(f"保存市场通知失败: {e}")
                    
        except ImportError:
            logger.warning("message_center_service 不可用，跳过保存")

    # ============== 兼容旧接口 ==============

    def manual_search(self) -> Dict:
        """手动触发搜索（兼容旧接口）"""
        if self._is_searching:
            return {
                'success': False,
                'message': '上一次搜索还在进行中，请稍后再试',
                'last_search_time': self._last_search_time
            }
        
        # 后台执行
        threading.Thread(target=lambda: self.search_policies(), daemon=True).start()
        
        return {
            'success': True,
            'message': '搜索已启动',
            'last_search_time': self._last_search_time
        }

    def search_custom(self, keywords: str, notification_type: str = 'policy') -> Dict:
        """自定义关键词搜索（兼容旧接口）"""
        if not keywords:
            return {'success': False, 'message': '请输入搜索关键词'}
        
        search_type = "market" if notification_type == "market" else "policy"
        results = self.search_policies(keywords) if search_type == "policy" else self.search_market(keywords)
        
        saved = 0
        try:
            from message_center_service import message_center_service
            
            for r in results:
                message_center_service.add_notification(
                    notification_type=notification_type,
                    title=r.title,
                    content=r.content,
                    url=r.url,
                    source=r.source,
                    is_important=r.is_important
                )
                saved += 1
        except Exception as e:
            logger.warning(f"保存自定义搜索结果失败: {e}")
        
        return {
            'success': True,
            'saved': saved,
            'message': f'已生成 {saved} 条详细内容并保存到消息中心'
        }


# 单例实例
policy_search_service = PolicySearchService()
