import pytest
import asyncio
from typing import Generator
from httpx import AsyncClient, ASGITransport

# ============== 测试配置 ==============

TEST_BASE_URL = "http://127.0.0.1:8000"
TEST_BUYER_URL = "http://127.0.0.1:8001"

# ============== Pytest 配置 ==============

@pytest.fixture(scope="session")
def event_loop():
    """创建事件循环（用于异步测试）"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
async def api_client() -> Generator[AsyncClient, None, None]:
    """
    异步 API 客户端
    
    用法:
        async def test_example(client):
            response = await client.get("/health")
            assert response.status_code == 200
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url=TEST_BASE_URL) as client:
        yield client


@pytest.fixture
def auth_headers():
    """获取认证头（需要在测试前先登录获取token）"""
    # 这里只是一个占位符，实际使用时需要先登录
    return {"Authorization": "Bearer test_token"}


# ============== 辅助函数 ==============

def create_test_customer(phone: str = None) -> dict:
    """创建测试客户数据"""
    import uuid
    if phone is None:
        phone = f"199{str(uuid.uuid4().int)[:8]}"
    return {
        "phone": phone,
        "name": f"测试客户_{uuid.uuid4().hex[:6]}",
        "region": "测试区域",
    }


def create_test_session() -> dict:
    """创建测试会话数据"""
    import uuid
    return {
        "session_id": str(uuid.uuid4()),
        "customer_id": f"test_customer_{uuid.uuid4().hex[:8]}",
        "status": "active",
    }


def create_test_message() -> dict:
    """创建测试消息数据"""
    import uuid
    return {
        "content": f"测试消息_{uuid.uuid4().hex[:8]}",
        "role": "user",
    }


# ============== Mock 数据 ==============

@pytest.fixture
def mock_customer_data():
    """Mock 客户数据"""
    return {
        "customer_id": "test_customer_001",
        "phone": "19912345678",
        "name": "测试客户",
        "region": "北京",
        "level": "VIP",
        "m_value": 1000,
        "created_at": "2024-01-01T00:00:00Z",
    }


@pytest.fixture
def mock_session_data():
    """Mock 会话数据"""
    return {
        "session_id": "test_session_001",
        "customer_id": "test_customer_001",
        "status": "active",
        "is_ai": True,
        "language": "zh",
        "created_at": "2024-01-01T00:00:00Z",
    }


@pytest.fixture
def mock_message_data():
    """Mock 消息数据"""
    return {
        "id": 1,
        "session_id": "test_session_001",
        "role": "user",
        "content": "你好，请问我的订单发货了吗？",
        "created_at": "2024-01-01T00:00:00Z",
    }


@pytest.fixture
def mock_stats_data():
    """Mock 统计数据"""
    return {
        "today_sessions": 42,
        "ai_resolution_rate": 0.85,
        "human_transfers": 5,
        "positive_rating_rate": 0.95,
        "avg_response_time": 1.2,
        "total_customers": 1234,
    }
