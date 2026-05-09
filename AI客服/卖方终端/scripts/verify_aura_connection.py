# -*- coding: utf-8 -*-
"""快速验证 Neo4j Aura 连接并检查是否有客户数据"""
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from config import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD
from neo4j import GraphDatabase

def main():
    print("正在连接 Neo4j...")
    print(f"  URI: {NEO4J_URI}")
    try:
        driver = GraphDatabase.driver(
            NEO4J_URI,
            auth=(NEO4J_USER, NEO4J_PASSWORD),
            connection_timeout=10
        )
        with driver.session() as session:
            session.run("RETURN 1").single()
        print("✅ 连接成功！\n")

        with driver.session() as session:
            r = session.run("MATCH (c:Customer) RETURN count(c) AS n").single()
            count = r["n"] if r else 0
        if count == 0:
            print("⚠️  当前数据库中没有 Customer 节点，所以查询 C005 会显示「未找到该客户」。")
            print("\n请先导入测试数据，任选一种方式：")
            print("  方式1：在 Neo4j Aura 控制台打开 Browser，执行项目里的 导入完整测试数据.cypher")
            print("  方式2：在本机执行：")
            print("    python import_data.py --customers 示例_客户.csv --orders 示例_订单.csv --products 示例_产品.csv --links 示例_订单产品关联.csv --verify")
        else:
            print(f"✅ 当前有 {count} 个客户节点。")
            with driver.session() as session:
                r = session.run("MATCH (c:Customer {id: 'C005'}) RETURN c").single()
            if r:
                print("✅ C005 存在:", dict(r["c"]))
            else:
                print("⚠️  C005 不存在，请确认是否导入了包含 C005 的数据。")
        driver.close()
    except Exception as e:
        print("❌ 连接失败:", e)
        print("\n请检查 .env 中的 NEO4J_URI、NEO4J_USER、NEO4J_PASSWORD 是否正确。")
        sys.exit(1)

if __name__ == "__main__":
    main()
