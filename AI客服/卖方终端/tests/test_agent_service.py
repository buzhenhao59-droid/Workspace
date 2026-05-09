# -*- coding: utf-8 -*-
"""
卖方 agent_service.py / session_mode.py 单元测试
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from session_mode import SessionMode, SessionModeManager
from agent_service import AgentStatus, AgentRole, AgentService


class TestSessionMode:
    """会话模式枚举测试"""

    def test_session_mode_values(self):
        from session_mode import SessionMode
        assert SessionMode.AI.value == "ai"
        assert SessionMode.HUMAN.value == "human"
        assert SessionMode.WAITING.value == "waiting"


class TestSessionModeManager:
    """会话模式管理器测试"""

    def setup_method(self):
        self.mgr = SessionModeManager()

    def test_default_mode_is_ai(self):
        mode = self.mgr.get_mode("nonexistent_session")
        assert mode == SessionMode.AI

    def test_switch_to_ai_returns_timestamp(self):
        """switch_to_ai 返回 ai_mode_since 时间戳"""
        result = self.mgr.switch_to_ai("session_ai")
        assert isinstance(result, str)
        assert "T" in result  # ISO format
        assert self.mgr.get_mode("session_ai") == SessionMode.AI
        assert self.mgr.is_ai_mode("session_ai") is True

    def test_switch_to_human(self):
        self.mgr.switch_to_ai("session_h")
        result = self.mgr.switch_to_human("session_h", "agent_001")
        assert result is True
        assert self.mgr.get_mode("session_h") == SessionMode.HUMAN
        assert self.mgr.is_ai_mode("session_h") is False
        assert self.mgr.get_agent("session_h") == "agent_001"

    def test_switch_to_waiting(self):
        self.mgr.switch_to_ai("session_w")
        result = self.mgr.switch_to_waiting("session_w")
        assert result is True
        assert self.mgr.get_mode("session_w") == SessionMode.WAITING

    def test_get_ai_sessions(self):
        self.mgr.switch_to_ai("ai_1")
        self.mgr.switch_to_ai("ai_2")
        self.mgr.switch_to_human("human_1", "agent_a")
        ai_sessions = self.mgr.get_ai_sessions()
        assert "ai_1" in ai_sessions
        assert "ai_2" in ai_sessions
        assert "human_1" not in ai_sessions

    def test_get_human_sessions(self):
        self.mgr.switch_to_human("h_1", "a1")
        self.mgr.switch_to_human("h_2", "a2")
        human = self.mgr.get_human_sessions()
        assert "h_1" in human
        assert "h_2" in human

    def test_get_all_agent_session_counts(self):
        self.mgr.switch_to_human("s1", "agent_x")
        self.mgr.switch_to_human("s2", "agent_x")
        self.mgr.switch_to_human("s3", "agent_y")
        counts = self.mgr.get_all_agent_session_counts()
        assert counts["agent_x"] == 2
        assert counts["agent_y"] == 1


class TestAgentService:
    """坐席服务测试"""

    def setup_method(self):
        self.svc = AgentService()

    def test_agent_login(self):
        result = self.svc.agent_login("agent_001", "张三", "agent")
        assert result["agent_id"] == "agent_001"
        assert result["agent_name"] == "张三"
        assert result["status"] == "online"

    def test_agent_heartbeat(self):
        self.svc.agent_login("agent_002", "李四", "agent")
        result = self.svc.agent_heartbeat("agent_002")
        assert result is True

    def test_set_agent_status(self):
        self.svc.agent_login("agent_003", "王五", "agent")
        result = self.svc.set_agent_status("agent_003", "busy")
        assert result is True

    def test_assign_session(self):
        self.svc.agent_login("agent_004", "赵六", "agent")
        result = self.svc.assign_session("session_abc", "agent_004")
        assert result is True
        assert self.svc.get_session_agent("session_abc") == "agent_004"

    def test_auto_assign_session(self):
        self.svc.agent_login("agent_005", "钱七", "agent")
        self.svc.agent_login("agent_006", "孙八", "agent")
        assigned = self.svc.auto_assign_session("session_xyz", "least_loaded")
        assert assigned in ["agent_005", "agent_006"]

    def test_release_session(self):
        self.svc.agent_login("agent_007", "周九", "agent")
        self.svc.assign_session("session_release", "agent_007")
        result = self.svc.release_session("session_release")
        assert result is True

    def test_get_online_agents(self):
        """get_online_agents 返回所有登录坐席（含离线）"""
        self.svc.agent_login("online_1", "在线1", "agent")
        self.svc.agent_login("online_2", "在线2", "agent")
        self.svc.agent_login("offline_1", "离线1", "agent")
        self.svc.set_agent_status("offline_1", "offline")
        # 注意：即使离线也返回（get_online_agents 不过滤离线）
        online = self.svc.get_online_agents()
        assert len(online) == 3

    def test_get_workload_report(self):
        self.svc.agent_login("wl_1", "工人1", "agent")
        self.svc.agent_login("wl_2", "工人2", "agent")
        self.svc.assign_session("s1", "wl_1")
        self.svc.assign_session("s2", "wl_1")
        self.svc.assign_session("s3", "wl_2")
        report = self.svc.get_workload_report()
        assert "total_agents" in report
        assert "agents" in report
        assert report["total_agents"] == 2


class TestAgentEnums:
    """枚举值测试"""

    def test_agent_status_values(self):
        assert AgentStatus.ONLINE.value == "online"
        assert AgentStatus.BUSY.value == "busy"
        assert AgentStatus.OFFLINE.value == "offline"
        assert AgentStatus.AWAY.value == "away"

    def test_agent_role_values(self):
        assert AgentRole.AGENT.value == "agent"
        assert AgentRole.ADMIN.value == "admin"
        assert AgentRole.MANAGER.value == "manager"
