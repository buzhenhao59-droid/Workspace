# -*- coding: utf-8 -*-
"""
Session 权限校验中间件
确保用户只能访问自己的会话和数据，防止越权访问

使用方法：
    from session_security import SessionSecurityValidator, require_session_access
    
    validator = SessionSecurityValidator()
    
    # 验证客户访问权限
    if not validator.validate_customer_access(session_id, customer_id):
        raise HTTPException(status_code=403, detail="无权访问此会话")
"""

import functools
import logging
from typing import Optional, Dict, Any, Callable
from fastapi import HTTPException, Request, Depends

logger = logging.getLogger(__name__)


class SessionSecurityValidator:
    """
    Session 安全验证器
    验证用户只能访问自己有权访问的会话和数据
    """
    
    def __init__(self):
        # 内存缓存：session_id -> owner_id 映射
        self._session_owners: Dict[str, Dict[str, Any]] = {}
        # 缓存过期时间（秒）
        self._cache_ttl = 3600
    
    def register_session(self, session_id: str, owner_id: str, owner_type: str = "customer") -> None:
        """
        注册会话所有权
        
        Args:
            session_id: 会话ID
            owner_id: 所有者ID（customer_id / agent_id / merchant_id）
            owner_type: 所有者类型（customer / agent / merchant / admin）
        """
        self._session_owners[session_id] = {
            "owner_id": owner_id,
            "owner_type": owner_type
        }
        logger.debug(f"Registered session {session_id} for {owner_type} {owner_id}")
    
    def validate_customer_access(self, session_id: str, customer_id: str) -> bool:
        """
        验证客户只能访问自己的会话
        
        Args:
            session_id: 会话ID
            customer_id: 客户ID
            
        Returns:
            True 如果客户有权访问此会话
        """
        session_info = self._session_owners.get(session_id)
        if not session_info:
            # 如果没有缓存记录，尝试从数据库获取
            return self._validate_from_db(session_id, customer_id, "customer")
        
        # 检查是否是会话所有者
        if session_info["owner_type"] == "customer":
            return session_info["owner_id"] == customer_id
        
        # 如果是管理员或客服，可以访问任何会话
        if session_info["owner_type"] in ("admin", "agent"):
            return True
        
        return False
    
    def validate_agent_access(self, session_id: str, agent_id: str) -> bool:
        """
        验证坐席只能访问分配给自己的会话
        
        Args:
            session_id: 会话ID
            agent_id: 坐席ID
            
        Returns:
            True 如果坐席有权访问此会话
        """
        session_info = self._session_owners.get(session_id)
        if not session_info:
            return self._validate_from_db(session_id, agent_id, "agent")
        
        # 如果是管理员，可以访问任何会话
        if session_info["owner_type"] == "admin":
            return True
        
        # 如果是坐席，只能访问自己的会话
        if session_info["owner_type"] == "agent":
            return session_info["owner_id"] == agent_id
        
        return False
    
    def validate_admin_access(self, requester_id: str) -> bool:
        """
        验证管理员权限
        
        Args:
            requester_id: 请求者ID
            
        Returns:
            True 如果是管理员
        """
        # 管理员ID通常以 admin- 开头
        return requester_id.startswith("admin-") or requester_id == "admin"
    
    def get_session_owner(self, session_id: str) -> Optional[Dict[str, Any]]:
        """获取会话所有者信息"""
        return self._session_owners.get(session_id)
    
    def remove_session(self, session_id: str) -> None:
        """移除会话（会话结束时调用）"""
        if session_id in self._session_owners:
            del self._session_owners[session_id]
            logger.debug(f"Removed session {session_id}")
    
    def _validate_from_db(self, session_id: str, user_id: str, user_type: str) -> bool:
        """
        从数据库验证权限（当内存缓存没有时）
        
        这个方法需要根据实际数据库结构实现
        """
        try:
            from db import get_session
            session = get_session(session_id)
            if not session:
                return False
            
            # 根据用户类型验证
            if user_type == "customer":
                return session.get("customer_id") == user_id
            elif user_type == "agent":
                return session.get("agent_id") == user_id or session.get("assigned_agent") == user_id
            
            return False
        except Exception as e:
            logger.error(f"Failed to validate from database: {e}")
            return False


# 全局实例
session_security = SessionSecurityValidator()


def require_session_access(param_name: str = "session_id", user_param: str = "customer_id", user_type: str = "customer"):
    """
    装饰器：验证会话访问权限
    
    Args:
        param_name: 会话ID参数名
        user_param: 用户ID参数名
        user_type: 用户类型（customer / agent / merchant）
    
    Example:
        @router.get("/session/{session_id}/messages")
        @require_session_access("session_id", "customer_id", "customer")
        async def get_messages(session_id: str, customer_id: str):
            ...
    """
    def decorator(func: Callable):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # 从请求或参数中获取值
            session_id = kwargs.get(param_name)
            user_id = kwargs.get(user_param)
            
            if not session_id:
                raise HTTPException(status_code=400, detail="缺少会话ID")
            if not user_id:
                raise HTTPException(status_code=401, detail="未登录")
            
            # 验证权限
            validator = SessionSecurityValidator()
            
            if user_type == "customer":
                if not validator.validate_customer_access(session_id, user_id):
                    logger.warning(f"Customer {user_id} attempted to access session {session_id}")
                    raise HTTPException(status_code=403, detail="无权访问此会话")
            elif user_type == "agent":
                if not validator.validate_agent_access(session_id, user_id):
                    logger.warning(f"Agent {user_id} attempted to access session {session_id}")
                    raise HTTPException(status_code=403, detail="无权访问此会话")
            
            return await func(*args, **kwargs)
        return wrapper
    return decorator


class SessionAccessDeniedError(HTTPException):
    """会话访问被拒绝异常"""
    
    def __init__(self, session_id: str = None, requester_id: str = None, detail: str = "权限不足"):
        self.session_id = session_id
        self.requester_id = requester_id
        super().__init__(
            status_code=403,
            detail=detail,
            headers={"WWW-Authenticate": "Bearer"}
        )
        logger.warning(f"Session access denied: session={session_id}, requester={requester_id}")
