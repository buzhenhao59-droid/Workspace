# -*- coding: utf-8 -*-
"""
HashiCorp Vault 密钥管理集成

支持:
- Vault Agent 侧载（Agent Sidecar，最推荐）
- 直接 Vault API 调用（Vault Server Sidecar 模式）
- 环境变量回退（Vault 不可用时降级）
- 动态数据库凭证（MySQL 动态用户名/密码）
- KV v2 密钥路径管理
- 自动续期 Lease

使用方式:
1. 生产环境: 启用 Vault Agent 作为 sidecar，自动将密钥注入到 /vault/secrets/
2. 开发环境: 回退到 .env 环境变量

参考 .env.example 中的 VAULT_* 配置项
"""
import os
import logging
import time
from typing import Optional, Dict, Any
from pathlib import Path
from contextlib import contextmanager
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# ============== 配置 ==============

VAULT_ENABLED = os.getenv("VAULT_ENABLED", "false").lower() == "true"
VAULT_ADDR = os.getenv("VAULT_ADDR", "https://vault.example.com:8200")
VAULT_TOKEN = os.getenv("VAULT_TOKEN", "")
VAULT_ROLE = os.getenv("VAULT_ROLE", "ruitalk-backend")
VAULT_KV_PREFIX = os.getenv("VAULT_KV_PREFIX", "secret/ruitalk")
VAULT_AUTH_METHOD = os.getenv("VAULT_AUTH_METHOD", "token")  # token | kubernetes | aws | gcp
VAULT_MOUNT_PATH = os.getenv("VAULT_MOUNT_PATH", "/run/secrets/sidecar")  # Agent 侧载路径


# ============== Vault Agent 侧载（推荐模式）==============

@dataclass
class VaultSecret:
    """Vault 密钥响应"""
    data: Dict[str, Any]
    lease_id: Optional[str] = None
    lease_duration: Optional[int] = None  # 秒
    expires_at: Optional[float] = None  # Unix timestamp


class VaultAgentLoader:
    """
    Vault Agent Sidecar 密钥加载器

    Vault Agent 会将密钥以文件形式写到指定目录:
        /vault/secrets/
            ├── mysql-password     (plain text value)
            ├── deepseek-api-key   (plain text value)
            └── db-creds.json      (JSON 格式)

    此加载器读取这些文件，提供与直接读取环境变量相同的接口。
    """

    def __init__(self, secret_dir: str = None):
        self.secret_dir = Path(secret_dir or VAULT_MOUNT_PATH)

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """
        获取密钥值

        优先级:
            1. Vault Agent 文件 (/vault/secrets/{key})
            2. 环境变量 (VAULT_PREFIXED_KEY)
            3. 直接环境变量
            4. default
        """
        # 1. Agent 文件
        secret_file = self.secret_dir / key
        if secret_file.exists():
            try:
                return secret_file.read_text(encoding="utf-8").strip()
            except Exception as e:
                logger.warning(f"读取 Vault Agent 文件失败 {secret_file}: {e}")

        # 2. VAULT_ 前缀环境变量
        val = os.getenv(f"VAULT_{key.upper()}")
        if val:
            return val

        # 3. 直接环境变量
        val = os.getenv(key)
        if val:
            return val

        return default

    def get_json(self, key: str) -> Dict[str, Any]:
        """获取 JSON 格式密钥"""
        import json
        content = self.get(key)
        if content:
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                logger.warning(f"Vault key '{key}' 不是有效的 JSON")
        return {}

    def get_all(self) -> Dict[str, str]:
        """获取所有 Agent 目录下的密钥"""
        result = {}
        if self.secret_dir.exists():
            for f in self.secret_dir.iterdir():
                if f.is_file():
                    try:
                        result[f.name] = f.read_text(encoding="utf-8").strip()
                    except Exception as e:
                        logger.warning(f"读取 {f} 失败: {e}")
        return result

    def is_available(self) -> bool:
        return self.secret_dir.exists() and any(self.secret_dir.iterdir())


# ============== Vault Server API 客户端 ==============

class VaultAPIClient:
    """
    Vault Server 直连客户端

    当 Vault Agent 不可用时（如开发环境），此客户端直接调用 Vault API。

    支持:
    - KV v2 密钥读写
    - Kubernetes Service Account 认证（k8s）
    - Token 认证
    - Lease 续期
    """

    def __init__(
        self,
        addr: str = VAULT_ADDR,
        token: str = VAULT_TOKEN,
        kv_prefix: str = VAULT_KV_PREFIX,
        timeout: int = 10,
    ):
        self.addr = addr.rstrip("/")
        self.token = token
        self.kv_prefix = kv_prefix
        self.timeout = timeout
        self._session = self._create_session()

    def _create_session(self):
        import requests
        session = requests.Session()
        session.headers["X-Vault-Token"] = self.token
        return session

    @property
    def _kv_base(self) -> str:
        return f"{self.addr}/v1/{self.kv_prefix}"

    def read_secret(self, path: str) -> Optional[VaultSecret]:
        """
        读取 KV v2 密钥

        Args:
            path: 密钥路径（不含 kv_prefix 前缀）
                  例如: "database/mysql" → "secret/ruitalk/database/mysql"

        Returns:
            VaultSecret 或 None（密钥不存在）
        """
        url = f"{self._kv_base}/{path}"
        try:
            resp = self._session.get(url, timeout=self.timeout)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            raw = resp.json()

            return VaultSecret(
                data=raw["data"]["data"],
                lease_id=raw.get("lease_id"),
                lease_duration=raw.get("lease_duration"),
                expires_at=time.time() + raw.get("lease_duration", 0) if raw.get("lease_duration") else None,
            )
        except Exception as e:
            logger.error(f"Vault read failed for {path}: {e}")
            return None

    def list_secrets(self, path: str = "") -> list:
        """列出密钥路径下的所有键"""
        url = f"{self._kv_base}/{path}"
        try:
            resp = self._session.list(url, timeout=self.timeout)
            resp.raise_for_status()
            return resp.json().get("data", {}).get("keys", [])
        except Exception:
            return []

    def write_secret(self, path: str, data: Dict[str, Any]) -> bool:
        """写入 KV v2 密钥"""
        url = f"{self._kv_base}/{path}"
        try:
            resp = self._session.post(url, json=data, timeout=self.timeout)
            resp.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"Vault write failed for {path}: {e}")
            return False

    def renew_lease(self, lease_id: str) -> bool:
        """续期 Lease（用于动态凭证）"""
        try:
            resp = self._session.post(
                f"{self.addr}/v1/sys/leases/renew",
                json={"lease_id": lease_id},
                timeout=self.timeout,
            )
            return resp.status_code in (200, 204)
        except Exception as e:
            logger.warning(f"Vault lease renewal failed: {e}")
            return False


# ============== 动态数据库凭证（MySQL）==============

class VaultDynamicDBClient:
    """
    Vault Database Secrets Engine 客户端

    动态生成 MySQL 用户名/密码，TTL 内自动续期。
    避免在代码中硬编码 MySQL 密码。

    Vault 配置参考:
        vault secrets enable database
        vault write database/config/my-mysql \
            plugin_name=mysql-aurora-database-plugin \
            connection_url="{{username}}:{{password}}@tcp(mysql:3306)/" \
            allowed_roles="ruitalk-role"
        vault write database/roles/ruitalk-role \
            db_name=my-mysql \
            creation_statements="CREATE USER '{{name}}'@'%' IDENTIFIED BY '{{password}}'; GRANT ALL ON ruitalk.* TO '{{name}}'@'%';" \
            default_ttl=1h \
            max_ttl=24h
    """

    def __init__(self, vault_client: VaultAPIClient, role: str = VAULT_ROLE):
        self.vault = vault_client
        self.role = role
        self._creds: Optional[VaultSecret] = None
        self._creds_path = "database/creds"

    @contextmanager
    def get_mysql_credentials(self):
        """
        获取 MySQL 动态凭证（上下文管理器，自动归还）

        用法:
            with vault_db.get_mysql_credentials() as creds:
                conn = pymysql.connect(
                    user=creds["username"],
                    password=creds["password"],
                    host="mysql-seller",
                    database="ruitalk",
                )
        """
        secret = self.vault.read_secret(f"{self._creds_path}/{self.role}")
        if not secret:
            raise RuntimeError(f"Vault 无法获取数据库凭证（role={self.role}）")

        try:
            yield secret.data
        finally:
            # Lease 自动过期，但主动吊销更安全
            if secret.lease_id:
                try:
                    self.vault._session.post(
                        f"{self.vault.addr}/v1/sys/leases/revoke",
                        json={"lease_id": secret.lease_id},
                        timeout=5,
                    )
                except Exception as e:
                    logger.warning(f"MySQL 凭证归还失败: {e}")

    def refresh_if_needed(self):
        """检查凭证是否快过期，必要时刷新"""
        if self._creds and self._creds.expires_at:
            remaining = self._creds.expires_at - time.time()
            if remaining < 300:  # 剩余 5 分钟时刷新
                logger.info("MySQL 动态凭证即将过期，触发续期")


# ============== 全局单例（统一 API）==============

_vault_agent: Optional[VaultAgentLoader] = None
_vault_api: Optional[VaultAPIClient] = None


def get_vault() -> VaultAgentLoader:
    """
    获取 Vault 访问接口（优先 Agent 模式）

    自动降级:
        Vault Agent → Vault API → 环境变量
    """
    global _vault_agent

    if _vault_agent is None:
        _vault_agent = VaultAgentLoader()

    return _vault_agent


def get_secret(key: str, default: Optional[str] = None) -> Optional[str]:
    """
    统一密钥读取接口

    等同于: os.getenv(key) 或从 Vault Agent/API 获取
    """
    vault = get_vault()
    return vault.get(key, default)


def get_secret_json(key: str) -> Dict[str, Any]:
    """统一 JSON 密钥读取"""
    vault = get_vault()
    return vault.get_json(key)


# ============== 初始化时验证 Vault 连接 ==============

def validate_vault_connection() -> Dict[str, Any]:
    """启动时验证 Vault 是否可用（仅在 VAULT_ENABLED=true 时）"""
    if not VAULT_ENABLED:
        return {"status": "skipped", "reason": "VAULT_ENABLED=false"}

    vault = get_vault()
    if vault.is_available():
        secrets = vault.get_all()
        return {
            "status": "ok",
            "mode": "agent",
            "secret_count": len(secrets),
            "keys": list(secrets.keys()),
        }

    # 尝试 API 模式
    try:
        global _vault_api
        _vault_api = VaultAPIClient()
        resp = _vault_api._session.get(
            f"{VAULT_ADDR}/v1/sys/health",
            timeout=5,
        )
        if resp.status_code in (200, 429):  # 429 = sealed
            return {"status": "ok", "mode": "api", "sealed": resp.status_code == 429}
    except Exception as e:
        return {"status": "error", "reason": str(e)}

    return {"status": "error", "reason": "Vault 不可用，将使用环境变量"}


# ============== .env 示例配置 ==============

"""
# HashiCorp Vault 配置
VAULT_ENABLED=true                                    # 启用 Vault
VAULT_ADDR=https://vault.example.com:8200            # Vault 服务器地址
VAULT_TOKEN=                                          # Vault Token（不推荐，用 k8s SA 代替）
VAULT_ROLE=ruitalk-backend                            # Kubernetes ServiceAccount Role
VAULT_KV_PREFIX=secret/ruitalk                         # KV v2 密钥前缀
VAULT_AUTH_METHOD=kubernetes                          # 认证方式: token | kubernetes | aws
VAULT_MOUNT_PATH=/run/secrets/sidecar                 # Agent 侧载文件目录

# K8s 部署时，通过 ServiceAccount Token 自动认证
# pod spec:
#   serviceAccountName: ruitalk-vault-sa
#   volumes:
#   - name: vault-token
#     projected:
#       sources:
#       - serviceAccountToken:
#           audience: vault
#           expirationSeconds: 3600
#           fileMode: 0600
#   - name: vault-secrets      # Vault Agent 输出
#     emptyDir: {}
#   containers:
#   - name: seller
#     volumeMounts:
#     - name: vault-token
#       mountPath: /var/run/secrets/tokens
#     - name: vault-secrets
#       mountPath: /run/secrets/sidecar
#     env:
#     - name: VAULT_ENABLED
#       value: "true"
#     - name: VAULT_AUTH_METHOD
#       value: "kubernetes"
"""
