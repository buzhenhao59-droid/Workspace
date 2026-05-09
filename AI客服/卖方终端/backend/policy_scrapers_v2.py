# -*- coding: utf-8 -*-
"""
垂直领域政策爬虫 - 精准数据抓取版 v3
核心改进：
  1. 8个权威数据源，真实政务/官方平台
  2. 精准日期解析（URL日期+文本日期+详情页日期三保险）
  3. SHA256(title+url) 去重
  4. 50+ 跨境电商关键词白名单 + 政务关键词
  5. 时间范围过滤（1天/3天/1周/1月）
  6. 详情页完整正文提取（2000字）
  7. 多策略列表解析（URL/ul/table/.list/TRS_Editor）
  8. 重试机制（3次，UA轮换）
"""

import re
import os
import time
import json
import hashlib
import logging
import threading
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger("ruitalk.scraper_v2")

# ============== 全局配置 ==============

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 RuitalkBot/2.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "Cache-Control": "no-cache",
}

REQUEST_TIMEOUT = 15
MAX_RETRIES = 3
RETRY_BACKOFF = 2.0
MAX_ITEMS_PER_SOURCE = 20  # 增加到20，每页多抓一些再过滤

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
]


# ============== 关键词白名单（50+ 跨境电商 + 政务）=============

CROSS_BORDER_KW = [
    # 进出口 & 贸易
    "跨境电商", "跨境出口", "跨境进口", "出口退税", "退税", "进口税",
    "进出口", "外贸", "跨境贸易", "贸易政策", "贸易便利化", "通关",
    "海关监管", "保税", "综试区", "跨境综试区", "自贸区", "自贸试验区",
    "跨境物流", "海外仓", "亚马逊", "Amazon", "TikTok", "tiktok shop",
    "亚马逊卖家", "速卖通", "AliExpress", "eBay", "SHEIN", "shopee",
    # 平台 & 政策
    "电商平台", "跨境平台", "电商法", "电子商务法", "平台政策",
    "卖家中心", "店铺运营", "商品备案", "商品归类", "HS编码",
    # 财务 & 税务
    "出口退税", "免税", "增值税", "企业所得税", "跨境电商税",
    "财税政策", "税务优惠", "税收优惠", "免税政策", "零税率",
    # 人才 & 产业
    "跨境人才", "电商人才", "外贸人才", "企业孵化", "产业集群",
    "产业带", "供应链", "供应链金融", "融资", "信贷",
    # 补贴 & 扶持
    "补贴", "扶持资金", "专项资金", "创业扶持", "中小企业扶持",
    "专项资金申请", "项目申报", "认定", "示范企业",
    # 合规 & 认证
    "3C认证", "CE认证", "FDA认证", "产品认证", "质量认证",
    "知识产权", "商标注册", "专利保护", "海关编码",
    # 市场 & 动态
    "市场准入", "关税", "配额", "许可证", "外贸订单", "订单",
]

GOVERNMENT_KW = [
    "通知", "公告", "政策", "补贴", "扶持", "决定", "办法",
    "意见", "公示", "申报", "规划", "方案", "计划", "条例",
    "法规", "文件", "认定", "标准", "指南", "通告", "解读",
    # 人社专项
    "人才补贴", "创业补贴", "社保", "养老保险", "医疗保险",
    "失业保险", "工伤保险", "生育保险", "公积金",
    "就业", "招聘", "培训", "职业技能", "职业培训",
    "高校毕业生", "就业补贴", "社保补贴", "岗位补贴",
    "创业贷款", "小额贷款", "就业创业", "劳动关系",
    "最低工资", "工资指导", "劳动仲裁", "劳务派遣",
    # 辽宁专项
    "辽宁省", "辽宁人社", "辽宁商务", "辽宁发改委", "辽宁税务",
    "辽宁省政府", "沈阳市", "大连市", "鞍山市", "抚顺市",
]

ALL_KEYWORDS = list(set(CROSS_BORDER_KW + GOVERNMENT_KW))

def is_policy_title(title: str) -> bool:
    """判断标题是否属于政策类"""
    if not title:
        return False
    t = title
    return any(k in t for k in [
        "通知", "公告", "政策", "补贴", "扶持", "决定", "办法",
        "意见", "公示", "申报", "规划", "方案", "条例",
        "法规", "文件", "认定", "标准", "指南", "通告", "解读",
    ])

def match_keywords(text: str) -> List[str]:
    """匹配文本中包含的所有关键词"""
    if not text:
        return []
    t = text
    return [kw for kw in ALL_KEYWORDS if kw in t]


# ============== 时间范围 ==============

class TimeRange:
    """时间范围过滤"""
    RANGES = {
        "1d": ("1天", 1),
        "3d": ("3天", 3),
        "1w": ("1周", 7),
        "1m": ("1月", 30),
        "all": ("全部", 99999),
    }

    def __init__(self, range_id: str):
        self.id = range_id
        self.label, self.days = self.RANGES.get(range_id, ("全部", 99999))

    def cutoff(self) -> datetime:
        """返回截止时间点"""
        if self.days >= 9999:
            return datetime.min
        return datetime.now() - timedelta(days=self.days)

    def is_within(self, dt: Optional[datetime]) -> bool:
        """判断日期是否在范围内（None日期在all模式下视为有效）"""
        if dt is None:
            return self.days >= 9999
        return dt >= self.cutoff()

    @classmethod
    def from_id(cls, rid: str) -> "TimeRange":
        return cls(rid if rid in cls.RANGES else "all")


# ============== 数据领域 ==============

class ContentDomain(Enum):
    CROSS_BORDER = "cross_border"   # 跨境电商
    GOVERNMENT = "government"     # 政务公告


# ============== 数据源定义 ==============

@dataclass
class PolicySource:
    """政策数据源配置"""
    id: str
    name: str
    name_short: str
    domain: ContentDomain
    base_url: str
    list_url: str
    item_selector: str
    title_selector: str
    date_selector: str
    link_selector: str
    content_selector: str
    # ↓ 以下字段有默认值，可省略
    page_urls: List[str] = field(default_factory=list)
    official_url: str = ""
    search_keywords: List[str] = field(default_factory=list)
    priority: int = 10
    requires_js: bool = False
    encoding: str = "utf-8"


# ============== 数据源定义（精准验证版 v3）============

POLICY_SOURCES: List[PolicySource] = [

    # ========== 跨境电商类 ==========

    # 商务部政策解读（综合商务/电商相关）
    PolicySource(
        id="mofcom_zcjd",
        name="商务部政策解读",
        name_short="商务部政策解读",
        domain=ContentDomain.CROSS_BORDER,
        base_url="https://www.mofcom.gov.cn",
        list_url="https://www.mofcom.gov.cn/zcjd/index.html",
        item_selector=".article-list li, ul.list li, .news-list li",
        title_selector="a",
        date_selector="span, .date",
        link_selector="a@href",
        content_selector=".TRS_Editor, #zoom, .content",
        official_url="https://www.mofcom.gov.cn",
        page_urls=[
            "https://www.mofcom.gov.cn/zcjd/zhsw/index.html",
            "https://www.mofcom.gov.cn/zcjd/gnmy/index.html",
        ],
        search_keywords=["商务部 跨境电商 2026", "电商司 政策 2026"],
        priority=55,
    ),

    # 商务部政策发布
    PolicySource(
        id="mofcom_policy",
        name="商务部政策发布",
        name_short="商务部政策发布",
        domain=ContentDomain.CROSS_BORDER,
        base_url="https://www.mofcom.gov.cn",
        list_url="https://www.mofcom.gov.cn/zcfb/index.html",
        item_selector=".TRS_Editor li, .article-list li, ul.list li",
        title_selector="a",
        date_selector="span, .date",
        link_selector="a@href",
        content_selector="#zoom, .TRS_Editor, .content",
        official_url="https://www.mofcom.gov.cn",
        page_urls=[
            "https://www.mofcom.gov.cn/zcfb/zhzc/index.html",
            "https://www.mofcom.gov.cn/zcfb/gnmygl/index.html",
            "https://www.mofcom.gov.cn/gztz/index.html",
        ],
        search_keywords=["商务部 公告 2026", "跨境电商 进出口 政策 2026"],
        priority=52,
    ),

    # 商务部电商司（综合商务）
    PolicySource(
        id="mofcom_ec",
        name="商务部综合商务",
        name_short="商务部综合",
        domain=ContentDomain.CROSS_BORDER,
        base_url="https://www.mofcom.gov.cn",
        list_url="https://www.mofcom.gov.cn/zcjd/zhsw/index.html",
        item_selector="li, .TRS_Editor li",
        title_selector="a",
        date_selector="span, .date",
        link_selector="a@href",
        content_selector="#zoom, .TRS_Editor",
        official_url="https://www.mofcom.gov.cn",
        search_keywords=["电商司 跨境电商 2026"],
        priority=50,
    ),

    # 国家税务总局
    PolicySource(
        id="nat_tax",
        name="国家税务总局",
        name_short="税务总局",
        domain=ContentDomain.CROSS_BORDER,
        base_url="https://www.chinatax.gov.cn",
        list_url="https://www.chinatax.gov.cn/chinatax/n810219/n810724/index.html",
        item_selector=".list li, ul.list li, .news-list li",
        title_selector="a",
        date_selector="span, .date",
        link_selector="a@href",
        content_selector="#zoom, .TRS_Editor, .content",
        official_url="https://www.chinatax.gov.cn",
        search_keywords=["国家税务总局 退税 政策 2026", "出口退税 最新公告 2026"],
        priority=48,
    ),

    # ========== 政务类（辽宁） ==========

    # 辽宁省政府
    PolicySource(
        id="ln_gov",
        name="辽宁省人民政府",
        name_short="辽宁省政府",
        domain=ContentDomain.GOVERNMENT,
        base_url="https://www.ln.gov.cn",
        list_url="https://www.ln.gov.cn/zfxx/zwgk/zfxxgkml/index.shtml",
        item_selector="ul.news-list li, div.list li, .article-list li",
        title_selector="a",
        date_selector="span, .date, .time",
        link_selector="a@href",
        content_selector="#zoom, .TRS_Editor, .article-content, .content",
        official_url="https://www.ln.gov.cn",
        page_urls=[
            "https://www.ln.gov.cn/zfxx/zwgk/zfxxgkml/index.shtml",
            "https://www.ln.gov.cn/zfxx/zwgk/zfxxgkml/index_1.shtml",
            "https://www.ln.gov.cn/zfxx/zwgk/zfxxgkml/index_2.shtml",
        ],
        search_keywords=["辽宁省 政策公告 2026", "辽宁省政府 最新文件 2026"],
        priority=60,
    ),

    # 辽宁省人社厅
    PolicySource(
        id="ln_rst",
        name="辽宁省人力资源和社会保障厅",
        name_short="辽宁人社厅",
        domain=ContentDomain.GOVERNMENT,
        base_url="https://rst.ln.gov.cn",
        list_url="https://rst.ln.gov.cn/eportal/ui?pageId=ab4555d39b8b4d06a3c48b4319b3801e",
        item_selector="table tr, .list-item",
        title_selector="a",
        date_selector="td, .date",
        link_selector="a@href",
        content_selector=".content, .article-content, #zoom",
        official_url="https://rst.ln.gov.cn",
        page_urls=[
            "https://rst.ln.gov.cn/eportal/ui?pageId=ab4555d39b8b4d06a3c48b4319b3801e",
            "https://rst.ln.gov.cn/eportal/ui?pageId=ab4555d39b8b4d06a3c48b4319b3801e&page=2",
        ],
        search_keywords=["辽宁省人社厅 通知 2026", "辽宁 人才补贴 创业扶持 2026"],
        priority=58,
    ),

    # 辽宁省商务厅
    PolicySource(
        id="ln_swt",
        name="辽宁省商务厅",
        name_short="辽宁商务厅",
        domain=ContentDomain.GOVERNMENT,
        base_url="https://swt.ln.gov.cn",
        list_url="https://swt.ln.gov.cn/swt/ywxx/zsyz/index.shtml",
        item_selector="ul.list li, .news-list li, .article-list li",
        title_selector="a",
        date_selector="span, .date, td",
        link_selector="a@href",
        content_selector=".content, .article-content",
        official_url="https://swt.ln.gov.cn",
        page_urls=[
            "https://swt.ln.gov.cn/swt/ywxx/zsyz/index.shtml",
            "https://swt.ln.gov.cn/swt/ywxx/dwmy/index.shtml",
            "https://swt.ln.gov.cn/swt/ywxx/dzjs/index.shtml",
        ],
        search_keywords=["辽宁省商务厅 通知 2026", "辽宁 跨境电商 扶持 2026"],
        priority=56,
    ),

    # 辽宁省发改委
    PolicySource(
        id="ln_fgw",
        name="辽宁省发展和改革委员会",
        name_short="辽宁发改委",
        domain=ContentDomain.GOVERNMENT,
        base_url="https://fgw.ln.gov.cn",
        list_url="https://fgw.ln.gov.cn/fgw/index/tzgg/",
        item_selector="ul.list li, div.news-list li",
        title_selector="a",
        date_selector="span, .date",
        link_selector="a@href",
        content_selector=".content, .article-content",
        official_url="https://fgw.ln.gov.cn",
        page_urls=[
            "https://fgw.ln.gov.cn/fgw/index/tzgg/",
            "https://fgw.ln.gov.cn/fgw/index/tzgg/index_1.shtml",
        ],
        search_keywords=["辽宁省发改委 公告 2026", "辽宁 企业扶持 政策 2026"],
        priority=40,
    ),
]



# ============== 标准化结果结构 ==============

@dataclass
class PolicyItem:
    """标准化政策条目"""
    id: str = ""                    # item_hash
    source_id: str = ""             # customs / mofcom / ln_gov / etc.
    source_name: str = ""          # 海关总署
    source_short: str = ""         # 海关总署（短）

    domain: str = ""               # cross_border / government
    domain_label: str = ""         # 跨境电商 / 政府公告

    title: str = ""               # 标题
    url: str = ""                 # 原文链接（直达官网）
    official_url: str = ""         # 官网首页（用于核验图标跳转）

    content: str = ""              # 正文摘要（前500字）
    full_content: str = ""        # 完整正文

    # 时间
    published_date: Optional[datetime] = None  # 原文发布日期（从网站解析）
    published_date_str: str = ""    # 原文发布日期（字符串，用于显示）
    crawled_date: datetime = field(default_factory=datetime.now)
    crawled_date_str: str = ""     # 抓取时间

    # AI分析
    ai_summary: str = ""          # AI一句话摘要
    target_audience: str = ""    # 适用人群

    # 状态
    is_important: bool = False
    is_fresh: bool = False       # 24小时内
    keywords_matched: List[str] = field(default_factory=list)
    keyword_score: int = 0        # 关键词匹配得分（越高越相关）

    def __post_init__(self):
        if not self.crawled_date_str:
            self.crawled_date_str = self.crawled_date.strftime("%Y-%m-%d %H:%M:%S")
        if self.published_date and not self.published_date_str:
            self.published_date_str = self._format_date(self.published_date)
        # 判断新鲜（24h内）
        if self.published_date:
            diff = datetime.now() - self.published_date
            self.is_fresh = diff.total_seconds() < 86400
        # 领域标签
        if self.domain == "government":
            self.domain_label = "政府公告"
        else:
            self.domain_label = "跨境电商"
        # 自动匹配关键词
        text = (self.title or "") + " " + (self.content or "") + " " + (self.full_content or "")
        self.keywords_matched = match_keywords(text)
        self.keyword_score = len(self.keywords_matched)

    def _format_date(self, dt: datetime) -> str:
        """格式化日期"""
        if not dt:
            return ""
        now = datetime.now()
        diff = now - dt
        if diff.days == 0:
            return f"今天 {dt.strftime('%H:%M')}"
        elif diff.days == 1:
            return f"昨天 {dt.strftime('%H:%M')}"
        elif diff.days < 7:
            return f"{diff.days}天前"
        elif dt.year == now.year:
            return dt.strftime("%m-%d")
        else:
            return dt.strftime("%Y-%m-%d")

    def compute_hash(self) -> str:
        """计算去重哈希"""
        raw = f"{self.title}|{self.url}".encode("utf-8")
        return hashlib.sha256(raw).hexdigest()[:16]

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "source_id": self.source_id,
            "source_name": self.source_name,
            "source_short": self.source_short,
            "domain": self.domain,
            "domain_label": self.domain_label,
            "title": self.title,
            "url": self.url,
            "official_url": self.official_url,
            "content": self.content,
            "full_content": self.full_content,
            "published_date": self.published_date.isoformat() if self.published_date else None,
            "published_date_str": self.published_date_str,
            "crawled_date_str": self.crawled_date_str,
            "ai_summary": self.ai_summary,
            "target_audience": self.target_audience,
            "is_important": self.is_important,
            "is_fresh": self.is_fresh,
            "keywords_matched": self.keywords_matched,
            "keyword_score": self.keyword_score,
        }


# ============== 核心爬虫引擎 ==============

class PolicyScraper:
    """
    精准政策爬虫
    支持从真实政务网站抓取，解析实际发布日期和原文链接
    """

    _session: requests.Session = None
    _session_lock = threading.Lock()

    def __init__(self, source: PolicySource):
        self.source = source
        self._ensure_session()

    def _ensure_session(self):
        if PolicyScraper._session is None:
            with PolicyScraper._session_lock:
                if PolicyScraper._session is None:
                    PolicyScraper._session = requests.Session()
                    PolicyScraper._session.headers.update(HEADERS)

    @property
    def session(self) -> requests.Session:
        return PolicyScraper._session

    def fetch(self, url: str, retries: int = MAX_RETRIES) -> Optional[str]:
        """
        获取页面 HTML（带重试机制）

        策略：
        1. 使用多个 User-Agent 轮换
        2. 失败后指数退避重试
        3. 忽略 SSL 证书错误
        4. 自动编码检测
        """
        last_error = None
        for attempt in range(retries):
            try:
                # 轮换 User-Agent
                ua = USER_AGENTS[attempt % len(USER_AGENTS)]
                headers = dict(HEADERS)
                headers["User-Agent"] = ua

                resp = self.session.get(
                    url,
                    headers=headers,
                    timeout=REQUEST_TIMEOUT,
                    allow_redirects=True,
                    verify=False,
                )
                if resp.status_code == 200:
                    enc = resp.apparent_encoding or self.source.encoding
                    if enc.lower() in ("gb2312", "gbk", "gb18030"):
                        enc = "gbk"
                    elif enc.lower() not in ("utf-8", "utf8", "iso-8859-1", "ascii"):
                        enc = "utf-8"
                    resp.encoding = enc
                    return resp.text
                elif resp.status_code in (403, 429, 500, 502, 503):
                    # 可重试状态码
                    last_error = f"HTTP {resp.status_code}"
                else:
                    logger.debug(f"[{self.source.id}] HTTP {resp.status_code}: {url}")
                    return None

            except requests.exceptions.Timeout:
                last_error = "超时"
                logger.debug(f"[{self.source.id}] 超时 (attempt {attempt + 1}/{retries}): {url}")
            except requests.exceptions.SSLError as e:
                last_error = f"SSL错误: {e}"
                logger.debug(f"[{self.source.id}] SSL错误: {url}")
            except Exception as e:
                last_error = str(e)
                logger.debug(f"[{self.source.id}] 请求失败: {e}")

            # 退避等待
            if attempt < retries - 1:
                time.sleep(RETRY_BACKOFF * (attempt + 1))

        logger.warning(f"[{self.source.id}] 获取失败（{retries}次重试）: {url} - {last_error}")
        return None

    def scrape_list_page(self, url: str) -> List[Dict]:
        """抓取单个列表页，返回原始条目"""
        html = self.fetch(url)
        if not html:
            return []
        return self._parse_list(html)

    def _parse_list(self, html: str) -> List[Dict]:
        """
        解析列表页 HTML - 通用 + 政府文件双策略

        策略1：从 URL 路径提取日期（/2026n/YYYYMMDD/ 格式）
              这是政府官方文件的典型 URL 结构
        策略2：从 ul/ol 列表提取
        策略3：关键词过滤兜底
        """
        items = []
        seen_urls = set()
        try:
            soup = BeautifulSoup(html, "lxml")
            for tag in soup.find_all(["nav", "footer", "aside", "script", "style", "header"]):
                tag.decompose()

            # 策略1：直接从 URL 路径提取日期（最准确）
            # 政府文件典型 URL: /2026n/2026041019105484412/index.shtml
            for a in soup.find_all("a", href=True):
                href = a.get("href", "")
                text = a.get_text(strip=True)
                if not self._is_valid_link(href) or len(text) < 6:
                    continue
                # 从 URL 路径提取日期
                date_str = self._extract_date_from_url(href)
                url = self._normalize_url(href)
                if url in seen_urls:
                    continue
                # 只接受日期可提取的链接，或包含政策关键词的链接
                if date_str or any(k in text for k in [
                    "通知", "公告", "政策", "补贴", "扶持", "决定", "办法",
                    "意见", "公示", "申报", "规划", "方案", "计划", "条例",
                    "法规", "文件", "认定", "标准", "指南", "通告", "解读",
                ]):
                    seen_urls.add(url)
                    items.append({"title": text, "url": url, "date": date_str})

            # 策略2：从 ul/ol 列表提取（只取包含政策关键词的列表）
            policy_kw = ["通知", "公告", "政策", "补贴", "扶持", "决定", "办法", "意见", "公示", "申报", "解读"]
            for lst in soup.find_all(["ul", "ol"]):
                # 只处理包含政策关键词的列表
                lst_text = lst.get_text(strip=True)
                if not any(kw in lst_text for kw in policy_kw):
                    continue
                for li in lst.find_all("li", recursive=False):
                    item = self._extract_item_from_li(li)
                    if item and item["url"] not in seen_urls:
                        seen_urls.add(item["url"])
                        items.append(item)

            # 策略3：从 table 行提取（税务局等表格布局网站）
            for table in soup.find_all("table"):
                for row in table.find_all("tr"):
                    cells = row.find_all(["td", "th"])
                    if len(cells) < 2:
                        continue
                    for i, cell in enumerate(cells):
                        a_tag = cell.find("a", href=True)
                        if a_tag:
                            href = a_tag.get("href", "")
                            if not self._is_valid_link(href):
                                continue
                            title = a_tag.get_text(strip=True)
                            if len(title) < 6:
                                continue
                            url = self._normalize_url(href)
                            if url in seen_urls:
                                continue
                            date_str = self._extract_date_from_url(href)
                            if not date_str:
                                for c in cells:
                                    text = c.get_text()
                                    m = re.search(r"\[(\d{2})-(\d{2})\]", text)
                                    if m:
                                        date_str = f"{datetime.now().year}-{m.group(1)}-{m.group(2)}"
                                        break
                                    d = self._extract_date(text)
                                    if d:
                                        date_str = d
                                        break
                            seen_urls.add(url)
                            items.append({"title": title, "url": url, "date": date_str})

            # 策略4：从 .list/.news-list 容器中提取（税务总局等）
            # 专门处理带日期的政策列表容器，不过滤seen_urls（因为策略2可能误加了导航）
            for container in soup.select(".list, ul.list, .news-list, ul.news-list"):
                for li in container.find_all("li", recursive=False):
                    a_tag = li.find("a", href=True)
                    if not a_tag:
                        continue
                    href = a_tag.get("href", "")
                    if not self._is_valid_link(href):
                        continue
                    title = a_tag.get_text(strip=True)
                    if len(title) < 6:
                        continue
                    normalized = self._normalize_url(href)
                    # 从 li 整体文本提取日期
                    li_text = li.get_text()
                    date_str = self._extract_date_from_url(href)
                    if not date_str:
                        m = re.search(r"\[(\d{2})-(\d{2})\]", li_text)
                        if m:
                            date_str = f"{datetime.now().year}-{m.group(1)}-{m.group(2)}"
                        else:
                            date_str = self._extract_date(li_text)
                    # 策略4的条目：优先添加（不管是否在seen_urls）
                    items.append({"title": title, "url": normalized, "date": date_str})
                    seen_urls.add(normalized)  # 加入seen防止后续策略重复

            # 策略5：从 TRS_Editor 内容块提取（政府网站通用）
            for editor in soup.select(".TRS_Editor, #zoom, .TRS_Editor *"):
                for a in editor.find_all("a", href=True):
                    href = a.get("href", "")
                    if not self._is_valid_link(href):
                        continue
                    text = a.get_text(strip=True)
                    if len(text) < 6:
                        continue
                    if any(k in text for k in ["通知", "公告", "政策", "补贴", "扶持", "决定", "办法"]):
                        url = self._normalize_url(href)
                        if url in seen_urls:
                            continue
                        date_str = self._extract_date_from_url(href)
                        if not date_str:
                            date_str = self._extract_date(editor.get_text())
                        seen_urls.add(url)
                        items.append({"title": text, "url": url, "date": date_str})

        except Exception as e:
            logger.warning(f"[{self.source.id}] 列表解析失败: {e}")
        return items[:MAX_ITEMS_PER_SOURCE]

    def _extract_date_from_url(self, url: str) -> str:
        """
        从 URL 路径提取日期（支持多种政府文件 URL 格式）

        支持格式：
          /2026n/2026041019105484412/index.shtml  (辽宁省政府)
          /2025/20251201/xxx/                    (通用 yyyy/mm/dd)
          /2025080509244910928/index.shtml         (yyyyMMddHHmmss + 随机)
          /2026/art_c5786609fa954c27bb288a5afbefec08.html  (MOFCOM article ID)
          /article/2026/art_XXXXXXXX.html          (MOFCOM /zcfb/ 风格)
          ?date=2026-04-10                        (URL 参数)
        """
        # 1. /2026n/20260410... 模式（辽宁省政府）
        m = re.search(r"/(\d{4}n)/(\d{8})", url)
        if m:
            d = m.group(2)
            if 19000101 <= int(d) <= 20991231:
                return f"{d[:4]}-{d[4:6]}-{d[6:8]}"

        # 2. /2025/20251201/ 模式
        m = re.search(r"/(\d{4})/(\d{8})/", url)
        if m:
            d = m.group(2)
            if 19000101 <= int(d) <= 20991231:
                return f"{d[:4]}-{d[4:6]}-{d[6:8]}"

        # 3. /2025080509244910928/index.shtml 模式（8位时间戳开头，辽宁商务厅等）
        m = re.search(r"/(\d{8})\d{4,}/", url)
        if m:
            d = m.group(1)
            if 20000101 <= int(d) <= 20991231:
                return f"{d[:4]}-{d[4:6]}-{d[6:8]}"

        # 4. /article/2026/art_XXXXXXXXXXXXXXXX.html (MOFCOM)
        m = re.search(r"/article/(\d{4})/art_", url)
        if m:
            return m.group(1) + "-01-01"  # 年份级精度

        # 5. /zcfb/zhzc/art/2026/art_XXX.html (MOFCOM 政策发布)
        m = re.search(r"/(\d{4})/art_", url)
        if m:
            return m.group(1) + "-01-01"

        # 6. URL 参数 ?date=2026-04-10
        m = re.search(r"[?&]date=(\d{4}-\d{2}-\d{2})", url)
        if m:
            return m.group(1)

        return ""

    def _extract_item_from_li(self, li) -> Optional[Dict]:
        """从 li 元素提取条目"""
        try:
            # 找链接
            a_tag = li.find("a", href=True)
            if not a_tag:
                return None

            href = a_tag.get("href", "")
            if not self._is_valid_link(href):
                return None

            title = a_tag.get_text(strip=True)
            if not self._is_valid_title(title):
                return None

            url = self._normalize_url(href)

            # 提取日期（从li文本中查找）
            li_text = li.get_text()
            date_str = self._extract_date(li_text)

            return {"title": title, "url": url, "date": date_str}
        except Exception:
            return None

    def _is_valid_link(self, href: str) -> bool:
        """判断是否为有效链接"""
        if not href or href.startswith("#") or href.startswith("javascript"):
            return False
        href_lower = href.lower()
        if any(k in href_lower for k in ["login", "logout", "register", "about", "contact", "sitemap"]):
            return False
        return True

    def _is_valid_title(self, title: str) -> bool:
        """判断是否为有效标题"""
        if not title or len(title) < 6:
            return False
        # 过滤广告性质的
        bad_kw = ["广告", "推广", "[广告]", "更多"]
        if any(k in title for k in bad_kw):
            return False
        return True

    def _normalize_url(self, href: str) -> str:
        """规范化 URL"""
        if not href:
            return ""
        href = href.strip()
        if href.startswith("//"):
            href = "https:" + href
        elif href.startswith("/"):
            href = self.source.base_url + href
        elif not href.startswith("http"):
            href = self.source.base_url + "/" + href
        # 清理锚点
        href = href.split("#")[0]
        return href

    def _extract_date(self, text: str) -> str:
        """
        从文本中提取日期（支持多种格式）
        包括：2026-04-10, 2026/04/10, 2026年4月10日, 04-06 (年隐含), 2026.04.10
        """
        text = text.strip()
        patterns = [
            (r"(\d{4}-\d{1,2}-\d{1,2})", "%Y-%m-%d"),
            (r"(\d{4}/\d{1,2}/\d{1,2})", "%Y/%m/%d"),
            (r"(\d{4}年\d{1,2}月\d{1,2}日)", "annual"),
            (r"(\d{4}\.\d{1,2}\.\d{1,2})", "%Y.%m.%d"),
            (r"(\d{4}-\d{2}-\d{2})", "%Y-%m-%d"),  # yyyy-MM-dd
            (r"(\d{4}\d{2}\d{2})", "compact"),      # yyyyMMdd
        ]
        for p, _ in patterns:
            m = re.search(p, text)
            if m:
                raw = m.group(1)
                # 年月日格式
                m2 = re.match(r"(\d{4})年(\d{1,2})月(\d{1,2})日", raw)
                if m2:
                    return f"{m2.group(1)}-{m2.group(2).zfill(2)}-{m2.group(3).zfill(2)}"
                # yyyyMMdd 紧凑格式
                if len(raw) == 8 and raw.isdigit():
                    return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
                return raw
        return ""

    def parse_date(self, date_str: str) -> Optional[datetime]:
        """解析日期字符串为 datetime"""
        if not date_str:
            return None
        date_str = date_str.strip()
        formats = [
            "%Y-%m-%d",
            "%Y/%m/%d",
            "%Y年%m月%d日",
            "%Y.%m.%d",
            "%Y-%m-%d %H:%M",
            "%Y/%m/%d %H:%M",
        ]
        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue
        # 手动提取
        m = re.search(r"(\d{4})[年/\.-](\d{1,2})[月/\.-](\d{1,2})", date_str)
        if m:
            try:
                return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                pass
        return None

    def fetch_detail(self, url: str, title: str = "") -> PolicyItem:
        """抓取详情页，提取正文和实际发布日期"""
        html = self.fetch(url)
        now = datetime.now()

        # 优先从 URL 提取日期（最准确）
        url_date_str = self._extract_date_from_url(url)
        url_date = self.parse_date(url_date_str) if url_date_str else None

        item = PolicyItem(
            source_id=self.source.id,
            source_name=self.source.name,
            source_short=self.source.name_short,
            domain=self.source.domain.value,
            domain_label="政府公告" if self.source.domain == ContentDomain.GOVERNMENT else "跨境电商",
            title=title,
            url=url,
            official_url=self.source.official_url,
            crawled_date=now,
            crawled_date_str=now.strftime("%Y-%m-%d %H:%M:%S"),
        )

        if not html:
            return item

        try:
            soup = BeautifulSoup(html, "lxml")

            # 移除无关标签
            for tag in soup.find_all(["nav", "footer", "aside", "script", "style", "header"]):
                tag.decompose()

            # 提取标题（如果详情页有独立标题）
            detail_title = self._extract_detail_title(soup)
            if detail_title and len(detail_title) > len(title):
                item.title = detail_title

            # 提取正文
            content_text = self._extract_content(soup)
            if content_text:
                item.full_content = content_text
                item.content = content_text[:500]

            # 提取实际发布日期（从详情页）
            pub_date = self._extract_published_date(soup, html)
            if pub_date:
                item.published_date = pub_date
                item.published_date_str = self._format_date(pub_date)
            else:
                # 兜底：用 URL 日期或当前时间
                item.published_date = url_date if url_date else now
                item.published_date_str = self._format_date(item.published_date)

            # 判断重要性
            item.is_important = self._judge_importance(item.title, content_text)

            # 判断新鲜（24h内）
            if item.published_date:
                diff = now - item.published_date
                item.is_fresh = diff.total_seconds() < 86400

        except Exception as e:
            logger.warning(f"[{self.source.id}] 详情解析失败: {e}")

        item.id = item.compute_hash()
        return item

    def _extract_detail_title(self, soup: BeautifulSoup) -> str:
        """从详情页提取标题"""
        selectors = [
            "h1.title", "h1.article-title", "h1", ".article-title",
            ".content-title", "h2.title", ".zoom h1",
        ]
        for sel in selectors:
            el = soup.select_one(sel)
            if el:
                t = el.get_text(strip=True)
                if t and len(t) > 5:
                    return t
        return ""

    def _extract_content(self, soup: BeautifulSoup) -> str:
        """提取正文内容（支持多种政府网站结构）"""
        # 选择器优先级：通用 > 各网站专用
        selectors = [
            # 通用
            "#zoom", ".TRS_Editor", ".article-content", ".content",
            ".article-detail", "#artibody", ".detail-content",
            "article", ".main-content",
            # 商务部
            ".article, .article-content, .news-content, .news_text",
            # 辽宁省政府/商务厅
            ".detail-content, .article-detail, .news-detail, .view-content",
            # 税务总局
            ".article_con, .content_con, .txt_con",
        ]
        for sel in selectors:
            el = soup.select_one(sel)
            if el:
                for tag in el.find_all(["script", "style", "nav"]):
                    tag.decompose()
                text = el.get_text(separator="\n", strip=True)
                if len(text) > 50:
                    return text

        # 兜底：找最大的文字块
        all_texts = []
        for tag in soup.find_all(["div", "section", "article"]):
            text = tag.get_text(strip=True)
            if len(text) > 200 and len(text) < 50000:
                all_texts.append((len(text), text))
        if all_texts:
            all_texts.sort(key=lambda x: -x[0])
            return all_texts[0][1]

        return ""

    def _extract_published_date(self, soup: BeautifulSoup, html: str) -> Optional[datetime]:
        """从详情页提取发布日期"""
        # 策略1：从 meta 标签
        for meta_name in ["publishdate", "PubDate", "article:published_time", "citation_publication_date"]:
            meta = soup.find("meta", {"name": meta_name}) or soup.find("meta", {"property": meta_name})
            if meta and meta.get("content"):
                date_str = meta.get("content")[:10]
                dt = self.parse_date(date_str)
                if dt:
                    return dt

        # 策略2：从日期选择器
        date_selectors = [
            ".info span", ".article-info span", ".date", ".time", ".article-date",
            ".publish-date", "span.date", "em.date", ".info-date",
        ]
        for sel in date_selectors:
            el = soup.select_one(sel)
            if el:
                text = el.get_text(strip=True)
                dt = self.parse_date(text)
                if dt:
                    return dt

        # 策略3：从 HTML 中直接正则
        patterns = [
            r"发布时间[：:]*(\d{4}[-年/\.]\d{1,2}[-月/\.]\d{1,2})",
            r"发布日期[：:]*(\d{4}[-年/\.]\d{1,2}[-月/\.]\d{1,2})",
            r"(\d{4}年\d{1,2}月\d{1,2}日)",
            r"(\d{4}-\d{2}-\d{2})",
        ]
        for p in patterns:
            m = re.search(p, html)
            if m:
                dt = self.parse_date(m.group(1))
                if dt:
                    return dt

        return None

    def _judge_importance(self, title: str, content: str) -> bool:
        """判断是否为重要政策"""
        important_kw = [
            "新增", "扩大", "优惠", "扶持", "补贴", "减免", "退税",
            "利好", "重要", "紧急", "试行", "实施", "通知",
            "申报", "认定", "公示",
        ]
        text = title + content[:500]
        score = sum(1 for kw in important_kw if kw in text)
        return score >= 2

    def _format_date(self, dt: datetime) -> str:
        if not dt:
            return ""
        now = datetime.now()
        diff = now - dt
        if diff.days == 0:
            return f"今天 {dt.strftime('%H:%M')}"
        elif diff.days == 1:
            return f"昨天 {dt.strftime('%H:%M')}"
        elif diff.days < 7:
            return f"{diff.days}天前"
        elif dt.year == now.year:
            return dt.strftime("%m-%d")
        else:
            return dt.strftime("%Y-%m-%d")

    def scrape_all_items(self, max_items: int = 20) -> List[PolicyItem]:
        """
        执行抓取（支持自定义抓取数量）

        Args:
            max_items: 最多抓取条数（默认20）
        """
        results = []
        urls_to_crawl = set()

        list_urls = []
        if self.source.list_url:
            list_urls.append(self.source.list_url)
        if self.source.page_urls:
            list_urls.extend(self.source.page_urls)

        seen_urls = set()
        for url in list_urls:
            if url not in seen_urls:
                seen_urls.add(url)
                items = self.scrape_list_page(url)
                for item in items:
                    if item["url"] not in urls_to_crawl:
                        urls_to_crawl.add(item["url"])
                        results.append({
                            "title": item["title"],
                            "url": item["url"],
                        })
                time.sleep(0.3)

        # 抓取详情
        final_results = []
        for basic in results[:max_items]:
            time.sleep(0.5)
            item = self.fetch_detail(basic["url"], basic["title"])
            final_results.append(item)

        return final_results

    def scrape(self) -> List[PolicyItem]:
        """执行抓取（默认10条）"""
        return self.scrape_all_items(max_items=10)


# ============== 聚合爬虫 ==============

class PolicyAggregator:
    """
    政策聚合爬虫
    同时从多个权威来源抓取，按发布时间排序
    """

    _seen_hashes: set = set()
    _lock = threading.Lock()

    def scrape_all(
        self,
        domain: str = "all",
        time_range: str = "all",
        keyword_filter: str = "",
        limit: int = 10,
    ) -> List[Dict]:
        """
        从所有来源抓取政策，支持时间过滤和关键词过滤。

        Args:
            domain: cross_border / government / all
            time_range: 1d / 3d / 1w / 1m / all（精确时间过滤）
            keyword_filter: 关键词搜索（在标题+正文中匹配）
            limit: 返回条数

        Returns:
            按关键词得分+发布时间排序的 PolicyItem 列表
        """
        time_filter = TimeRange.from_id(time_range)
        kw_list = [k.strip() for k in keyword_filter.split() if k.strip()] if keyword_filter else []

        sources = POLICY_SOURCES
        if domain == "cross_border":
            sources = [s for s in POLICY_SOURCES if s.domain == ContentDomain.CROSS_BORDER]
        elif domain == "government":
            sources = [s for s in POLICY_SOURCES if s.domain == ContentDomain.GOVERNMENT]

        all_items: List[PolicyItem] = []

        for source in sources:
            try:
                scraper = PolicyScraper(source)
                # 多抓一些（limit × 3），确保过滤后仍有足够数量
                items = scraper.scrape_all_items(max_items=limit * 3)
                for item in items:
                    # === 时间过滤 ===
                    if not time_filter.is_within(item.published_date):
                        continue

                    # === 关键词过滤（标题+正文）===
                    if kw_list:
                        full_text = (item.title or "") + " " + (item.content or "") + " " + (item.full_content or "")
                        if not any(kw.lower() in full_text.lower() for kw in kw_list):
                            continue

                    # === 去重 ===
                    h = item.compute_hash()
                    with PolicyAggregator._lock:
                        if h not in PolicyAggregator._seen_hashes:
                            PolicyAggregator._seen_hashes.add(h)
                            all_items.append(item)

                logger.info(f"[Scraper] {source.name}: 抓取{len(items)}条, 通过过滤{len([i for i in items if time_filter.is_within(i.published_date or datetime.min)])}条")
            except Exception as e:
                logger.warning(f"[Scraper] {source.name} 失败: {e}")

        # === 排序：关键词得分 > 发布时间 ===
        def sort_key(item: PolicyItem):
            pub = item.published_date or datetime.min
            return (-item.keyword_score, -pub.timestamp())

        all_items.sort(key=sort_key)

        # 如果关键词过滤后数量不足，扩大时间范围重试
        if len(all_items) < limit and time_range != "all" and kw_list:
            # 尝试扩大时间范围
            wider_ranges = {"1d": "3d", "3d": "1w", "1w": "1m", "1m": "all"}
            wider = wider_ranges.get(time_range, "all")
            if wider != time_range:
                wider_filter = TimeRange.from_id(wider)
                extra = []
                for source in sources:
                    try:
                        scraper = PolicyScraper(source)
                        items = scraper.scrape_all_items(max_items=limit * 3)
                        for item in items:
                            if wider_filter.is_within(item.published_date):
                                if kw_list:
                                    full_text = (item.title or "") + " " + (item.content or "")
                                    if not any(kw.lower() in full_text.lower() for kw in kw_list):
                                        continue
                                h = item.compute_hash()
                                with PolicyAggregator._lock:
                                    if h not in PolicyAggregator._seen_hashes:
                                        PolicyAggregator._seen_hashes.add(h)
                                        extra.append(item)
                    except Exception:
                        pass
                extra.sort(key=sort_key)
                all_items.extend(extra)

        result = all_items[:limit]
        logger.info(f"[Aggregator] 最终返回 {len(result)} 条（时间={time_range}, 关键词={keyword_filter}, 领域={domain}）")
        return [item.to_dict() for item in result]

    def scrape_stream(
        self,
        domain: str = "all",
        time_range: str = "all",
        keyword_filter: str = "",
        limit: int = 10,
    ):
        """
        流式抓取（Generator）：每个数据源爬完后立即 yield 条目。
        用于 SSE 流式推送，前端实时渲染。

        Yields:
            dict: 单条政策条目（带 source_name 标注）
        """
        time_filter = TimeRange.from_id(time_range)
        kw_list = [k.strip() for k in keyword_filter.split() if k.strip()] if keyword_filter else []

        sources = POLICY_SOURCES
        if domain == "cross_border":
            sources = [s for s in POLICY_SOURCES if s.domain == ContentDomain.CROSS_BORDER]
        elif domain == "government":
            sources = [s for s in POLICY_SOURCES if s.domain == ContentDomain.GOVERNMENT]

        seen = set()
        yielded_count = 0

        for idx, source in enumerate(sources):
            try:
                scraper = PolicyScraper(source)
                items = scraper.scrape_all_items(max_items=limit * 3)

                # 先推送进度事件
                yield {
                    "_type": "progress",
                    "source_id": source.id,
                    "source_name": source.name,
                    "source_idx": idx + 1,
                    "source_total": len(sources),
                    "fetched_count": len(items),
                }

                for item in items:
                    # 时间过滤
                    if not time_filter.is_within(item.published_date):
                        continue
                    # 关键词过滤
                    if kw_list:
                        full_text = (item.title or "") + " " + (item.content or "") + " " + (item.full_content or "")
                        if not any(kw.lower() in full_text.lower() for kw in kw_list):
                            continue
                    # 去重
                    h = item.compute_hash()
                    with PolicyAggregator._lock:
                        if h in PolicyAggregator._seen_hashes:
                            continue
                        PolicyAggregator._seen_hashes.add(h)
                    seen.add(h)

                    d = item.to_dict()
                    d["_type"] = "item"
                    d["source_idx"] = idx + 1
                    d["source_total"] = len(sources)
                    yield d
                    yielded_count += 1
                    if yielded_count >= limit:
                        return  # 达到数量上限

                logger.info(f"[Stream] {source.name}: 爬{len(items)}条, 通过{len([i for i in items if time_filter.is_within(i.published_date or datetime.min)])}条")
            except Exception as e:
                logger.warning(f"[Stream] {source.name} 失败: {e}")
                yield {
                    "_type": "error",
                    "source_id": source.id,
                    "source_name": source.name,
                    "error": str(e),
                }

        # 推送完成
        yield {
            "_type": "done",
            "total": yielded_count,
            "filters": {"time_range": time_range, "domain": domain, "keyword": keyword_filter},
        }

    def get_source_stats(self) -> List[Dict]:
        """获取所有数据源统计"""
        return [
            {
                "id": s.id,
                "name": s.name,
                "name_short": s.name_short,
                "domain": s.domain.value,
                "domain_label": "政府公告" if s.domain == ContentDomain.GOVERNMENT else "跨境电商",
                "base_url": s.base_url,
                "official_url": s.official_url,
                "list_url": s.list_url,
                "priority": s.priority,
            }
            for s in sorted(POLICY_SOURCES, key=lambda x: -x.priority)
        ]


# 单例
policy_aggregator = PolicyAggregator()
