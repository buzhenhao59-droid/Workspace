# -*- coding: utf-8 -*-
"""
MySQL TLS/SSL 加密连接支持

使用方法:
1. 获取 MySQL 服务器 CA 证书
2. 设置环境变量或修改配置
3. 连接自动使用 TLS

生产部署建议:
- 使用 MySQL 8.0+，强制 TLS 1.2+
- CA 证书存放在容器不可变层（不随代码变更）
- TLS 证书路径通过 Docker Secret 或 K8s Secret 挂载
"""
import os
import ssl
import logging
from typing import Optional
from pathlib import Path

logger = logging.getLogger(__name__)

# ============== TLS 配置 ==============

class MySQLTLSConfig:
    """
    MySQL TLS 连接配置

    环境变量:
        MYSQL_SSL_MODE: verify_identity | verify_ca | required | disabled
        MYSQL_SSL_CA: CA 证书路径（pem 格式）
        MYSQL_SSL_CERT: 客户端证书路径（mTLS 用）
        MYSQL_SSL_KEY: 客户端私钥路径（mTLS 用）
    """

    DISABLED = "disabled"
    REQUIRED = "required"
    VERIFY_CA = "verify_ca"
    VERIFY_IDENTITY = "verify_identity"

    def __init__(
        self,
        mode: Optional[str] = None,
        ca_cert_path: Optional[str] = None,
        client_cert_path: Optional[str] = None,
        client_key_path: Optional[str] = None,
    ):
        self.mode = mode or os.getenv("MYSQL_SSL_MODE", self.DISABLED)
        self.ca_cert_path = ca_cert_path or os.getenv("MYSQL_SSL_CA", "")
        self.client_cert_path = client_cert_path or os.getenv("MYSQL_SSL_CERT", "")
        self.client_key_path = client_key_path or os.getenv("MYSQL_SSL_KEY", "")

    @property
    def is_enabled(self) -> bool:
        return self.mode != self.DISABLED

    def get_ssl_context(self) -> Optional[ssl.SSLContext]:
        """构建 Python ssl.SSLContext（用于 pymysql）"""
        if not self.is_enabled:
            return None

        try:
            ctx = ssl.create_default_context(
                purpose=ssl.Purpose.SERVER_AUTH,
                cafile=self.ca_cert_path or None,
            )

            if self.client_cert_path and self.client_key_path:
                ctx.load_cert_chain(
                    certfile=self.client_cert_path,
                    keyfile=self.client_key_path,
                )

            # MySQL 要求 TLS 1.2+
            ctx.minimum_version = ssl.TLSVersion.TLSv1_2

            logger.info(
                f"MySQL TLS enabled: mode={self.mode}, "
                f"ca={self.ca_cert_path}, mTLS={bool(self.client_cert_path)}"
            )
            return ctx

        except FileNotFoundError as e:
            logger.error(f"MySQL TLS 证书文件未找到: {e}")
            raise
        except Exception as e:
            logger.error(f"MySQL TLS 上下文创建失败: {e}")
            raise

    def get_pymysql_ssl_args(self) -> dict:
        """返回 pymysql.connect() 可用的 ssl 参数"""
        if not self.is_enabled:
            return {}

        return {
            "ssl": self.get_ssl_context(),
            # pymysql 也可以直接传 ssl 参数字典
            # "ssl": {"ca": self.ca_cert_path, "check_hostname": True},
        }

    def validate(self) -> list:
        """验证 TLS 配置，返回错误列表（空=有效）"""
        errors = []

        if not self.is_enabled:
            return errors

        if self.mode in (self.VERIFY_CA, self.VERIFY_IDENTITY):
            if not self.ca_cert_path:
                errors.append("MYSQL_SSL_CA 证书路径未设置（verify_ca/verify_identity 模式必需）")
            elif not Path(self.ca_cert_path).exists():
                errors.append(f"MYSQL_SSL_CA 证书不存在: {self.ca_cert_path}")

        if self.client_cert_path and not Path(self.client_cert_path).exists():
            errors.append(f"MYSQL_SSL_CERT 证书不存在: {self.client_cert_path}")

        if self.client_key_path and not Path(self.client_key_path).exists():
            errors.append(f"MYSQL_SSL_KEY 私钥不存在: {self.client_key_path}")

        return errors


# ============== 全局单例 ==============

_mysql_tls_config: Optional[MySQLTLSConfig] = None


def get_mysql_tls_config() -> MySQLTLSConfig:
    global _mysql_tls_config
    if _mysql_tls_config is None:
        _mysql_tls_config = MySQLTLSConfig()
    return _mysql_tls_config


# ============== MySQL 连接字符串（支持 TLS）==============

def build_mysql_connection_url(
    host: str,
    port: int,
    user: str,
    password: str,
    database: str,
    ssl_mode: str = "disabled",
    ssl_ca: str = "",
) -> str:
    """
    构建 MySQL 连接 URL，支持 TLS 参数

    示例（生产 TLS）:
        mysql+pymysql://user:pass@host:3306/db?ssl_mode=verify_ca&ssl_ca=/certs/ca.pem
    """
    from urllib.parse import quote_plus

    user_part = quote_plus(user)
    pass_part = quote_plus(password)

    url = f"mysql+pymysql://{user_part}:{pass_part}@{host}:{port}/{database}"

    params = []
    if ssl_mode and ssl_mode != "disabled":
        params.append(f"ssl_mode={ssl_mode}")
        if ssl_ca:
            params.append(f"ssl_ca={quote_plus(ssl_ca)}")

    if params:
        url += "?" + "&".join(params)

    return url


# ============== Docker / K8s TLS 证书挂载示例 ==============

"""
# docker-compose.yml 中添加（示例）
services:
  seller:
    volumes:
      - ./certs/mysql-ca.pem:/certs/mysql-ca.pem:ro
      - ./certs/mysql-client-cert.pem:/certs/mysql-client-cert.pem:ro
      - ./certs/mysql-client-key.pem:/certs/mysql-client-key.pem:ro
    environment:
      MYSQL_SSL_MODE: verify_identity
      MYSQL_SSL_CA: /certs/mysql-ca.pem
      MYSQL_SSL_CERT: /certs/mysql-client-cert.pem
      MYSQL_SSL_KEY: /certs/mysql-client-key.pem

# Kubernetes Secret 示例
# kubectl create secret generic mysql-tls \
#   --from-file=ca.pem=./certs/mysql-ca.pem \
#   --from-file=client-cert.pem=./certs/mysql-client-cert.pem \
#   --from-file=client-key.pem=./certs/mysql-client-key.pem
"""

# ============== MySQL 服务器端强制 TLS 配置（参考）==============

"""
-- 在 MySQL 服务器上执行（生产环境）
-- 1. 要求所有连接使用 TLS
ALTER USER 'ruitalk_app'@'%' REQUIRE SSL;

-- 2. 仅允许 TLS 1.2+，限制加密套件
ALTER USER 'ruitalk_app'@'%'
  REQUIRE SUBJECT '/CN=ruitalk-app/O=Ruitalk/C=CN'
  AND ISSUER '/CN=MySQL CA/O=Ruitalk/C=CN'
  AND CIPHER 'TLS_AES_256_GCM_SHA384';

-- 3. 创建应用专用用户（最小权限原则）
CREATE USER IF NOT EXISTS 'ruitalk_app'@'%'
  IDENTIFIED BY 'strong_random_password'
  REQUIRE SSL
  WITH MAX_QUERIES_PER_HOUR 1000
       MAX_UPDATES_PER_HOUR 100
       MAX_CONNECTIONS_PER_HOUR 50;

GRANT SELECT, INSERT, UPDATE, DELETE ON ruitalk.* TO 'ruitalk_app'@'%';
"""
