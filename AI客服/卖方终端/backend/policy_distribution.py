# -*- coding: utf-8 -*-
"""
政策精准分发服务 - 基于用户画像的智能推送
支持按平台、店铺等级、行业、地区等维度精准推送政策
"""
import logging
import json
import sqlite3
import threading
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from enum import Enum
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# ============== 枚举定义 ==============

class TargetType(str, Enum):
    """推送目标类型"""
    ALL = "all"                    # 全部用户
    PLATFORM = "platform"          # 按平台
    LEVEL = "level"                # 按店铺等级
    INDUSTRY = "industry"          # 按行业
    REGION = "region"              # 按地区
    AGENT = "agent"                # 按坐席
    CUSTOM_TAG = "custom_tag"       # 自定义标签


class PolicyLevel(str, Enum):
    """政策重要等级"""
    URGENT = "urgent"              # 紧急
    IMPORTANT = "important"         # 重要
    NORMAL = "normal"               # 一般


# ============== 数据结构 ==============

@dataclass
class PushTarget:
    """推送目标定义"""
    target_type: TargetType
    values: List[str]              # 如 ["shopee", "lazada"] 或 ["gold", "silver"]
    exclude_values: List[str] = None  # 排除的值


@dataclass
class PolicyPush:
    """政策推送记录"""
    push_id: str
    policy_id: str
    title: str
    content: str
    url: str = None
    targets: List[PushTarget]
    created_by: str
    created_at: datetime
    sent_count: int = 0
    read_count: int = 0
    click_count: int = 0


# ============== 用户画像缓存 ==============

class UserProfileCache:
    """用户画像缓存，减少数据库查询"""
    
    def __init__(self, ttl: int = 300):  # 5分钟 TTL
        self._cache: Dict[str, Dict] = {}
        self._timestamps: Dict[str, float] = {}
        self._ttl = ttl
        self._lock = threading.Lock()
    
    def get(self, user_id: str) -> Optional[Dict]:
        """获取缓存的用户画像"""
        with self._lock:
            if user_id in self._cache:
                if datetime.now().timestamp() - self._timestamps[user_id] < self._ttl:
                    return self._cache[user_id]
                else:
                    # TTL 过期，删除
                    del self._cache[user_id]
                    del self._timestamps[user_id]
        return None
    
    def set(self, user_id: str, profile: Dict):
        """设置用户画像缓存"""
        with self._lock:
            self._cache[user_id] = profile
            self._timestamps[user_id] = datetime.now().timestamp()
    
    def invalidate(self, user_id: str = None):
        """清除缓存"""
        with self._lock:
            if user_id:
                self._cache.pop(user_id, None)
                self._timestamps.pop(user_id, None)
            else:
                self._cache.clear()
                self._timestamps.clear()


# 全局画像缓存
_profile_cache = UserProfileCache()


# ============== 画像构建 ==============

def build_seller_profile(seller_id: str) -> Dict:
    """
    构建卖家画像（用于政策分发）
    
    返回字段：
    - seller_id: 卖家ID
    - username: 用户名
    - platforms: 经营的平台列表
    - level: 店铺等级 (gold/silver/bronze/new)
    - industry: 行业分类
    - region: 地区
    - tags: 自定义标签
    - created_days: 注册天数
    """
    cached = _profile_cache.get(seller_id)
    if cached:
        return cached
    
    profile = {
        "seller_id": seller_id,
        "username": "",
        "platforms": [],
        "level": "new",
        "industry": "general",
        "region": "other",
        "tags": [],
        "created_days": 0,
        "order_count": 0,
        "total_revenue": 0.0,
    }
    
    try:
        from db import get_db
        with get_db() as (conn, cursor):
            # 查询卖家基本信息
            cursor.execute(
                "SELECT username, role, created_at FROM sellers WHERE seller_id = ? OR username = ?",
                (seller_id, seller_id)
            )
            row = cursor.fetchone()
            if row:
                cols = [d[0] for d in cursor.description]
                data = dict(zip(cols, row))
                profile["username"] = data.get("username", "")
                
                # 计算注册天数
                created_at = data.get("created_at")
                if created_at:
                    try:
                        if isinstance(created_at, str):
                            created = datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S")
                        else:
                            created = created_at
                        profile["created_days"] = (datetime.now() - created).days
                    except Exception:
                        pass
                
                # 从 role 推断等级
                role = data.get("role", "")
                if "gold" in role.lower():
                    profile["level"] = "gold"
                elif "silver" in role.lower():
                    profile["level"] = "silver"
                elif "bronze" in role.lower():
                    profile["level"] = "bronze"
                else:
                    profile["level"] = "new"
            
            # 查询店铺信息
            try:
                cursor.execute(
                    "SELECT platform, shop_name FROM shops WHERE seller_id = ? LIMIT 10",
                    (seller_id,)
                )
                for row in cursor.fetchall():
                    cols = [d[0] for d in cursor.description]
                    data = dict(zip(cols, row))
                    platform = data.get("platform", "")
                    if platform and platform not in profile["platforms"]:
                        profile["platforms"].append(platform)
            except Exception:
                pass
            
            # 查询订单统计
            try:
                cursor.execute(
                    "SELECT COUNT(*), SUM(total) FROM orders WHERE seller_id = ?",
                    (seller_id,)
                )
                row = cursor.fetchone()
                if row:
                    profile["order_count"] = row[0] or 0
                    profile["total_revenue"] = float(row[1] or 0)
            except Exception:
                pass
                
    except Exception as e:
        logger.debug(f"[PolicyPush] 构建卖家画像失败: {e}")
    
    _profile_cache.set(seller_id, profile)
    return profile


def build_agent_profile(agent_id: str) -> Dict:
    """
    构建坐席画像（用于政策分发）
    """
    cached = _profile_cache.get(agent_id)
    if cached:
        return cached
    
    profile = {
        "agent_id": agent_id,
        "role": "agent",
        "level": "normal",
        "platforms": [],
        "tags": [],
    }
    
    try:
        from db import get_db
        with get_db() as (conn, cursor):
            cursor.execute(
                "SELECT username, role, permissions FROM sellers WHERE seller_id = ? OR username = ?",
                (agent_id, agent_id)
            )
            row = cursor.fetchone()
            if row:
                cols = [d[0] for d in cursor.description]
                data = dict(zip(cols, row))
                profile["role"] = data.get("role", "agent")
                
                # 从权限推断等级
                perms = data.get("permissions", "")
                if "all" in str(perms).lower():
                    profile["level"] = "admin"
                elif "premium" in str(perms).lower():
                    profile["level"] = "senior"
    except Exception:
        pass
    
    _profile_cache.set(agent_id, profile)
    return profile


# ============== 目标匹配 ==============

def matches_target(profile: Dict, target: PushTarget) -> bool:
    """
    判断用户画像是否匹配推送目标
    """
    if target.target_type == TargetType.ALL:
        return True
    
    if target.target_type == TargetType.PLATFORM:
        profile_platforms = profile.get("platforms", [])
        return any(p in target.values for p in profile_platforms)
    
    if target.target_type == TargetType.LEVEL:
        return profile.get("level", "") in target.values
    
    if target.target_type == TargetType.INDUSTRY:
        return profile.get("industry", "") in target.values
    
    if target.target_type == TargetType.REGION:
        return profile.get("region", "") in target.values
    
    if target.target_type == TargetType.CUSTOM_TAG:
        profile_tags = profile.get("tags", [])
        return any(t in target.values for t in profile_tags)
    
    if target.target_type == TargetType.AGENT:
        return profile.get("agent_id", "") in target.values
    
    return False


def matches_any_target(profile: Dict, targets: List[PushTarget]) -> bool:
    """判断是否匹配任意一个目标"""
    if not targets:
        return True  # 无目标，匹配全部
    return any(matches_target(profile, t) for t in targets)


# ============== 推送统计 ==============

def record_push_action(push_id: str, user_id: str, action: str):
    """
    记录推送动作（发送/已读/点击）
    
    Args:
        push_id: 推送记录ID
        user_id: 用户ID
        action: sent | read | click
    """
    try:
        from db import get_db
        with get_db() as (conn, cursor):
            cursor.execute("""
                INSERT INTO policy_push_actions (push_id, user_id, action, created_at)
                VALUES (?, ?, ?, ?)
            """, (push_id, user_id, action, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            conn.commit()
    except sqlite3.OperationalError:
        # 表不存在，创建
        try:
            with get_db() as (conn, cursor):
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS policy_push_actions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        push_id TEXT NOT NULL,
                        user_id TEXT NOT NULL,
                        action TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    )
                """)
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_push_action ON policy_push_actions(push_id, action)
                """)
                conn.commit()
                cursor.execute("""
                    INSERT INTO policy_push_actions (push_id, user_id, action, created_at)
                    VALUES (?, ?, ?, ?)
                """, (push_id, user_id, action, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
                conn.commit()
        except Exception as e:
            logger.warning(f"[PolicyPush] 记录推送动作失败: {e}")
    except Exception as e:
        logger.warning(f"[PolicyPush] 记录推送动作失败: {e}")


def get_push_stats(push_id: str) -> Dict:
    """获取推送统计数据"""
    stats = {"sent": 0, "read": 0, "click": 0}
    try:
        from db import get_db
        with get_db() as (conn, cursor):
            cursor.execute("""
                SELECT action, COUNT(*) FROM policy_push_actions
                WHERE push_id = ? GROUP BY action
            """, (push_id,))
            for row in cursor.fetchall():
                action, count = row
                if action in stats:
                    stats[action] = count
    except Exception:
        pass
    return stats


# ============== 核心分发方法 ==============

class PolicyDistributionService:
    """
    政策分发服务
    
    使用示例:
        svc = PolicyDistributionService()
        
        # 发布政策
        push_id = svc.publish_policy(
            title="Shopee 新政策公告",
            content="...",
            url="https://...",
            targets=[
                PushTarget(TargetType.PLATFORM, ["shopee"]),
                PushTarget(TargetType.LEVEL, ["gold", "silver"])
            ],
            created_by="admin"
        )
        
        # 立即推送
        result = svc.push_to_matched_users(push_id)
        
        # 查询用户画像
        profile = svc.get_user_profile("seller_123")
    """
    
    def __init__(self):
        self._ensure_tables()
    
    def _ensure_tables(self):
        """确保数据库表存在"""
        try:
            from db import get_db
            with get_db() as (conn, cursor):
                # 政策推送主表
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS policy_pushes (
                        push_id TEXT PRIMARY KEY,
                        policy_id TEXT,
                        title TEXT NOT NULL,
                        content TEXT,
                        url TEXT,
                        targets_json TEXT,
                        created_by TEXT,
                        created_at TEXT,
                        status TEXT DEFAULT 'draft'
                    )
                """)
                
                # 推送动作记录表
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS policy_push_actions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        push_id TEXT NOT NULL,
                        user_id TEXT NOT NULL,
                        action TEXT NOT NULL,
                        created_at TEXT
                    )
                """)
                
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_push_action ON policy_push_actions(push_id, action)
                """)
                
                conn.commit()
        except Exception as e:
            logger.warning(f"[PolicyPush] 初始化表失败: {e}")
    
    def publish_policy(
        self,
        title: str,
        content: str,
        url: str = None,
        targets: List[PushTarget] = None,
        created_by: str = "admin",
        auto_push: bool = True,
        **kwargs
    ) -> str:
        """
        发布政策（保存草稿或立即推送）
        
        Returns:
            push_id: 推送记录ID
        """
        import uuid
        push_id = f"PP{datetime.now().strftime('%Y%m%d%H%M%S')}{str(uuid.uuid4())[:6].upper()}"
        
        targets = targets or [PushTarget(TargetType.ALL, [])]
        targets_json = json.dumps([
            {"type": t.target_type.value, "values": t.values, "exclude": t.exclude_values or []}
            for t in targets
        ], ensure_ascii=False)
        
        status = "published" if auto_push else "draft"
        
        try:
            from db import get_db
            with get_db() as (conn, cursor):
                cursor.execute("""
                    INSERT INTO policy_pushes 
                    (push_id, policy_id, title, content, url, targets_json, created_by, created_at, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (push_id, kwargs.get("policy_id"), title, content, url, targets_json, 
                      created_by, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), status))
                conn.commit()
            
            logger.info(f"[PolicyPush] 发布政策: {title} (push_id={push_id})")
            
            # 立即推送
            if auto_push:
                self.push_to_matched_users(push_id)
            
            return push_id
            
        except Exception as e:
            logger.error(f"[PolicyPush] 发布政策失败: {e}")
            raise
    
    def push_to_matched_users(self, push_id: str) -> Dict:
        """
        向匹配目标的用户推送政策
        
        Returns:
            dict: 推送结果统计
        """
        try:
            from db import get_db
            with get_db() as (conn, cursor):
                cursor.execute(
                    "SELECT title, content, url, targets_json, status FROM policy_pushes WHERE push_id = ?",
                    (push_id,)
                )
                row = cursor.fetchone()
                if not row:
                    return {"error": "推送不存在"}
                
                cols = [d[0] for d in cursor.description]
                data = dict(zip(cols, row))
                
                if data.get("status") == "completed":
                    return {"error": "已推送完成"}
                
                targets_json = data.get("targets_json", "[]")
                targets_data = json.loads(targets_json)
                targets = [
                    PushTarget(
                        target_type=TargetType(t.get("type", "all")),
                        values=t.get("values", []),
                        exclude_values=t.get("exclude", [])
                    )
                    for t in targets_data
                ]
                
                # 查询所有卖家
                cursor.execute("SELECT seller_id FROM sellers")
                all_sellers = [row[0] for row in cursor.fetchall()]
                
                # 查询所有坐席
                cursor.execute("SELECT seller_id FROM sellers WHERE role != 'seller'")
                all_agents = [row[0] for row in cursor.fetchall()]
                
                sent_count = 0
                matched_users = []
                
                for seller_id in all_sellers:
                    profile = build_seller_profile(seller_id)
                    if matches_any_target(profile, targets):
                        record_push_action(push_id, seller_id, "sent")
                        sent_count += 1
                        matched_users.append(seller_id)
                
                for agent_id in all_agents:
                    profile = build_agent_profile(agent_id)
                    if matches_any_target(profile, targets):
                        record_push_action(push_id, agent_id, "sent")
                        sent_count += 1
                        matched_users.append(agent_id)
                
                # 更新状态
                cursor.execute(
                    "UPDATE policy_pushes SET status = 'completed' WHERE push_id = ?",
                    (push_id,)
                )
                conn.commit()
                
                logger.info(f"[PolicyPush] 推送完成: push_id={push_id}, sent={sent_count}")
                
                return {
                    "push_id": push_id,
                    "title": data.get("title"),
                    "sent_count": sent_count,
                    "matched_users": matched_users[:100],  # 最多返回100个示例
                }
                
        except Exception as e:
            logger.error(f"[PolicyPush] 推送失败: {e}")
            return {"error": str(e)}
    
    def get_user_profile(self, user_id: str) -> Dict:
        """获取用户画像"""
        # 尝试卖家画像
        profile = build_seller_profile(user_id)
        if profile.get("username"):
            return profile
        
        # 尝试坐席画像
        return build_agent_profile(user_id)
    
    def record_read(self, push_id: str, user_id: str):
        """记录已读"""
        record_push_action(push_id, user_id, "read")
    
    def record_click(self, push_id: str, user_id: str):
        """记录点击"""
        record_push_action(push_id, user_id, "click")
    
    def get_push_history(self, user_id: str, limit: int = 20) -> List[Dict]:
        """获取用户的推送历史"""
        try:
            from db import get_db
            with get_db() as (conn, cursor):
                cursor.execute("""
                    SELECT DISTINCT p.push_id, p.title, p.content, p.url, p.created_at,
                           a.action, a.created_at as action_time
                    FROM policy_pushes p
                    JOIN policy_push_actions a ON p.push_id = a.push_id
                    WHERE a.user_id = ? AND a.action = 'sent'
                    ORDER BY p.created_at DESC
                    LIMIT ?
                """, (user_id, limit))
                
                results = []
                for row in cursor.fetchall():
                    cols = [d[0] for d in cursor.description]
                    results.append(dict(zip(cols, row)))
                return results
        except Exception as e:
            logger.warning(f"[PolicyPush] 获取推送历史失败: {e}")
            return []
    
    def get_dashboard_stats(self) -> Dict:
        """获取推送统计仪表盘"""
        try:
            from db import get_db
            with get_db() as (conn, cursor):
                # 总推送数
                cursor.execute("SELECT COUNT(*) FROM policy_pushes")
                total = cursor.fetchone()[0] or 0
                
                # 今日推送
                today = datetime.now().strftime("%Y-%m-%d")
                cursor.execute(
                    "SELECT COUNT(*) FROM policy_pushes WHERE created_at LIKE ?",
                    (f"{today}%",)
                )
                today_count = cursor.fetchone()[0] or 0
                
                # 总发送/已读/点击
                cursor.execute("""
                    SELECT action, COUNT(*) FROM policy_push_actions GROUP BY action
                """)
                action_stats = {row[0]: row[1] for row in cursor.fetchall()}
                
                return {
                    "total_pushes": total,
                    "today_pushes": today_count,
                    "total_sent": action_stats.get("sent", 0),
                    "total_read": action_stats.get("read", 0),
                    "total_click": action_stats.get("click", 0),
                    "read_rate": round(
                        action_stats.get("read", 0) / max(action_stats.get("sent", 1), 1) * 100, 1
                    ),
                    "click_rate": round(
                        action_stats.get("click", 0) / max(action_stats.get("sent", 1), 1) * 100, 1
                    ),
                }
        except Exception as e:
            logger.warning(f"[PolicyPush] 获取统计失败: {e}")
            return {}


# 单例
_policy_dist_service = None


def get_policy_distribution_service() -> PolicyDistributionService:
    """获取政策分发服务单例"""
    global _policy_dist_service
    if _policy_dist_service is None:
        _policy_dist_service = PolicyDistributionService()
    return _policy_dist_service
