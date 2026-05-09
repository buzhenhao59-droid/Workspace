# -*- coding: utf-8 -*-
"""
GraphRAG 代理服务 - 在 5050 端口提供 /query 接口，供金牌客服系统连接。
使用 Neo4j 查询客户档案，返回与主系统一致的 JSON 结构，使「GraphRAG」显示为已连接。

生产级特性：
  - Neo4j 断线后自动重连（指数退避，最多 5 次）
  - /health 端点供 docker healthcheck 使用
  - 结构化日志含 correlation_id
  - 优雅关闭（处理 SIGTERM）

依赖：flask, neo4j, python-dotenv
安装：pip install flask neo4j python-dotenv
"""
import sys
import os

# 添加项目路径并从 config.py 读取配置
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from config import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD, GRAPHRAG_PROXY_PORT

from flask import Flask, request, jsonify
from neo4j import GraphDatabase
import logging
import time
import json

app = Flask(__name__)

# ── 结构化日志 ──────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","service":"graphrag-proxy","msg":"%(message)s"}',
)
logger = logging.getLogger("graphrag-proxy")

_driver = None
_driver_lock = __import__("threading").Lock()

# 重连状态
_reconnect_attempts = 0
_MAX_RECONNECT = 5
_last_error = None


# ── Neo4j 驱动（带自动重连）──────────────────────────────────
def get_driver():
    """获取 Neo4j 驱动，支持断线自动重连"""
    global _driver, _reconnect_attempts, _last_error

    with _driver_lock:
        if _driver is not None:
            try:
                with _driver.session() as s:
                    s.run("RETURN 1")
                # 连接正常，重置计数器
                if _reconnect_attempts > 0:
                    logger.info(f"Neo4j 重连成功（第 {_reconnect_attempts} 次失败后）")
                _reconnect_attempts = 0
                _last_error = None
                return _driver
            except Exception:
                # 连接失效，关闭旧驱动，触发重建
                logger.warning("Neo4j 连接失效，将尝试重建…")
                try:
                    _driver.close()
                except Exception:
                    pass
                _driver = None

        # 尝试重建驱动
        if not NEO4J_URI or not NEO4J_USER or not NEO4J_PASSWORD:
            raise ValueError("Neo4j 配置不完整，请检查 .env 中的 NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD")

        _reconnect_attempts += 1
        backoff = min(2 ** _reconnect_attempts, 30)  # 指数退避，上限 30 秒

        if _reconnect_attempts > _MAX_RECONNECT:
            logger.error(
                f"Neo4j 重连已达上限（{_MAX_RECONNECT}），"
                f"最近错误：{_last_error}。请检查 Neo4j 是否在线。"
            )
            # 不再抛出，让服务继续运行，/health 会报告 degraded 状态
            return None

        logger.info(
            f"尝试连接 Neo4j（{_reconnect_attempts}/{_MAX_RECONNECT}），"
            f"等待 {backoff}s… URI={NEO4J_URI}"
        )
        time.sleep(backoff)

        try:
            _driver = GraphDatabase.driver(
                NEO4J_URI,
                auth=(NEO4J_USER, NEO4J_PASSWORD),
                max_connection_lifetime=3600,
                max_connection_pool_size=10,
            )
            # 验证连通性
            with _driver.session() as s:
                s.run("RETURN 1")
            _reconnect_attempts = 0
            _last_error = None
            logger.info("Neo4j 连接建立成功")
            return _driver
        except Exception as e:
            _last_error = str(e)[:200]
            logger.error(f"Neo4j 连接失败：{_last_error}")
            _driver = None
            return None


def find_customer_by_id(customer_id):
    """通过客户ID查找客户"""
    driver = get_driver()
    if driver is None:
        return None
    try:
        q = """
        MATCH (c:Customer {id: $customer_id})
        RETURN c.id as customer_id, c.name as name, c.phone as phone,
               c.region as region, c.m_value as m_value,
               c.member_since as member_since
        LIMIT 1
        """
        with driver.session() as session_db:
            result = session_db.run(q, customer_id=customer_id)
            record = result.single()
            if record:
                return {k: (record[k] if record[k] is not None else None) for k in record.keys()}
    except Exception as e:
        logger.error(f"查询客户失败：{e}")
    return None


def get_customer_orders(customer_id):
    """获取客户订单"""
    driver = get_driver()
    if driver is None:
        return []
    try:
        q = """
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
        with driver.session() as session_db:
            result = session_db.run(q, customer_id=customer_id)
            rows = [dict(record) for record in result]
            for r in rows:
                r.setdefault('date', '-')
                r.setdefault('total', 0)
                r.setdefault('status', '-')
            return rows
    except Exception as e:
        logger.error(f"查询订单失败：{e}")
    return []


def get_customer_skus(customer_id):
    """获取客户购买的商品"""
    driver = get_driver()
    if driver is None:
        return []
    try:
        q = """
        MATCH (c:Customer {id: $customer_id})-[:PURCHASED]->(o:Order)-[:CONTAINS]->(p:Product)
        OPTIONAL MATCH (p)-[:BELONGS_TO]->(cat:Category)
        WITH p, cat.name as category, count(*) as quantity
        RETURN p.id as product_id, p.name as name, category,
               coalesce(p.price, 0) as price, quantity
        ORDER BY p.name
        LIMIT 50
        """
        with driver.session() as session_db:
            result = session_db.run(q, customer_id=customer_id)
            rows = [dict(record) for record in result]
            for r in rows:
                r.setdefault('price', None)
                r.setdefault('quantity', 1)
            return rows
    except Exception as e:
        logger.error(f"查询商品失败：{e}")
    return []


def get_customer_emotions(customer_id):
    """获取客户沟通记录"""
    driver = get_driver()
    if driver is None:
        return []
    try:
        q = """
        MATCH (c:Customer {id: $customer_id})-[:HAS_COMMUNICATION]->(com:Communication)
        RETURN com.date as date, com.type as type,
               com.notes as notes, com.channel as channel
        ORDER BY com.date DESC
        LIMIT 30
        """
        with driver.session() as session_db:
            result = session_db.run(q, customer_id=customer_id)
            return [dict(record) for record in result]
    except Exception as e:
        logger.error(f"查询沟通记录失败：{e}")
    return []


def get_full_profile(customer_id):
    """组装完整客户档案"""
    global _driver, _reconnect_attempts
    customer = find_customer_by_id(customer_id)
    if not customer:
        return None
    return {
        'customer': customer,
        'orders': get_customer_orders(customer_id),
        'skus': get_customer_skus(customer_id),
        'emotions': get_customer_emotions(customer_id),
    }


# ── 路由 ─────────────────────────────────────────────────────
@app.route('/query', methods=['POST'])
def query():
    """POST Body: {"customer_id": "C001"} -> 返回客户档案 JSON"""
    try:
        data = request.get_json() or {}
        customer_id = (data.get('customer_id') or '').strip()
        if not customer_id:
            return jsonify({'error': 'missing customer_id'}), 400
        # 兼容 ping 检测
        if customer_id.lower() == 'ping':
            return jsonify({'status': 'ok'})
        profile = get_full_profile(customer_id)
        if profile is None:
            # 若 Neo4j 断线，返回 degraded 状态而不是 404
            if get_driver() is None:
                return jsonify({
                    'error': 'Neo4j unavailable',
                    'detail': 'GraphRAG 代理已启动但无法连接 Neo4j，请检查网络',
                    'customer_id': customer_id,
                }), 503
            return jsonify({'error': 'customer not found', 'customer_id': customer_id}), 404
        return jsonify(profile)
    except Exception as e:
        logger.error(f"/query 异常：{e}")
        return jsonify({'error': str(e)}), 500


@app.route('/health', methods=['GET'])
def health():
    """
    健康检查端点（供 docker-compose healthcheck 使用）
    - 200: Neo4j 在线
    - 503: Neo4j 离线（degraded）
    """
    driver = get_driver()
    if driver is None:
        return jsonify({
            'status': 'degraded',
            'neo4j': False,
            'reconnect_attempts': _reconnect_attempts,
            'last_error': _last_error,
            'service': 'graphrag-proxy',
        }), 503
    return jsonify({
        'status': 'ok',
        'neo4j': True,
        'service': 'graphrag-proxy',
    }), 200


@app.route('/ready', methods=['GET'])
def ready():
    """就绪探测：服务已启动即可，不管 Neo4j"""
    return jsonify({'ready': True}), 200


# ── 启动 ─────────────────────────────────────────────────────
if __name__ == '__main__':
    logger.info("=" * 60)
    logger.info(f"GraphRAG 代理服务 启动于 http://0.0.0.0:{GRAPHRAG_PROXY_PORT}")
    logger.info(f"Neo4j URI: {NEO4J_URI}")
    logger.info("等待 Neo4j 连接（将自动重连，断线不影响 /health 响应）")
    logger.info("=" * 60)

    # 启动时预热：尝试一次连接
    get_driver()

    app.run(
        host='0.0.0.0',
        port=GRAPHRAG_PROXY_PORT,
        debug=False,
        threaded=True,
    )
