# -*- coding: utf-8 -*-
"""
金牌客服系统 - Gold Customer Service System
功能：
1. 管理后台 - 查询客户完整档案
2. 客户聊天端 - 通过手机号识别客户，自动获取档案，生成高情绪价值回复
3. 完全隔离的会话管理
"""

import sys
import os

# 获取 Python site-packages 路径（动态获取，避免硬编码）
# Python 会自动搜索 site-packages，这里不再需要手动添加
# 但为了兼容性，保留对常见位置的检查

import os
import json
import uuid
import time
import threading
import logging
from datetime import datetime
from flask import Flask, render_template, render_template_string, request, jsonify, session, redirect, url_for, send_from_directory, send_file, abort
from neo4j import GraphDatabase
import requests

# 导入瑞托管家语料库
try:
    from ruitalk_corpus import (
        get_corpus_response,
        get_dynamic_response,
        get_random_icebreak,
        get_response_multilingual,
        stress_test_corpus,
        detect_intent,
    )
    CORPUS_ENABLED = True
except ImportError:
    CORPUS_ENABLED = False
    logger = logging.getLogger(__name__)
    logger.warning("ruitalk_corpus 导入失败，将使用基础回复模式")

# ============== 配置区域 ==============
# 改为从 config.py 读取配置（支持 .env 文件）
_script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(_script_dir)
# 确保从项目目录加载 .env（避免工作目录不同时读不到）
# 优先检查 backend 目录，然后检查根目录
try:
    from dotenv import load_dotenv
    _env_path = os.path.join(_script_dir, ".env")
    if not os.path.exists(_env_path):
        # 如果 backend 目录没有 .env，从根目录加载
        _env_path = os.path.join(os.path.dirname(_script_dir), ".env")
    load_dotenv(_env_path)
except Exception:
    pass
try:
    from config import (
        NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD, DEEPSEEK_API_KEY, DEEPSEEK_API_URL,
        GRAPHRAG_API_URL, SECRET_KEY, ADMIN_PASSWORD, ALLOWED_ORIGINS, GOLD_CS_PORT,
    )
except ImportError:
    # 如果 config.py 加载失败，使用下面的默认值
    NEO4J_URI = "bolt://localhost:7687"
    NEO4J_USER = "neo4j"
    NEO4J_PASSWORD = "ZEhua?041015"
    DEEPSEEK_API_KEY = "sk-8cb01226e8b945c4825c550911f469e4"
    DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
    GRAPHRAG_API_URL = "http://127.0.0.1:5050/query"
    SECRET_KEY = str(uuid.uuid4())
    ADMIN_PASSWORD = "123456"
    GOLD_CS_PORT = int(os.getenv("GOLD_CS_PORT", "5001"))

# ============== 日志配置 ==============
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============== Flask 应用初始化 ==============
# 关闭 Flask 默认 /static 处理器，使用我们自定义的静态文件路由（兼容中文路径）
app = Flask(__name__, template_folder='../frontend', static_folder=None)
app.secret_key = SECRET_KEY

# 前端目录路径
FRONTEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'frontend'))
STATIC_DIR = os.path.join(FRONTEND_DIR, 'static')

# 确保静态文件路径正确
@app.route('/static/<path:filename>')
def serve_static(filename):
    """服务前端静态文件"""
    # Windows 下带中文路径时，send_from_directory 可能出现 404（安全拼接失败/路径编码问题）
    static_root = os.path.abspath(STATIC_DIR)
    full_path = os.path.abspath(os.path.join(static_root, filename))
    if not (full_path == static_root or full_path.startswith(static_root + os.sep)):
        abort(404)
    if not os.path.exists(full_path):
        abort(404)
    return send_file(full_path)


def load_html(filename):
    """从 frontend 目录加载 HTML 文件"""
    try:
        filepath = os.path.join(FRONTEND_DIR, filename)
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        logger.error(f"HTML 文件未找到: {filename}")
        return "<h1>404 - 页面未找到</h1>", 404
    except Exception as e:
        logger.error(f"加载 HTML 文件失败: {e}")
        return "<h1>500 - 服务器错误</h1>", 500

# CORS配置（从环境变量读取，生产环境禁止 *）
@app.after_request
def add_cors_headers(response):
    from flask import request
    origin = request.headers.get('Origin', '')
    # 生产环境：仅允许配置的域名
    if ALLOWED_ORIGINS:
        if origin in ALLOWED_ORIGINS:
            response.headers['Access-Control-Allow-Origin'] = origin
        else:
            response.headers['Access-Control-Allow-Origin'] = ALLOWED_ORIGINS[0] if ALLOWED_ORIGINS else ''
    else:
        response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, X-Internal-Token'
    return response

@app.before_request
def handle_preflight():
    from flask import request, make_response
    if request.method == 'OPTIONS':
        r = make_response()
        origin = request.headers.get('Origin', '')
        if ALLOWED_ORIGINS:
            if origin in ALLOWED_ORIGINS:
                r.headers['Access-Control-Allow-Origin'] = origin
            else:
                r.headers['Access-Control-Allow-Origin'] = ALLOWED_ORIGINS[0] if ALLOWED_ORIGINS else ''
        else:
            r.headers['Access-Control-Allow-Origin'] = '*'
        r.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
        r.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, X-Internal-Token'
        return r

# ============== 全局变量 ==============
# 线程安全的客户会话存储
customer_sessions = {}
sessions_lock = threading.RLock()  # 使用可重入锁

# 存储活跃的WebSocket连接 (简化版:使用轮询)
active_connections = {}

# ============== Neo4j 连接管理 ==============
class Neo4jConnection:
    def __init__(self, uri, user, password):
        self.uri = uri
        self.user = user
        self.password = password
        self.driver = None
    
    def connect(self):
        """建立 Neo4j 连接（短超时，失败时快速回退SQLite）"""
        try:
            self.driver = GraphDatabase.driver(
                self.uri,
                auth=(self.user, self.password),
                max_connection_lifetime=3600,
                max_connection_pool_size=50,
                connection_timeout=5  # 5秒超时，快速失败
            )
            # 立即验证连接
            with self.driver.session() as session:
                session.run("RETURN 1")
            logger.info("Neo4j 连接成功")
            return True
        except Exception as e:
            logger.warning(f"Neo4j 连接失败（将回退SQLite）: {e}")
            self.driver = None
            return False
    
    def close(self):
        if self.driver:
            self.driver.close()
    
    def find_customer_by_phone(self, phone):
        """通过手机号查找客户"""
        if not self.driver:
            return None

        # 尝试通过 phone 属性查找
        query = """
        MATCH (c:Customer {phone: $phone})
        RETURN c.id as customer_id, c.name as name, c.phone as phone,
               c.region as region, c.m_value as m_value,
               c.member_since as member_since
        LIMIT 1
        """
        try:
            with self.driver.session() as session_db:
                result = session_db.run(query, phone=phone)
                record = result.single()
                if record:
                    return {
                        'customer_id': record['customer_id'],
                        'name': record['name'],
                        'phone': record['phone'],
                        'region': record['region'],
                        'level': record['m_value'],  # m_value 是 VIP 等级
                        'member_since': record['member_since']
                    }
        except Exception as e:
            logger.error(f"查询客户失败: {e}")
        return None

    def find_customer_by_id(self, customer_id):
        """通过客户ID查找客户"""
        if not self.driver:
            return None

        # 匹配实际的字段: id, name, member_since, region, m_value
        query = """
        MATCH (c:Customer {id: $customer_id})
        RETURN c.id as customer_id, c.name as name, c.phone as phone,
               c.region as region, c.m_value as m_value,
               c.member_since as member_since
        LIMIT 1
        """
        try:
            with self.driver.session() as session_db:
                result = session_db.run(query, customer_id=customer_id)
                record = result.single()
                if record:
                    return {
                        'customer_id': record['customer_id'],
                        'name': record['name'],
                        'phone': record['phone'],
                        'region': record['region'],
                        'level': record['m_value'],  # m_value 是 VIP 等级
                        'member_since': record['member_since']
                    }
        except Exception as e:
            logger.error(f"查询客户失败: {e}")
        return None

    def get_customer_orders(self, customer_id):
        """获取客户订单 - Neo4j Order 节点属性: id, created_at, total, status；订单内商品通过 CONTAINS 获取"""
        if not self.driver:
            return []

        # 兼容两种 Order 结构：created_at/total（常见）与 date/amount（示例数据）
        query = """
        MATCH (c:Customer {id: $customer_id})-[:PURCHASED]->(o:Order)
        OPTIONAL MATCH (o)-[:CONTAINS]->(prod:Product)
        WITH o, collect(prod.name) as items
        RETURN o.id as order_id,
               coalesce(o.created_at, o.date) as date,
               coalesce(o.total, o.amount) as total,
               o.status as status, items
        ORDER BY coalesce(o.created_at, o.date) DESC
        LIMIT 20
        """
        try:
            with self.driver.session() as session_db:
                result = session_db.run(query, customer_id=customer_id)
                rows = [dict(record) for record in result]
                for r in rows:
                    if r.get('date') is None:
                        r['date'] = '-'
                    if r.get('total') is None:
                        r['total'] = 0
                    if r.get('status') is None:
                        r['status'] = '-'
                return rows
        except Exception as e:
            logger.error(f"查询订单失败: {e}")
        return []

    def get_customer_skus(self, customer_id):
        """获取客户购买的商品：按商品去重聚合，返回价格与购买次数（数量）"""
        if not self.driver:
            return []

        # 按商品聚合：同一商品在多个订单中出现只占一行，quantity 为购买次数，price 取自 Product
        query = """
        MATCH (c:Customer {id: $customer_id})-[:PURCHASED]->(o:Order)-[:CONTAINS]->(p:Product)
        OPTIONAL MATCH (p)-[:BELONGS_TO]->(cat:Category)
        WITH p, cat.name as category, count(*) as quantity
        RETURN p.id as product_id, p.name as name, category,
               coalesce(p.price, 0) as price, quantity
        ORDER BY p.name
        LIMIT 50
        """
        try:
            with self.driver.session() as session_db:
                result = session_db.run(query, customer_id=customer_id)
                rows = [dict(record) for record in result]
                for r in rows:
                    if r.get('price') is None:
                        r['price'] = 0
                    if r.get('quantity') is None:
                        r['quantity'] = 1
                return rows
        except Exception as e:
            logger.error(f"查询商品失败: {e}")
        return []

    def get_customer_emotions(self, customer_id):
        """获取客户沟通记录 - 使用 HAS_COMMUNICATION 关系"""
        if not self.driver:
            return []

        # 实际关系是 HAS_COMMUNICATION
        query = """
        MATCH (c:Customer {id: $customer_id})-[:HAS_COMMUNICATION]->(com:Communication)
        RETURN com.date as date, com.type as type,
               com.notes as notes, com.channel as channel
        ORDER BY com.date DESC
        LIMIT 30
        """
        try:
            with self.driver.session() as session_db:
                result = session_db.run(query, customer_id=customer_id)
                return [dict(record) for record in result]
        except Exception as e:
            logger.error(f"查询沟通记录失败: {e}")
        return []
    
    def get_full_profile(self, customer_id):
        """获取完整客户档案"""
        customer = self.find_customer_by_id(customer_id)
        if not customer:
            return None
        
        orders = self.get_customer_orders(customer_id)
        skus = self.get_customer_skus(customer_id)
        emotions = self.get_customer_emotions(customer_id)
        
        return {
            'customer': customer,
            'orders': orders,
            'skus': skus,
            'emotions': emotions
        }


# ============== DeepSeek API 调用 ==============
def call_deepseek(prompt, system_prompt=None):
    """调用DeepSeek API生成回复（带重试和合理超时）"""
    if not DEEPSEEK_API_KEY:
        return "[!] DeepSeek API密钥未配置，请联系管理员"

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}"
    }

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    data = {
        "model": "deepseek-chat",
        "messages": messages,
        "temperature": 0.5,
        "max_tokens": 300
    }

    # 重试策略：(connect_timeout, read_timeout)
    timeouts = (5, 30)
    last_error = None
    for attempt, timeout in enumerate(timeouts):
        try:
            response = requests.post(
                DEEPSEEK_API_URL,
                headers=headers,
                json=data,
                timeout=timeout
            )

            if response.status_code != 200:
                logger.error(f"DeepSeek API错误: {response.status_code} - {response.text}")
                if attempt < len(timeouts) - 1:
                    continue
                return "[!] AI回复生成失败，请稍后重试"

            result = response.json()
            choices = result.get("choices") or []
            if not choices:
                logger.error("DeepSeek API 返回无 choices")
                if attempt < len(timeouts) - 1:
                    continue
                return "[!] AI回复生成失败，请稍后重试"
            msg = choices[0].get("message") or {}
            content = (msg.get("content") or "").strip()
            if not content:
                if attempt < len(timeouts) - 1:
                    continue
                return "[!] AI回复为空，请稍后重试"
            return content
        except requests.exceptions.Timeout:
            logger.warning(f"DeepSeek API 超时（尝试 {attempt + 1}/{len(timeouts)}）")
            last_error = "超时"
        except requests.exceptions.RequestException as e:
            logger.warning(f"DeepSeek API 网络异常（尝试 {attempt + 1}/{len(timeouts)}）: {e}")
            last_error = str(e)
        # 循环继续执行下一次重试
    # 所有重试均失败
    return "[!] 服务暂时不可用，请稍后重试"


# ============== 情绪识别 ==============
def detect_emotion(user_message):
    """识别客户情绪，返回情绪类型: happy/calm/sad/angry/anxious/neutral"""
    msg = (user_message or '').lower().strip()

    # 愤怒/生气关键词
    angry_keywords = ['生气', '愤怒', '恼火', '发火', '烦', '讨厌', '垃圾', '差', '烂', '退货', '投诉', '不满', '再也不', '恨', '滚', 'shut up', 'angry', 'mad', 'hate', 'terrible', 'awful', 'worst', 'complaint', 'refund', 'return', 'annoyed', 'frustrated', 'плохо', 'ужасно', 'жалоба']

    # 难过/低落关键词
    sad_keywords = ['难过', '伤心', '失望', '郁闷', '烦心', '累', '压力', '无奈', '心累', 'sad', 'unhappy', 'disappointed', 'depressed', 'tired', 'upset', 'frustrating', 'upset', 'грустно', 'печально', 'разочарован']

    # 焦虑/着急关键词
    anxious_keywords = ['着急', '急', '焦虑', '担心', '害怕', '不安', '紧张', '什么时候', '多久', 'worried', 'anxious', 'worried', 'when', 'how long', 'soon', 'волнуюсь', 'переживаю', 'скорее']

    # 开心/满意关键词
    happy_keywords = ['谢谢', '感谢', '好样的', '棒', '喜欢', '满意', '开心', '高兴', '不错', '很好', '很好', '优秀', '完美', 'good', 'great', 'excellent', 'amazing', 'wonderful', 'love', 'thank', 'thanks', 'perfect', 'спасибо', 'отлично', 'прекрасно', 'классно']

    # 检查情绪
    if any(kw in msg for kw in angry_keywords):
        return 'angry'
    if any(kw in msg for kw in sad_keywords):
        return 'sad'
    if any(kw in msg for kw in anxious_keywords):
        return 'anxious'
    if any(kw in msg for kw in happy_keywords):
        return 'happy'

    return 'neutral'


def get_emotion_response(customer_info, user_message, language='zh'):
    """生成回复时考虑客户情绪，返回(主回复, 俏皮话/安慰语)"""
    emotion = detect_emotion(user_message)
    customer = customer_info.get('customer', {})
    name = customer.get('name') or '您'

    # 根据情绪生成不同的回复策略
    emotion_responses = {
        'zh': {
            'angry': {
                'reply': '我完全理解您的不满，抱歉给您带来不好的体验。',
                'extra': '消消气~咱们一起想办法解决好不好？'
            },
            'sad': {
                'reply': '听您这么说，我也跟着心疼了。',
                'extra': '抱抱~有我在呢，咱们慢慢聊。'
            },
            'anxious': {
                'reply': '别着急，我这就帮您查。',
                'extra': '放心，很快就好啦~'
            },
            'happy': {
                'reply': '能帮到您我也很开心！',
                'extra': '今天运气真好，遇见您这么可爱的客户~'
            },
            'neutral': {
                'reply': None,
                'extra': None
            }
        },
        'en': {
            'angry': {
                'reply': 'I completely understand your frustration. Sorry for the inconvenience.',
                'extra': 'Take a breath~ Let\'s solve this together, okay?'
            },
            'sad': {
                'reply': 'I feel for you. Sorry you\'re going through this.',
                'extra': 'Sending you a hug~ I\'m here for you.'
            },
            'anxious': {
                'reply': 'No worries, let me check that for you right away.',
                'extra': 'Relax, it\'ll be quick~'
            },
            'happy': {
                'reply': 'Happy to help! It\'s my pleasure.',
                'extra': 'You just made my day~'
            },
            'neutral': {
                'reply': None,
                'extra': None
            }
        },
        'ar': {
            'angry': {
                'reply': 'أفهم إحباطك تماماً. نأسف للإزعاج.',
                'extra': 'اهدأ قليلاً، سنحل الأمر معاً.'
            },
            'sad': {
                'reply': 'أشعر معك. أنا هنا للمساعدة.',
                'extra': 'عناق~ أنا هنا من أجلك.'
            },
            'anxious': {
                'reply': 'لا تقلق، سأتحقق فوراً.',
                'extra': 'ستراه قريباً.'
            },
            'happy': {
                'reply': 'سعيد بمساعدتك!',
                'extra': 'يومك جميل.'
            },
            'neutral': {
                'reply': None,
                'extra': None
            }
        },
        'ru': {
            'angry': {
                'reply': 'Полностью понимаю ваше недовольство. Извините за неудобства.',
                'extra': 'Успокойтесь~ Давайте решим вместе, хорошо?'
            },
            'sad': {
                'reply': 'Сочувствую вам. Я здесь, чтобы помочь.',
                'extra': 'Держитесь~ Я рядом.'
            },
            'anxious': {
                'reply': 'Не волнуйтесь, проверю прямо сейчас.',
                'extra': 'Скоро будет~'
            },
            'happy': {
                'reply': 'Рад(a) помочь!',
                'extra': 'Вы сделали мой день~'
            },
            'neutral': {
                'reply': None,
                'extra': None
            }
        }
    }

    if language not in emotion_responses:
        language = 'zh'

    return emotion, emotion_responses[language].get(emotion, emotion_responses[language]['neutral'])


# ============== 高级情绪分析与客户画像 ==============
def advanced_emotion_analysis(customer_info, user_message, language='zh'):
    """高级情绪分析：结合上下文、历史情绪、购买行为进行深度分析"""
    orders = customer_info.get('orders', [])
    skus = customer_info.get('skus', [])
    emotions = customer_info.get('emotions', [])
    customer = customer_info.get('customer', {})
    
    # 基础情绪检测
    base_emotion = detect_emotion(user_message)
    
    # 分析历史情绪趋势
    emotion_history = []
    for e in emotions[:10]:  # 最近10条情绪记录
        emotion_type = (e.get('type') or '').lower()
        if 'positive' in emotion_type or 'happy' in emotion_type or '满意' in emotion_type:
            emotion_history.append('positive')
        elif 'negative' in emotion_type or 'angry' in emotion_type or '不满' in emotion_type:
            emotion_history.append('negative')
        else:
            emotion_history.append('neutral')
    
    # 计算情绪趋势
    if emotion_history:
        positive_count = emotion_history.count('positive')
        negative_count = emotion_history.count('negative')
        if negative_count > positive_count * 1.5:
            emotion_trend = 'declining'  # 情绪下降趋势
        elif positive_count > negative_count * 1.5:
            emotion_trend = 'improving'  # 情绪改善趋势
        else:
            emotion_trend = 'stable'
    else:
        emotion_trend = 'unknown'
    
    # 分析购买行为与情绪关联
    total_spent = 0
    for o in orders:
        total = o.get('total') or o.get('amount') or 0
        try:
            total_spent += float(total) if total else 0
        except (ValueError, TypeError):
            total_spent += 0
    
    purchase_behavior = {
        'total_orders': len(orders),
        'total_spent': total_spent,
        'avg_order_value': 0,
        'recent_activity': len([o for o in orders if o.get('date')]) > 0
    }
    if purchase_behavior['total_orders'] > 0:
        purchase_behavior['avg_order_value'] = purchase_behavior['total_spent'] / purchase_behavior['total_orders']
    
    # 构建情绪分析结果
    emotion_analysis = {
        'base_emotion': base_emotion,
        'emotion_trend': emotion_trend,
        'emotion_history': emotion_history,
        'purchase_behavior': purchase_behavior,
        'urgency_level': 'high' if base_emotion in ['angry', 'anxious'] else 'normal'
    }
    
    return emotion_analysis


def build_customer_psychological_profile(customer_info, language='zh'):
    """构建客户心理画像：基于购买历史、情绪记录、消费模式"""
    customer = customer_info.get('customer', {})
    orders = customer_info.get('orders', [])
    skus = customer_info.get('skus', [])
    emotions = customer_info.get('emotions', [])
    
    # 消费能力分析
    total_spent = 0
    for o in orders:
        total = o.get('total') or o.get('amount') or 0
        try:
            total_spent += float(total) if total else 0
        except (ValueError, TypeError):
            total_spent += 0
    order_count = len(orders)
    avg_order_value = total_spent / order_count if order_count > 0 else 0
    
    # 消费偏好分析
    categories = {}
    for sku in skus:
        cat = sku.get('category') or '其他'
        categories[cat] = categories.get(cat, 0) + (sku.get('quantity', 1) or 1)
    
    top_categories = sorted(categories.items(), key=lambda x: x[1], reverse=True)[:3]
    
    # 客户类型判断
    customer_type = '新客户'
    if order_count >= 10:
        customer_type = '忠实客户'
    elif order_count >= 5:
        customer_type = '活跃客户'
    elif order_count >= 1:
        customer_type = '普通客户'
    
    # 价值敏感度（基于价格分布）
    prices = []
    for sku in skus:
        price_raw = sku.get('price') or 0
        if price_raw:
            try:
                price = float(price_raw) if price_raw else 0
                if price > 0:
                    prices.append(price)
            except (ValueError, TypeError):
                continue
    value_sensitivity = 'price_sensitive'  # 价格敏感
    if prices:
        avg_price = sum(prices) / len(prices)
        if avg_price > 500:
            value_sensitivity = 'premium_seeker'  # 追求品质
        elif avg_price > 200:
            value_sensitivity = 'balanced'  # 平衡型
    
    # 情绪稳定性
    positive_emotions = sum(1 for e in emotions if 'positive' in (e.get('type') or '').lower() or 'happy' in (e.get('type') or '').lower())
    negative_emotions = sum(1 for e in emotions if 'negative' in (e.get('type') or '').lower() or 'angry' in (e.get('type') or '').lower())
    emotion_stability = 'stable' if abs(positive_emotions - negative_emotions) <= 2 else 'volatile'
    
    # 构建心理画像
    profile = {
        'customer_type': customer_type,
        'consumption_level': 'high' if total_spent > 5000 else ('medium' if total_spent > 1000 else 'low'),
        'preferred_categories': [cat for cat, _ in top_categories],
        'value_sensitivity': value_sensitivity,
        'emotion_stability': emotion_stability,
        'loyalty_score': min(100, order_count * 10 + (total_spent // 100)),
        'engagement_level': 'high' if order_count >= 5 and len(emotions) >= 3 else ('medium' if order_count >= 2 else 'low')
    }
    
    return profile


def interpret_product_design(customer_info, user_message, language='zh'):
    """产品设计解读：理解客户购买的产品背后的设计理念和用户需求"""
    skus = customer_info.get('skus', [])
    orders = customer_info.get('orders', [])
    
    if not skus:
        return None
    
    # 分析产品类别和特征
    product_insights = []
    categories = {}
    price_ranges = []
    
    for sku in skus[:10]:  # 分析前10个商品
        name = sku.get('name', '')
        category = sku.get('category', '')
        price_raw = sku.get('price', 0) or 0
        
        # 安全转换价格为数字
        try:
            price = float(price_raw) if price_raw else 0
        except (ValueError, TypeError):
            price = 0
        
        if category:
            categories[category] = categories.get(category, 0) + 1
        if price > 0:
            price_ranges.append(price)
    
    # 推断用户需求
    needs = []
    if '数码' in str(categories.keys()) or '电子' in str(categories.keys()):
        needs.append('tech_enthusiast')  # 科技爱好者
    if any(p > 500 for p in price_ranges):
        needs.append('quality_seeker')  # 追求品质
    if len(categories) > 3:
        needs.append('diverse_needs')  # 需求多样化
    
    # 设计理念解读
    design_philosophy = []
    if needs:
        if 'tech_enthusiast' in needs:
            design_philosophy.append('追求创新与科技感')
        if 'quality_seeker' in needs:
            design_philosophy.append('注重品质与体验')
        if 'diverse_needs' in needs:
            design_philosophy.append('生活场景多元化')
    
    return {
        'product_categories': list(categories.keys())[:5],
        'inferred_needs': needs,
        'design_philosophy': design_philosophy,
        'price_preference': 'premium' if price_ranges and sum(price_ranges) / len(price_ranges) > 300 else 'value'
    }


def map_experience_value(customer_info, emotion_analysis, psychological_profile, language='zh'):
    """体验价值映射：将客户体验转化为价值建议"""
    customer = customer_info.get('customer', {})
    orders = customer_info.get('orders', [])
    
    # 基于情绪分析的价值建议
    value_suggestions = []
    
    if emotion_analysis.get('emotion_trend') == 'declining':
        value_suggestions.append({
            'type': 'retention',
            'priority': 'high',
            'suggestion': '需要重点关注客户满意度，提供个性化关怀'
        })
    
    if psychological_profile.get('engagement_level') == 'low':
        value_suggestions.append({
            'type': 'engagement',
            'priority': 'medium',
            'suggestion': '建议通过优惠活动或个性化推荐提升参与度'
        })
    
    if psychological_profile.get('value_sensitivity') == 'premium_seeker':
        value_suggestions.append({
            'type': 'upsell',
            'priority': 'medium',
            'suggestion': '可推荐高端产品或增值服务'
        })
    
    # 基于消费模式的价值建议
    if len(orders) > 0:
        try:
            recent_orders = sorted(orders, key=lambda x: x.get('date', '') or '', reverse=True)[:3]
            recent_totals = []
            for o in recent_orders:
                total = o.get('total') or o.get('amount') or 0
                try:
                    total_val = float(total) if total else 0
                    if total_val > 0:
                        recent_totals.append(total_val)
                except (ValueError, TypeError):
                    continue
            if recent_totals:
                avg_recent = sum(recent_totals) / len(recent_totals)
                if avg_recent > 500:
                    value_suggestions.append({
                        'type': 'loyalty',
                        'priority': 'high',
                        'suggestion': '高价值客户，建议提供VIP专属服务'
                    })
        except Exception as e:
            logger.debug(f"消费模式分析失败: {e}")
    
    return {
        'value_suggestions': value_suggestions,
        'customer_value_tier': psychological_profile.get('consumption_level', 'medium'),
        'recommended_action': value_suggestions[0]['suggestion'] if value_suggestions else '保持现有服务水平'
    }


def generate_emotional_response(customer_info, user_message, language='zh'):
    """生成简洁、直接回复，支持多语言和情绪识别。升级版：集成瑞托管家语料库、高级情绪分析、客户心理画像、产品设计解读和体验价值映射。"""
    try:
        customer = customer_info.get('customer', {})
        orders = customer_info.get('orders', [])
        skus = customer_info.get('skus', [])
        emotions = customer_info.get('emotions', [])

        user_msg_lower = (user_message or '').strip().lower()
        name = customer.get('name') or customer.get('customer_id') or '您'
        dear = DEAR_BY_LANG.get(language, '亲爱的')

        # 确保语言有效（默认中文）
        if language not in LANGUAGE_TEMPLATES:
            language = 'zh'
        t = LANGUAGE_TEMPLATES[language]

        # ========== 高级分析模块 ==========
        try:
            emotion_analysis = advanced_emotion_analysis(customer_info, user_message, language)
            base_emotion = emotion_analysis.get('base_emotion', 'neutral')
            emotion_trend = emotion_analysis.get('emotion_trend', 'unknown')
            urgency_level = emotion_analysis.get('urgency_level', 'normal')
        except Exception as e:
            logger.warning(f"高级情绪分析失败: {e}")
            emotion_analysis = {}
            base_emotion = 'neutral'
            emotion_trend = 'unknown'
            urgency_level = 'normal'
        
        try:
            psychological_profile = build_customer_psychological_profile(customer_info, language)
            customer_type = psychological_profile.get('customer_type', '普通客户')
            engagement_level = psychological_profile.get('engagement_level', 'low')
        except Exception as e:
            logger.warning(f"客户心理画像构建失败: {e}")
            psychological_profile = {}
            customer_type = '普通客户'
            engagement_level = 'low'
        
        try:
            product_insights = interpret_product_design(customer_info, user_message, language)
        except Exception as e:
            logger.warning(f"产品设计解读失败: {e}")
            product_insights = None
        
        try:
            experience_value = map_experience_value(customer_info, emotion_analysis, psychological_profile, language)
        except Exception as e:
            logger.warning(f"体验价值映射失败: {e}")
            experience_value = {'recommended_action': '保持现有服务水平'}
        
        # 获取基础情绪回复
        emotion, emotion_data = get_emotion_response(customer_info, user_message, language)

        # ========== 瑞托管家语料库优先匹配 ==========
        if CORPUS_ENABLED:
            # 构建上下文
            context = {
                'hour': datetime.now().hour,
                'is_returning': len(orders) > 0,
                'customer_type': customer_type,
            }
            
            # 尝试从语料库获取回复
            corpus_reply = get_dynamic_response(user_message, base_emotion, context)
            if corpus_reply and not corpus_reply.startswith("[!]"):
                # 语料库命中 - 根据情绪增强回复
                if base_emotion == 'angry' and "抱歉" not in corpus_reply:
                    corpus_reply = f"真的非常抱歉。{corpus_reply}"
                elif base_emotion == 'sad' and "心疼" not in corpus_reply:
                    corpus_reply = f"听您这么说我也心疼。{corpus_reply}"
                elif base_emotion == 'happy' and "开心" not in corpus_reply:
                    corpus_reply = f"能帮到您我也很开心！{corpus_reply}"
                
                # 简短回复直接返回（符合50字原则）
                if len(corpus_reply) <= 60:
                    # 添加俏皮话/安慰语
                    if base_emotion != 'neutral':
                        extra = emotion_data.get('extra')
                        if extra:
                            corpus_reply = f"{corpus_reply}\n{extra}"
                    return corpus_reply

        # ========== 原有业务逻辑（订单、商品、政策等） ==========
        # 明确问订单 → 直接返回订单数据
        order_keywords = ['order', '订单', '购买记录', '购买历史', '消费记录', '有什么订单', '订单号', '我的订单', 'commande', 'pedido']
        if any(kw in user_msg_lower for kw in order_keywords):
            if not orders:
                return t['no_orders'].format(name=dear)
            lines = []
            for o in orders[:10]:
                items_str = '、'.join(o.get('items') or []) or '-'
                date_val = o.get('date') if o.get('date') is not None else '-'
                total_val = o.get('total') if o.get('total') is not None else 0
                status_val = o.get('status') if o.get('status') else '-'
                lines.append(t['order_item'].format(
                    order_id=o.get('order_id') or '-',
                    date=date_val,
                    total=total_val,
                    status=status_val,
                    items=items_str
                ))
            body = '\n'.join(lines)
            return f"{t['orders_title'].format(name=dear)}\n{body}"

        recommend_keywords = ['推荐', 'recommend', 'recommendation', '建议', 'suggest', '有什么好的', '推荐商品', '推荐产品']
        if any(kw in user_msg_lower for kw in recommend_keywords):
            if product_insights and product_insights.get('product_categories'):
                categories = product_insights['product_categories']
                suggestions = '、'.join(categories[:3]) + '等' if categories else ''
            elif skus:
                categories = list({(p.get('category') or '数码配件') for p in skus[:5]})
                suggestions = '、'.join(categories[:3]) + '等' if categories else '数码配件、手机支架等'
            else:
                suggestions = ''
            if suggestions:
                return t['recommend_has'].format(name=dear, suggestions=suggestions)
            return t['recommend_no'].format(name=dear)

        product_keywords = ['product', '商品', '买过', '买了什么', '购买过', 'sku', 'achat', 'compra', 'покупка']
        if any(kw in user_msg_lower for kw in product_keywords):
            if not skus:
                return t['no_products'].format(name=dear)
            items = [f"{p.get('name', '-')}（{p.get('category', '-')}）" for p in skus[:15]]
            return f"{t['products_title'].format(name=dear)}{'、'.join(items)}"

        emotion_keywords = ['emotion', '情绪', '沟通', '反馈', '投诉', '表扬', 'communication', 'связь']
        if any(kw in user_msg_lower for kw in emotion_keywords):
            if not emotions:
                return t['no_emotions'].format(name=dear)
            parts = [f"{e.get('date', '-')} {e.get('type', '-')}（{e.get('channel', '-')}）" for e in emotions[:5]]
            return f"{t['emotions_title'].format(name=dear)}{'；'.join(parts)}"

        # ========== 其他问题走 AI，但用指定语言 ==========
        # 构建增强的数据上下文（包含高级分析结果）
        data_str = ""
        if orders:
            data_str += "订单：" + "；".join([f"{o.get('order_id', '-')}({o.get('date', '-')},¥{o.get('total', 0)},{o.get('status', '-')})" for o in orders[:5]]) + "\n"
        if skus:
            data_str += "商品：" + "、".join([f"{p.get('name', '-')}({p.get('category', '-')})" for p in skus[:8]]) + "\n"
        
        # 添加高级分析信息到上下文
        analysis_context = ""
        if emotion_trend != 'unknown':
            analysis_context += f"【情绪趋势】{emotion_trend}；"
        if customer_type:
            analysis_context += f"【客户类型】{customer_type}；"
        if product_insights and product_insights.get('design_philosophy'):
            analysis_context += f"【产品偏好】{'、'.join(product_insights['design_philosophy'][:2])}；"
        if experience_value and experience_value.get('recommended_action'):
            analysis_context += f"【服务建议】{experience_value.get('recommended_action')}；"
        
        if not data_str:
            data_str = "无"
        if analysis_context:
            data_str += "\n" + analysis_context

        lang_name = SUPPORTED_LANGUAGES.get(language, {}).get('native', '中文')

        # 根据情绪生成回复规则（增强版）
        ai_rules = {
            'zh': '回复最多2句话；禁止客套感谢；禁止反问；直接回答；有数据列数据。客户生气/低落/焦虑时先处理情绪再给答案。基于客户画像和产品偏好提供个性化建议。',
            'en': 'Reply max 2 sentences; no thanks; no follow-up; answer directly. If customer upset, handle emotion first. Provide personalized suggestions based on customer profile and product preferences.',
            'ar': 'ردود قصيرة جداً. بدون شكر؛ أجب مباشرة. إذا مستاء، طمئنه أولاً. قدم اقتراحات مخصصة بناءً على ملف العميل.',
            'ru': 'Максимум 2 предложения. Без благодарностей; отвечай прямо. Если расстроен - успокой сначала. Предлагай персонализированные советы на основе профиля клиента.'
        }

        # 增强的情绪上下文（基于高级分析）
        emotion_context = ""
        if base_emotion == 'angry':
            emotion_context = "【客户很生气，必须先道歉并表示理解】"
            if emotion_trend == 'declining':
                emotion_context += "【注意：客户情绪呈下降趋势，需要特别关注】"
        elif base_emotion == 'sad':
            emotion_context = "【客户情绪低落，必须先安慰】"
            if emotion_trend == 'declining':
                emotion_context += "【注意：客户情绪呈下降趋势，需要特别关注】"
        elif base_emotion == 'anxious':
            emotion_context = "【客户很着急，必须先安抚】"
            if urgency_level == 'high':
                emotion_context += "【高优先级：需要快速响应】"
        elif base_emotion == 'happy':
            emotion_context = "【客户很开心，可以活泼一点】"
            if emotion_trend == 'improving':
                emotion_context += "【客户情绪在改善，可以适当推荐产品或服务】"
        
        # 添加客户画像上下文
        profile_context = ""
        if customer_type != '普通客户':
            profile_context += f"【客户类型】{customer_type}，"
        if engagement_level == 'high':
            profile_context += "【高参与度客户】，"
        elif engagement_level == 'low':
            profile_context += "【低参与度客户，建议提升互动】，"
        
        if product_insights and product_insights.get('inferred_needs'):
            needs_str = '、'.join(product_insights['inferred_needs'][:2]) if isinstance(product_insights['inferred_needs'], list) else str(product_insights['inferred_needs'])
            profile_context += f"【产品偏好】{needs_str}，"

        system_prompt = f"""你是专业客服。规则：{ai_rules.get(language, ai_rules['zh'])}
{emotion_context}
{profile_context}
【语言】整段回复必须且仅用{lang_name}一种语言；禁止在同一句话或同一段中混入中文、英文、阿拉伯文、俄文等任何其他语言或文字。
【称呼】称呼客户请用「{dear}」，不要使用客户真实姓名。
【智能分析】基于客户画像、情绪趋势和产品偏好，提供个性化、有温度的服务。
客户数据（仅供你参考，回复中勿写客户真名）：{data_str}"""

        user_prompt = f"客户说：{user_message}\n请直接用{lang_name}回答。"

        ai_reply = call_deepseek(user_prompt, system_prompt)
        
        # 确保 ai_reply 不为空
        if not ai_reply or not ai_reply.strip():
            logger.warning("AI回复为空，使用默认回复")
            if language == 'zh':
                ai_reply = f"{dear}，我理解您的问题，正在为您处理中。"
            elif language == 'en':
                ai_reply = f"{dear}, I understand your question and I'm processing it for you."
            elif language == 'ar':
                ai_reply = f"{dear}، أفهم سؤالك وأنا أعالجه لك."
            elif language == 'ru':
                ai_reply = f"{dear}, я понимаю ваш вопрос и обрабатываю его для вас."
            else:
                ai_reply = f"{dear}, I'm processing your question."

        # 根据情绪添加俏皮话/安慰语
        if not ai_reply.startswith("[!]") and base_emotion != 'neutral':
            main_reply = emotion_data.get('reply')
            extra = emotion_data.get('extra')

            if main_reply and extra:
                return f"{main_reply}\n{ai_reply}\n{extra}"
            elif main_reply:
                return f"{main_reply}\n{ai_reply}"
            elif extra:
                return f"{ai_reply} {extra}"

        return ai_reply
    except Exception as e:
        logger.error(f"generate_emotional_response 内部错误: {e}", exc_info=True)
        # 如果所有逻辑都失败，返回一个基本的友好回复
        dear = DEAR_BY_LANG.get(language, '亲爱的')
        if language == 'zh':
            return f"{dear}，我理解您的问题，但暂时无法处理，请稍后再试。"
        elif language == 'en':
            return f"{dear}, I understand your question, but I'm unable to process it right now. Please try again later."
        elif language == 'ar':
            return f"{dear}، أفهم سؤالك، لكنني غير قادر على معالجته الآن. يرجى المحاولة مرة أخرى لاحقاً."
        elif language == 'ru':
            return f"{dear}, я понимаю ваш вопрос, но сейчас не могу его обработать. Пожалуйста, попробуйте позже."
        else:
            return f"{dear}, please try again later."


# ============== 多语言支持 ==============
# 支持中文、英文、阿拉伯语、俄语
SUPPORTED_LANGUAGES = {
    'zh': {'name': '中文', 'native': '中文'},
    'en': {'name': 'English', 'native': 'English'},
    'ar': {'name': 'العربية', 'native': 'العربية'},
    'ru': {'name': 'Русский', 'native': 'Русский'}
}

# 后续回复中的亲昵称呼（欢迎语仍用客户姓名，此处仅用于对话中的称呼）
DEAR_BY_LANG = {
    'zh': '亲爱的',
    'en': 'dear',
    'ar': 'عزيزي',
    'ru': 'дорогой',
    'th': 'คุณ',
    'vi': 'bạn',
    'id': 'kak',
    'ms': 'kak',
    'tl': 'ka'
}

# 语言切换关键词（客户用任意一种语言说这些词即切换为对应语言）
LANGUAGE_SWITCH_KEYWORDS = {
    'zh': ['说中文', '用中文', '中文', '换中文', '中文回复', '请用中文', 'chinese', 'in chinese', 'switch to chinese'],
    'en': ['speak english', 'in english', 'english please', 'switch to english', 'use english', '英文', '用英文', '用英语', '英语回复', '可以用英语', '可以直接用英文回复', '用英文回复我'],
    'ar': [
        '用阿拉伯语', '阿拉伯语', '阿拉伯语回复', '请用阿拉伯语', '用阿拉伯语回复', '换阿拉伯语', '说阿拉伯语',
        'بالعربية', 'باللغة العربية', 'تحدث بالعربية', 'الرد بالعربية', 'أريد العربية',
        'in arabic', 'arabic please', 'switch to arabic', 'reply in arabic', 'speak arabic',
        'по-арабски', 'на арабском'
    ],
    'ru': [
        '用俄语', '俄语', '俄语回复', '请用俄语', '用俄语回复', '换俄语', '说俄语',
        'по-русски', 'на русском', 'русский', 'русский язык', 'ответьте по-русски',
        'in russian', 'russian please', 'switch to russian', 'reply in russian', 'speak russian',
        'بالروسية', 'باللغة الروسية'
    ],
    'th': [
        '用泰语', '泰语', '泰语回复', '请用泰语', '换泰语', '说泰语',
        'ภาษาไทย', 'พูดไทย', 'เปลี่ยนเป็นไทย', 'ตอบเป็นภาษาไทย',
        'in thai', 'thai please', 'switch to thai', 'reply in thai',
        'บางาไทย', 'bahasa thai'
    ],
    'vi': [
        '用越南语', '越南语', '越南语回复', '请用越南语', '换越南语', '说越南语',
        'tiếng việt', 'nói tiếng việt', 'chuyển sang việt', 'trả lời tiếng việt',
        'in vietnamese', 'vietnamese please', 'switch to vietnamese', 'reply in vietnamese'
    ],
    'id': [
        '用印尼语', '印尼语', '印尼语回复', '请用印尼语', '换印尼语',
        'bahasa indonesia', 'pakai indonesia', 'ganti ke indonesia',
        'in indonesian', 'indonesian please', 'switch to indonesian', 'reply in indonesian'
    ],
    'ms': [
        '用马来语', '马来语', '马来语回复', '请用马来语', '换马来语',
        'bahasa melayu', 'pakai melayu', 'tukar ke melayu',
        'in malay', 'malay please', 'switch to malay', 'reply in malay'
    ],
    'tl': [
        '用菲律宾语', '菲律宾语', '菲律宾语回复', '请用菲律宾语', '换菲律宾语',
        'tagalog', 'gumamit ng tagalog', 'mag tagalog', 'bumalik sa tagalog',
        'in tagalog', 'tagalog please', 'switch to tagalog', 'reply in tagalog'
    ]
}

# 各语言模板
LANGUAGE_TEMPLATES = {
    'zh': {
        'no_orders': '{name}，暂无订单记录哦。',
        'orders_title': '{name}，您的订单：',
        'order_item': '{order_id} | {date} | ¥{total} | {status}',
        'no_products': '{name}，还没有购买记录呢。',
        'products_title': '{name}，您买过的：',
        'no_emotions': '{name}，暂无沟通记录。',
        'emotions_title': '{name}，沟通记录：',
        'recommend_has': '{name}，给您推荐：{suggestions}，看看有没有心仪的？',
        'recommend_no': '{name}，店里热销：数码配件、手机支架等，欢迎来看看~',
        'lang_confirm': '好嘞，已切换为中文~',
        'lang_current': '当前用中文服务~'
    },
    'en': {
        'no_orders': '{name}, no orders yet.',
        'orders_title': '{name}, your orders:',
        'order_item': '{order_id} | {date} | ¥{total} | {status}',
        'no_products': '{name}, no purchases yet.',
        'products_title': '{name}, what you bought:',
        'no_emotions': '{name}, no communication records.',
        'emotions_title': '{name}, history:',
        'recommend_has': '{name}, recommend: {suggestions}. Check them out!',
        'recommend_no': '{name}, hot items: phone stands, accessories~',
        'lang_confirm': 'Switched to English~',
        'lang_current': 'Using English~'
    },
    'ar': {
        'no_orders': '{name}، لا توجد طلبات.',
        'orders_title': '{name}، طلباتك:',
        'order_item': '{order_id} | {date} | ¥{total} | {status}',
        'no_products': '{name}، لا توجد مشتريات.',
        'products_title': '{name}، مشترياتك:',
        'no_emotions': '{name}، لا توجد سجلات.',
        'emotions_title': '{name}، السجلات:',
        'recommend_has': '{name}، نوصي: {suggestions}!',
        'recommend_no': '{name}، منتجاتنا الأكثر مبيعاً: إكسسوارات الهاتف~',
        'lang_confirm': 'تم~',
        'lang_current': 'بالعربية~'
    },
    'ru': {
        'no_orders': '{name}, заказов нет.',
        'orders_title': '{name}, ваши заказы:',
        'order_item': '{order_id} | {date} | ¥{total} | {status}',
        'no_products': '{name}, покупок нет.',
        'products_title': '{name}, ваши покупки:',
        'no_emotions': '{name}, записей нет.',
        'emotions_title': '{name}, история:',
        'recommend_has': '{name}, рекомендуем: {suggestions}!',
        'recommend_no': '{name}, хиты: аксессуары~',
        'lang_confirm': 'Готово~',
        'lang_current': 'По-русски~'
    },
    'th': {
        'no_orders': '{name}，ไม่มีคำสั่งซื้อ',
        'orders_title': '{name}，คำสั่งซื้อของคุณ:',
        'order_item': '{order_id} | {date} | ¥{total} | {status}',
        'no_products': '{name}，ยังไม่มีรายการสั่งซื้อ',
        'products_title': '{name}，รายการสั่งซื้อของคุณ:',
        'no_emotions': '{name}，ไม่มีประวัติการสื่อสาร',
        'emotions_title': '{name}，ประวัติการสื่อสาร:',
        'recommend_has': '{name}，แนะนำ: {suggestions}!',
        'recommend_no': '{name}，สินค้าขายดี: อุปกรณ์เสริม~',
        'lang_confirm': 'สลับเป็นภาษาไทยแล้ว~',
        'lang_current': 'กำลังใช้ภาษาไทย~'
    },
    'vi': {
        'no_orders': '{name}，không có đơn hàng',
        'orders_title': '{name}，đơn hàng của bạn:',
        'order_item': '{order_id} | {date} | ¥{total} | {status}',
        'no_products': '{name}，chưa có sản phẩm nào',
        'products_title': '{name}，sản phẩm bạn đã mua:',
        'no_emotions': '{name}，không có hồ sơ giao dịch',
        'emotions_title': '{name}，lịch sử giao dịch:',
        'recommend_has': '{name}，đề xuất: {suggestions}!',
        'recommend_no': '{name}，sản phẩm bán chạy: phụ kiện~',
        'lang_confirm': 'Đã chuyển sang tiếng Việt~',
        'lang_current': 'Đang dùng tiếng Việt~'
    },
    'id': {
        'no_orders': '{name}，tidak ada pesanan',
        'orders_title': '{name}，pesanan Anda:',
        'order_item': '{order_id} | {date} | ¥{total} | {status}',
        'no_products': '{name}，belum ada produk',
        'products_title': '{name}，produk yang Anda beli:',
        'no_emotions': '{name}，tidak ada rekam jejak',
        'emotions_title': '{name}，riwayat:',
        'recommend_has': '{name}，rekomendasi: {suggestions}!',
        'recommend_no': '{name}，produk laris: aksesoris HP~',
        'lang_confirm': 'Sudah beralih ke Bahasa Indonesia~',
        'lang_current': 'Menggunakan Bahasa Indonesia~'
    },
    'ms': {
        'no_orders': '{name}，tiada pesanan',
        'orders_title': '{name}，pesanan anda:',
        'order_item': '{order_id} | {date} | ¥{total} | {status}',
        'no_products': '{name}，belum ada produk',
        'products_title': '{name}，produk yang anda beli:',
        'no_emotions': '{name}，tiada rekod',
        'emotions_title': '{name}，rekod:',
        'recommend_has': '{name}，cadangan: {suggestions}!',
        'recommend_no': '{name}，produk laris: aksesori telefon~',
        'lang_confirm': 'Sudah tukar kepada Bahasa Melayu~',
        'lang_current': 'Menggunakan Bahasa Melayu~'
    },
    'tl': {
        'no_orders': '{name}，wala pang order',
        'orders_title': '{name}，ang iyong order:',
        'order_item': '{order_id} | {date} | ¥{total} | {status}',
        'no_products': '{name}，wala pang produk',
        'products_title': '{name}，mga produk mo:',
        'no_emotions': '{name}，wala pang record',
        'emotions_title': '{name}，historya:',
        'recommend_has': '{name}，mungkahi: {suggestions}!',
        'recommend_no': '{name}，pinakamabentang: accessories~',
        'lang_confirm': 'Lumipat na sa Tagalog~',
        'lang_current': 'Gumagamit ng Tagalog~'
    }
}

# 欢迎语（与默认语言一致，默认英语）
WELCOME_BY_LANG = {
    'zh': '嗨 {name}~ 我是你的专属客服，有事找我呀~',
    'en': 'Hey {name}! Your personal assistant here~ What can I do for you?',
    'ar': 'مرحباً {name}! مساعدك الشخصي~',
    'ru': 'Привет {name}! Ваш помощник~ Чем могу помочь?',
    'th': 'สวัสดีค่ะ {name}~ มีอะไรให้ช่วยไหมคะ?',
    'vi': 'Xin chào {name}~ Tôi là trợ lý của bạn~ Cần giúp gì không?',
    'id': 'Halo {name}~ Saya asisten Anda~ Ada yang bisa saya bantu?',
    'ms': 'Hai {name}~ Pembantu peribadi anda~ Ada yang boleh saya bantu?',
    'tl': 'Kamusta {name}~ Ako ang iyong assistant~ May maitutulong ba ako?'
}


def get_welcome_message(lang, name='Guest'):
    """按会话语言返回欢迎语（支持 zh/en/ar/ru/th/vi/id/ms/tl）"""
    if lang not in WELCOME_BY_LANG:
        lang = 'en'
    return WELCOME_BY_LANG[lang].format(name=name or 'Guest')


def detect_language(msg, current_lang='en'):
    """检测用户消息语言，支持切换语言"""
    msg_lower = msg.lower().strip()
    
    # 检查是否切换语言
    for lang_code, keywords in LANGUAGE_SWITCH_KEYWORDS.items():
        for kw in keywords:
            if kw in msg_lower:
                return lang_code, True  # 第二个参数表示需要切换语言
    
    # 检测语言（简单字符范围判断）
    # 中文
    if any('\u4e00' <= c <= '\u9fff' for c in msg):
        return 'zh', False
    # 英文（默认）
    else:
        return 'en', False


# ============== GraphRAG 查询 ==============
def query_graphrag(customer_id):
    """调用GraphRAG获取客户信息；失败时返回 None，调用方会回退到 Neo4j 直连"""
    try:
        logger.info(f"query_graphrag: 开始调用 GraphRAG API for {customer_id}")
        response = requests.post(
            GRAPHRAG_API_URL,
            json={"customer_id": customer_id},
            timeout=5   # 5秒超时，未启动时快速回退到 Neo4j
        )
        logger.info(f"query_graphrag: GraphRAG API 返回状态码 {response.status_code}")

        if response.status_code == 200:
            data = response.json()
            # GraphRAG 可能返回两种格式：
            # 1. 直接返回 {customer, orders, skus, emotions}
            # 2. 返回 {profile: {orders, products, ...}}
            if 'customer' in data:
                # 格式1: 直接返回
                return data
            elif 'profile' in data:
                # 格式2: 需要转换
                profile = data.get('profile', {})
                return {
                    'customer': {
                        'customer_id': data.get('customer_id'),
                        'name': data.get('full_name'),
                        'level': data.get('vip_level'),
                        'region': profile.get('preferences', {}).get('region'),
                        'member_since': profile.get('preferences', {}).get('member_since')
                    },
                    'orders': profile.get('orders', []),
                    'skus': profile.get('products', []),
                    'emotions': profile.get('returns', [])
                }
        else:
            logger.debug(f"GraphRAG API 返回: {response.status_code}，将使用 Neo4j 直连")
            return None
    except Exception as e:
        logger.debug(f"GraphRAG 调用异常（将使用 Neo4j 直连）: {e}")
        return None


# ============== 客户会话管理 ==============
def create_customer_session(phone):
    """创建新的客户会话"""
    with sessions_lock:
        session_id = str(uuid.uuid4())
        
        # 创建会话结构
        customer_sessions[session_id] = {
            'session_id': session_id,
            'phone': phone,
            'customer_info': None,
            'messages': [],
            'language': 'en',  # 默认英语
            'created_at': datetime.now().isoformat(),
            'last_activity': datetime.now().isoformat()
        }
        
        logger.info(f"创建新客户会话: {session_id}, 手机号: {phone}")
        return session_id


def get_or_create_session(phone):
    """获取或创建客户会话"""
    logger.info(f"get_or_create_session: 开始获取会话, phone={phone}")
    with sessions_lock:
        logger.info("get_or_create_session: 已获取锁")
        # 查找已存在的会话
        for session_id, sess in customer_sessions.items():
            if sess['phone'] == phone:
                sess['last_activity'] = datetime.now().isoformat()
                logger.info(f"get_or_create_session: 找到已有会话 {session_id}")
                return session_id, sess

        logger.info("get_or_create_session: 创建新会话")
        # 创建新会话
        session_id = create_customer_session(phone)
        logger.info(f"get_or_create_session: 新会话创建成功 {session_id}")
        return session_id, customer_sessions[session_id]


def update_session_customer_info(session_id, customer_info):
    """更新会话中的客户信息"""
    with sessions_lock:
        if session_id in customer_sessions:
            customer_sessions[session_id]['customer_info'] = customer_info
            customer_sessions[session_id]['last_activity'] = datetime.now().isoformat()


def add_message_to_session(session_id, role, content):
    """添加消息到会话"""
    with sessions_lock:
        if session_id in customer_sessions:
            customer_sessions[session_id]['messages'].append({
                'role': role,
                'content': content,
                'timestamp': datetime.now().isoformat()
            })
            customer_sessions[session_id]['last_activity'] = datetime.now().isoformat()


# ============== HTML 模板 ==============

# 首页 - 选择入口
INDEX_HTML = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>金牌客服系统 - Gold Customer Service</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            margin: 0;
            min-height: 100vh;
            padding-top: 70px;
        }
        .page-wrap {
            display: flex;
            align-items: stretch;
            justify-content: center;
            min-height: calc(100vh - 70px);
            gap: 0;
        }
        .bg-left, .bg-right {
            flex: 1;
            min-width: 0;
            background-size: cover;
            background-position: center;
            background-repeat: no-repeat;
        }
        .bg-left, .bg-right {
            background: url(/static/images/bg-silkroad.png) center/cover no-repeat;
        }
        .container-wrap {
            flex-shrink: 0;
            display: flex;
            align-items: center;
            padding: 20px 24px;
        }
        .container {
            background: white;
            border-radius: 20px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            padding: 40px;
            max-width: 500px;
            width: 100%;
            flex-shrink: 0;
        }
        h1 {
            color: #333;
            text-align: center;
            margin-bottom: 10px;
            font-size: 28px;
        }
        .subtitle {
            text-align: center;
            color: #666;
            margin-bottom: 30px;
        }
        .btn-group {
            display: flex;
            flex-direction: column;
            gap: 15px;
        }
        .btn {
            padding: 18px 30px;
            border: none;
            border-radius: 12px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s;
            text-decoration: none;
            display: block;
            text-align: center;
        }
        .btn-customer {
            background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
            color: white;
        }
        .btn-customer:hover {
            transform: translateY(-3px);
            box-shadow: 0 10px 30px rgba(245, 87, 108, 0.4);
        }
        .top-bar {
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            height: 50px;
            display: flex;
            justify-content: flex-end;
            align-items: center;
            padding: 0 20px;
            z-index: 100;
        }
        .btn-admin-corner {
            padding: 6px 14px;
            font-size: 13px;
            color: #666;
            background: rgba(255,255,255,0.9);
            border: 1px solid #ddd;
            border-radius: 8px;
            text-decoration: none;
            cursor: pointer;
            transition: all 0.2s;
        }
        .btn-admin-corner:hover {
            color: #333;
            background: #f5f5f5;
        }
        .features {
            margin-top: 30px;
            padding-top: 20px;
            border-top: 1px solid #eee;
        }
        .feature-item {
            display: flex;
            align-items: center;
            margin-bottom: 10px;
            color: #666;
            font-size: 14px;
        }
        .feature-icon {
            margin-right: 10px;
            font-size: 18px;
        }
    </style>
</head>
<body>
    <div class="top-bar">
        <a href="/admin/login" class="btn-admin-corner">管理后台</a>
    </div>
    <div class="page-wrap">
        <div class="bg-left" role="img" aria-label="共同之路 Belt and Road: A Shared Path"></div>
        <div class="container-wrap">
        <div class="container">
            <h1>🎯 金牌客服系统</h1>
            <p class="subtitle">Gold Customer Service System</p>
            
            <div class="btn-group">
            <a href="/customer" class="btn btn-customer">
                👤 客户聊天端
            </a>
        </div>
        
        <div class="status-box" id="backend-status" style="margin-top:20px;padding:12px;background:#f5f5f5;border-radius:10px;font-size:14px;color:#333;">
            <div style="margin-bottom:8px;"><strong>后端连接状态</strong></div>
            <div id="status-neo4j">Neo4j: 检测中...</div>
            <div id="status-graphrag">GraphRAG 代理(5050): 检测中...</div>
            <div class="slogan-grid" style="margin-top:16px;display:grid;grid-template-columns:1fr 1fr;gap:12px 20px;text-align:center;font-size:15px;font-weight:600;color:#333;line-height:1.6;">
                <div>和平合作</div>
                <div>开放包容</div>
                <div>互学互鉴</div>
                <div>互利互赢</div>
            </div>
        </div>
        <div class="features">
            <div class="feature-item">
                <span class="feature-icon">🔒</span>
                <span>客户信息完全隔离，保障隐私安全</span>
            </div>
            <div class="feature-item">
                <span class="feature-icon">🤖</span>
                <span>AI智能回复，提供高情绪价值服务</span>
            </div>
            <div class="feature-item">
                <span class="feature-icon">📊</span>
                <span>完整客户档案，助力精准服务</span>
            </div>
        </div>
        </div>
        </div>
        <div class="bg-right" role="img" aria-label="丝路上的新征程 The New Silk Road"></div>
    </div>
    <script>
    fetch('/api/status').then(r=>r.json()).then(function(d){
        document.getElementById('status-neo4j').textContent = 'Neo4j: ' + (d.neo4j ? '✅ 已连接' : '❌ 未连接');
        document.getElementById('status-graphrag').textContent = 'GraphRAG 代理(5050): ' + (d.graphrag ? '✅ 已连接' : '未启动（使用 Neo4j 直连，不影响功能）');
    }).catch(function(){ 
        document.getElementById('status-neo4j').textContent = 'Neo4j: 检测失败'; 
        document.getElementById('status-graphrag').textContent = 'GraphRAG 代理(5050): 检测失败'; 
    });
    </script>
</body>
</html>
"""

# 管理后台登录页面
ADMIN_LOGIN_HTML = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>管理后台登录 - Gold Customer Service</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            padding: 20px;
        }
        .login-container {
            background: white;
            border-radius: 20px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            padding: 40px;
            max-width: 400px;
            width: 100%;
        }
        h1 {
            color: #333;
            text-align: center;
            margin-bottom: 10px;
            font-size: 24px;
        }
        .subtitle {
            text-align: center;
            color: #666;
            margin-bottom: 30px;
        }
        .form-group {
            margin-bottom: 20px;
        }
        .form-group label {
            display: block;
            margin-bottom: 8px;
            color: #333;
            font-weight: 500;
        }
        .form-group input {
            width: 100%;
            padding: 12px 15px;
            border: 2px solid #ddd;
            border-radius: 10px;
            font-size: 16px;
            outline: none;
            transition: border-color 0.3s;
        }
        .form-group input:focus {
            border-color: #4facfe;
        }
        .btn-login {
            width: 100%;
            padding: 15px;
            background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
            color: white;
            border: none;
            border-radius: 12px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s;
        }
        .btn-login:hover {
            transform: translateY(-2px);
            box-shadow: 0 10px 30px rgba(79, 172, 254, 0.4);
        }
        .error-msg {
            background: #fee;
            color: #c00;
            padding: 12px;
            border-radius: 8px;
            margin-bottom: 20px;
            text-align: center;
            display: none;
        }
        .back-btn {
            display: block;
            text-align: center;
            margin-top: 20px;
            color: #666;
            text-decoration: none;
        }
    </style>
</head>
<body>
    <div class="login-container">
        <h1>⚙️ 管理后台</h1>
        <p class="subtitle">请输入密码登录</p>
        
        <div class="error-msg" id="errorMsg"></div>
        
        <form onsubmit="return login(event)">
            <div class="form-group">
                <label>管理密码</label>
                <input type="password" id="password" required>
            </div>
            <button type="submit" class="btn-login">登录</button>
        </form>
        
        <a href="/" class="back-btn">← 返回首页</a>
    </div>

    <script>
        async function login(event) {
            event.preventDefault();
            
            const password = document.getElementById('password').value;
            const errorDiv = document.getElementById('errorMsg');
            
            try {
                const response = await fetch('/api/admin/login', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({password: password})
                });
                
                const data = await response.json();
                
                if (data.success) {
                    window.location.href = '/admin/dashboard';
                } else {
                    errorDiv.textContent = data.message || '密码错误';
                    errorDiv.style.display = 'block';
                }
            } catch (error) {
                errorDiv.textContent = '系统错误，请稍后重试';
                errorDiv.style.display = 'block';
            }
            
            return false;
        }
    </script>
</body>
</html>
"""

# 管理后台主页面
ADMIN_DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>客户档案查询 - 管理后台</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
            min-height: 100vh;
            padding: 20px;
        }
        .container {
            max-width: 1200px;
            margin: 0 auto;
        }
        .header {
            background: white;
            border-radius: 20px 20px 0 0;
            padding: 20px 30px;
            box-shadow: 0 4px 20px rgba(0,0,0,0.1);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .header h1 {
            color: #333;
            font-size: 24px;
        }
        .btn-logout {
            background: #ff4757;
            color: white;
            padding: 10px 20px;
            border: none;
            border-radius: 10px;
            cursor: pointer;
            text-decoration: none;
        }
        .search-section {
            background: white;
            padding: 30px;
            box-shadow: 0 4px 20px rgba(0,0,0,0.1);
        }
        .search-group {
            display: flex;
            gap: 15px;
            max-width: 600px;
            margin: 0 auto;
        }
        .search-input {
            flex: 1;
            padding: 15px 20px;
            border: 2px solid #ddd;
            border-radius: 12px;
            font-size: 16px;
            outline: none;
        }
        .search-input:focus {
            border-color: #4facfe;
        }
        .btn-search {
            padding: 15px 30px;
            background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
            color: white;
            border: none;
            border-radius: 12px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s;
        }
        .btn-search:hover {
            transform: translateY(-2px);
            box-shadow: 0 5px 20px rgba(79, 172, 254, 0.4);
        }
        .result-section {
            background: white;
            margin-top: 20px;
            border-radius: 20px;
            box-shadow: 0 4px 20px rgba(0,0,0,0.1);
            padding: 30px;
            display: none;
        }
        .result-section.show {
            display: block;
        }
        .section-title {
            color: #333;
            font-size: 20px;
            margin-bottom: 20px;
            padding-bottom: 10px;
            border-bottom: 2px solid #4facfe;
        }
        .customer-header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 25px;
            border-radius: 15px;
            margin-bottom: 25px;
        }
        .customer-name {
            font-size: 28px;
            font-weight: 600;
            margin-bottom: 10px;
        }
        .customer-meta {
            display: flex;
            gap: 20px;
            flex-wrap: wrap;
        }
        .meta-item {
            background: rgba(255,255,255,0.2);
            padding: 8px 15px;
            border-radius: 20px;
            font-size: 14px;
        }
        .info-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 15px;
            margin-bottom: 25px;
        }
        .info-card {
            background: #f8f9fa;
            padding: 15px;
            border-radius: 10px;
            border-left: 4px solid #4facfe;
        }
        .info-label {
            color: #666;
            font-size: 12px;
            margin-bottom: 5px;
        }
        .info-value {
            color: #333;
            font-size: 16px;
            font-weight: 500;
        }
        .data-table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 15px;
        }
        .data-table th,
        .data-table td {
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #eee;
        }
        .data-table th {
            background: #f8f9fa;
            font-weight: 600;
            color: #333;
        }
        .data-table tr:hover {
            background: #f8f9fa;
        }
        .tag {
            display: inline-block;
            padding: 4px 10px;
            border-radius: 15px;
            font-size: 12px;
            margin-right: 5px;
            margin-bottom: 5px;
        }
        .tag-primary {
            background: #e3f2fd;
            color: #1976d2;
        }
        .tag-success {
            background: #e8f5e9;
            color: #388e3c;
        }
        .tag-warning {
            background: #fff3e0;
            color: #f57c00;
        }
        .tag-danger {
            background: #ffebee;
            color: #d32f2f;
        }
        .emotion-positive {
            color: #4caf50;
        }
        .emotion-neutral {
            color: #ff9800;
        }
        .emotion-negative {
            color: #f44336;
        }
        .back-btn {
            display: inline-block;
            background: white;
            color: #333;
            padding: 10px 20px;
            border-radius: 25px;
            text-decoration: none;
            box-shadow: 0 4px 15px rgba(0,0,0,0.1);
            font-weight: 500;
        }
        .loading {
            text-align: center;
            padding: 40px;
            color: #666;
        }
        .no-data {
            text-align: center;
            padding: 40px;
            color: #999;
        }
        .status-badge {
            display: inline-block;
            padding: 4px 10px;
            border-radius: 15px;
            font-size: 12px;
        }
        .status-completed {
            background: #e8f5e9;
            color: #388e3c;
        }
        .status-pending {
            background: #fff3e0;
            color: #f57c00;
        }
        .status-cancelled {
            background: #ffebee;
            color: #d32f2f;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div>
                <a href="/" class="back-btn" style="margin-right: 15px;">← 首页</a>
                <h1 style="display: inline;">📋 客户档案查询</h1>
            </div>
            <a href="/admin/logout" class="btn-logout">退出登录</a>
        </div>
        
        <div class="search-section">
            <div class="search-group">
                <input type="text" class="search-input" id="customerIdInput" 
                       placeholder="请输入客户ID">
                <button class="btn-search" onclick="searchCustomer()">查询</button>
            </div>
            <p style="text-align: center; margin-top: 15px; color: #999; font-size: 14px;">
                输入客户的唯一ID查询完整档案信息
            </p>
        </div>
        
        <div class="result-section" id="resultSection">
            <div id="resultContent"></div>
        </div>
    </div>

    <script>
        async function searchCustomer() {
            const customerId = document.getElementById('customerIdInput').value.trim();
            const resultSection = document.getElementById('resultSection');
            const resultContent = document.getElementById('resultContent');
            
            if (!customerId) {
                alert('请输入客户ID');
                return;
            }
            
            resultSection.classList.add('show');
            resultContent.innerHTML = '<div class="loading">正在查询...</div>';
            
            try {
                const response = await fetch('/api/admin/customer/' + customerId);
                const rawText = await response.text();
                let data = null;
                try {
                    data = rawText ? JSON.parse(rawText) : null;
                } catch (e) {
                    resultContent.innerHTML = '<div class="no-data">服务器返回非 JSON（' + response.status + '）。请检查后端是否报错。内容: ' + (rawText.substring(0, 300) || '空') + '</div>';
                    return;
                }
                if (!response.ok) {
                    resultContent.innerHTML = '<div class="no-data">请求失败 ' + response.status + (data && data.message ? '：' + data.message : '') + '</div>';
                    return;
                }
                if (data && data.success) {
                    renderCustomerProfile(data.data);
                } else {
                    resultContent.innerHTML = '<div class="no-data">' + (data && data.message ? data.message : '查询失败') + '</div>';
                }
            } catch (error) {
                resultContent.innerHTML = '<div class="no-data"><strong>连接失败</strong>，请稍后重试。<br><br>请确认：<br>1）后端已用 <b>启动_调试.bat</b> 或 <b>启动.vbs</b> 启动；<br>2）本页地址为 <b>http://后端所在电脑的IP:5000/admin/dashboard</b>（前端同事请用后端同事的 IP 访问，不要用 127.0.0.1）。<br><br>错误信息：' + (error.message || '网络异常') + '</div>';
                console.error(error);
            }
        }
        
        function renderCustomerProfile(profile) {
            const customer = profile.customer;
            const orders = profile.orders || [];
            const skus = profile.skus || [];
            const emotions = profile.emotions || [];
            
            let html = '';
            
            // 若仅有客户ID/等级而其他信息为空，提示数据不完整
            // 支持新字段: region, m_value (会员等级), member_since (注册时间)
            const hasBasicInfo = !!(customer.phone || customer.email || customer.region || customer.member_since);
            const hasAnyRecords = orders.length > 0 || skus.length > 0 || emotions.length > 0;
            if ((!hasBasicInfo || !hasAnyRecords) && (customer.customer_id || customer.id)) {
                html += '<div class="no-data" style="margin-bottom:1rem;padding:0.75rem;background:#fff8e6;border:1px solid #ffc107;border-radius:6px;">';
                html += '💡 当前仅能查到该客户ID，手机/邮箱/地址、订单与情绪等为空。请检查 Neo4j 中 Customer 节点是否包含完整属性，以及是否已创建订单/情绪关系；若使用 GraphRAG，请确认其返回了完整客户档案。';
                html += '</div>';
            }

            // 客户基本信息
            html += `
                <div class="customer-header">
                    <div class="customer-name">${customer.name || '未知客户'}</div>
                    <div class="customer-meta">
                        <span class="meta-item">📱 ${customer.phone || '-'}</span>
                        <span class="meta-item">⭐ ${customer.level || customer.m_value || '普通会员'}</span>
                        <span class="meta-item">🌍 ${customer.region || '-'}</span>
                    </div>
                </div>
            `;

            // 详细信息
            html += '<h3 class="section-title">基本信息</h3>';
            html += '<div class="info-grid">';
            html += createInfoCard('客户ID', customer.customer_id || customer.id);
            html += createInfoCard('手机号', customer.phone || '-');
            html += createInfoCard('地区', customer.region || '-');
            html += createInfoCard('会员等级', customer.level || customer.m_value || '普通');
            html += createInfoCard('注册时间', customer.member_since || customer.register_date || '-');
            
            if (customer.tags && customer.tags.length > 0) {
                const tagsHtml = customer.tags.map(t => `<span class="tag tag-primary">${t}</span>`).join('');
                html += `<div class="info-card"><div class="info-label">标签</div><div class="info-value">${tagsHtml}</div></div>`;
            }
            html += '</div>';
            
            // 订单信息
            html += '<h3 class="section-title">订单记录 (' + orders.length + ')</h3>';
            if (orders.length > 0) {
                html += '<table class="data-table"><thead><tr>';
                html += '<th>订单ID</th><th>日期</th><th>金额</th><th>状态</th><th>商品</th>';
                html += '</tr></thead><tbody>';
                
                orders.forEach(order => {
                    const statusClass = getStatusClass(order.status);
                    const itemsStr = Array.isArray(order.items) ? order.items.join('、') : (order.items || '-');
                    html += '<tr>';
                    html += `<td>${order.order_id || '-'}</td>`;
                    html += `<td>${order.date || '-'}</td>`;
                    html += `<td>¥${order.total || 0}</td>`;
                    html += `<td><span class="status-badge ${statusClass}">${order.status || '-'}</span></td>`;
                    html += `<td>${itemsStr.length > 80 ? itemsStr.substring(0, 80) + '...' : itemsStr}</td>`;
                    html += '</tr>';
                });
                html += '</tbody></table>';
            } else {
                html += '<div class="no-data">暂无订单记录</div>';
            }
            
            // 购买商品
            html += '<h3 class="section-title">购买商品 (' + skus.length + ')</h3>';
            if (skus.length > 0) {
                html += '<table class="data-table"><thead><tr>';
                html += '<th>商品ID</th><th>商品名称</th><th>分类</th><th>价格</th><th>数量</th>';
                html += '</tr></thead><tbody>';
                
                skus.forEach(sku => {
                    html += '<tr>';
                    html += `<td>${sku.product_id || sku.sku_id || '-'}</td>`;
                    html += `<td>${sku.name || '-'}</td>`;
                    html += `<td>${sku.category || '-'}</td>`;
                    html += `<td>¥${sku.price || 0}</td>`;
                    html += `<td>${sku.quantity || 1}</td>`;
                    html += '</tr>';
                });
                html += '</tbody></table>';
            } else {
                html += '<div class="no-data">暂无购买记录</div>';
            }
            
            // 情绪记录
            html += '<h3 class="section-title">情绪记录 (' + emotions.length + ')</h3>';
            if (emotions.length > 0) {
                html += '<table class="data-table"><thead><tr>';
                html += '<th>日期</th><th>类型</th><th>评分</th><th>来源</th><th>备注</th>';
                html += '</tr></thead><tbody>';
                
                emotions.forEach(e => {
                    const emotionClass = getEmotionClass(e.type);
                    html += '<tr>';
                    html += `<td>${e.date || '-'}</td>`;
                    html += `<td class="${emotionClass}">${e.type || '-'}</td>`;
                    html += `<td>${e.score || '-'}</td>`;
                    html += `<td>${e.source || '-'}</td>`;
                    html += `<td>${e.notes || '-'}</td>`;
                    html += '</tr>';
                });
                html += '</tbody></table>';
            } else {
                html += '<div class="no-data">暂无情绪记录</div>';
            }
            
            document.getElementById('resultContent').innerHTML = html;
        }
        
        function createInfoCard(label, value) {
            return `
                <div class="info-card">
                    <div class="info-label">${label}</div>
                    <div class="info-value">${value || '-'}</div>
                </div>
            `;
        }
        
        function getStatusClass(status) {
            if (!status) return '';
            status = status.toLowerCase();
            if (status.includes('completed') || status.includes('完成')) return 'status-completed';
            if (status.includes('pending') || status.includes('待')) return 'status-pending';
            if (status.includes('cancel') || status.includes('取消')) return 'status-cancelled';
            return '';
        }
        
        function getEmotionClass(type) {
            if (!type) return '';
            type = type.toLowerCase();
            if (type.includes('positive') || type.includes('happy') || type.includes('满意')) return 'emotion-positive';
            if (type.includes('negative') || type.includes('angry') || type.includes('不满')) return 'emotion-negative';
            return 'emotion-neutral';
        }
        
        // 回车搜索
        document.getElementById('customerIdInput').addEventListener('keypress', function(e) {
            if (e.key === 'Enter') {
                searchCustomer();
            }
        });
    </script>
</body>
</html>
"""

# ============== 路由 ==============

@app.route('/')
def index():
    """首页 - 从前端文件加载"""
    return load_html('index.html')


# ========== 客户聊天端 API ==========

@app.route('/customer')
def customer_chat():
    """客户聊天页面 - 从主页搜索后直接进入客服聊天（无图二中间页）"""
    return load_html('customer/chat.html')


@app.route('/api/customer/start', methods=['POST'])
def customer_start():
    """客户开始会话 - 通过手机号或客户ID识别（Neo4j失效时回退SQLite）"""
    try:
        logger.info("customer_start: 收到请求")
        data = request.get_json() or {}
        phone = (data.get('phone') or '').strip()
        customer_id = (data.get('customer_id') or '').strip()
        logger.info(f"customer_start: phone={phone}, customer_id={customer_id}")

        if not phone and not customer_id:
            return jsonify({'success': False, 'message': '请输入手机号或客户ID'})

        customer = None
        neo4j_conn = None
        neo4j_available = False

        # 优先尝试 Neo4j
        logger.info("customer_start: 正在连接 Neo4j...")
        try:
            neo4j_conn = Neo4jConnection(NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD)
            if neo4j_conn.connect():
                neo4j_available = True
                logger.info("customer_start: Neo4j 连接成功，查找客户")
                if phone:
                    customer = neo4j_conn.find_customer_by_phone(phone)
                    logger.info(f"customer_start: 按手机号查找结果: {customer}")
                if not customer and customer_id:
                    customer = neo4j_conn.find_customer_by_id(customer_id)
                    logger.info(f"customer_start: 按客户ID查找结果: {customer}")
        except Exception as e:
            logger.warning(f"customer_start: Neo4j 异常（将回退SQLite）: {e}")
            if neo4j_conn:
                try:
                    neo4j_conn.close()
                except Exception:
                    pass
            neo4j_conn = None

        # Neo4j 找不到或不可用 → 回退到 SQLite
        if not customer:
            logger.info("customer_start: 回退到 SQLite customers 表...")
            try:
                from db import find_customer_by_phone, get_customer, create_customer
                if phone:
                    customer = find_customer_by_phone(phone)
                if not customer and customer_id:
                    customer = get_customer(customer_id)
                # SQLite 也没有 → 自动注册
                if not customer and phone:
                    cid = f"flask_auto_{phone}"
                    create_customer(customer_id=cid, phone=phone, name=f"客户{phone[-4:]}", region="未知")
                    customer = find_customer_by_phone(phone)
                    logger.info(f"customer_start: SQLite 自动注册新客户: {cid}")
            except Exception as e:
                logger.error(f"customer_start: SQLite 回退失败: {e}")

        if not customer:
            neo4j_conn and neo4j_conn.close()
            return jsonify({
                'success': False,
                'message': '未找到您的信息，请检查手机号或客户ID是否正确'
            })

        # 使用手机号或客户ID创建会话标识（优先使用手机号）
        session_key = phone if phone else customer_id
        logger.info("customer_start: 准备创建会话...")
        session_id, session_data = get_or_create_session(session_key)
        logger.info(f"customer_start: session_id={session_id}, 继续获取档案...")

        # 获取完整客户档案
        cid = customer.get('customer_id') or customer.get('id')
        if not cid:
            neo4j_conn and neo4j_conn.close()
            return jsonify({'success': False, 'message': '客户数据异常，缺少客户ID'})
        customer['customer_id'] = cid
        logger.info(f"customer_start: 正在获取客户档案, cid={cid}, neo4j_available={neo4j_available}")

        # 尝试调用GraphRAG获取更详细信息
        graphrag_data = None
        if neo4j_available:
            try:
                logger.info("customer_start: 调用 GraphRAG...")
                graphrag_data = query_graphrag(cid)
                logger.info(f"customer_start: GraphRAG 返回: {graphrag_data is not None}")
            except Exception as e:
                logger.warning(f"customer_start: GraphRAG 调用失败: {e}")

        if graphrag_data:
            full_profile = {
                'customer': customer,
                'orders': graphrag_data.get('orders', []),
                'skus': graphrag_data.get('skus', []),
                'emotions': graphrag_data.get('emotions', [])
            }
        elif neo4j_available:
            try:
                full_profile = neo4j_conn.get_full_profile(cid)
            except Exception as e:
                logger.warning(f"customer_start: Neo4j 档案获取失败: {e}")
                full_profile = None
        else:
            full_profile = None

        # Neo4j不可用时，用SQLite简版档案兜底
        if not full_profile:
            from db import get_customer as db_get_customer
            sq_customer = db_get_customer(cid)
            full_profile = {
                'customer': sq_customer or customer,
                'orders': [],
                'skus': [],
                'emotions': []
            }
            logger.info(f"customer_start: 使用SQLite简版档案, customer={full_profile['customer']}")

        # 更新会话中的客户信息
        update_session_customer_info(session_id, full_profile)

        # 按会话语言生成欢迎消息（默认英语）
        session_lang = session_data.get('language', 'en')
        welcome_msg = get_welcome_message(session_lang, customer.get('name') or 'Guest')

        if neo4j_conn:
            try:
                neo4j_conn.close()
            except Exception:
                pass

        return jsonify({
            'success': True,
            'session_id': session_id,
            'customer_info': full_profile,
            'welcome_message': welcome_msg,
            'language': session_lang,
            'data_mode': 'neo4j_full' if neo4j_available else 'sqlite_fallback'
        })

    except Exception as e:
        logger.error(f"customer_start 请求错误: {e}")
        return jsonify({'success': False, 'message': '请求异常，请稍后重试'}), 200


@app.route('/api/customer/chat', methods=['POST'])
def customer_chat_api():
    """客户发送消息"""
    try:
        data = request.get_json()
        session_id = data.get('session_id')
        user_message = data.get('message', '').strip()
        
        if not session_id or not user_message:
            return jsonify({'success': False, 'message': '参数错误'})
        
        # 获取会话
        with sessions_lock:
            if session_id not in customer_sessions:
                return jsonify({'success': False, 'message': '会话已失效，请重新输入手机号或客户ID'})
            
            session_data = customer_sessions[session_id]
            customer_info = session_data.get('customer_info')
            current_lang = session_data.get('language', 'en')
        
        if not customer_info:
            return jsonify({'success': False, 'message': '会话已失效，请重新输入手机号或客户ID'})
        
        # 检测语言
        detected_lang, need_switch = detect_language(user_message, current_lang)
        
        # 如果需要切换语言（显式语言切换指令，如"说中文"/"English please"）
        if need_switch:
            with sessions_lock:
                customer_sessions[session_id]['language'] = detected_lang
            t = LANGUAGE_TEMPLATES[detected_lang]
            response = t['lang_confirm']
            add_message_to_session(session_id, 'user', user_message)
            add_message_to_session(session_id, 'assistant', response)
            return jsonify({
                'success': True,
                'response': response,
                'language': detected_lang
            })
        
        # 【自动语言适配】如果检测到的语言与当前会话语言不同，自动切换
        # （修复：中文消息默认英文回复的 bug）
        effective_lang = detected_lang
        if detected_lang != current_lang and not need_switch:
            effective_lang = detected_lang
            logger.info(f"[LangAutoSwitch] session={session_id} 从 {current_lang} 切换到 {detected_lang}（自动）")
            with sessions_lock:
                customer_sessions[session_id]['language'] = detected_lang
        
        # 使用检测到的语言生成回复（自动适配，不再依赖会话原始语言）
        response = generate_emotional_response(customer_info, user_message, effective_lang)
        
        # 确保 response 不为空
        if not response or not response.strip():
            logger.error("generate_emotional_response 返回空响应")
            return jsonify({
                'success': False,
                'message': '回复生成失败，请稍后重试'
            })

        # 若返回的是错误提示（以 [!] 开头），不写入会话，直接返回失败
        if response.strip().startswith("[!]"):
            return jsonify({
                'success': False,
                'message': '回复生成暂时不可用，请稍后重试'
            })

        # 添加消息到会话
        add_message_to_session(session_id, 'user', user_message)
        add_message_to_session(session_id, 'assistant', response)

        return jsonify({
            'success': True,
            'response': response,
            'language': effective_lang
        })

    except Exception as e:
        logger.error(f"聊天错误: {e}")
        return jsonify({'success': False, 'message': '系统错误，请稍后重试'})


@app.route('/api/translate', methods=['POST'])
def translate_api():
    """将文本翻译为指定语言（支持 zh/en/ar/ru/th/vi/id/ms/tl）"""
    try:
        data = request.get_json()
        text = (data.get('text') or '').strip()
        target = (data.get('target') or 'en').lower()
        # 支持的语言: en, zh, ar, ru, th, vi, id, ms, tl
        supported = {'en', 'zh', 'ar', 'ru', 'th', 'vi', 'id', 'ms', 'tl'}
        if target not in supported:
            target = 'en'
        if not text:
            return jsonify({'success': False, 'message': '缺少文本'})
        target_names = {
            'en': 'English', 'zh': 'Chinese', 'ar': 'Arabic', 'ru': 'Russian',
            'th': 'Thai', 'vi': 'Vietnamese', 'id': 'Indonesian',
            'ms': 'Malay', 'tl': 'Tagalog'
        }
        target_name = target_names.get(target, 'English')
        prompt = f"Only output the translation, no other text. Translate the following into {target_name}:\n\n{text}"
        translated = call_deepseek(prompt, system_prompt="You are a translator. Output only the translation.")
        translated = (translated or '').strip()
        # 若 DeepSeek 返回的是错误提示（以 [!] 开头），则视为翻译失败
        if translated.startswith("[!]"):
            return jsonify({'success': False, 'message': '翻译服务暂时不可用，请稍后重试'})
        return jsonify({'success': True, 'translated': translated, 'target': target})
    except Exception as e:
        logger.error(f"翻译错误: {e}")
        return jsonify({'success': False, 'message': '翻译失败'})


@app.route('/api/customer/change_language', methods=['POST'])
def customer_change_language():
    """切换 AI 回复语言（zh/en/ar/ru/th/vi/id/ms/tl）"""
    try:
        data = request.get_json() or {}
        session_id = data.get('session_id')
        language = (data.get('language') or 'zh').strip().lower()
        supported = {'zh', 'en', 'ar', 'ru', 'th', 'vi', 'id', 'ms', 'tl'}
        if language not in supported:
            return jsonify({'success': False, 'message': '不支持的语言，请使用 zh/en/ar/ru/th/vi/id/ms/tl'})
        with sessions_lock:
            if not session_id or session_id not in customer_sessions:
                return jsonify({'success': False, 'message': '会话已失效，请重新登录'})
            customer_sessions[session_id]['language'] = language
            session_data = customer_sessions[session_id]
        customer_info = session_data.get('customer_info') or {}
        customer = customer_info.get('customer') or {}
        name = customer.get('name') or customer.get('customer_id') or '您'
        welcome_message = get_welcome_message(language, name)
        return jsonify({'success': True, 'language': language, 'welcome_message': welcome_message})
    except Exception as e:
        logger.exception('change_language')
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/customer/logout', methods=['POST'])
def customer_logout():
    """客户退出"""
    try:
        data = request.get_json()
        session_id = data.get('session_id')

        if session_id:
            with sessions_lock:
                if session_id in customer_sessions:
                    del customer_sessions[session_id]

        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False})


@app.route('/api/customer/myinfo', methods=['POST'])
def customer_myinfo():
    """客户查看自己的个人信息 - 需要session_id验证（Neo4j失效时回退SQLite）"""
    try:
        data = request.get_json()
        session_id = data.get('session_id')

        if not session_id:
            return jsonify({'success': False, 'message': '未登录'})

        # 获取会话中的客户信息
        with sessions_lock:
            if session_id not in customer_sessions:
                return jsonify({'success': False, 'message': '会话已失效，请重新登录'})
            session_data = customer_sessions[session_id]
            customer_info = session_data.get('customer_info')

        if not customer_info:
            return jsonify({'success': False, 'message': '未找到客户信息'})

        # 只返回当前客户的个人信息
        customer = customer_info.get('customer', {})
        customer_id = customer.get('customer_id') or customer.get('id')

        # 优先从Neo4j获取完整档案
        profile = None
        try:
            neo4j_conn = Neo4jConnection(NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD)
            if neo4j_conn.connect():
                profile = neo4j_conn.get_full_profile(customer_id)
                neo4j_conn.close()
        except Exception as e:
            logger.warning(f"customer_myinfo: Neo4j 获取档案失败（将回退SQLite）: {e}")

        # Neo4j不可用 → 用SQLite兜底
        if not profile:
            from db import get_customer as db_get_customer
            sq_customer = db_get_customer(customer_id)
            profile = {
                'customer': sq_customer or customer,
                'orders': [],
                'skus': [],
                'emotions': []
            }
            logger.info(f"customer_myinfo: 使用SQLite简版档案")

        profile = _normalize_profile(profile)
        return jsonify({
            'success': True,
            'data': profile
        })

    except Exception as e:
        logger.error(f"customer_myinfo 错误: {e}")
        return jsonify({'success': False, 'message': '系统错误'})


# ========== 管理后台 API ==========

@app.route('/admin/login')
def admin_login_page():
    """管理后台登录页面"""
    if session.get('admin_logged_in'):
        return redirect('/admin/dashboard')
    return load_html('admin/login.html')


@app.route('/api/admin/login', methods=['POST'])
def admin_login():
    """管理后台登录"""
    try:
        data = request.get_json()
        password = data.get('password', '')
        
        if password == ADMIN_PASSWORD:
            session['admin_logged_in'] = True
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'message': '密码错误'})
    except Exception as e:
        return jsonify({'success': False, 'message': '系统错误'})


@app.route('/admin/dashboard')
def admin_dashboard():
    """管理后台主页"""
    if not session.get('admin_logged_in'):
        return redirect('/admin/login')
    return load_html('admin/dashboard.html')


@app.route('/admin/logout')
def admin_logout():
    """管理后台退出"""
    session.pop('admin_logged_in', None)
    return redirect('/')


def _normalize_profile(profile):
    """确保 profile 为 { customer, orders, skus, emotions } 结构，供前端使用"""
    if not profile:
        return None
    if isinstance(profile, dict) and 'customer' in profile and 'orders' in profile:
        return {
            'customer': profile.get('customer') or {},
            'orders': profile.get('orders') or [],
            'skus': profile.get('skus') or [],
            'emotions': profile.get('emotions') or []
        }
    # GraphRAG 可能只返回顶层 customer 字段，包装成统一格式
    if isinstance(profile, dict) and 'customer' not in profile:
        return {
            'customer': profile,
            'orders': profile.get('orders') or [],
            'skus': profile.get('skus') or [],
            'emotions': profile.get('emotions') or []
        }
    return profile


@app.route('/api/admin/customer/<customer_id>')
def admin_get_customer(customer_id):
    """管理后台查询客户（Neo4j失效时回退SQLite）"""
    if not session.get('admin_logged_in'):
        return jsonify({'success': False, 'message': '未登录'}), 200

    from db import get_customer as db_get_customer
    profile = None
    neo4j_available = False

    try:
        neo4j_conn = Neo4jConnection(NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD)
        if neo4j_conn.connect():
            neo4j_available = True
            try:
                profile = neo4j_conn.get_full_profile(customer_id)
            except Exception as e:
                logger.warning(f"Neo4j 查询错误: {e}")
            if not profile:
                try:
                    profile = query_graphrag(customer_id)
                except Exception as e:
                    logger.debug(f"GraphRAG 调用异常: {e}")
            neo4j_conn.close()
    except Exception as e:
        logger.warning(f"admin_get_customer: Neo4j 不可用（将回退SQLite）: {e}")

    # Neo4j不可用 → SQLite 简版档案
    if not profile:
        sq_customer = db_get_customer(customer_id)
        if sq_customer:
            profile = {
                'customer': sq_customer,
                'orders': [],
                'skus': [],
                'emotions': []
            }
            logger.info(f"admin_get_customer: 使用SQLite简版档案")

    if not profile:
        return jsonify({'success': False, 'message': f'未找到该客户（ID: {customer_id}）'}), 200

    profile = _normalize_profile(profile)
    return jsonify({
        'success': True,
        'data': profile,
        'data_mode': 'neo4j_full' if neo4j_available else 'sqlite_fallback'
    }), 200


# ============== 健康检查与后端状态 ==============

@app.route('/health')
def health_check():
    """健康检查"""
    return jsonify({
        'status': 'ok',
        'timestamp': datetime.now().isoformat(),
        'sessions': len(customer_sessions)
    })


@app.route('/api/status')
def api_status():
    """返回 Neo4j、GraphRAG 连接状态，供前端显示"""
    neo4j_ok = False
    graphrag_ok = False
    try:
        conn = Neo4jConnection(NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD)
        neo4j_ok = conn.connect()
        conn.close()
    except Exception as e:
        logger.debug(f"Neo4j 连接检查失败: {e}")
    try:
        r = requests.post(GRAPHRAG_API_URL, json={"customer_id": "ping"}, timeout=2)
        graphrag_ok = r.status_code == 200
    except Exception as e:
        logger.debug(f"GraphRAG 连接检查失败: {e}")
    return jsonify({
        'neo4j': neo4j_ok,
        'graphrag': graphrag_ok,
        'message': 'Neo4j 与 GraphRAG 为本系统后端，已检测连接状态'
    })


# ============== 语料库管理API ==============

@app.route('/api/corpus/stats')
def corpus_stats():
    """获取语料库统计信息"""
    if not CORPUS_ENABLED:
        return jsonify({'success': False, 'message': '语料库未启用'}), 200
    
    try:
        from ruitalk_corpus import CORPUS_LIBRARY
        
        stats = {
            'enabled': True,
            'categories': {},
            'total_responses': 0,
        }
        
        for cat_name, cat_data in CORPUS_LIBRARY.items():
            cat_count = 0
            for subcat, responses in cat_data.items():
                cat_count += len(responses)
            stats['categories'][cat_name] = {
                'subcategories': len(cat_data),
                'responses': cat_count,
            }
            stats['total_responses'] += cat_count
        
        return jsonify({'success': True, 'data': stats}), 200
    except Exception as e:
        logger.error(f"语料库统计错误: {e}")
        return jsonify({'success': False, 'message': str(e)}), 200


@app.route('/api/corpus/test', methods=['POST'])
def corpus_test():
    """测试语料库回复（用于调试）"""
    if not CORPUS_ENABLED:
        return jsonify({'success': False, 'message': '语料库未启用'}), 200
    
    try:
        data = request.get_json() or {}
        user_message = data.get('message', '')
        emotion = data.get('emotion', 'neutral')
        language = data.get('language', 'zh')
        
        if not user_message:
            return jsonify({'success': False, 'message': '消息不能为空'}), 200
        
        response = get_dynamic_response(user_message, emotion, {'hour': datetime.now().hour})
        category, subcategory, _ = detect_intent(user_message)
        
        return jsonify({
            'success': True,
            'data': {
                'user_message': user_message,
                'ai_response': response,
                'detected_emotion': emotion,
                'detected_category': category,
                'detected_subcategory': subcategory,
            }
        }), 200
    except Exception as e:
        logger.error(f"语料库测试错误: {e}")
        return jsonify({'success': False, 'message': str(e)}), 200


@app.route('/api/corpus/stress-test', methods=['POST'])
def corpus_stress_test():
    """压力测试语料库（模拟300次对话）"""
    if not CORPUS_ENABLED:
        return jsonify({'success': False, 'message': '语料库未启用'}), 200
    
    try:
        data = request.get_json() or {}
        iterations = min(data.get('iterations', 300), 1000)  # 最多1000次
        
        results = stress_test_corpus(iterations)
        
        return jsonify({
            'success': True,
            'data': {
                'iterations': iterations,
                'human_like_rate': results['human_like_rate'],
                'robot_mode_count': results['robot_mode_count'],
                'total': results['total'],
                'status': '通过' if results['robot_mode_count'] == 0 else '有改进空间',
            }
        }), 200
    except Exception as e:
        logger.error(f"语料库压力测试错误: {e}")
        return jsonify({'success': False, 'message': str(e)}), 200


@app.route('/api/corpus/random-greeting')
def corpus_random_greeting():
    """获取随机破冰语"""
    if not CORPUS_ENABLED:
        return jsonify({'success': False, 'message': '语料库未启用'}), 200
    
    try:
        is_returning = request.args.get('returning', 'false').lower() == 'true'
        greeting = get_random_icebreak(datetime.now().hour, is_returning)
        
        return jsonify({
            'success': True,
            'data': {
                'greeting': greeting,
                'hour': datetime.now().hour,
                'is_returning': is_returning,
            }
        }), 200
    except Exception as e:
        logger.error(f"随机破冰语错误: {e}")
        return jsonify({'success': False, 'message': str(e)}), 200


# ============== 主程序 ==============

if __name__ == '__main__':
    print("=" * 50)
    print(">>> 金牌客服系统 启动中...")
    print("=" * 50)
    # 明确显示当前连接的 Neo4j 地址，便于确认是否连到 Aura
    _uri_display = (NEO4J_URI or "").replace(NEO4J_PASSWORD or "", "***") if NEO4J_PASSWORD else (NEO4J_URI or "未配置")
    print(f"\n   Neo4j 当前连接: {_uri_display}")
    print(f"\n请在浏览器中打开: http://127.0.0.1:{GOLD_CS_PORT} ")
    print("\n[!] 请确保已配置以下内容:")
    print(f"   - Neo4j 密码: {'已设置' if NEO4J_PASSWORD else '未配置'}")
    print(f"   - DeepSeek API密钥: {DEEPSEEK_API_KEY if DEEPSEEK_API_KEY else '未配置'}")
    print(f"   - GraphRAG API地址: {GRAPHRAG_API_URL}")
    print(f"   - GraphRAG 服务: 将自动检测（若不可用则使用 Neo4j 直连）")
    if CORPUS_ENABLED:
        print(f"   - 瑞托管家语料库: 已启用")
    else:
        print(f"   - 瑞托管家语料库: 未启用（请检查 ruitalk_corpus.py）")
    print("\n管理后台密码:", ADMIN_PASSWORD)
    print("=" * 50)
    
    # 启动Flask应用
    app.run(host='0.0.0.0', port=GOLD_CS_PORT, debug=False, threaded=True)
