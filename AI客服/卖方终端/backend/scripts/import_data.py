# -*- coding: utf-8 -*-
"""
数据导入脚本 - 将客户数据导入到 Neo4j 图数据库
用法（在 backend 目录或项目根目录执行，CSV 路径请换成你的实际文件）:
    python scripts/import_data.py --customers <客户.csv> --orders <订单.csv> --products <产品.csv>
或只导入客户:
    python scripts/import_data.py --customers <客户.csv>
"""
import sys
import os
import argparse
import csv

# 添加 backend 路径以便导入 config（脚本位于 backend/scripts/）
_backend = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _backend not in sys.path:
    sys.path.insert(0, _backend)

from config import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD
from neo4j import GraphDatabase

# =============================================
# 可配置的字段映射（根据你的CSV表头修改）
# =============================================
# 把客户的CSV表头映射到标准字段
CUSTOMER_MAPPING = {
    '客户ID': 'id',
    '客户编号': 'id',
    'id': 'id',
    '手机号': 'phone',
    '电话': 'phone',
    'phone': 'phone',
    '客户名': 'name',
    '姓名': 'name',
    'name': 'name',
    '姓名': 'name',
}

ORDER_MAPPING = {
    '订单ID': 'id',
    '订单编号': 'id',
    'id': 'id',
    '客户ID': 'customer_id',
    '客户编号': 'customer_id',
    'customer_id': 'customer_id',
    '订单日期': 'order_date',
    '日期': 'order_date',
    '金额': 'amount',
    'total_amount': 'amount',
}

PRODUCT_MAPPING = {
    '产品ID': 'id',
    '产品编号': 'id',
    'id': 'id',
    '产品名': 'name',
    '产品名称': 'name',
    'name': 'name',
    '类别': 'category',
    '分类': 'category',
    'category': 'category',
    '价格': 'price',
}

# 标准图谱结构
SCHEMA = """
节点类型:
  - Customer: 客户 (必填字段: id, phone, name)
  - Order: 订单 (必填字段: id, customer_id)
  - Product: 产品 (必填字段: id, name, category)
  - Category: 类别 (必填字段: name)
  - Communication: 沟通记录 (必填字段: customer_id, content)

关系类型:
  - [:PURCHASED]: 客户 --[购买]--> 订单
  - [:CONTAINS]: 订单 --[包含]--> 产品
  - [:BELONGS_TO]: 产品 --[属于]--> 类别
  - [:HAS_COMMUNICATION]: 客户 --[有沟通]--> 沟通记录
"""


class DataImporter:
    def __init__(self, uri, user, password):
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        print(f"✅ 连接到 Neo4j: {uri}")
    
    def close(self):
        self.driver.close()
    
    def clear_all(self):
        """清空所有数据（危险操作！）"""
        confirm = input("⚠️  确定要清空所有数据吗？这不可恢复！(yes/no): ")
        if confirm.lower() != 'yes':
            print("❌ 已取消")
            return
        
        with self.driver.session() as session:
            session.run("MATCH (n) DETACH DELETE n")
        print("✅ 已清空所有数据")
    
    def import_customers(self, csv_file, mapping=None):
        """导入客户数据"""
        mapping = mapping or CUSTOMER_MAPPING
        
        if not os.path.exists(csv_file):
            print(f"❌ 文件不存在: {csv_file}")
            return 0
        
        with open(csv_file, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        
        if not rows:
            print("❌ CSV 文件为空")
            return 0
        
        # 检测表头映射
        sample = rows[0]
        field_map = {}
        for csv_header, standard_field in mapping.items():
            if csv_header in sample:
                field_map[csv_header] = standard_field
        
        print(f"📋 检测到字段映射: {field_map}")
        
        # 导入客户
        with self.driver.session() as session:
            count = 0
            for row in rows:
                # 提取标准字段
                customer_data = {}
                for csv_header, standard_field in field_map.items():
                    val = row.get(csv_header, '').strip()
                    if val:
                        customer_data[standard_field] = val
                
                if not customer_data.get('id'):
                    # 如果没有id，用phone生成一个
                    customer_data['id'] = f"CUSTOMER_{customer_data.get('phone', count)}"
                
                if customer_data.get('phone') or customer_data.get('name'):
                    session.run("""
                        MERGE (c:Customer {id: $id})
                        SET c.phone = $phone, c.name = $name
                    """, 
                        id=customer_data.get('id'),
                        phone=customer_data.get('phone', ''),
                        name=customer_data.get('name', '')
                    )
                    count += 1
        
        print(f"✅ 成功导入 {count} 个客户")
        return count
    
    def import_orders(self, csv_file, mapping=None):
        """导入订单数据"""
        mapping = mapping or ORDER_MAPPING
        
        if not os.path.exists(csv_file):
            print(f"❌ 文件不存在: {csv_file}")
            return 0
        
        with open(csv_file, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        
        if not rows:
            print("❌ CSV 文件为空")
            return 0
        
        sample = rows[0]
        field_map = {}
        for csv_header, standard_field in mapping.items():
            if csv_header in sample:
                field_map[csv_header] = standard_field
        
        print(f"📋 检测到字段映射: {field_map}")
        
        with self.driver.session() as session:
            count = 0
            for row in rows:
                order_data = {}
                for csv_header, standard_field in field_map.items():
                    val = row.get(csv_header, '').strip()
                    if val:
                        order_data[standard_field] = val
                
                if not order_data.get('id'):
                    continue
                
                # 创建订单并建立关系
                session.run("""
                    MATCH (c:Customer {id: $customer_id})
                    MERGE (o:Order {id: $id})
                    SET o.order_date = $order_date, o.amount = $amount
                    MERGE (c)-[:PURCHASED]->(o)
                """,
                    id=order_data.get('id'),
                    customer_id=order_data.get('customer_id'),
                    order_date=order_data.get('order_date', ''),
                    amount=order_data.get('amount', '0')
                )
                count += 1
        
        print(f"✅ 成功导入 {count} 个订单")
        return count
    
    def import_products(self, csv_file, mapping=None):
        """导入产品数据"""
        mapping = mapping or PRODUCT_MAPPING
        
        if not os.path.exists(csv_file):
            print(f"❌ 文件不存在: {csv_file}")
            return 0
        
        with open(csv_file, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        
        if not rows:
            print("❌ CSV 文件为空")
            return 0
        
        sample = rows[0]
        field_map = {}
        for csv_header, standard_field in mapping.items():
            if csv_header in sample:
                field_map[csv_header] = standard_field
        
        print(f"📋 检测到字段映射: {field_map}")
        
        with self.driver.session() as session:
            count = 0
            for row in rows:
                product_data = {}
                for csv_header, standard_field in field_map.items():
                    val = row.get(csv_header, '').strip()
                    if val:
                        product_data[standard_field] = val
                
                if not product_data.get('id'):
                    continue
                
                # 创建产品和类别
                category = product_data.get('category', '未分类')
                session.run("""
                    MERGE (p:Product {id: $id})
                    SET p.name = $name, p.price = $price
                    MERGE (cat:Category {name: $category})
                    MERGE (p)-[:BELONGS_TO]->(cat)
                """,
                    id=product_data.get('id'),
                    name=product_data.get('name', ''),
                    price=product_data.get('price', ''),
                    category=category
                )
                count += 1
        
        print(f"✅ 成功导入 {count} 个产品")
        return count
    
    def link_orders_to_products(self, order_product_csv):
        """导入订单-产品关联（一个订单包含多个产品）"""
        if not os.path.exists(order_product_csv):
            print(f"⚠️  关联文件不存在: {order_product_csv}")
            return 0
        
        with open(order_product_csv, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        
        if not rows:
            return 0
        
        # 检测字段
        sample = rows[0]
        order_col = None
        product_col = None
        for col in ['订单ID', 'order_id', '订单编号', 'id']:
            if col in sample:
                order_col = col
                break
        for col in ['产品ID', 'product_id', '产品编号', '产品id']:
            if col in sample:
                product_col = col
                break
        
        if not order_col or not product_col:
            print("❌ 无法识别订单ID或产品ID列")
            return 0
        
        with self.driver.session() as session:
            count = 0
            for row in rows:
                order_id = row.get(order_col, '').strip()
                product_id = row.get(product_col, '').strip()
                
                if order_id and product_id:
                    session.run("""
                        MATCH (o:Order {id: $order_id})
                        MATCH (p:Product {id: $product_id})
                        MERGE (o)-[:CONTAINS]->(p)
                    """, order_id=order_id, product_id=product_id)
                    count += 1
        
        print(f"✅ 成功建立 {count} 个订单-产品关联")
        return count
    
    def show_schema(self):
        """显示标准数据结构"""
        print(SCHEMA)
    
    def verify_import(self):
        """验证导入结果"""
        with self.driver.session() as session:
            print("\n📊 导入统计:")
            
            result = session.run("MATCH (c:Customer) RETURN count(c) as count")
            count = result.single()['count']
            print(f"   客户 (Customer): {count}")
            
            result = session.run("MATCH (o:Order) RETURN count(o) as count")
            count = result.single()['count']
            print(f"   订单 (Order): {count}")
            
            result = session.run("MATCH (p:Product) RETURN count(p) as count")
            count = result.single()['count']
            print(f"   产品 (Product): {count}")
            
            result = session.run("MATCH (c:Category) RETURN count(c) as count")
            count = result.single()['count']
            print(f"   类别 (Category): {count}")
            
            result = session.run("MATCH ()-[r:PURCHASED]->() RETURN count(r) as count")
            count = result.single()['count']
            print(f"   购买关系: {count}")
            
            result = session.run("MATCH ()-[r:CONTAINS]->() RETURN count(r) as count")
            count = result.single()['count']
            print(f"   包含关系: {count}")


def main():
    parser = argparse.ArgumentParser(description='数据导入工具')
    parser.add_argument('--customers', '-c', help='客户数据 CSV 文件')
    parser.add_argument('--orders', '-o', help='订单数据 CSV 文件')
    parser.add_argument('--products', '-p', help='产品数据 CSV 文件')
    parser.add_argument('--links', '-l', help='订单-产品关联 CSV 文件')
    parser.add_argument('--clear', action='store_true', help='导入前清空所有数据')
    parser.add_argument('--verify', '-v', action='store_true', help='导入后验证结果')
    parser.add_argument('--schema', '-s', action='store_true', help='显示标准数据结构')
    
    args = parser.parse_args()
    
    if args.schema:
        importer = DataImporter(NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD)
        importer.show_schema()
        importer.close()
        return
    
    if not any([args.customers, args.orders, args.products]):
        print("❌ 请指定至少一个数据文件")
        print("\n用法示例:")
        print("  python import_data.py --customers 客户.csv")
        print("  python import_data.py --customers 客户.csv --orders 订单.csv --products 产品.csv")
        print("  python import_data.py --schema  # 查看标准数据结构")
        print("\n详细帮助: python import_data.py -h")
        return
    
    # 创建导入器
    importer = DataImporter(NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD)
    
    # 清空数据
    if args.clear:
        importer.clear_all()
    
    # 导入数据
    if args.customers:
        importer.import_customers(args.customers)
    
    if args.orders:
        importer.import_orders(args.orders)
    
    if args.products:
        importer.import_products(args.products)
    
    if args.links:
        importer.link_orders_to_products(args.links)
    
    # 验证
    if args.verify:
        importer.verify_import()
    
    importer.close()
    print("\n🎉 导入完成!")


if __name__ == "__main__":
    main()
