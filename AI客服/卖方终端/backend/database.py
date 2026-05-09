# -*- coding: utf-8 -*-
"""
Neo4j 数据库连接与管理
适配实际数据库结构
"""
import logging
from datetime import datetime
from neo4j import GraphDatabase
from neo4j.time import DateTime as Neo4jDateTime
from config import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD

logger = logging.getLogger(__name__)


def _to_json_serializable(obj):
    """
    将 Neo4j 返回的对象（包括 DateTime、Node 等）转换为 JSON 可序列化类型。
    解决 Pydantic FastAPI 序列化 neo4j.time.DateTime 报错的问题。
    """
    if obj is None:
        return None
    if isinstance(obj, Neo4jDateTime):
        return obj.iso_format()
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _to_json_serializable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_json_serializable(item) for item in obj]
    # Neo4j Node / Relationship 等
    if hasattr(obj, "_properties"):
        return _to_json_serializable(dict(obj._properties))
    return obj


class Neo4jConnection:
    def __init__(self, uri=None, user=None, password=None):
        self.uri = uri or NEO4J_URI
        self.user = user or NEO4J_USER
        self.password = password or NEO4J_PASSWORD
        self.driver = None

    def connect(self):
        """建立 Neo4j 连接（短超时，失败时快速回退SQLite）"""
        last_err = None
        for attempt in range(2):  # 最多2次，快速失败
            try:
                self.driver = GraphDatabase.driver(
                    self.uri,
                    auth=(self.user, self.password),
                    max_connection_lifetime=3600,
                    max_connection_pool_size=50,
                    connection_timeout=5  # 5秒超时，快速失败
                )
                with self.driver.session() as session:
                    session.run("RETURN 1 AS n")
                logger.info(f"Neo4j 连接成功: {self.uri}")
                return True
            except Exception as e:
                last_err = e
                logger.warning(f"Neo4j 连接第 {attempt + 1}/2 次失败: {e}")
                if attempt < 1:
                    import time
                    time.sleep(1)
        logger.warning(f"Neo4j 连接失败（已重试 2 次）: {last_err}")
        return False

    def close(self):
        """关闭连接"""
        if self.driver:
            self.driver.close()
            self.driver = None

    def verify_connectivity(self):
        """验证连接是否有效"""
        try:
            with self.driver.session() as session:
                result = session.run("RETURN 1 AS n")
                return result.single() is not None
        except Exception as e:
            logger.error(f"Neo4j 连接验证失败: {e}")
            return False

    def find_customer_by_phone(self, phone: str):
        """通过手机号查找客户，返回带 customer_id 的字典"""
        with self.driver.session() as session:
            result = session.run(
                "MATCH (c:Customer {phone: $phone}) RETURN c LIMIT 1",
                phone=phone
            )
            record = result.single()
            if record:
                c = _to_json_serializable(dict(record["c"]))
                if "customer_id" not in c and "id" in c:
                    c["customer_id"] = c["id"]
                return c
            return None

    def find_customer_by_id(self, customer_id: str):
        """通过客户ID查找客户（实际字段是 id），返回带 customer_id 的字典便于前后端统一使用"""
        with self.driver.session() as session:
            result = session.run(
                "MATCH (c:Customer {id: $customer_id}) RETURN c LIMIT 1",
                customer_id=customer_id
            )
            record = result.single()
            if record:
                c = _to_json_serializable(dict(record["c"]))
                if "customer_id" not in c and "id" in c:
                    c["customer_id"] = c["id"]
                return c
            return None

    def get_customer_orders(self, customer_id: str):
        """获取客户订单（关系是 PURCHASED）"""
        with self.driver.session() as session:
            result = session.run(
                """
                MATCH (c:Customer {id: $customer_id})-[r:PURCHASED]->(o:Order)
                RETURN o ORDER BY o.created_at DESC LIMIT 20
                """,
                customer_id=customer_id
            )
            orders = []
            for record in result:
                order = _to_json_serializable(dict(record["o"]))
                order["products"] = self._get_order_products(record["o"]["id"])
                orders.append(order)
            return orders

    def _get_order_products(self, order_id: str):
        """获取订单包含的商品"""
        with self.driver.session() as session:
            result = session.run(
                """
                MATCH (o:Order {id: $order_id})-[:CONTAINS]->(p:Product)
                RETURN p.name AS name, p.id AS product_id
                """,
                order_id=order_id
            )
            return [dict(record) for record in result]

    def get_customer_products(self, customer_id: str):
        """获取客户购买过的商品"""
        with self.driver.session() as session:
            result = session.run(
                """
                MATCH (c:Customer {id: $customer_id})-[:PURCHASED]->(o:Order)-[:CONTAINS]->(p:Product)
                RETURN p, COUNT(*) AS times ORDER BY times DESC LIMIT 10
                """,
                customer_id=customer_id
            )
            return [_to_json_serializable(dict(record["p"])) for record in result]

    def get_customer_communications(self, customer_id: str):
        """获取客户沟通记录"""
        with self.driver.session() as session:
            result = session.run(
                """
                MATCH (c:Customer {id: $customer_id})-[r:HAS_COMMUNICATION]->(com)
                RETURN com ORDER BY com.created_at DESC LIMIT 10
                """,
                customer_id=customer_id
            )
            return [_to_json_serializable(dict(record["com"])) for record in result]

    def get_full_profile(self, customer_id: str):
        """获取完整客户档案"""
        customer = self.find_customer_by_id(customer_id)
        if not customer:
            return None

        return {
            "customer": customer,
            "orders": self.get_customer_orders(customer_id),
            "products": self.get_customer_products(customer_id),
            "communications": self.get_customer_communications(customer_id)
        }

    def get_all_orders(
        self,
        status: str = None,
        platform: str = None,
        start_date: str = None,
        end_date: str = None,
        limit: int = 100,
        offset: int = 0
    ):
        """获取全部订单（支持筛选）"""
        with self.driver.session() as session:
            # 构建查询条件
            conditions = []
            params = {"limit": limit, "offset": offset}

            # 状态筛选
            if status and status != "全部":
                if status == "待付款":
                    conditions.append("o.status = 'pending_payment' OR o.status = '待付款'")
                elif status == "待发货":
                    conditions.append("o.status = 'pending_shipment' OR o.status = '待发货'")
                elif status == "已发货":
                    conditions.append("o.status = 'shipped' OR o.status = '已发货'")
                elif status == "已完成":
                    conditions.append("o.status = 'completed' OR o.status = '已完成'")

            # 站点筛选
            if platform and platform != "全部":
                conditions.append("o.platform = $platform")
                params["platform"] = platform

            # 日期筛选（兼容 created_at / order_date）
            if start_date:
                conditions.append("(o.created_at >= $start_date OR o.order_date >= $start_date)")
                params["start_date"] = start_date
            if end_date:
                conditions.append("(o.created_at <= $end_date OR o.order_date <= $end_date)")
                params["end_date"] = end_date

            where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""

            query = f"""
                MATCH (c:Customer)-[:PURCHASED]->(o:Order)
                {where_clause}
                RETURN o, c.id AS customer_id, c.name AS customer_name,
                       c.phone AS customer_phone, c.email AS customer_email
                ORDER BY coalesce(o.created_at, o.order_date) DESC
                SKIP $offset LIMIT $limit
            """

            result = session.run(query, **params)
            orders = []
            for record in result:
                o_node = record.get("o")
                if o_node is None:
                    continue
                try:
                    order = dict(o_node)
                except (TypeError, ValueError):
                    order = {}
                order["customer_id"] = record.get("customer_id")
                order["customer_name"] = record.get("customer_name")
                order["customer_phone"] = record.get("customer_phone")
                order["customer_email"] = record.get("customer_email")
                order_id = order.get("id")
                order["products"] = self._get_order_products(order_id) if order_id else []
                # 统一日期字段，供前端显示（兼容 date / order_date / created_at）
                order["display_date"] = (
                    order.get("created_at") or order.get("order_date") or order.get("date")
                )
                orders.append(order)
            return orders

    def get_orders_count(
        self,
        status: str = None,
        platform: str = None,
        start_date: str = None,
        end_date: str = None
    ):
        """获取订单总数（用于分页）"""
        with self.driver.session() as session:
            conditions = []
            params = {}

            if status and status != "全部":
                if status == "待付款":
                    conditions.append("o.status = 'pending_payment' OR o.status = '待付款'")
                elif status == "待发货":
                    conditions.append("o.status = 'pending_shipment' OR o.status = '待发货'")
                elif status == "已发货":
                    conditions.append("o.status = 'shipped' OR o.status = '已发货'")
                elif status == "已完成":
                    conditions.append("o.status = 'completed' OR o.status = '已完成'")

            if platform and platform != "全部":
                conditions.append("o.platform = $platform")
                params["platform"] = platform

            if start_date:
                conditions.append("(o.created_at >= $start_date OR o.order_date >= $start_date)")
                params["start_date"] = start_date
            if end_date:
                conditions.append("(o.created_at <= $end_date OR o.order_date <= $end_date)")
                params["end_date"] = end_date

            where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""

            query = f"MATCH (c:Customer)-[:PURCHASED]->(o:Order){where_clause} RETURN count(o) as total"
            result = session.run(query, **params)
            single = result.single()
            return single["total"] if single is not None else 0
