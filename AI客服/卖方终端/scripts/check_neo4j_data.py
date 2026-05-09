# -*- coding: utf-8 -*-
"""检查 Neo4j 中的数据结构和关系"""
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# 从 config.py 读取配置
try:
    from config import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD
except ImportError:
    NEO4J_URI = "bolt://localhost:7687"
    NEO4J_USER = "neo4j"
    NEO4J_PASSWORD = "ZEhua?041015"

from neo4j import GraphDatabase

driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
session = driver.session()

# 1. 查看所有 Customer 的字段
print("=" * 50)
print("【Customer 节点字段】")
print("=" * 50)
result = session.run("MATCH (c:Customer) RETURN c")
for record in result:
    print(dict(record['c']))

# 2. 查看关系类型
print("\n" + "=" * 50)
print("【关系类型】")
print("=" * 50)
result = session.run("MATCH (a)-[r]->(b) RETURN type(r) as rel_type, labels(a) as from_node, labels(b) as to_node")
rels = set()
for record in result:
    rels.add(f"{record['from_node']} -> {record['rel_type']} -> {record['to_node']}")
for r in sorted(rels):
    print(r)

# 3. 查看 Customer C001 的关系
print("\n" + "=" * 50)
print("【C001 的关系】")
print("=" * 50)
result = session.run('MATCH (c:Customer {id: "C001"})-[r]->(n) RETURN type(r) as rel, labels(n) as target, n')
for record in result:
    print(f"  {record['rel_type']} -> {record['target']}: {dict(record['n'])}")

# 4. 查看 Order 字段
print("\n" + "=" * 50)
print("【Order 节点字段】")
print("=" * 50)
result = session.run("MATCH (o:Order) RETURN o")
for record in result:
    print(dict(record['o']))

session.close()
driver.close()
