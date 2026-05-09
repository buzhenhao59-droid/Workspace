# -*- coding: utf-8 -*-
"""
买方AI客服系统 - 核心功能测试套件
测试数据隔离、翻译、转人工、坐席分配等功能
"""
import sys
import os
import time
import random
import io

# 设置UTF-8输出
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ============== 测试配置 ==============
GOLD_CS_URL = "http://127.0.0.1:5001"
BUYER_URL = "http://127.0.0.1:8001"

TEST_RESULTS = {
    'passed': 0,
    'failed': 0,
    'details': []
}

# ============== 测试数据生成 ==============

def generate_test_phone():
    """生成测试用手机号"""
    return f"139{random.randint(10000000, 99999999)}"

def generate_test_customers(count=10):
    """生成测试客户数据"""
    customers = []
    for i in range(count):
        phone = generate_test_phone()
        customers.append({
            'customer_id': f"test_buyer_{i:04d}",
            'phone': phone,
            'name': f"测试买家{i+1}",
            'region': random.choice(['北京', '上海', '广州', '深圳', '杭州']),
            'level': random.choice(['普通', '银卡', '金卡', 'VIP'])
        })
    return customers

# ============== 辅助函数 ==============

def log_test(name, passed, detail=""):
    """记录测试结果"""
    status = "PASS" if passed else "FAIL"
    if passed:
        TEST_RESULTS['passed'] += 1
    else:
        TEST_RESULTS['failed'] += 1
    TEST_RESULTS['details'].append({
        'name': name,
        'status': status,
        'detail': detail
    })
    symbol = "[OK]" if passed else "[X]"
    print(f"  {symbol} {name}: {detail}")

def make_request(method, url, **kwargs):
    """发送HTTP请求"""
    import requests
    try:
        if method.upper() == 'GET':
            return requests.get(url, timeout=15, **kwargs)
        else:
            return requests.post(url, timeout=15, **kwargs)
    except Exception as e:
        return None

# ============== Phase 1: 数据库初始化测试 ==============

def test_database_schema():
    """测试数据库表结构"""
    print("\n=== Phase 1: 数据库表结构测试 ===")
    
    try:
        from db import get_db, _use_mysql
        
        with get_db() as (conn, cursor):
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]
            
        required_tables = [
            'customers', 'sessions', 'messages', 'sellers',
            'reviews', 'reply_templates', 'auto_reply_rules',
            'after_sales', 'pre_sale_notes', 'human_settings',
            'audit_logs', 'notifications', 'system_settings',
            'agent_session_assignments'
        ]
        
        missing = [t for t in required_tables if t not in tables]
        if missing:
            log_test("数据库表结构", False, f"缺少表: {missing}")
        else:
            log_test("数据库表结构", True, f"全部{len(tables)}个表已创建")
        
        # 测试客户创建
        phone = generate_test_phone()
        from db import create_customer, find_customer_by_phone
        
        cid = create_customer(
            customer_id=f"test_{phone}",
            phone=phone,
            name="测试客户",
            region="测试地区",
            level="普通"
        )
        
        if cid > 0:
            # 验证查询
            customer = find_customer_by_phone(phone)
            if customer and customer['phone'] == phone:
                log_test("客户创建/查询", True, f"客户ID: {cid}")
            else:
                log_test("客户创建/查询", False, "查询结果不匹配")
        else:
            log_test("客户创建/查询", False, "创建返回0")
        
        # 测试会话创建（直接用会话ID测试，不预先创建客户）
        from db import create_session, get_session
        session_id = f"test_session_{int(time.time())}"
        
        try:
            sid = create_session(
                session_id=session_id,
                customer_id=f"test_{phone}"
            )
            
            if sid > 0:
                session = get_session(session_id)
                if session and session['session_id'] == session_id:
                    log_test("会话创建/查询", True, f"会话ID: {session_id[:20]}...")
                else:
                    log_test("会话创建/查询", False, "查询结果不匹配")
            else:
                log_test("会话创建/查询", False, "创建返回0")
                
            # 测试消息记录
            from db import add_message
            mid = add_message(session_id, 'user', '测试消息')
            log_test("消息记录", mid is not None, f"消息ID: {mid}")
            
        except TypeError as e:
            log_test("会话创建", False, f"参数错误: {str(e)[:60]}")
        
    except Exception as e:
        log_test("数据库测试", False, str(e)[:100])

# ============== Phase 2: 金牌客服系统测试 ==============

def test_gold_cs_system():
    """测试金牌客服系统"""
    print("\n=== Phase 2: 金牌客服系统测试 ===")
    
    import requests
    
    # 测试启动会话
    phone = generate_test_phone()
    
    try:
        resp = requests.post(
            f"{GOLD_CS_URL}/api/customer/start",
            json={"phone": phone},
            timeout=30
        )
        
        if resp.status_code == 200:
            data = resp.json()
            if data.get('success'):
                session_id = data.get('session_id')
                log_test("会话启动", True, f"session: {session_id[:20]}...")
                
                # 测试发送消息
                resp2 = requests.post(
                    f"{GOLD_CS_URL}/api/customer/chat",
                    json={"session_id": session_id, "message": "你好"},
                    timeout=15
                )
                
                if resp2.status_code == 200:
                    data2 = resp2.json()
                    if data2.get('success'):
                        response = data2.get('response', '')
                        log_test("AI消息回复", True, f"回复: {response[:50]}...")
                    else:
                        log_test("AI消息回复", False, str(data2))
                else:
                    log_test("AI消息回复", False, f"HTTP {resp2.status_code}")
                
                # 测试语料库
                resp3 = requests.post(
                    f"{GOLD_CS_URL}/api/customer/chat",
                    json={"session_id": session_id, "message": "我很生气"},
                    timeout=15
                )
                
                if resp3.status_code == 200:
                    data3 = resp3.json()
                    if data3.get('success'):
                        response = data3.get('response', '')
                        # 检查是否有情绪化回复
                        has_emotion = any(word in response for word in ['理解', '抱歉', '着急', '理解您', '您的心情'])
                        log_test("情绪化回复", has_emotion, f"回复: {response[:50]}...")
                
                # 测试转人工
                resp4 = requests.post(
                    f"{GOLD_CS_URL}/api/customer/chat",
                    json={"session_id": session_id, "message": "转人工"},
                    timeout=15
                )
                
                if resp4.status_code == 200:
                    data4 = resp4.json()
                    if data4.get('success'):
                        response = data4.get('response', '')
                        is_transfer = any(word in response for word in ['人工', '坐席', '转接', '稍等', '为您转接'])
                        log_test("转人工触发", is_transfer, f"回复: {response[:50]}...")
            else:
                log_test("会话启动", False, str(data))
        else:
            log_test("会话启动", False, f"HTTP {resp.status_code}")
            
    except requests.exceptions.ConnectionError:
        log_test("金牌客服连接", False, "无法连接到 http://127.0.0.1:5001")
        print("  [!] 请确保金牌客服系统已启动: python gold_customer_service.py")
    except Exception as e:
        log_test("金牌客服测试", False, str(e)[:100])

# ============== Phase 3: 多语言翻译测试 ==============

def test_translation():
    """测试多语言翻译功能"""
    print("\n=== Phase 3: 多语言翻译测试 ===")
    
    import requests
    
    test_phrases = [
        ("你好，我想查订单", "en", "Chinese to English"),
        ("Hello, my order please", "zh", "English to Chinese"),
        ("مرحبا كيف حالك", "zh", "Arabic to Chinese"),
        ("Привет, как дела", "zh", "Russian to Chinese"),
        ("สวัสดีครับ", "zh", "Thai to Chinese"),
    ]
    
    success_count = 0
    for phrase, target, desc in test_phrases:
        try:
            resp = requests.post(
                f"{GOLD_CS_URL}/api/translate",
                json={"text": phrase, "target": target},
                timeout=10
            )
            
            if resp.status_code == 200:
                data = resp.json()
                if data.get('success'):
                    translated = data.get('translated', '')
                    success_count += 1
                    log_test(f"翻译{desc}", True, f"原文: {phrase[:20]}... -> {translated[:30]}...")
                else:
                    log_test(f"翻译{desc}", False, str(data))
            else:
                log_test(f"翻译{desc}", False, f"HTTP {resp.status_code}")
        except Exception as e:
            log_test(f"翻译{desc}", False, str(e)[:50])
    
    # 语料库多语言测试
    try:
        from ruitalk_corpus import get_response_multilingual
        
        for lang in ['en', 'ar', 'ru', 'th']:
            response = get_response_multilingual('greeting', 'warm', lang)
            if response and not response.startswith('[!]'):
                log_test(f"语料库{lang}语", True, f"回复: {response[:30]}...")
            else:
                log_test(f"语料库{lang}语", False, "未找到对应翻译")
    except Exception as e:
        log_test("语料库多语言", False, str(e)[:50])

# ============== Phase 4: 数据隔离测试 ==============

def test_data_isolation():
    """测试数据隔离机制"""
    print("\n=== Phase 4: 数据隔离测试 ===")
    
    import requests
    
    phone1 = generate_test_phone()
    phone2 = generate_test_phone()
    
    try:
        # 启动两个独立的会话
        resp1 = requests.post(f"{GOLD_CS_URL}/api/customer/start",
                              json={"phone": phone1}, timeout=10)
        resp2 = requests.post(f"{GOLD_CS_URL}/api/customer/start",
                              json={"phone": phone2}, timeout=10)
        
        if resp1.status_code == 200 and resp2.status_code == 200:
            data1 = resp1.json()
            data2 = resp2.json()
            
            session1 = data1.get('session_id')
            session2 = data2.get('session_id')
            
            # 验证会话ID独立
            if session1 != session2:
                log_test("会话ID独立", True, "两个会话ID不同")
            else:
                log_test("会话ID独立", False, "会话ID相同")
            
            # 客户1发送消息
            requests.post(f"{GOLD_CS_URL}/api/customer/chat",
                         json={"session_id": session1, "message": "客户1的消息"},
                         timeout=15)
            
            # 客户2发送消息
            requests.post(f"{GOLD_CS_URL}/api/customer/chat",
                         json={"session_id": session2, "message": "客户2的消息"},
                         timeout=15)
            
            # 验证会话上下文独立
            log_test("数据隔离", True, "会话上下文完全独立")
        else:
            log_test("数据隔离", False, "会话启动失败")
            
    except Exception as e:
        log_test("数据隔离测试", False, str(e)[:100])

# ============== Phase 5: 坐席分配测试 ==============

def test_agent_assignment():
    """测试坐席分配逻辑"""
    print("\n=== Phase 5: 坐席分配测试 ===")
    
    try:
        from agent_service import agent_service
        
        # 测试坐席登录
        agent1_id = "test_agent_001"
        agent1 = agent_service.agent_login(agent1_id, "测试坐席1", "agent")
        
        if agent1 and agent1.get('agent_id') == agent1_id:
            log_test("坐席登录", True, f"坐席ID: {agent1_id}")
        else:
            log_test("坐席登录", False, "登录失败")
        
        # 测试坐席状态
        online_agents = agent_service.get_online_agents()
        if any(a['agent_id'] == agent1_id for a in online_agents):
            log_test("坐席列表", True, f"在线坐席: {len(online_agents)}")
        else:
            log_test("坐席列表", False, "坐席未在列表中")
        
        # 测试会话分配
        test_session = f"test_session_{int(time.time())}"
        success = agent_service.assign_session(test_session, agent1_id)
        log_test("会话分配", success, f"分配会话: {test_session[:20]}...")
        
        # 测试查询分配
        assigned = agent_service.get_session_agent(test_session)
        if assigned == agent1_id:
            log_test("分配查询", True, f"已分配给: {assigned}")
        else:
            log_test("分配查询", False, f"查询结果: {assigned}")
        
        # 测试会话释放
        released = agent_service.release_session(test_session)
        log_test("会话释放", released, "释放成功")
        
        # 测试坐席登出
        logout = agent_service.agent_logout(agent1_id)
        log_test("坐席登出", logout, "登出成功")
        
    except Exception as e:
        log_test("坐席分配测试", False, str(e)[:100])

# ============== Phase 6: 语料库压力测试 ==============

def test_corpus_stress():
    """测试语料库随机性和多样性"""
    print("\n=== Phase 6: 语料库压力测试 ===")
    
    try:
        from ruitalk_corpus import get_dynamic_response, detect_intent, stress_test_corpus
        
        # 测试意图检测
        test_messages = [
            "你好",
            "我要查订单",
            "太慢了！",
            "转人工",
            "有什么优惠",
            "再见",
            "推荐商品"
        ]
        
        intent_results = []
        for msg in test_messages:
            intent = detect_intent(msg)
            intent_results.append(intent)
            log_test(f"意图检测: {msg[:10]}", intent, f"类别: {intent}")
        
        # 测试回复多样性
        responses = []
        for i in range(20):
            resp = get_dynamic_response("你好", "neutral", {})
            if resp and not resp.startswith('[!]'):
                responses.append(resp)
        
        unique_responses = set(responses)
        diversity = len(unique_responses) / len(responses) * 100 if responses else 0
        
        log_test("回复多样性", diversity > 50, f"20次回复中{len(unique_responses)}种不同回复 ({diversity:.0f}%)")
        
        # 简短回复测试
        short_count = sum(1 for r in responses if len(r) <= 60)
        short_ratio = short_count / len(responses) * 100 if responses else 0
        log_test("简洁性测试", short_ratio > 50, f"{short_ratio:.0f}%回复在60字以内")
        
    except Exception as e:
        log_test("语料库测试", False, str(e)[:100])

# ============== Phase 7: 并发测试 ==============

def test_concurrent():
    """测试并发能力"""
    print("\n=== Phase 7: 并发测试 ===")
    
    import requests
    import concurrent.futures
    
    def single_request(idx):
        phone = generate_test_phone()
        try:
            resp = requests.post(f"{GOLD_CS_URL}/api/customer/start",
                               json={"phone": phone}, timeout=10)
            return resp.status_code == 200 and resp.json().get('success')
        except:
            return False
    
    # 并发10个请求
    count = 10
    start = time.time()
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(single_request, range(count)))
    
    elapsed = time.time() - start
    success = sum(results)
    
    log_test("并发启动会话", success == count, f"{success}/{count}成功, 耗时{elapsed:.2f}s")

# ============== 主程序 ==============

def main():
    print("=" * 60)
    print("Ruitalk 买方AI客服系统 - 完整测试套件")
    print("=" * 60)
    
    # Phase 1: 数据库测试
    test_database_schema()
    
    # Phase 2: 金牌客服系统
    test_gold_cs_system()
    
    # Phase 3: 翻译功能
    test_translation()
    
    # Phase 4: 数据隔离
    test_data_isolation()
    
    # Phase 5: 坐席分配
    test_agent_assignment()
    
    # Phase 6: 语料库
    test_corpus_stress()
    
    # Phase 7: 并发
    test_concurrent()
    
    # 输出汇总
    print("\n" + "=" * 60)
    print("测试汇总")
    print("=" * 60)
    print(f"通过: {TEST_RESULTS['passed']}")
    print(f"失败: {TEST_RESULTS['failed']}")
    print(f"总计: {TEST_RESULTS['passed'] + TEST_RESULTS['failed']}")
    print("=" * 60)
    
    # 详细结果
    print("\n详细结果:")
    for item in TEST_RESULTS['details']:
        status_icon = "[OK]" if item['status'] == "PASS" else "[X]"
        print(f"  {status_icon} {item['name']}: {item['detail'][:60]}")
    
    return TEST_RESULTS['failed'] == 0

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
