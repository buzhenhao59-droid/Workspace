# -*- coding: utf-8 -*-
"""
Keycloak / OAuth2 OIDC 集成模块

支持:
- Authorization Code Flow（Web 应用，推荐）
- Client Credentials Flow（机器到机器 / 服务账号）
- Token 验证与 JWT 校验
- 角色映射（Realm roles + Client roles）
- 单点登出（Single Logout）

使用方式:
1. 配置 Keycloak 服务器信息到 .env
2. 在 main.py 中注册 auth router
3. 使用 Depends(get_current_user) 保护端点

参考 .env.example 中的 KEYCLOAK_* 配置项
"""
import os
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode, urljoin
import jwt
import requests
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import OAuth2AuthorizationCodeBearer
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# ============== 配置 ==============

KEYCLOAK_URL = os.getenv("KEYCLOAK_URL", "https://auth.example.com").rstrip("/")
KEYCLOAK_REALM = os.getenv("KEYCLOAK_REALM", "ruitalk")
KEYCLOAK_CLIENT_ID = os.getenv("KEYCLOAK_CLIENT_ID", "ruitalk-backend")
KEYCLOAK_CLIENT_SECRET = os.getenv("KEYCLOAK_CLIENT_SECRET", "")
KEYCLOAK_SCOPES = os.getenv("KEYCLOAK_SCOPES", "openid profile email roles")
KEYCLOAK_ALLOWED_ORIGINS = [
    o.strip()
    for o in os.getenv("KEYCLOAK_ALLOWED_ORIGINS", "").split(",")
    if o.strip()
]

# Keycloak OIDC 端点
_keycloak_openid_url = f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}"
KEYCLOAK_ISSUER = _keycloak_openid_url
KEYCLOAK_JWKS_URI = f"{_keycloak_openid_url}/protocol/openid-connect/certs"
KEYCLOAK_TOKEN_URL = f"{_keycloak_openid_url}/protocol/openid-connect/token"
KEYCLOAK_USERINFO_URL = f"{_keycloak_openid_url}/protocol/openid-connect/userinfo"
KEYCLOAK_LOGOUT_URL = f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/logout"
KEYCLOAK_AUTH_URL = f"{_keycloak_openid_url}/protocol/openid-connect/auth"


# ============== 数据模型 ==============

class KeycloakUser(BaseModel):
    """Keycloak 用户信息（从 token/userinfo 解析）"""
    sub: str                      # 用户唯一 ID（对应 Keycloak user uuid）
    email: Optional[str] = None
    email_verified: bool = False
    name: Optional[str] = None
    preferred_username: Optional[str] = None
    given_name: Optional[str] = None
    family_name: Optional[str] = None
    realm_roles: List[str] = []   # Realm-level 角色
    client_roles: Dict[str, List[str]] = {}  # Client-specific 角色
    tenant_id: Optional[str] = None  # 自定义属性映射
    exp: Optional[int] = None

    @property
    def user_id(self) -> str:
        return self.sub

    @property
    def is_admin(self) -> bool:
        return "admin" in self.realm_roles or "ADMIN" in self.realm_roles

    def has_role(self, role: str) -> bool:
        return role in self.realm_roles or any(
            role in roles for roles in self.client_roles.values()
        )


class KeycloakTokenResponse(BaseModel):
    access_token: str
    refresh_token: Optional[str] = None
    id_token: Optional[str] = None
    token_type: str
    expires_in: int
    refresh_expires_in: Optional[int] = None
    scope: Optional[str] = None


# ============== Keycloak 客户端 ==============

class KeycloakClient:
    """
    Keycloak OIDC 客户端

    提供 token 获取、验证、刷新、用户信息查询、单点登出功能
    """

    def __init__(
        self,
        client_id: str = KEYCLOAK_CLIENT_ID,
        client_secret: str = KEYCLOAK_CLIENT_SECRET,
        realm: str = KEYCLOAK_REALM,
        issuer: str = KEYCLOAK_ISSUER,
        jwks_uri: str = KEYCLOAK_JWKS_URI,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.realm = realm
        self.issuer = issuer
        self._jwks_uri = jwks_uri
        self._jwks_cache: Optional[Dict] = None
        self._jwks_cache_expires: datetime = datetime.min
        self._jwks_cache_ttl = timedelta(minutes=15)

    # ---- Token Operations ----

    def get_token_by_code(
        self,
        code: str,
        redirect_uri: str,
        code_verifier: Optional[str] = None,
    ) -> KeycloakTokenResponse:
        """
        Authorization Code Flow：使用授权码交换 access token

        Args:
            code: 授权码（来自 Keycloak 重定向）
            redirect_uri: 必须与授权请求中的 redirect_uri 完全一致
            code_verifier: PKCE code verifier（如果授权时使用了 PKCE）
        """
        data = {
            "grant_type": "authorization_code",
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
        }
        if self.client_secret:
            data["client_secret"] = self.client_secret
        if code_verifier:
            data["code_verifier"] = code_verifier

        resp = requests.post(KEYCLOAK_TOKEN_URL, data=data, timeout=10)
        resp.raise_for_status()
        return KeycloakTokenResponse(**resp.json())

    def get_token_client_credentials(self) -> KeycloakTokenResponse:
        """
        Client Credentials Flow：用于服务账号（机器到机器）

        示例: AI 客服自动回复服务使用此方式获取 token
        """
        data = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scope": KEYCLOAK_SCOPES,
        }
        resp = requests.post(KEYCLOAK_TOKEN_URL, data=data, timeout=10)
        resp.raise_for_status()
        return KeycloakTokenResponse(**resp.json())

    def refresh_token(self, refresh_token_str: str) -> KeycloakTokenResponse:
        """刷新 access token"""
        data = {
            "grant_type": "refresh_token",
            "client_id": self.client_id,
            "refresh_token": refresh_token_str,
        }
        if self.client_secret:
            data["client_secret"] = self.client_secret

        resp = requests.post(KEYCLOAK_TOKEN_URL, data=data, timeout=10)
        resp.raise_for_status()
        return KeycloakTokenResponse(**resp.json())

    def logout(self, refresh_token_str: str, id_token: Optional[str] = None) -> bool:
        """单点登出（使 refresh token 失效）"""
        data = {
            "client_id": self.client_id,
            "refresh_token": refresh_token_str,
        }
        if id_token:
            data["id_token_hint"] = id_token
        if self.client_secret:
            data["client_secret"] = self.client_secret

        try:
            resp = requests.post(KEYCLOAK_LOGOUT_URL, data=data, timeout=10)
            return resp.status_code in (200, 204, 400)
        except Exception as e:
            logger.warning(f"Keycloak logout failed: {e}")
            return False

    # ---- Token 验证 ----

    def _get_jwks(self) -> Dict:
        """获取 JWKS（带缓存）"""
        now = datetime.now(timezone.utc)
        if self._jwks_cache and now < self._jwks_cache_expires:
            return self._jwks_cache

        try:
            resp = requests.get(self._jwks_uri, timeout=10)
            resp.raise_for_status()
            self._jwks_cache = resp.json()
            self._jwks_cache_expires = now + self._jwks_cache_ttl
            return self._jwks_cache
        except Exception as e:
            if self._jwks_cache:
                logger.warning(f"JWKS 刷新失败，使用缓存: {e}")
                return self._jwks_cache
            raise

    def verify_token(self, token: str) -> KeycloakUser:
        """
        验证 JWT token（使用 Keycloak JWKS）

        支持 RS256 签名算法（Keycloak 默认）
        验证: iss, aud, exp, iat, auth_time
        """
        try:
            # 自动发现密钥
            jwks = self._get_jwks()
            unverified_header = jwt.get_unverified_header(token)

            key = next(
                (k for k in jwks.get("keys", []) if k["kid"] == unverified_header["kid"]),
                None,
            )
            if not key:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token signing key not found",
                )

            # 构建公钥
            public_key = jwt.algorithms.RSAAlgorithm.from_jwk(key)

            payload = jwt.decode(
                token,
                public_key,
                algorithms=["RS256"],
                audience=self.client_id,
                issuer=self.issuer,
                options={
                    "verify_exp": True,
                    "verify_iat": True,
                    "verify_auth_time": True,
                    "require": ["exp", "iat", "sub"],
                },
            )

            return self._parse_keycloak_payload(payload)

        except jwt.ExpiredSignatureError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token 已过期，请刷新",
            )
        except jwt.InvalidAudienceError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token audience 无效",
            )
        except jwt.InvalidIssuerError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token issuer 无效",
            )
        except Exception as e:
            logger.warning(f"Token 验证失败: {e}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token 无效",
            )

    def _parse_keycloak_payload(self, payload: Dict[str, Any]) -> KeycloakUser:
        """解析 Keycloak JWT payload 为 KeycloakUser"""
        realm_access = payload.get("realm_access", {})
        resource_access = payload.get("resource_access", {})

        realm_roles: List[str] = realm_access.get("roles", [])
        client_roles: Dict[str, List[str]] = {}
        if self.client_id in resource_access:
            client_roles = {
                self.client_id: resource_access[self.client_id].get("roles", [])
            }

        return KeycloakUser(
            sub=payload["sub"],
            email=payload.get("email"),
            email_verified=payload.get("email_verified", False),
            name=payload.get("name"),
            preferred_username=payload.get("preferred_username"),
            given_name=payload.get("given_name"),
            family_name=payload.get("family_name"),
            realm_roles=realm_roles,
            client_roles=client_roles,
            tenant_id=payload.get("tenant_id"),
            exp=payload.get("exp"),
        )

    def get_userinfo(self, access_token: str) -> KeycloakUser:
        """通过 UserInfo 端点获取用户详情"""
        resp = requests.get(
            KEYCLOAK_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
        resp.raise_for_status()
        payload = resp.json()
        return self._parse_keycloak_payload(payload)


# ============== 全局单例 ==============

_keycloak_client: Optional[KeycloakClient] = None


def get_keycloak_client() -> KeycloakClient:
    global _keycloak_client
    if _keycloak_client is None:
        _keycloak_client = KeycloakClient()
    return _keycloak_client


# ============== FastAPI 依赖 ==============

# 延迟初始化，避免导入时 .env 未加载
_oauth2_scheme: Optional[OAuth2AuthorizationCodeBearer] = None


def get_oauth2_scheme():
    global _oauth2_scheme
    if _oauth2_scheme is None:
        _oauth2_scheme = OAuth2AuthorizationCodeBearer(
            authorizationUrl=f"{KEYCLOAK_AUTH_URL}?client_id={KEYCLOAK_CLIENT_ID}",
            tokenUrl=KEYCLOAK_TOKEN_URL,
            auto_error=False,
        )
    return _oauth2_scheme


async def get_current_user(
    token: Optional[str] = Depends(get_oauth2_scheme()),
) -> KeycloakUser:
    """
    FastAPI 依赖：从 Bearer token 获取当前 Keycloak 用户

    用法:
        @app.get("/api/v1/admin/users")
        async def list_users(user: KeycloakUser = Depends(get_current_user)):
            if not user.is_admin:
                raise HTTPException(403, "需要管理员权限")
            ...
    """
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未提供认证令牌",
            headers={"WWW-Authenticate": "Bearer"},
        )

    client = get_keycloak_client()
    return client.verify_token(token)


async def get_current_active_user(
    user: KeycloakUser = Depends(get_current_user),
) -> KeycloakUser:
    """验证用户是否激活（可扩展）"""
    return user


# ============== OAuth2 授权 URL 生成 ==============

def build_authorization_url(
    redirect_uri: str,
    state: Optional[str] = None,
    nonce: Optional[str] = None,
    pkce_code_challenge: Optional[str] = None,
) -> str:
    """
    构建 Keycloak 授权 URL（Authorization Code Flow）

    返回格式:
        {KEYCLOAK_URL}/realms/{REALM}/protocol/openid-connect/auth
            ?client_id=...
            &redirect_uri=...
            &response_type=code
            &scope=openid+profile+email+roles
            &state=...
            &nonce=...
            &code_challenge=...（PKCE）
            &code_challenge_method=S256
    """
    params = {
        "client_id": KEYCLOAK_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": KEYCLOAK_SCOPES,
    }
    if state:
        params["state"] = state
    if nonce:
        params["nonce"] = nonce
    if pkce_code_challenge:
        params["code_challenge"] = pkce_code_challenge
        params["code_challenge_method"] = "S256"

    return f"{KEYCLOAK_AUTH_URL}?{urlencode(params)}"


# ============== 与现有 JWT 系统的桥接 ==============

def keycloak_user_to_claims(user: KeycloakUser) -> Dict[str, Any]:
    """
    将 Keycloak 用户映射为现有 JWT claims 格式

    这样可以复用现有的 JWT 认证中间件
    """
    return {
        "sub": user.sub,
        "email": user.email,
        "name": user.name,
        "role": "admin" if user.is_admin else "user",
        "tenant_id": user.tenant_id,
        "realm_roles": user.realm_roles,
        "client_roles": user.client_roles,
        "idp": "keycloak",
    }
