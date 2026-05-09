# -*- coding: utf-8 -*-
"""买方AI客服系统多轮测试脚本"""
import requests
import json
import time
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

BASE_URL = "http://127.0.0.1:5001"

def start_session(phone="13800138000"):
    """启动客户会话"""
    resp = requests.post(f"{BASE_URL}/api/customer/start", json={"phone": phone})
    data = resp.json()
    if data.get("success"):
        print(f"[OK] 会话启动成功! session_id: {data['session_id'][:20]}...")
        print(f"     欢迎语: {data['welcome_message']}")
        return data['session_id'], data['language']
    else:
        print(f"[FAIL] 会话启动失败: {data.get('message')}")
        return None, None

def send_message(session_id, message):
    """发送消息"""
    resp = requests.post(f"{BASE_URL}/api/customer/chat", 
                         json={"session_id": session_id, "message": message})
    data = resp.json()
    if data.get("success"):
        return data['response'], data.get('language', 'zh')
    else:
        return f"[FAIL] 发送失败: {data.get('message')}", None

def change_language(session_id, lang):
    """切换语言"""
    resp = requests.post(f"{BASE_URL}/api/customer/change_language",
                        json={"session_id": session_id, "language": lang})
    data = resp.json()
    if data.get("success"):
        return data['welcome_message']
    return f"切换失败: {data.get('message')}"

def translate(text, target):
    """翻译测试"""
    resp = requests.post(f"{BASE_URL}/api/translate",
                         json={"text": text, "target": target})
    data = resp.json()
    if data.get("success"):
        return data['translated']
    return f"翻译失败: {data.get('message')}"

def run_conversation_test():
    """运行多轮对话测试"""
    print("\n" + "=" * 60)
    print("买方AI客服系统 - 多轮对话测试")
    print("=" * 60)
    
    # 启动虚拟客户会话
    print("\n[Round 1] 启动虚拟客户会话")
    session_id, lang = start_session("13900000001")
    if not session_id:
        return
    
    # 第2轮：问候
    print("\n[Round 2] 客户问候")
    response, lang = send_message(session_id, "你好，我想了解一下你们的产品")
    print(f"   客户: 你好，我想了解一下你们的产品")
    print(f"   AI: {response}")
    
    # 第3轮：询问价格
    print("\n[Round 3] 询问价格")
    response, lang = send_message(session_id, "这款产品多少钱？")
    print(f"   客户: 这款产品多少钱？")
    print(f"   AI: {response}")
    
    # 第4轮：表达不满
    print("\n[Round 4] 客户表达不满")
    response, lang = send_message(session_id, "等了好久还没收到货！太失望了！")
    print(f"   客户: 等了好久还没收到货！太失望了！")
    print(f"   AI: {response}")
    
    # 第5轮：政策查询
    print("\n[Round 5] 政策查询")
    response, lang = send_message(session_id, "有什么最新的优惠政策吗？")
    print(f"   客户: 有什么最新的优惠政策吗？")
    print(f"   AI: {response}")
    
    # 第6轮：转人工
    print("\n[Round 6] 转人工")
    response, lang = send_message(session_id, "转人工吧")
    print(f"   客户: 转人工吧")
    print(f"   AI: {response}")
    
    # 第7轮：道别
    print("\n[Round 7] 道别")
    response, lang = send_message(session_id, "好的，我先不聊了，再见")
    print(f"   客户: 好的，我先不聊了，再见")
    print(f"   AI: {response}")

def run_language_test():
    """九国语言翻译测试"""
    print("\n" + "=" * 60)
    print("九国语言翻译测试")
    print("=" * 60)
    
    test_text = "您好，我是您的专属客服，请问有什么可以帮到您的？"
    languages = [
        ("zh", "中文"),
        ("en", "英文"),
        ("ar", "阿拉伯文"),
        ("ru", "俄文"),
        ("th", "泰文"),
        ("vi", "越南文"),
        ("id", "印尼文"),
        ("ms", "马来文"),
        ("tl", "菲律宾文"),
    ]
    
    print(f"\n原文: {test_text}\n")
    
    for code, name in languages:
        try:
            result = translate(test_text, code)
            print(f"[{name}] {result}")
        except Exception as e:
            print(f"[{name}] 翻译失败: {e}")

def run_emotion_response_test():
    """情绪回复测试"""
    print("\n" + "=" * 60)
    print("情绪回复测试")
    print("=" * 60)
    
    session_id, lang = start_session("13900000002")
    if not session_id:
        return
    
    test_cases = [
        ("我非常生气！产品太差了！", "愤怒"),
        ("有点失望，等了好久", "失望"),
        ("谢谢你的帮助！", "感谢"),
        ("好的，我知道了", "中性"),
    ]
    
    for message, emotion_type in test_cases:
        print(f"\n[{emotion_type}] 客户: {message}")
        response, _ = send_message(session_id, message)
        print(f"        AI: {response}")
        time.sleep(0.5)

def run_corpus_test():
    """语料库测试"""
    print("\n" + "=" * 60)
    print("语料库测试 - 各类别随机回复")
    print("=" * 60)
    
    session_id, lang = start_session("13900000003")
    if not session_id:
        return
    
    # 测试各类型输入，触发语料库
    test_inputs = [
        ("你们产品太差了，等了三天都没到", "质量投诉"),
        ("查一下我的个人信息", "查询信息"),
        ("有什么推荐的商品吗", "商品推荐"),
        ("优惠券怎么领取", "优惠券"),
        ("我是AI机器人吗？", "闲聊"),
    ]
    
    for message, desc in test_inputs:
        print(f"\n[{desc}] 客户: {message}")
        response, _ = send_message(session_id, message)
        print(f"        AI: {response}")
        time.sleep(0.3)

def run_corpus_stats_test():
    """语料库统计测试"""
    print("\n" + "=" * 60)
    print("语料库统计测试")
    print("=" * 60)
    
    try:
        resp = requests.get(f"{BASE_URL}/api/corpus/stats")
        data = resp.json()
        if data.get("success"):
            stats = data['data']
            print(f"\n语料库状态: {'已启用' if stats['enabled'] else '未启用'}")
            print(f"总回复数: {stats['total_responses']}")
            print("\n各分类统计:")
            for cat, info in stats['categories'].items():
                print(f"  - {cat}: {info['responses']}条回复, {info['subcategories']}个子类")
        else:
            print(f"获取统计失败: {data.get('message')}")
    except Exception as e:
        print(f"API调用失败: {e}")

def run_stress_test():
    """压力测试"""
    print("\n" + "=" * 60)
    print("语料库压力测试 (50次对话)")
    print("=" * 60)
    
    try:
        resp = requests.post(f"{BASE_URL}/api/corpus/stress-test", json={"iterations": 50})
        data = resp.json()
        if data.get("success"):
            result = data['data']
            print(f"\n测试完成:")
            print(f"  - 总测试次数: {result['iterations']}")
            print(f"  - 拟人化率: {result['human_like_rate']}")
            print(f"  - 机器人模式次数: {result['robot_mode_count']}")
            print(f"  - 状态: {result['status']}")
        else:
            print(f"压力测试失败: {data.get('message')}")
    except Exception as e:
        print(f"API调用失败: {e}")

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("开始买方AI客服系统全面测试")
    print("=" * 60)
    
    # 0. 语料库统计
    run_corpus_stats_test()
    
    # 1. 多轮对话测试
    run_conversation_test()
    
    # 2. 九国语言翻译测试
    run_language_test()
    
    # 3. 情绪回复测试
    run_emotion_response_test()
    
    # 4. 语料库测试
    run_corpus_test()
    
    # 5. 压力测试
    run_stress_test()
    
    print("\n" + "=" * 60)
    print("测试完成!")
    print("=" * 60)
