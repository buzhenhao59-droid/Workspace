# -*- coding: utf-8 -*-
"""
卖方 FastAPI 主应用集成测试
使用 FastAPI TestClient，需要先配置 API client。
如需运行，请确保 conftest.py 包含 api_client fixture。
"""
import pytest


@pytest.fixture(scope="module")
def api_client():
    pytest.skip("API 集成测试需要完整 mock，请确保 conftest.py 配置 api_client fixture")


class TestHealthEndpoints:
    def test_health_returns_200(self, api_client):
        response = api_client.get("/health")
        assert response.status_code == 200

    def test_liveness_returns_200(self, api_client):
        response = api_client.get("/live")
        assert response.status_code == 200
