# -*- coding: utf-8 -*-
"""
Chaos Mesh 混沌工程实验配置

用途: 在 Kubernetes 环境中注入故障，验证系统韧性

支持的故障类型:
- Pod 级别: 杀 Pod、Pod 网络延迟、Pod 丢包、Pod DNS 故障
- 网络级别: 网络分区、网络延迟、丢包、重复包、Corrupted Packet
- IO 级别: IO 延迟、IO 错误、IO 限流
- 内核级别: 磁盘填充、JVM GC 延迟
- 时间注入: 时钟偏移
- DNS 故障: DNS 解析错误/超时

使用前提:
1. Chaos Mesh 已安装: helm install chaos-mesh chaos-mesh/chaos-mesh -n chaos-mesh --create-namespace
2. 已配置 RBAC 权限
"""
import yaml
import os
from typing import Optional


# ============== 实验模板 ==============

class ChaosExperiment:
    """混沌实验基类"""

    def __init__(self, name: str, namespace: str = "default"):
        self.name = name
        self.namespace = namespace
        self.labels: dict = {"app": "ruitalk", "component": "backend"}

    def to_yaml(self) -> str:
        return yaml.dump(self.to_dict(), allow_unicode=True, sort_keys=False)

    def to_dict(self) -> dict:
        raise NotImplementedError


# ============== 1. Pod 杀容器实验 ==============

class KillSellerPodExperiment(ChaosExperiment):
    """
    场景: 模拟 seller Pod 被意外杀死
    期望: Kubernetes 自动重启 Pod，服务在 30s 内恢复
    """

    def __init__(self):
        super().__init__("kill-seller-pod", namespace="ruitalk")
        self.labels["app"] = "ruitalk-seller"

    def to_dict(self) -> dict:
        return {
            "apiVersion": "chaos-mesh.org/v1alpha1",
            "kind": "PodChaos",
            "metadata": {
                "name": self.name,
                "namespace": self.namespace,
                "labels": self.labels,
            },
            "spec": {
                "action": "pod-failure",
                "mode": "one",
                "duration": "30s",
                "selector": {
                    "namespaces": [self.namespace],
                    "labelSelectors": {"app": "ruitalk-seller"},
                },
            },
            "metadata": {
                "experiment": "kill-seller-pod",
                "expected_recovery_time": "30s",
            },
        }


# ============== 2. 网络延迟实验 ==============

class NetworkLatencyExperiment(ChaosExperiment):
    """
    场景: seller → MySQL 网络链路注入 500ms 延迟
    期望: 请求延迟增加但仍能正常响应（无超时错误）
    """

    def __init__(self, delay_ms: int = 500, duration: str = "60s"):
        super().__init__("network-latency-seller-mysql", namespace="ruitalk")
        self.delay_ms = delay_ms
        self.duration = duration

    def to_dict(self) -> dict:
        return {
            "apiVersion": "chaos-mesh.org/v1alpha1",
            "kind": "NetworkChaos",
            "metadata": {
                "name": self.name,
                "namespace": self.namespace,
                "labels": self.labels,
            },
            "spec": {
                "action": "delay",
                "mode": "all",
                "duration": self.duration,
                "delay": {
                    "latency": f"{self.delay_ms}ms",
                    "correlation": "0",
                    "jitter": "50ms",
                },
                "direction": "to",
                "target": {
                    "selector": {
                        "namespaces": [self.namespace],
                        "labelSelectors": {"app": "mysql-seller"},
                    },
                },
                "selector": {
                    "namespaces": [self.namespace],
                    "labelSelectors": {"app": "ruitalk-seller"},
                },
            },
            "metadata": {
                "experiment": "network-latency",
                "target": "seller → MySQL",
                "injected_delay": f"{self.delay_ms}ms",
            },
        }


# ============== 3. Redis 连接失败实验 ==============

class RedisFailureExperiment(ChaosExperiment):
    """
    场景: Redis 不可用（连接超时）
    期望: 系统降级到无缓存模式，限流退化为内存模式
    """

    def __init__(self):
        super().__init__("redis-failure", namespace="ruitalk")

    def to_dict(self) -> dict:
        return {
            "apiVersion": "chaos-mesh.org/v1alpha1",
            "kind": "PodChaos",
            "metadata": {
                "name": self.name,
                "namespace": self.namespace,
                "labels": self.labels,
            },
            "spec": {
                "action": "pod-failure",
                "mode": "all",
                "duration": "120s",
                "selector": {
                    "namespaces": [self.namespace],
                    "labelSelectors": {"app": "ruitalk-redis"},
                },
            },
            "metadata": {
                "experiment": "redis-failure",
                "expected_degradation": [
                    "限流退化为内存模式",
                    "Session 降级为无持久化",
                    "AI 响应降级（无缓存）",
                ],
            },
        }


# ============== 4. DeepSeek API 超时实验 ==============

class AIServiceTimeoutExperiment(ChaosExperiment):
    """
    场景: DeepSeek API 响应超时（模拟 API 宕机）
    期望: 熔断器触发，fallback 回复生效
    """

    def __init__(self, delay_ms: int = 10000):
        super().__init__("ai-service-timeout", namespace="ruitalk")
        self.delay_ms = delay_ms

    def to_dict(self) -> dict:
        return {
            "apiVersion": "chaos-mesh.org/v1alpha1",
            "kind": "NetworkChaos",
            "metadata": {
                "name": self.name,
                "namespace": self.namespace,
                "labels": self.labels,
            },
            "spec": {
                "action": "delay",
                "mode": "all",
                "duration": "120s",
                "delay": {
                    "latency": f"{self.delay_ms}ms",
                    "correlation": "100",
                },
                "target": {
                    "selector": {
                        "namespaces": [self.namespace],
                        "labelSelectors": {"app": "ruitalk-seller"},
                    },
                },
                "selector": {
                    "namespaces": [self.namespace],
                    "labelSelectors": {"app": "ruitalk-seller"},
                },
                "externalTargets": ["api.deepseek.com"],
            },
            "metadata": {
                "experiment": "ai-service-timeout",
                "injected_delay": f"{self.delay_ms}ms",
                "expected_circuit_breaker": "OPEN after 5 failures",
            },
        }


# ============== 5. MySQL 连接耗尽实验 ==============

class MySQLConnectionExhaustionExperiment(ChaosExperiment):
    """
    场景: MySQL 连接池耗尽（所有连接被占用）
    期望: 新请求排队或返回 503，超时后释放连接
    """

    def __init__(self):
        super().__init__("mysql-connection-exhaustion", namespace="ruitalk")

    def to_dict(self) -> dict:
        return {
            "apiVersion": "chaos-mesh.org/v1alpha1",
            "kind": "StressChaos",
            "metadata": {
                "name": self.name,
                "namespace": self.namespace,
                "labels": self.labels,
            },
            "spec": {
                "mode": "all",
                "duration": "60s",
                "selector": {
                    "namespaces": [self.namespace],
                    "labelSelectors": {"app": "mysql-seller"},
                },
                " stressors": {
                    "cpu": {"load": 100, "workers": 8},
                    "memory": {"size": "100%", "workers": 1},
                },
            },
            "metadata": {
                "experiment": "mysql-connection-exhaustion",
                "expected_behavior": "MySQL CPU 100%，连接处理变慢",
            },
        }


# ============== 6. Buyer 服务不可用实验 ==============

class BuyerServiceDownExperiment(ChaosExperiment):
    """
    场景: Buyer AI 客服服务不可用（Pod 被删除）
    期望: 卖方内部回调失败，记录日志，不影响主流程
    """

    def __init__(self):
        super().__init__("buyer-service-down", namespace="ruitalk")
        self.labels["app"] = "ruitalk-buyer"

    def to_dict(self) -> dict:
        return {
            "apiVersion": "chaos-mesh.org/v1alpha1",
            "kind": "PodChaos",
            "metadata": {
                "name": self.name,
                "namespace": self.namespace,
                "labels": self.labels,
            },
            "spec": {
                "action": "pod-failure",
                "mode": "all",
                "duration": "180s",
                "selector": {
                    "namespaces": [self.namespace],
                    "labelSelectors": {"app": "ruitalk-buyer"},
                },
            },
            "metadata": {
                "experiment": "buyer-service-down",
                "expected_behavior": [
                    "webhook 重试 3 次（指数退避）",
                    "所有重试失败后，记录错误日志",
                    "主流程不受影响",
                ],
            },
        }


# ============== 7. 磁盘 IO 延迟实验 ==============

class DiskIODelayExperiment(ChaosExperiment):
    """
    场景: MySQL 数据目录磁盘 IO 延迟增加
    期望: 查询变慢但仍能响应（不触发超时熔断）
    """

    def __init__(self, delay: str = "50ms"):
        super().__init__("mysql-disk-io-delay", namespace="ruitalk")
        self.delay = delay

    def to_dict(self) -> dict:
        return {
            "apiVersion": "chaos-mesh.org/v1alpha1",
            "kind": "IOChaos",
            "metadata": {
                "name": self.name,
                "namespace": self.namespace,
                "labels": self.labels,
            },
            "spec": {
                "action": "delay",
                "mode": "all",
                "duration": "60s",
                "delay": self.delay,
                "path": "/var/lib/mysql",
                "selector": {
                    "namespaces": [self.namespace],
                    "labelSelectors": {"app": "mysql-seller"},
                },
            },
            "metadata": {
                "experiment": "mysql-disk-io-delay",
                "injected_delay": self.delay,
            },
        }


# ============== YAML 文件生成 ==============

EXPERIMENTS = [
    KillSellerPodExperiment(),
    NetworkLatencyExperiment(),
    RedisFailureExperiment(),
    AIServiceTimeoutExperiment(),
    MySQLConnectionExhaustionExperiment(),
    BuyerServiceDownExperiment(),
    DiskIODelayExperiment(),
]


def generate_all_experiments(output_dir: str = "chaos/"):
    """生成所有混沌实验 YAML 文件"""
    os.makedirs(output_dir, exist_ok=True)
    for exp in EXPERIMENTS:
        filename = f"{output_dir}{exp.name}.yaml"
        with open(filename, "w", encoding="utf-8") as f:
            f.write("# " + "=" * 60 + "\n")
            f.write(f"# Chaos Experiment: {exp.name}\n")
            f.write(f"# " + "=" * 60 + "\n")
            if hasattr(exp, "metadata"):
                for k, v in getattr(exp, "metadata", {}).items():
                    f.write(f"# Expected: {k} = {v}\n")
            f.write("#\n")
            f.write("# 应用方法:\n")
            f.write(f"#   kubectl apply -f {filename}\n")
            f.write("# 查看状态:\n")
            f.write(f"#   kubectl get workflow {exp.name}-workflow -n ruitalk\n")
            f.write("# 停止实验:\n")
            f.write(f"#   kubectl delete -f {filename}\n")
            f.write("#\n\n")
            f.write(exp.to_yaml())


if __name__ == "__main__":
    generate_all_experiments()
    print("所有混沌实验 YAML 文件已生成到 chaos/ 目录")
