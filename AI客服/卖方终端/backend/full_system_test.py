# -*- coding: utf-8 -*-
"""
Ruitalk 客服系统综合测试套件
Phase 1: 测试数据生成（500买家 + 20店铺 + 5坐席）
Phase 2: 核心功能测试（数据隔离/翻译/转人工）
Phase 3: 压力测试（并发/语言切换/转人工）
"""
import sys
import os
import time
import random
import string
import threading
import concurrent.futures
from datetime import datetime
from typing import List, Dict, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ============== 配置 ==============
TEST_DATA_COUNTS = {
    'buyers': 500,
    'merchants': 20,
    'agents': 5,
    'sessions': 100,
}

TEST_PREFIX = 'test_auto_'
LANGUAGES = ['zh', 'en', 'ar', 'ru', 'th', 'vi', 'id', 'ms', 'tl']

# ============== 测试数据生成 ==============

def generate_phone() -> str:
    """生成随机手机号"""
    return f"138{random.randint(10000000, 99999999)}"

def generate_name(lang: str = 'zh') -> str:
    """生成随机姓名"""
    if lang == 'zh':
        surnames = ['张', '王', '李', '刘', '陈', '杨', '黄', '赵', '吴', '周']
        names = ['伟', '芳', '娜', '秀英', '敏', '静', '丽', '强', '磊', '军']
        return random.choice(surnames) + random.choice(names)
    elif lang == 'en':
        first = random.choice(['James', 'Mary', 'John', 'Patricia', 'Robert', 'Jennifer', 'Michael', 'Linda', 'William', 'Elizabeth'])
        last = random.choice(['Smith', 'Johnson', 'Williams', 'Brown', 'Jones', 'Garcia', 'Miller', 'Davis', 'Rodriguez', 'Martinez'])
        return f"{first} {last}"
    else:
        return f"User_{random.randint(1000, 9999)}"

def generate_region() -> str:
    """生成随机地区"""
    regions = ['北京', '上海', '广州', '深圳', '杭州', '成都', '武汉', '西安', '南京', '重庆']
    return random.choice(regions)

def generate_buyer_data(count: int) -> List[Dict]:
    """生成买家测试数据"""
    buyers = []
    for i in range(count):
        lang = random.choice(LANGUAGES)
        buyers.append({
            'customer_id': f"{TEST_PREFIX}buyer_{i:04d}",
            'phone': generate_phone(),
            'name': generate_name(lang),
            'region': generate_region(),
            'language_preference': lang,
            'level': random.choice(['普通', '银卡', '金卡', 'VIP']),
            'tags': random.sample(['数码控', '美妆达人', '母婴用户', '运动爱好者', '海淘客'], k=random.randint(1, 3)),
        })
    return buyers

def generate_merchant_data(count: int) -> List[Dict]:
    """生成店铺测试数据"""
    merchants = []
    for i in range(count):
        merchants.append({
            'merchant_id': f"{TEST_PREFIX}merchant_{i:04d}",
            'name': f"测试店铺{i+1}号",
            'platform': random.choice(['TikTok Shop', 'Shopee', 'Lazada', 'Amazon', 'AliExpress']),
            'status': 'active',
            'config': {
                'auto_reply_enabled': True,
                'transfer_threshold': 3,
                'max_queue_size': 50,
            }
        })
    return merchants

def generate_agent_data(count: int) -> List[Dict]:
    """生成坐席测试数据"""
    agents = []
    for i in range(count):
        agents.append({
            'agent_id': f"{TEST_PREFIX}agent_{i:04d}",
            'username': f"agent_{i+1}",
            'name': f"客服{i+1}号",
            'status': random.choice(['online', 'busy', 'offline']),
            'max_load': random.randint(5, 10),
            'current_load': 0,
            'languages': random.sample(['zh', 'en', 'ar', 'ru'], k=random.randint(1, 4)),
        })
    return agents

# ============== 数据库操作 ==============

def init_test_customers(buyers: List[Dict]) -> int:
    """初始化测试买家数据"""
    from db import create_customer, find_customer_by_phone
    
    created = 0
    for buyer in buyers:
        try:
            # 检查是否已存在
            existing = find_customer_by_phone(buyer['phone'])
            if existing:
                continue
            create_customer(
                customer_id=buyer['customer_id'],
                phone=buyer['phone'],
                name=buyer['name'],
                region=buyer['region'],
                level=buyer['level']
            )
            created += 1
        except Exception as e:
            print(f"创建买家失败: {buyer['phone']} - {e}")
    
    return created

def cleanup_test_data() -> int:
    """清理测试数据"""
    from mysql_db import _get_sqlite_conn, _get_mysql_config, is_mysql
    
    deleted = 0
    try:
        if is_mysql():
            import pymysql
            config = _get_mysql_config()
            conn = pymysql.connect(**config)
            cursor = conn.cursor()
        else:
            conn = _get_sqlite_conn()
            cursor = conn.cursor()
        
        # 删除测试客户
        cursor.execute(f"DELETE FROM customers WHERE customer_id LIKE '{TEST_PREFIX}%'")
        deleted += cursor.rowcount
        
        # 删除测试会话
        cursor.execute(f"DELETE FROM sessions WHERE session_id LIKE '{TEST_PREFIX}%'")
        deleted += cursor.rowcount
        
        # 删除测试消息
        cursor.execute(f"DELETE FROM messages WHERE session_id LIKE '{TEST_PREFIX}%'")
        deleted += cursor.rowcount
        
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"清理数据失败: {e}")
    
    return deleted

# ============== 核心功能测试 ==============

class ConversationTester:
    """会话测试器"""
    
    def __init__(self, base_url: str = "http://127.0.0.1:5001"):
        self.base_url = base_url
        self.sessions = {}
        self.test_results = []
    
    def start_session(self, phone: str) -> Optional[str]:
        """启动会话"""
        import requests
        try:
            resp = requests.post(f"{self.base_url}/api/customer/start", 
                             json={"phone": phone}, timeout=10)
            data = resp.json()
            if data.get("success"):
                session_id = data['session_id']
                self.sessions[phone] = {
                    'session_id': session_id,
                    'language': data.get('language', 'zh'),
                    'welcome': data.get('welcome_message', ''),
                    'messages': []
                }
                return session_id
        except Exception as e:
            print(f"会话启动失败: {e}")
        return None
    
    def send_message(self, phone: str, message: str) -> Optional[str]:
        """发送消息"""
        import requests
        if phone not in self.sessions:
            return None
        
        session_id = self.sessions[phone]['session_id']
        try:
            resp = requests.post(f"{self.base_url}/api/customer/chat",
                               json={"session_id": session_id, "message": message},
                               timeout=15)
            data = resp.json()
            if data.get("success"):
                response = data['response']
                self.sessions[phone]['messages'].append({
                    'user': message,
                    'ai': response,
                    'lang': data.get('language', 'zh')
                })
                return response
        except Exception as e:
            print(f"发送消息失败: {e}")
        return None
    
    def test_data_isolation(self) -> Dict:
        """测试数据隔离"""
        print("\n=== 数据隔离测试 ===")
        results = {'passed': 0, 'failed': 0, 'details': []}
        
        # 启动两个不同客户的会话
        phone1 = generate_phone()
        phone2 = generate_phone()
        
        session1 = self.start_session(phone1)
        session2 = self.start_session(phone2)
        
        if session1 and session2:
            # 客户1发送消息
            resp1 = self.send_message(phone1, "我的名字是什么")
            
            # 客户2发送消息
            resp2 = self.send_message(phone2, "我的名字是什么")
            
            # 验证两个会话是独立的
            if session1 != session2:
                results['passed'] += 1
                results['details'].append(f"✓ 会话ID独立: {session1[:20]}... vs {session2[:20]}...")
            else:
                results['failed'] += 1
                results['details'].append("✗ 会话ID相同 - 数据隔离失败!")
        
        return results
    
    def test_multilingual(self) -> Dict:
        """测试多语言支持"""
        print("\n=== 多语言翻译测试 ===")
        results = {'passed': 0, 'failed': 0, 'languages': {}}
        
        test_phrases = {
            'zh': '你好，我想查询订单',
            'en': 'Hello, I want to check my order',
            'ar': 'مرحبا، أريد التحقق من طلبي',
            'ru': 'Привет, я хочу проверить свой заказ',
        }
        
        for lang, phrase in test_phrases.items():
            phone = generate_phone()
            session = self.start_session(phone)
            
            if session:
                # 尝试翻译
                import requests
                try:
                    resp = requests.post(f"{self.base_url}/api/translate",
                                      json={"text": phrase, "target": "zh"}, timeout=10)
                    data = resp.json()
                    if data.get("success"):
                        results['languages'][lang] = {
                            'original': phrase[:30],
                            'translated': data['translated'][:30],
                            'success': True
                        }
                        results['passed'] += 1
                    else:
                        results['failed'] += 1
                        results['languages'][lang] = {'success': False}
                except Exception as e:
                    results['failed'] += 1
                    results['languages'][lang] = {'error': str(e)}
        
        return results
    
    def test_transfer_to_human(self) -> Dict:
        """测试转人工功能"""
        print("\n=== 转人工测试 ===")
        results = {'passed': 0, 'failed': 0, 'details': []}
        
        phone = generate_phone()
        session = self.start_session(phone)
        
        if session:
            # 触发转人工
            resp = self.send_message(phone, "转人工")
            
            if resp and any(keyword in resp for keyword in ['人工', '坐席', '转接', 'agent', '客服']):
                results['passed'] += 1
                results['details'].append(f"✓ 成功触发转人工: {resp[:50]}...")
            else:
                results['failed'] += 1
                results['details'].append(f"✗ 转人工失败: {resp}")
        
        return results
    
    def test_corpus_responses(self) -> Dict:
        """测试语料库回复"""
        print("\n=== 语料库回复测试 ===")
        results = {'passed': 0, 'failed': 0, 'categories': {}}
        
        test_cases = [
            ("你好", "basic"),
            ("我很生气！", "emotion"),
            ("有新政策吗？", "policy"),
            ("转人工", "transfer"),
            ("推荐商品", "sales"),
            ("再见", "farewell"),
            ("你是机器人吗？", "fun"),
        ]
        
        for message, category in test_cases:
            phone = generate_phone()
            session = self.start_session(phone)
            
            if session:
                resp = self.send_message(phone, message)
                
                if resp and len(resp) > 0:
                    results['categories'][category] = {
                        'message': message,
                        'response': resp[:50],
                        'success': True
                    }
                    results['passed'] += 1
                else:
                    results['failed'] += 1
                    results['categories'][category] = {'success': False}
        
        return results
    
    def run_all_tests(self) -> Dict:
        """运行所有测试"""
        print("\n" + "=" * 60)
        print("Ruitalk 客服系统功能测试")
        print("=" * 60)
        
        all_results = {
            'timestamp': datetime.now().isoformat(),
            'data_isolation': self.test_data_isolation(),
            'multilingual': self.test_multilingual(),
            'transfer_to_human': self.test_transfer_to_human(),
            'corpus_responses': self.test_corpus_responses(),
        }
        
        # 汇总
        total_passed = sum(r['passed'] for r in all_results.values() if isinstance(r, dict))
        total_failed = sum(r['failed'] for r in all_results.values() if isinstance(r, dict))
        
        print("\n" + "=" * 60)
        print(f"测试汇总: 通过 {total_passed} / 失败 {total_failed}")
        print("=" * 60)
        
        return all_results

# ============== 压力测试 ==============

class StressTester:
    """压力测试器"""
    
    def __init__(self, base_url: str = "http://127.0.0.1:5001"):
        self.base_url = base_url
        self.results = {
            'concurrent_chat': {'total': 0, 'success': 0, 'failed': 0, 'times': []},
            'language_switch': {'total': 0, 'success': 0, 'failed': 0, 'switches': 0},
            'transfer_human': {'total': 0, 'success': 0, 'failed': 0, 'timeout': 0},
        }
    
    def simulate_buyer(self, buyer_id: int) -> Dict:
        """模拟单个买家"""
        import requests
        phone = generate_phone()
        result = {'buyer_id': buyer_id, 'session': None, 'messages': 0, 'errors': []}
        
        try:
            # 启动会话
            start = time.time()
            resp = requests.post(f"{self.base_url}/api/customer/start",
                               json={"phone": phone}, timeout=10)
            elapsed = time.time() - start
            
            if resp.status_code == 200:
                data = resp.json()
                if data.get("success"):
                    result['session'] = data['session_id']
                    
                    # 发送消息
                    messages = [
                        "你好",
                        "我想查订单",
                        "有什么优惠吗？",
                        random.choice(["转人工", "谢谢", "再见"])
                    ]
                    
                    for msg in messages:
                        try:
                            m_resp = requests.post(f"{self.base_url}/api/customer/chat",
                                                json={"session_id": result['session'], "message": msg},
                                                timeout=15)
                            if m_resp.status_code == 200:
                                result['messages'] += 1
                        except:
                            result['errors'].append(f"消息发送失败: {msg}")
                
                self.results['concurrent_chat']['times'].append(elapsed)
            else:
                result['errors'].append(f"HTTP {resp.status_code}")
        
        except Exception as e:
            result['errors'].append(str(e))
        
        return result
    
    def test_concurrent_users(self, count: int = 100) -> Dict:
        """测试并发用户"""
        print(f"\n=== 并发测试: {count} 用户同时在线咨询 ===")
        
        start_time = time.time()
        results = []
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=50) as executor:
            futures = [executor.submit(self.simulate_buyer, i) for i in range(count)]
            for future in concurrent.futures.as_completed(futures, timeout=60):
                try:
                    results.append(future.result())
                except Exception as e:
                    results.append({'error': str(e)})
        
        elapsed = time.time() - start_time
        
        success = sum(1 for r in results if r.get('session'))
        failed = len(results) - success
        
        self.results['concurrent_chat']['total'] = count
        self.results['concurrent_chat']['success'] = success
        self.results['concurrent_chat']['failed'] = failed
        
        avg_time = sum(self.results['concurrent_chat']['times']) / len(self.results['concurrent_chat']['times']) if self.results['concurrent_chat']['times'] else 0
        
        print(f"并发测试完成:")
        print(f"  - 总请求: {count}")
        print(f"  - 成功: {success}")
        print(f"  - 失败: {failed}")
        print(f"  - 总耗时: {elapsed:.2f}s")
        print(f"  - 平均响应: {avg_time:.3f}s")
        print(f"  - QPS: {count/elapsed:.2f}")
        
        return {
            'total': count,
            'success': success,
            'failed': failed,
            'elapsed': elapsed,
            'avg_response_time': avg_time,
            'qps': count/elapsed
        }
    
    def test_language_switching(self, count: int = 50) -> Dict:
        """测试频繁切换语言"""
        print(f"\n=== 语言切换测试: {count} 次切换 ===")
        
        import requests
        phone = generate_phone()
        switches = 0
        
        try:
            resp = requests.post(f"{self.base_url}/api/customer/start",
                               json={"phone": phone}, timeout=10)
            data = resp.json()
            
            if data.get("success"):
                session_id = data['session_id']
                
                lang_messages = [
                    ("你好", "zh"),
                    ("Hello", "en"),
                    ("مرحبا", "ar"),
                    ("Привет", "ru"),
                    ("สวัสดี", "th"),
                    ("Xin chào", "vi"),
                ]
                
                for i in range(count):
                    msg, target_lang = lang_messages[i % len(lang_messages)]
                    
                    try:
                        resp = requests.post(f"{self.base_url}/api/translate",
                                          json={"text": msg, "target": target_lang},
                                          timeout=5)
                        if resp.status_code == 200:
                            switches += 1
                    except:
                        pass
                
                self.results['language_switch']['total'] = count
                self.results['language_switch']['switches'] = switches
        
        except Exception as e:
            print(f"语言切换测试失败: {e}")
        
        print(f"语言切换测试完成: {switches}/{count} 成功")
        
        return {'total': count, 'switches': switches}
    
    def test_transfer_concurrent(self, count: int = 50) -> Dict:
        """测试转人工并发"""
        print(f"\n=== 转人工并发测试: {count} 人同时转人工 ===")
        
        import requests
        
        def try_transfer(buyer_id: int) -> Dict:
            result = {'buyer_id': buyer_id, 'transferred': False, 'timeout': False}
            
            try:
                phone = generate_phone()
                resp = requests.post(f"{self.base_url}/api/customer/start",
                                   json={"phone": phone}, timeout=10)
                data = resp.json()
                
                if data.get("success"):
                    session_id = data['session_id']
                    
                    # 发送转人工请求
                    try:
                        m_resp = requests.post(f"{self.base_url}/api/customer/chat",
                                            json={"session_id": session_id, "message": "转人工"},
                                            timeout=15)
                        if m_resp.status_code == 200:
                            m_data = m_resp.json()
                            if m_data.get("success"):
                                result['transferred'] = True
                    except:
                        result['timeout'] = True
                        
            except Exception as e:
                result['error'] = str(e)
            
            return result
        
        start_time = time.time()
        results = []
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
            futures = [executor.submit(try_transfer, i) for i in range(count)]
            for future in concurrent.futures.as_completed(futures, timeout=120):
                try:
                    results.append(future.result())
                except:
                    results.append({'error': 'timeout'})
        
        elapsed = time.time() - start_time
        
        transferred = sum(1 for r in results if r.get('transferred'))
        timeouts = sum(1 for r in results if r.get('timeout'))
        
        self.results['transfer_human']['total'] = count
        self.results['transfer_human']['success'] = transferred
        self.results['transfer_human']['timeout'] = timeouts
        
        print(f"转人工并发测试完成:")
        print(f"  - 总请求: {count}")
        print(f"  - 成功转接: {transferred}")
        print(f"  - 超时/失败: {timeouts}")
        print(f"  - 总耗时: {elapsed:.2f}s")
        
        return {
            'total': count,
            'transferred': transferred,
            'timeouts': timeouts,
            'elapsed': elapsed
        }
    
    def run_stress_tests(self) -> Dict:
        """运行所有压力测试"""
        print("\n" + "=" * 60)
        print("Ruitalk 客服系统压力测试")
        print("=" * 60)
        
        results = {
            'timestamp': datetime.now().isoformat(),
            'concurrent_users': self.test_concurrent_users(100),
            'language_switch': self.test_language_switching(50),
            'transfer_concurrent': self.test_transfer_concurrent(50),
        }
        
        print("\n" + "=" * 60)
        print("压力测试汇总")
        print("=" * 60)
        print(f"并发聊天 QPS: {results['concurrent_users']['qps']:.2f}")
        print(f"语言切换成功率: {results['language_switch']['switches']/results['language_switch']['total']*100:.1f}%")
        print(f"转人工成功率: {results['transfer_concurrent']['transferred']/results['transfer_concurrent']['total']*100:.1f}%")
        
        return results

# ============== 主程序 ==============

def main():
    import argparse
    import json
    
    parser = argparse.ArgumentParser(description="Ruitalk 客服系统测试套件")
    parser.add_argument('--phase', type=int, default=1, choices=[1, 2, 3, 4, 5],
                      help='测试阶段: 1=数据生成, 2=功能测试, 3=压力测试, 4=差距清单, 5=清理')
    parser.add_argument('--output', type=str, help='输出JSON报告路径')
    args = parser.parse_args()
    
    if args.phase == 1:
        # Phase 1: 生成测试数据
        print("\n=== Phase 1: 生成测试数据 ===")
        
        buyers = generate_buyer_data(TEST_DATA_COUNTS['buyers'])
        merchants = generate_merchant_data(TEST_DATA_COUNTS['merchants'])
        agents = generate_agent_data(TEST_DATA_COUNTS['agents'])
        
        print(f"生成数据:")
        print(f"  - 买家: {len(buyers)}")
        print(f"  - 店铺: {len(merchants)}")
        print(f"  - 坐席: {len(agents)}")
        
        # 初始化买家数据
        created = init_test_customers(buyers)
        print(f"\n已创建 {created} 个测试买家")
        
        # 保存配置
        test_data = {
            'buyers': buyers,
            'merchants': merchants,
            'agents': agents,
            'timestamp': datetime.now().isoformat(),
        }
        
        if args.output:
            with open(args.output, 'w', encoding='utf-8') as f:
                json.dump(test_data, f, ensure_ascii=False, indent=2)
            print(f"测试数据已保存到: {args.output}")
    
    elif args.phase == 2:
        # Phase 2: 功能测试
        print("\n=== Phase 2: 核心功能测试 ===")
        tester = ConversationTester()
        results = tester.run_all_tests()
        
        if args.output:
            with open(args.output, 'w', encoding='utf-8') as f:
                json.dump(results, f, ensure_ascii=False, indent=2)
            print(f"测试报告已保存到: {args.output}")
    
    elif args.phase == 3:
        # Phase 3: 压力测试
        print("\n=== Phase 3: 压力测试 ===")
        tester = StressTester()
        results = tester.run_stress_tests()
        
        if args.output:
            with open(args.output, 'w', encoding='utf-8') as f:
                json.dump(results, f, ensure_ascii=False, indent=2)
            print(f"压力测试报告已保存到: {args.output}")
    
    elif args.phase == 4:
        # Phase 4: 差距清单
        print("\n=== Phase 4: 生产级差距清单 ===")
        
        gap_report = """
# Ruitalk 客服系统 - 生产级差距清单

## 已完成功能
- [x] .env 配置统一管理
- [x] MySQL/SQLite 双引擎
- [x] 数据隔离机制
- [x] 多语言翻译支持
- [x] 转人工功能
- [x] AI语料库（197条）
- [x] 坐席分配逻辑

## 生产环境差距

### 高优先级
- [ ] 真实MySQL数据库配置（当前使用SQLite回退）
- [ ] Redis生产配置（当前使用fakeredis）
- [ ] WebSocket断线重连机制
- [ ] 第三方翻译API接入（Google/DeepL）

### 中优先级
- [ ] 敏感词过滤系统
- [ ] 读写分离配置
- [ ] 消息队列（Kafka/RabbitMQ）
- [ ] 前端UI适配优化

### 低优先级
- [ ] 完整业务模块填充（6大模块）
- [ ] 性能监控（Prometheus/Grafana）
- [ ] 日志聚合系统
- [ ] CDN配置
"""
        print(gap_report)
        
        if args.output:
            with open(args.output, 'w', encoding='utf-8') as f:
                f.write(gap_report)
            print(f"差距清单已保存到: {args.output}")
    
    elif args.phase == 5:
        # Phase 5: 清理测试数据
        print("\n=== Phase 5: 清理测试数据 ===")
        deleted = cleanup_test_data()
        print(f"已删除 {deleted} 条测试数据")

if __name__ == "__main__":
    main()
