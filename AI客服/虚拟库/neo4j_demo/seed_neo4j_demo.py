# -*- coding: utf-8 -*-
"""
向演示 Neo4j 写入与 seller 假数据同主题的 Customer / Order / Product 图，
供「全部订单」等接口通过 Neo4jConnection.get_all_orders 读取。

用法（先 docker compose up -d）:
  pip install neo4j
  set NEO4J_URI=bolt://127.0.0.1:7687
  set NEO4J_USER=neo4j
  set NEO4J_PASSWORD=ruitalk_demo_2026
  python seed_neo4j_demo.py
"""
import os
import sys

CYPHERS = """
MERGE (c1:Customer {id: 'CUST_TT_SWIM_001'})
SET c1.name = 'Sophia Lee', c1.phone = '+8613800100101', c1.email = 'sophia@swim.demo';

MERGE (c2:Customer {id: 'CUST_SHP_SWIM_002'})
SET c2.name = 'Maria Garcia', c2.phone = '+5521987654321', c2.email = 'maria@swim.demo';

MERGE (o1:Order {id: 'TT-DEMO-ORDER-0001'})
SET o1.status = 'pending_payment', o1.platform = 'tiktok', o1.total = 89.9,
    o1.amount = 89.9, o1.created_at = '2026-03-15T10:30:00', o1.order_date = '2026-03-15';

MERGE (o2:Order {id: 'TT-DEMO-ORDER-0002'})
SET o2.status = 'pending_shipment', o2.platform = 'tiktok', o2.total = 156.0,
    o2.amount = 156.0, o2.created_at = '2026-03-18T14:00:00', o2.order_date = '2026-03-18';

MERGE (o3:Order {id: 'SHP-DEMO-ORDER-0003'})
SET o3.status = 'shipped', o3.platform = 'shopee', o3.total = 42.5,
    o3.amount = 42.5, o3.created_at = '2026-03-10T09:00:00', o3.order_date = '2026-03-10';

MERGE (o4:Order {id: 'LAZ-DEMO-ORDER-0004'})
SET o4.status = 'completed', o4.platform = 'lazada', o4.total = 210.0,
    o4.amount = 210.0, o4.created_at = '2026-02-28T16:20:00', o4.order_date = '2026-02-28';

MERGE (p1:Product {id: 'SKU-BIKINI-BLK-S'})
SET p1.name = '黑色比基尼套装 S';

MERGE (p2:Product {id: 'SKU-ONEPIECE-NAVY-M'})
SET p2.name = '连体泳衣 深蓝 M';

MERGE (p3:Product {id: 'SKU-KIDS-130'})
SET p3.name = '儿童连体泳装 130';

MERGE (c1)-[:PURCHASED]->(o1);
MERGE (c1)-[:PURCHASED]->(o2);
MERGE (c2)-[:PURCHASED]->(o3);
MERGE (c2)-[:PURCHASED]->(o4);

MERGE (o1)-[:CONTAINS]->(p1);
MERGE (o2)-[:CONTAINS]->(p2);
MERGE (o3)-[:CONTAINS]->(p1);
MERGE (o4)-[:CONTAINS]->(p3);
"""


def main():
    uri = os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "ruitalk_demo_2026")
    try:
        from neo4j import GraphDatabase
    except ImportError:
        print("请先安装: pip install neo4j", file=sys.stderr)
        sys.exit(1)

    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        with driver.session() as session:
            for stmt in CYPHERS.split(";"):
                q = stmt.strip()
                if not q:
                    continue
                session.run(q)
        print("OK: 已写入演示节点 Customer/Order/Product 及 PURCHASED、CONTAINS 关系。")
    finally:
        driver.close()


if __name__ == "__main__":
    main()
