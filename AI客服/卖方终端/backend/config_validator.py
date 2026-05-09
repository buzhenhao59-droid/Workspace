# -*- coding: utf-8 -*-
"""
.env 配置文件校验脚本
启动时自动检查所有必填配置项

使用方法：
    # 仅检查
    python config_validator.py
    
    # 严格模式（缺失必填项会抛出异常）
    python config_validator.py --strict
    
    # 在代码中调用
    from config_validator import validate_config, enforce_config
    
    result = validate_config(strict=False)
    if not result["valid"]:
        print("配置错误:", result["errors"])
"""

import os
import sys
import json
import argparse
from typing import Dict, List, Any, Optional
from pathlib import Path


class ConfigValidator:
    """配置验证器"""
    
    # 配置项定义
    CONFIG_DEFINITIONS = {
        # 必填项（生产环境必须配置）
        "required": {
            "DEEPSEEK_API_KEY": {
                "type": str,
                "description": "DeepSeek API 密钥",
                "example": "sk-xxxxxxxxxxxxxxxx"
            },
            "MYSQL_PASSWORD": {
                "type": str,
                "description": "MySQL 数据库密码",
                "min_length": 6,
                "warning": "生产环境请使用强密码"
            },
            "SECRET_KEY": {
                "type": str,
                "description": "应用密钥",
                "min_length": 32,
                "warning": "生产环境请使用随机密钥"
            }
        },
        
        # 推荐项（未配置会有警告）
        "recommended": {
            "REDIS_PASSWORD": {
                "type": str,
                "description": "Redis 密码"
            },
            "JWT_SECRET_KEY": {
                "type": str,
                "description": "JWT 签名密钥",
                "min_length": 64,
                "warning": "生产环境请使用随机密钥"
            },
            "ADMIN_PASSWORD_SALT": {
                "type": str,
                "description": "密码哈希盐",
                "min_length": 32,
                "warning": "生产环境请使用随机盐值"
            },
            "ADMIN_PASSWORD": {
                "type": str,
                "description": "管理员密码",
                "warning": "生产环境请修改默认密码"
            }
        },
        
        # 可选项（有默认值）
        "optional": {
            "NEO4J_URI": {
                "type": str,
                "default": "neo4j+s://xxx.databases.neo4j.io",
                "description": "Neo4j 数据库 URI"
            },
            "REDIS_HOST": {
                "type": str,
                "default": "127.0.0.1",
                "description": "Redis 主机"
            },
            "REDIS_PORT": {
                "type": int,
                "default": 6379,
                "description": "Redis 端口"
            },
            "FASTAPI_PORT": {
                "type": int,
                "default": 8000,
                "description": "服务端口"
            }
        }
    }
    
    def __init__(self, env_path: str = None):
        if env_path is None:
            # 查找 .env 文件（从当前文件向上逐级查找）
            script_dir = Path(__file__).resolve().parent
            possible_paths = [
                script_dir.parent.parent.parent / ".env",  # 项目根目录
                script_dir.parent.parent / ".env",         # 卖方终端上级
                script_dir.parent / ".env",                # backend 本地
                Path.cwd() / ".env",                       # 当前工作目录
            ]
            for p in possible_paths:
                if p.exists():
                    env_path = str(p)
                    break
        
        self.env_path = env_path
        self.config = {}
        self.errors: List[Dict[str, Any]] = []
        self.warnings: List[Dict[str, Any]] = []
        
    def load_config(self) -> None:
        """从环境变量和 .env 文件加载配置"""
        # 先尝试加载 .env 文件
        if self.env_path and os.path.exists(self.env_path):
            from dotenv import load_dotenv
            load_dotenv(self.env_path)
        
        # 加载所有配置
        for category in self.CONFIG_DEFINITIONS.values():
            for key, definition in category.items():
                value = os.getenv(key)
                
                # 处理类型转换
                if value:
                    expected_type = definition.get("type", str)
                    try:
                        if expected_type == int:
                            value = int(value)
                        elif expected_type == float:
                            value = float(value)
                        elif expected_type == bool:
                            value = value.lower() in ("true", "1", "yes")
                    except (ValueError, TypeError):
                        self.errors.append({
                            "key": key,
                            "message": f"值 '{value}' 无法转换为 {expected_type.__name__}",
                            "severity": "error"
                        })
                        continue
                
                self.config[key] = value or definition.get("default")
    
    def validate(self, strict: bool = False) -> Dict[str, Any]:
        """
        验证配置
        
        Args:
            strict: 严格模式，未配置必填项会抛出异常
            
        Returns:
            验证结果字典
        """
        self.errors = []
        self.warnings = []
        
        # 加载配置
        self.load_config()
        
        # 检查必填项
        for key, definition in self.CONFIG_DEFINITIONS["required"].items():
            value = self.config.get(key)
            
            if not value:
                self.errors.append({
                    "key": key,
                    "message": f"缺少必填配置: {key} - {definition['description']}",
                    "severity": "error",
                    "suggestion": f"请在 .env 文件中设置 {key}"
                })
                continue
            
            # 检查最小长度
            min_len = definition.get("min_length", 0)
            if min_len and len(str(value)) < min_len:
                self.errors.append({
                    "key": key,
                    "message": f"{key} 太短（最小 {min_len} 字符）",
                    "severity": "error"
                })
        
        # 检查推荐项
        for key, definition in self.CONFIG_DEFINITIONS["recommended"].items():
            value = self.config.get(key)
            
            if not value:
                warning_msg = definition.get("warning", f"建议配置: {key} - {definition['description']}")
                self.warnings.append({
                    "key": key,
                    "message": warning_msg,
                    "severity": "warning",
                    "suggestion": f"请在 .env 文件中设置 {key}"
                })
        
        # 检测弱密码
        self._check_weak_passwords()
        
        result = {
            "valid": len(self.errors) == 0,
            "errors": self.errors,
            "warnings": self.warnings,
            "config": self.config
        }
        
        if strict and not result["valid"]:
            raise ConfigValidationError(result["errors"])
        
        return result
    
    def _check_weak_passwords(self) -> None:
        """检查弱密码"""
        weak_passwords = [
            "123456", "123456789", "password", "admin", "root"
        ]
        
        password_keys = ["ADMIN_PASSWORD", "MYSQL_PASSWORD", "REDIS_PASSWORD"]
        
        for key in password_keys:
            value = self.config.get(key, "")
            if value and value.lower() in weak_passwords:
                self.warnings.append({
                    "key": key,
                    "message": f"检测到弱密码: {key}",
                    "severity": "warning",
                    "suggestion": "请使用强密码（包含大小写字母、数字、特殊字符）"
                })
    
    def print_report(self) -> None:
        """打印验证报告"""
        result = self.validate()
        
        print("=" * 60)
        print("Ruitalk 配置验证报告")
        print("=" * 60)
        
        if result["valid"]:
            print("\n✅ 所有必填配置项已正确配置")
        else:
            print(f"\n❌ 发现 {len(result['errors'])} 个错误:")
            for i, error in enumerate(result["errors"], 1):
                print(f"\n  {i}. [{error['key']}]")
                print(f"     {error['message']}")
                if "suggestion" in error:
                    print(f"     💡 {error['suggestion']}")
        
        if result["warnings"]:
            print(f"\n⚠️  发现 {len(result['warnings'])} 个警告:")
            for i, warning in enumerate(result["warnings"], 1):
                print(f"\n  {i}. [{warning['key']}]")
                print(f"     {warning['message']}")
                if "suggestion" in warning:
                    print(f"     💡 {warning['suggestion']}")
        
        print("\n" + "=" * 60)
        
        # 打印配置概览
        print("\n📋 配置概览:")
        print("-" * 40)
        for category, items in self.CONFIG_DEFINITIONS.items():
            print(f"\n  [{category.upper()}]")
            for key, definition in items.items():
                value = self.config.get(key, "<未配置>")
                if key in ["PASSWORD", "SECRET", "KEY", "TOKEN"]:
                    value = "***" if value else "<未配置>"
                status = "✅" if value and value != "<未配置>" else "❌" if category == "required" else "⚠️"
                print(f"    {status} {key}: {value}")


class ConfigValidationError(Exception):
    """配置验证错误"""
    
    def __init__(self, errors: List[Dict[str, Any]]):
        self.errors = errors
        message = "配置验证失败:\n"
        for error in errors:
            message += f"  - {error['key']}: {error['message']}\n"
        super().__init__(message)


def validate_config(strict: bool = False) -> Dict[str, Any]:
    """
    便捷函数：验证配置
    
    Args:
        strict: 严格模式
        
    Returns:
        验证结果字典
    """
    validator = ConfigValidator()
    return validator.validate(strict=strict)


def enforce_config() -> None:
    """
    强制验证配置
    如果验证失败，抛出 ConfigValidationError 异常
    """
    validator = ConfigValidator()
    validator.validate(strict=True)


def main():
    """命令行入口"""
    parser = argparse.ArgumentParser(description="Ruitalk 配置验证工具")
    parser.add_argument("--strict", action="store_true", help="严格模式")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    parser.add_argument("--check", action="store_true", help="仅检查")
    args = parser.parse_args()
    
    validator = ConfigValidator()
    
    if args.json:
        result = validator.validate(strict=args.strict)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        validator.print_report()
        
        if args.strict and not validator.errors:
            print("\n✅ 验证通过！")
            sys.exit(0)
        elif validator.errors:
            print("\n❌ 验证失败！")
            sys.exit(1)
        else:
            print("\n✅ 验证通过（警告不影响运行）")
            sys.exit(0)


if __name__ == "__main__":
    main()
