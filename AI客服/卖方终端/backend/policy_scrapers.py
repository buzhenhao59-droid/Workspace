# -*- coding: utf-8 -*-
"""
垂直领域政策数据爬虫 - Policy Scraper Module
覆盖跨境电商 + 政务两大垂直领域，共 6 个核心数据源

数据源：
  跨境电商类：
    1. customs.gov.cn    - 海关总署跨境电商公告
    2. Amazon Seller    - Amazon Seller Central 新闻（RSS/HTML）
    3. TikTok Shop       - TikTok Shop 卖家公告（HTML）
    4. MOFCOM            - 商务部电子商务司

  政务类（以辽宁为例）：
    5. ln.gov.cn         - 辽宁省人民政府政务公开
    6. rst.ln.gov.cn     - 辽宁省人社厅通知公告
    7. lnbt.gov.cn       - 辽宁省商务厅

关键词白名单：
    跨境出口、海外仓、退税、TikTok 政策更新、人才补贴、
    企业创业扶持、跨境电商、市场监管、出口退税

去重机制：SHA256(title + url) 哈希去重
"""

import re
import os
import time
import json
import hashlib
import logging
import threading
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Callable
from dataclasses import dataclass, field
from enum import Enum
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger("ruitalk.scraper")

# ============== 配置常量 ==============

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 RuitalkBot/1.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "Referer": "https://www.google.com",
}

REQUEST_TIMEOUT = 15  # 秒

# 关键词白名单（命中以下关键词才收录）
KEYWORD_WHITELIST = [
    # 跨境电商核心词
    "跨境电商", "跨境出口", "跨境进口", "海外仓", "出口退税", "退税",
    "TikTok Shop", "TikTok", "tiktok", "Shopee", "Lazada", "Amazon",
    "Amazon Seller", "AliExpress", "aliexpress",
    # 政策类
    "跨境", "海关", "总署", "商务部", "电商", "综合试验区",
    # 政务/辽宁
    "辽宁", "人社", "人力资源", "社会保障", "补贴", "人才",
    "创业扶持", "企业扶持", "创业", "就业", "培训",
    # 监管类
    "市场监管", "商品检验", "进出口", "通关", "报关",
    # 平台动态
    "卖家公告", "政策更新", "新规", "公告", "通知",
]

# 排除词（命中以下直接丢弃）
KEYWORD_BLACKLIST = [
    "广告", "推广", "赌博", "色情", "诈骗",
]

# ============== 数据源定义 ==============

class DataSource(Enum):
    CUSTOMS = "customs"           # 海关总署
    MOFCOM = "mofcom"             # 商务部
    AMAZON = "amazon"             # Amazon Seller
    TIKTOK = "tiktok"             # TikTok Shop
    LN_GOV = "ln_gov"             # 辽宁省政府
    LN_RST = "ln_rst"             # 辽宁省人社厅
    LN_BT = "ln_bt"               # 辽宁省商务厅
    OTHER = "other"


class ContentDomain(Enum):
    """内容领域"""
    CROSS_BORDER = "cross_border"   # 跨境电商
    GOVERNMENT = "government"        # 政务/政府公告


@dataclass
class ScraperConfig:
    """爬虫配置"""
    source: DataSource
    domain: ContentDomain
    name_cn: str                    # 中文名称
    name_en: str                    # 英文名称
    base_url: str                   # 基础URL
    list_url: str                  # 列表页URL
    list_selectors: Dict[str, str]  # 列表页CSS选择器
    item_selectors: Dict[str, str]  # 详情页字段选择器
    rss_url: Optional[str] = None   # RSS源（若有）
    requires_js: bool = False        # 是否需要JS渲染
    encoding: str = "utf-8"         # 页面编码


# ============== 数据源配置表 ==============

DATA_SOURCE_CONFIGS: List[ScraperConfig] = [
    # ---- 跨境电商类 ----
    ScraperConfig(
        source=DataSource.CUSTOMS,
        domain=ContentDomain.CROSS_BORDER,
        name_cn="海关总署",
        name_en="China Customs",
        base_url="https://www.customs.gov.cn",
        list_url="https://www.customs.gov.cn/customs/zt/2868/zt89/index.html",
        list_selectors={
            "item": "ul.news_list li, div.news-list li, .article-list li",
            "title": "a",
            "url": "a@href",
            "date": ".date, .time, span",
        },
        item_selectors={
            "title": "h2.title, .article-title, h1",
            "content": "div.content, .article-content, #zoom, .TRS_Editor",
            "date": ".info span, .article-info",
            "source": ".source",
        },
    ),
    ScraperConfig(
        source=DataSource.MOFCOM,
        domain=ContentDomain.CROSS_BORDER,
        name_cn="商务部电子商务司",
        name_en="MOFCOM E-Commerce",
        base_url="http://images.mofcom.gov.cn",
        list_url="https://ec.mofcom.gov.cn/article/zcjd/",
        list_selectors={
            "item": "ul.list, div.news-list li, .article-list li",
            "title": "a",
            "url": "a@href",
            "date": ".date, span",
        },
        item_selectors={
            "title": "h2, .article-title",
            "content": ".article-content, #artibody, div.content",
            "date": ".article-info span",
            "source": ".source",
        },
    ),
    ScraperConfig(
        source=DataSource.AMAZON,
        domain=ContentDomain.CROSS_BORDER,
        name_cn="Amazon Seller Central",
        name_en="Amazon Seller",
        base_url="https://sellercentral.amazon.com",
        list_url="https://sellercentral.amazon.co.uk/news?ref_=xx_news_pl",
        list_selectors={
            "item": "article, .news-item, .announcement-item",
            "title": "h3, .title, .headline",
            "url": "a@href",
            "date": "time, .date, .timestamp",
        },
        item_selectors={
            "title": "h1, .article-title",
            "content": ".article-body, .content",
            "date": "time, .date",
            "source": ".source",
        },
    ),
    ScraperConfig(
        source=DataSource.TIKTOK,
        domain=ContentDomain.CROSS_BORDER,
        name_cn="TikTok Shop 卖家中心",
        name_en="TikTok Shop Seller",
        base_url="https://seller-uk.tiktok.com",
        list_url="https://seller-uk.tiktok.com/newsroom/announcements",
        list_selectors={
            "item": "article, .announcement-item, .news-item",
            "title": "h3, .title",
            "url": "a@href",
            "date": "time, .date",
        },
        item_selectors={
            "title": "h1, .article-title",
            "content": ".article-content, .content",
            "date": "time",
            "source": ".source",
        },
    ),

    # ---- 政务类（辽宁） ----
    ScraperConfig(
        source=DataSource.LN_GOV,
        domain=ContentDomain.GOVERNMENT,
        name_cn="辽宁省人民政府",
        name_en="Liaoning Provincial Government",
        base_url="https://www.ln.gov.cn",
        list_url="https://www.ln.gov.cn/zfxx/zwgk_12451/zfxxgkml/index_1.shtml",
        list_selectors={
            "item": "ul.news-list li, div.list li, .article-list li",
            "title": "a",
            "url": "a@href",
            "date": "span, .date, .time",
        },
        item_selectors={
            "title": "h1.title, .article-title, h2",
            "content": ".content, .article-content, #zoom",
            "date": ".info span, .article-info",
            "source": ".source, .from",
        },
    ),
    ScraperConfig(
        source=DataSource.LN_RST,
        domain=ContentDomain.GOVERNMENT,
        name_cn="辽宁省人力资源和社会保障厅",
        name_en="Liaoning HR & Social Security",
        base_url="https://rst.ln.gov.cn",
        list_url="https://rst.ln.gov.cn/zwgk/tzgg/index.shtml",
        list_selectors={
            "item": "ul.list li, div.news-list li",
            "title": "a",
            "url": "a@href",
            "date": "span, .date",
        },
        item_selectors={
            "title": "h1, .article-title",
            "content": ".content, .article-content",
            "date": ".article-info, .info",
            "source": ".source",
        },
    ),
    ScraperConfig(
        source=DataSource.LN_BT,
        domain=ContentDomain.GOVERNMENT,
        name_cn="辽宁省商务厅",
        name_en="Liaoning Commerce Department",
        base_url="https://swt.ln.gov.cn",
        list_url="https://swt.ln.gov.cn/tzgg/index.shtml",
        list_selectors={
            "item": "ul.news-list li, div.list li",
            "title": "a",
            "url": "a@href",
            "date": "span, .date",
        },
        item_selectors={
            "title": "h1, .article-title",
            "content": ".content, .article-content",
            "date": ".article-info",
            "source": ".source",
        },
    ),
]


# ============== 标准化结果结构 ==============

@dataclass
class ScrapedItem:
    """标准化爬取结果"""
    # 唯一标识（哈希去重）
    item_hash: str = ""

    # 内容领域
    domain: str = ""          # cross_border / government
    data_source: str = ""     # customs / mofcom / ln_gov / etc.

    # 基础信息
    title: str = ""
    url: str = ""
    content: str = ""
    summary: str = ""        # AI 生成的一句话摘要

    # 元数据
    published_date: Optional[datetime] = None
    crawled_date: datetime = field(default_factory=datetime.now)
    author: str = ""
    source_name: str = ""     # 显示用：海关总署

    # AI 分析字段
    target_audience: str = ""    # 特定人群或企业类型
    policy_type: str = ""       # 利好 / 风险 / 通知
    key_benefit: str = ""        # 核心利好或风险点（一句话）
    timeliness_check: str = ""   # 时效性核实结果

    # 状态
    is_important: bool = False
    is_fresh: bool = False      # 24h 内
    keywords_matched: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "item_hash": self.item_hash,
            "domain": self.domain,
            "data_source": self.data_source,
            "title": self.title,
            "url": self.url,
            "content": self.content,
            "summary": self.summary,
            "published_date": self.published_date.isoformat() if self.published_date else None,
            "crawled_date": self.crawled_date.isoformat() if isinstance(self.crawled_date, datetime) else self.crawled_date,
            "author": self.author,
            "source_name": self.source_name,
            "target_audience": self.target_audience,
            "policy_type": self.policy_type,
            "key_benefit": self.key_benefit,
            "timeliness_check": self.timeliness_check,
            "is_important": self.is_important,
            "is_fresh": self.is_fresh,
            "keywords_matched": self.keywords_matched,
        }


# ============== 核心爬虫类 ==============

class BaseScraper:
    """爬虫基类"""

    def __init__(self, config: ScraperConfig):
        self.config = config
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def _fetch_page(self, url: str, encoding: str = None) -> Optional[str]:
        """获取页面 HTML"""
        try:
            resp = self.session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
            if resp.status_code != 200:
                logger.warning(f"[{self.config.source.value}] HTTP {resp.status_code}: {url}")
                return None
            # 自动检测编码
            enc = encoding or resp.apparent_encoding or "utf-8"
            try:
                resp.encoding = enc
            except Exception:
                resp.encoding = "utf-8"
            return resp.text
        except requests.exceptions.Timeout:
            logger.warning(f"[{self.config.source.value}] 超时: {url}")
        except Exception as e:
            logger.warning(f"[{self.config.source.value}] 请求失败: {e}")
        return None

    def _fetch_rss(self, url: str) -> List[Dict]:
        """获取 RSS 源"""
        items = []
        try:
            resp = self.session.get(url, timeout=REQUEST_TIMEOUT)
            if resp.status_code != 200:
                return items
            root = ET.fromstring(resp.content)
            channel = root.find("channel")
            if channel is not None:
                for item in channel.findall("item"):
                    title = self._get_text(item, "title")
                    link = self._get_text(item, "link")
                    pub_date = self._get_text(item, "pubDate")
                    desc = self._get_text(item, "description")
                    if title and link:
                        items.append({
                            "title": title.strip(),
                            "url": link.strip(),
                            "date": pub_date or "",
                            "content": desc or "",
                        })
        except Exception as e:
            logger.warning(f"[{self.config.source.value}] RSS 解析失败: {e}")
        return items

    @staticmethod
    def _get_text(elem: ET.Element, tag: str) -> str:
        child = elem.find(tag)
        return child.text.strip() if child is not None and child.text else ""

    def _normalize_url(self, url: str) -> str:
        """规范化 URL"""
        if not url:
            return ""
        if url.startswith("//"):
            url = "https:" + url
        elif url.startswith("/"):
            url = self.config.base_url + url
        elif not url.startswith("http"):
            url = self.config.base_url + "/" + url
        return url.strip()

    def _parse_date(self, date_str: str) -> Optional[datetime]:
        """解析日期"""
        if not date_str:
            return None
        date_str = date_str.strip()
        patterns = [
            "%Y-%m-%d",
            "%Y/%m/%d",
            "%Y年%m月%d日",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%a, %d %b %Y %H:%M:%S %z",
            "%d %b %Y",
        ]
        # 清理
        date_str = re.sub(r"[\[\]]", "", date_str)
        for fmt in patterns:
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue
        # 手动提取
        match = re.search(r"(\d{4})[年/-](\d{1,2})[月/-](\d{1,2})", date_str)
        if match:
            try:
                return datetime(int(match.group(1)), int(match.group(2)), int(match.group(3)))
            except ValueError:
                pass
        return None

    def _check_keywords(self, text: str) -> tuple[bool, List[str]]:
        """关键词过滤检查"""
        text_lower = text.lower()
        matched = []
        for kw in KEYWORD_WHITELIST:
            if kw.lower() in text_lower:
                matched.append(kw)
        if not matched:
            return False, []
        for kw in KEYWORD_BLACKLIST:
            if kw in text_lower:
                return False, []
        return True, matched

    def _compute_hash(self, title: str, url: str) -> str:
        """计算内容哈希（用于去重）"""
        raw = (title + url).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()[:16]

    def fetch_list(self) -> List[Dict]:
        """获取列表页所有条目"""
        if self.config.rss_url:
            return self._fetch_rss(self.config.rss_url)
        html = self._fetch_page(self.config.list_url)
        if not html:
            return []
        return self._parse_list_html(html)

    def _parse_list_html(self, html: str) -> List[Dict]:
        """解析列表页 HTML"""
        items = []
        try:
            soup = BeautifulSoup(html, "lxml")
            # 尝试多种选择器
            selectors = self.config.list_selectors.get("item", "li").split(",")
            container = None
            for sel in selectors:
                container = soup.select_one(sel.strip())
                if container:
                    break
            if not container:
                container = soup
            # 查找所有链接条目
            for a_tag in soup.find_all("a", href=True):
                href = a_tag.get("href", "")
                if not href or href.startswith("#") or "javascript" in href.lower():
                    continue
                title = a_tag.get_text(strip=True)
                if not title or len(title) < 5:
                    continue
                url = self._normalize_url(href)
                # 提取日期（尝试从父级或相邻元素）
                date_str = ""
                parent = a_tag.find_parent(["li", "div"])
                if parent:
                    date_spans = parent.find_all(["span", "time", "em"])
                    for sp in date_spans:
                        t = sp.get_text(strip=True)
                        if re.search(r"\d{4}", t):
                            date_str = t
                            break
                items.append({
                    "title": title,
                    "url": url,
                    "date": date_str,
                    "content": "",
                })
        except Exception as e:
            logger.warning(f"[{self.config.source.value}] 列表解析失败: {e}")
        return items

    def fetch_detail(self, url: str, title: str = "") -> Optional[ScrapedItem]:
        """获取详情页内容"""
        html = self._fetch_page(url)
        if not html:
            return None
        return self._parse_detail_html(html, url, title)

    def _parse_detail_html(self, html: str, url: str, title: str = "") -> Optional[ScrapedItem]:
        """解析详情页 HTML"""
        try:
            soup = BeautifulSoup(html, "lxml")

            # 提取标题
            parsed_title = title
            for sel in self.config.item_selectors.get("title", "h1").split(","):
                el = soup.select_one(sel.strip())
                if el:
                    parsed_title = el.get_text(strip=True)
                    break

            # 关键词过滤
            check_title = parsed_title or title
            passed, matched_kw = self._check_keywords(check_title)
            if not passed:
                return None

            # 提取正文
            content = ""
            for sel in self.config.item_selectors.get("content", ".content").split(","):
                el = soup.select_one(sel.strip())
                if el:
                    # 移除脚本和样式
                    for tag in el.find_all(["script", "style", "nav", "footer", "aside"]):
                        tag.decompose()
                    content = el.get_text(separator="\n", strip=True)
                    if len(content) > 100:
                        break

            # 如果正文太短，跳过
            if len(content) < 50:
                return None

            # 关键词二次确认（正文也需要命中）
            if not self._check_keywords(content + check_title)[0]:
                return None

            # 提取日期
            pub_date = None
            for sel in self.config.item_selectors.get("date", ".date").split(","):
                el = soup.select_one(sel.strip())
                if el:
                    date_str = el.get_text(strip=True)
                    pub_date = self._parse_date(date_str)
                    if pub_date:
                        break

            # 提取来源
            source_name = self.config.name_cn
            for sel in self.config.item_selectors.get("source", ".source").split(","):
                el = soup.select_one(sel.strip())
                if el:
                    src = el.get_text(strip=True)
                    if src:
                        source_name = re.sub(r"来源[：:]*", "", src).strip() or source_name
                        break

            item_hash = self._compute_hash(parsed_title or title, url)
            now = datetime.now()
            is_fresh = False
            if pub_date:
                is_fresh = (now - pub_date) < timedelta(hours=24)

            return ScrapedItem(
                item_hash=item_hash,
                domain=self.config.domain.value,
                data_source=self.config.source.value,
                title=parsed_title or title,
                url=url,
                content=content[:3000],  # 限制长度
                published_date=pub_date,
                crawled_date=now,
                source_name=source_name,
                is_fresh=is_fresh,
                keywords_matched=matched_kw,
            )
        except Exception as e:
            logger.warning(f"[{self.config.source.value}] 详情解析失败: {e}")
        return None

    def scrape(self) -> List[ScrapedItem]:
        """执行抓取（列表 + 详情）"""
        results = []
        try:
            list_items = self.fetch_list()
            if not list_items:
                logger.info(f"[{self.config.source.value}] 列表为空，尝试备用策略")
                list_items = self._fallback_list()
            for li in list_items[:20]:  # 最多处理 20 条
                time.sleep(0.3)  # 礼貌爬取
                item = self.fetch_detail(li["url"], li["title"])
                if item:
                    results.append(item)
        except Exception as e:
            logger.error(f"[{self.config.source.value}] 抓取出错: {e}")
        return results

    def _fallback_list(self) -> List[Dict]:
        """备用列表获取（通用链接提取）"""
        items = []
        html = self._fetch_page(self.config.list_url)
        if not html:
            return items
        soup = BeautifulSoup(html, "lxml")
        seen_urls = set()
        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            if not href or href.startswith("#") or "javascript" in href.lower():
                continue
            title = a.get_text(strip=True)
            if len(title) < 8:
                continue
            url = self._normalize_url(href)
            if url in seen_urls:
                continue
            seen_urls.add(url)
            items.append({"title": title, "url": url, "date": "", "content": ""})
        return items[:30]


# ============== 爬虫工厂 ==============

class ScraperFactory:
    """爬虫工厂"""

    _scrapers: Dict[DataSource, BaseScraper] = {}
    _lock = threading.Lock()

    @classmethod
    def get_scraper(cls, source: DataSource) -> Optional[BaseScraper]:
        if source in cls._scrapers:
            return cls._scrapers[source]
        with cls._lock:
            if source in cls._scrapers:
                return cls._scrapers[source]
            config = next((c for c in DATA_SOURCE_CONFIGS if c.source == source), None)
            if not config:
                return None
            scraper: BaseScraper
            if source == DataSource.CUSTOMS:
                scraper = CustomsScraper(config)
            elif source == DataSource.MOFCOM:
                scraper = MofcomScraper(config)
            elif source == DataSource.AMAZON:
                scraper = AmazonScraper(config)
            elif source == DataSource.TIKTOK:
                scraper = TikTokScraper(config)
            elif source == DataSource.LN_GOV:
                scraper = LnGovScraper(config)
            elif source == DataSource.LN_RST:
                scraper = LnRstScraper(config)
            elif source == DataSource.LN_BT:
                scraper = LnBtScraper(config)
            else:
                scraper = BaseScraper(config)
            cls._scrapers[source] = scraper
            return scraper

    @classmethod
    def get_all_scrapers(cls) -> List[BaseScraper]:
        """获取所有配置的爬虫"""
        scrapers = []
        for config in DATA_SOURCE_CONFIGS:
            s = cls.get_scraper(config.source)
            if s:
                scrapers.append(s)
        return scrapers


# ============== 专用爬虫（各站点定制） ==============

class CustomsScraper(BaseScraper):
    """海关总署专用爬虫"""

    def fetch_list(self) -> List[Dict]:
        # 尝试 RSS
        rss_url = "https://www.customs.gov.cn/ customs/zt/2868/zt89/index.html"
        rss_url = "https://www.customs.gov.cn/rss/news.xml"
        items = self._fetch_rss(rss_url)
        if items:
            return items
        return self._fallback_list()


class MofcomScraper(BaseScraper):
    """商务部专用爬虫"""

    def fetch_list(self) -> List[Dict]:
        rss_url = "https://ec.mofcom.gov.cn/article/rss/"
        items = self._fetch_rss(rss_url)
        if items:
            return items
        return self._fallback_list()


class AmazonScraper(BaseScraper):
    """Amazon Seller 专用爬虫"""

    def fetch_list(self) -> List[Dict]:
        # Amazon Seller News 通常没有公开 RSS，使用通用解析
        html = self._fetch_page(self.config.list_url)
        if not html:
            # 备用：使用搜索接口
            search_url = "https://sellercentral.amazon.co.uk/help/hub/news"
            html = self._fetch_page(search_url)
        if not html:
            return []
        return self._parse_list_html(html)


class TikTokScraper(BaseScraper):
    """TikTok Shop 专用爬虫"""

    def fetch_list(self) -> List[Dict]:
        # TikTok Shop 页面通常需要 JS 渲染，使用备用策略
        return self._fallback_list()


class LnGovScraper(BaseScraper):
    """辽宁省政府专用爬虫"""

    def fetch_list(self) -> List[Dict]:
        rss_url = "https://www.ln.gov.cn/rss/news.xml"
        items = self._fetch_rss(rss_url)
        if items:
            return items
        # 尝试翻页
        all_items = self._fallback_list()
        for page in range(1, 3):
            page_url = f"https://www.ln.gov.cn/zfxx/zwgk/zfxxgkml/index_{page}.shtml"
            html = self._fetch_page(page_url)
            if not html:
                break
            items = self._parse_list_html(html)
            all_items.extend(items)
            if not items:
                break
        return all_items[:30]


class LnRstScraper(BaseScraper):
    """辽宁省人社厅专用爬虫"""

    def fetch_list(self) -> List[Dict]:
        all_items = self._fallback_list()
        # 翻页
        for page in range(1, 3):
            page_url = f"https://rst.ln.gov.cn/zwgk/tzgg/index_{page}.shtml"
            html = self._fetch_page(page_url)
            if not html:
                break
            items = self._parse_list_html(html)
            all_items.extend(items)
            if not items:
                break
        return all_items[:30]


class LnBtScraper(BaseScraper):
    """辽宁省商务厅专用爬虫"""

    def fetch_list(self) -> List[Dict]:
        all_items = self._fallback_list()
        for page in range(1, 3):
            page_url = f"https://swt.ln.gov.cn/tzgg/index_{page}.shtml"
            html = self._fetch_page(page_url)
            if not html:
                break
            items = self._parse_list_html(html)
            all_items.extend(items)
            if not items:
                break
        return all_items[:30]


# ============== 垂直领域聚合爬虫 ==============

class VerticalPolicyScraper:
    """
    垂直领域政策聚合爬虫
    同时抓取跨境电商 + 政务两大领域的多个数据源
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
        if hasattr(self, "_initialized"):
            return
        self._initialized = True
        self._scrapers = ScraperFactory.get_all_scrapers()
        self._seen_hashes: set = set()

    def scrape_all(self, domains: List[str] = None) -> List[ScrapedItem]:
        """
        抓取所有/指定领域的数据

        Args:
            domains: 抓取领域过滤，如 ["cross_border", "government"]，None 表示全部

        Returns:
            去重后的 ScrapedItem 列表
        """
        all_items: List[ScrapedItem] = []

        for scraper in self._scrapers:
            # 领域过滤
            if domains and scraper.config.domain.value not in domains:
                continue

            logger.info(f"[Scraper] 开始抓取: {scraper.config.name_cn}")
            try:
                items = scraper.scrape()
                logger.info(f"[Scraper] {scraper.config.name_cn} 抓取完成: {len(items)} 条")
                all_items.extend(items)
            except Exception as e:
                logger.error(f"[Scraper] {scraper.config.name_cn} 抓取异常: {e}")

        # 去重（基于 title + url 哈希）
        return self._deduplicate(all_items)

    def scrape_by_source(self, source: DataSource) -> List[ScrapedItem]:
        """按单个数据源抓取"""
        scraper = ScraperFactory.get_scraper(source)
        if not scraper:
            return []
        items = scraper.scrape()
        return self._deduplicate(items)

    def _deduplicate(self, items: List[ScrapedItem]) -> List[ScrapedItem]:
        """基于 item_hash 去重"""
        unique = []
        for item in items:
            if item.item_hash and item.item_hash not in self._seen_hashes:
                self._seen_hashes.add(item.item_hash)
                unique.append(item)
            else:
                logger.debug(f"[Scraper] 跳过重复: {item.title[:30]}")
        # 限制内存中哈希集合大小
        if len(self._seen_hashes) > 50000:
            self._seen_hashes = set(list(self._seen_hashes)[-30000:])
        return unique

    def get_scraper_stats(self) -> Dict:
        """获取爬虫统计"""
        stats = {}
        for scraper in self._scrapers:
            stats[scraper.config.source.value] = {
                "name_cn": scraper.config.name_cn,
                "domain": scraper.config.domain.value,
                "base_url": scraper.config.base_url,
                "list_url": scraper.config.list_url,
            }
        return stats


# ============== 快捷调用函数 ==============

def scrape_cross_border() -> List[ScrapedItem]:
    """抓取跨境电商类政策"""
    scraper = VerticalPolicyScraper()
    return scraper.scrape_all(domains=["cross_border"])


def scrape_government() -> List[ScrapedItem]:
    """抓取政务类政策"""
    scraper = VerticalPolicyScraper()
    return scraper.scrape_all(domains=["government"])


def scrape_all_policies() -> List[ScrapedItem]:
    """抓取所有政策（跨境电商 + 政务）"""
    scraper = VerticalPolicyScraper()
    return scraper.scrape_all(domains=None)


# 单例导出
vertical_scraper = VerticalPolicyScraper()
