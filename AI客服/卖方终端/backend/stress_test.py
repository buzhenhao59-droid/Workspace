# -*- coding: utf-8 -*-
"""
压力测试脚本 - 模拟多语言、多人并发场景
"""
import requests
import json
import time
import threading
import queue
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE_URL = "http://127.0.0.1:8000"

# 测试结果收集
results = {
    "total_requests": 0,
    "successful_requests": 0,
    "failed_requests": 0,
    "response_times": [],
    "errors": [],
    "lock": threading.Lock()
}

def print_result(name, success, detail=""):
    status = "[PASS]" if success else "[FAIL]"
    print(f"{status} {name}")
    if detail:
        print(f"       Detail: {detail}")

def test_endpoint(url, method="GET", json_data=None, headers=None, timeout=10):
    """测试单个端点"""
    start_time = time.time()
    try:
        if method == "POST":
            response = requests.post(url, json=json_data, headers=headers, timeout=timeout)
        else:
            response = requests.get(url, headers=headers, timeout=timeout)
        
        elapsed = time.time() - start_time
        
        with results["lock"]:
            results["total_requests"] += 1
            if response.status_code < 400:
                results["successful_requests"] += 1
                results["response_times"].append(elapsed)
                return True, elapsed, response.status_code
            else:
                results["failed_requests"] += 1
                results["errors"].append(f"{url}: {response.status_code}")
                return False, elapsed, response.status_code
    except Exception as e:
        elapsed = time.time() - start_time
        with results["lock"]:
            results["total_requests"] += 1
            results["failed_requests"] += 1
            results["errors"].append(f"{url}: {str(e)}")
        return False, elapsed, 0

def concurrent_users_test(num_users=10, requests_per_user=5):
    """模拟多用户并发访问"""
    print(f"\n{'='*60}")
    print(f"  Concurrent Users Test: {num_users} users x {requests_per_user} requests")
    print("="*60)
    
    # 获取token
    r = requests.post(f"{BASE_URL}/api/admin/login", json={
        "username": "admin",
        "password": "123456789"
    })
    if r.status_code != 200:
        print("[FAIL] Login failed")
        return
    
    token = r.json()["data"]["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    
    endpoints = [
        ("GET", "/api/pre-sale-notes", None),
        ("GET", "/api/admin/after-sales", None),
        ("GET", "/api/admin/sessions", None),
        ("GET", "/api/admin/reviews", None),
        ("GET", "/api/admin/quick-replies", None),
        ("GET", "/orders", None),
        ("GET", "/returns", None),
        ("GET", "/platforms", None),
    ]
    
    def user_requests(user_id):
        user_results = []
        for i in range(requests_per_user):
            method, endpoint, _ = endpoints[i % len(endpoints)]
            url = f"{BASE_URL}{endpoint}"
            success, elapsed, status = test_endpoint(url, method, None, headers)
            user_results.append((user_id, method, endpoint, success, elapsed, status))
        return user_results
    
    start_time = time.time()
    
    with ThreadPoolExecutor(max_workers=num_users) as executor:
        futures = [executor.submit(user_requests, i) for i in range(num_users)]
        all_results = []
        for future in as_completed(futures):
            all_results.extend(future.result())
    
    total_time = time.time() - start_time
    
    # 打印结果
    print(f"\nTotal requests: {results['total_requests']}")
    print(f"Successful: {results['successful_requests']}")
    print(f"Failed: {results['failed_requests']}")
    print(f"Total time: {total_time:.2f}s")
    print(f"Requests per second: {results['total_requests'] / total_time:.2f}")
    
    if results["response_times"]:
        avg_time = sum(results["response_times"]) / len(results["response_times"])
        max_time = max(results["response_times"])
        min_time = min(results["response_times"])
        print(f"Avg response time: {avg_time*1000:.2f}ms")
        print(f"Max response time: {max_time*1000:.2f}ms")
        print(f"Min response time: {min_time*1000:.2f}ms")
    
    if results["errors"]:
        print(f"\nErrors (first 5):")
        for error in results["errors"][:5]:
            print(f"  - {error}")
    
    return results["failed_requests"] == 0

def multi_language_test():
    """测试多语言翻译功能"""
    print(f"\n{'='*60}")
    print("  Multi-Language Translation Test")
    print("="*60)
    
    # 获取token
    r = requests.post(f"{BASE_URL}/api/admin/login", json={
        "username": "admin",
        "password": "123456789"
    })
    if r.status_code != 200:
        print("[FAIL] Login failed")
        return False
    
    token = r.json()["data"]["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    
    # 测试消息中心翻译预览端点
    languages = [
        ("en", "Hello, I need help with my order"),
        ("zh", "你好，我想查询订单状态"),
        ("es", "Hola, necesito ayuda con mi pedido"),
        ("fr", "Bonjour, j'ai besoin d'aide avec ma commande"),
        ("de", "Hallo, ich brauche Hilfe bei meiner Bestellung"),
        ("ja", "こんにちは、注文についてヘルプが必要です"),
        ("ko", "안녕하세요, 주문에 대한 도움이 필요합니다"),
    ]
    
    all_passed = True
    for lang, text in languages:
        url = f"{BASE_URL}/api/v1/message-center/translate-preview"
        data = {"text": text, "target_lang": lang, "source_lang": "auto"}
        success, elapsed, status = test_endpoint(url, "POST", data, headers)
        print_result(f"Translate to {lang.upper()}", success, f"Status: {status}, Time: {elapsed*1000:.2f}ms")
        if not success:
            all_passed = False
    
    return all_passed

def session_concurrent_test(num_sessions=20):
    """测试会话并发处理"""
    print(f"\n{'='*60}")
    print(f"  Session Concurrent Test: {num_sessions} sessions")
    print("="*60)
    
    # 获取token
    r = requests.post(f"{BASE_URL}/api/admin/login", json={
        "username": "admin",
        "password": "123456789"
    })
    if r.status_code != 200:
        print("[FAIL] Login failed")
        return False
    
    token = r.json()["data"]["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    
    def create_session(session_id):
        # 模拟查询会话
        url = f"{BASE_URL}/api/admin/sessions"
        success, elapsed, status = test_endpoint(url, "GET", None, headers)
        return success, session_id
    
    start_time = time.time()
    
    with ThreadPoolExecutor(max_workers=num_sessions) as executor:
        futures = [executor.submit(create_session, i) for i in range(num_sessions)]
        results_list = [f.result() for f in as_completed(futures)]
    
    total_time = time.time() - start_time
    
    passed = sum(1 for r in results_list if r[0])
    print(f"\nSessions queried: {passed}/{num_sessions}")
    print(f"Total time: {total_time:.2f}s")
    print(f"Queries per second: {num_sessions / total_time:.2f}")
    
    return passed == num_sessions

def main():
    print("\n" + "="*60)
    print("  Ruitalk Stress Test Suite")
    print("="*60)
    print(f"Test time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Test URL: {BASE_URL}")
    
    # 重置结果
    results["total_requests"] = 0
    results["successful_requests"] = 0
    results["failed_requests"] = 0
    results["response_times"] = []
    results["errors"] = []
    
    # 1. 多用户并发测试
    concurrent_users_test(num_users=10, requests_per_user=10)
    
    # 2. 多语言测试
    multi_language_test()
    
    # 3. 会话并发测试
    session_concurrent_test(num_sessions=20)
    
    # 最终总结
    print("\n" + "="*60)
    print("  Stress Test Summary")
    print("="*60)
    print(f"Total requests: {results['total_requests']}")
    print(f"Successful: {results['successful_requests']}")
    print(f"Failed: {results['failed_requests']}")
    success_rate = (results['successful_requests'] / results['total_requests'] * 100) if results['total_requests'] > 0 else 0
    print(f"Success rate: {success_rate:.2f}%")
    
    if results["response_times"]:
        avg_time = sum(results["response_times"]) / len(results["response_times"])
        print(f"Average response time: {avg_time*1000:.2f}ms")
    
    print("="*60)

if __name__ == "__main__":
    main()
