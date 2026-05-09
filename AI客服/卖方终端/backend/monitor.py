# -*- coding: utf-8 -*-
"""
Prometheus 监控模块 - 全指标埋点
提供完整的系统指标收集，支持 Prometheus 拉取和 Grafana 可视化
含自动清理机制：指标超过 1 小时未更新自动清除，防止内存无限增长
"""
import time
import logging
import platform
import psutil
import asyncio
import threading
from typing import Dict, List, Optional, Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)

# ============== 指标类型 ==============

class MetricType(str, Enum):
    COUNTER = "counter"     # 计数器（只增不减）
    GAUGE = "gauge"        # 仪表（可增可减）
    HISTOGRAM = "histogram" # 直方图（分布统计）
    SUMMARY = "summary"     # 摘要（分位数）


@dataclass
class Metric:
    """指标"""
    name: str
    description: str
    metric_type: MetricType
    labels: Dict[str, str] = field(default_factory=dict)
    value: float = 0.0
    last_updated: float = field(default_factory=time.time)


# ============== 指标收集器 ==============

class MetricsCollector:
    """
    指标收集器 - 收集系统、业务、应用指标
    """

    def __init__(self):
        # 系统指标
        self._system_metrics: Dict[str, Metric] = {}
        # 业务指标
        self._business_metrics: Dict[str, Metric] = {}
        # HTTP 指标
        self._http_metrics: Dict[str, Metric] = {}
        # WebSocket 指标
        self._ws_metrics: Dict[str, Metric] = {}
        # 数据库指标
        self._db_metrics: Dict[str, Metric] = {}
        # 清理锁（防止并发清理冲突）
        self._cleanup_lock = threading.Lock()
        # 清理阈值（秒）：指标超过此时间未更新则清除
        self._metric_ttl = 3600  # 1小时
        # 清理计数器（每 N 次记录触发一次清理）
        self._cleanup_counter = 0
        self._cleanup_interval = 100  # 每 100 次记录后触发清理

        self._init_system_metrics()
        # 启动后台清理线程
        self._start_cleanup_thread()

    def _start_cleanup_thread(self):
        """启动后台清理线程（每 10 分钟检查一次）"""
        def _cleanup_loop():
            while True:
                try:
                    time.sleep(600)  # 10 分钟
                    self._cleanup_stale_metrics()
                except Exception as e:
                    logger.warning(f"指标清理线程异常: {e}")

        t = threading.Thread(target=_cleanup_loop, daemon=True)
        t.start()
        logger.info("指标清理线程已启动（每 10 分钟清理 1 小时以上的过时指标）")

    def _cleanup_stale_metrics(self):
        """清理超过 TTL 的过时指标，防止内存无限增长"""
        now = time.time()
        cleaned = 0
        with self._cleanup_lock:
            for collection_name in ("_business_metrics", "_http_metrics", "_ws_metrics", "_db_metrics"):
                collection = getattr(self, collection_name)
                stale = [
                    k for k, m in collection.items()
                    if now - m.last_updated > self._metric_ttl
                ]
                for k in stale:
                    del collection[k]
                    cleaned += 1
        if cleaned > 0:
            logger.info(f"指标清理完成：清除 {cleaned} 个过时指标")

    def _init_system_metrics(self):
        """初始化系统指标"""
        system_info = [
            Metric("system_cpu_usage", "CPU 使用率 (%)", MetricType.GAUGE, {"cpu": "total"}),
            Metric("system_memory_total", "系统总内存 (bytes)", MetricType.GAUGE),
            Metric("system_memory_used", "系统已用内存 (bytes)", MetricType.GAUGE),
            Metric("system_memory_percent", "内存使用率 (%)", MetricType.GAUGE),
            Metric("system_disk_total", "磁盘总空间 (bytes)", MetricType.GAUGE),
            Metric("system_disk_used", "磁盘已用空间 (bytes)", MetricType.GAUGE),
            Metric("system_disk_percent", "磁盘使用率 (%)", MetricType.GAUGE),
            Metric("system_network_sent", "网络发送字节数", MetricType.COUNTER),
            Metric("system_network_recv", "网络接收字节数", MetricType.COUNTER),
            Metric("process_open_fds", "进程打开的文件描述符数", MetricType.GAUGE),
            Metric("process_threads", "进程线程数", MetricType.GAUGE),
            Metric("process_memory_rss", "进程 RSS 内存 (bytes)", MetricType.GAUGE),
            Metric("process_uptime", "进程运行时间 (秒)", MetricType.GAUGE),
        ]
        for m in system_info:
            self._system_metrics[m.name] = m

    def collect_system_metrics(self):
        """收集系统指标"""
        try:
            # CPU
            cpu = psutil.cpu_percent(interval=0.1)
            self._system_metrics["system_cpu_usage"].value = cpu

            # 内存
            mem = psutil.virtual_memory()
            self._system_metrics["system_memory_total"].value = mem.total
            self._system_metrics["system_memory_used"].value = mem.used
            self._system_metrics["system_memory_percent"].value = mem.percent

            # 磁盘
            disk = psutil.disk_usage('/')
            self._system_metrics["system_disk_total"].value = disk.total
            self._system_metrics["system_disk_used"].value = disk.used
            self._system_metrics["system_disk_percent"].value = disk.percent

            # 网络
            net = psutil.net_io_counters()
            self._system_metrics["system_network_sent"].value = net.bytes_sent
            self._system_metrics["system_network_recv"].value = net.bytes_recv

            # 进程
            p = psutil.Process()
            self._system_metrics["process_open_fds"].value = p.num_fds() if hasattr(p, 'num_fds') else 0
            self._system_metrics["process_threads"].value = p.num_threads()
            self._system_metrics["process_memory_rss"].value = p.memory_info().rss
            self._system_metrics["process_uptime"].value = time.time() - p.create_time()

        except Exception as e:
            logger.warning(f"收集系统指标失败: {e}")

    # ============== 业务指标 ==============

    def inc_counter(self, name: str, labels: Dict[str, str] = None, value: float = 1.0):
        """递增计数器"""
        key = self._make_key(name, labels)
        if key not in self._business_metrics:
            self._business_metrics[key] = Metric(
                name=name, description=f"业务计数器: {name}",
                metric_type=MetricType.COUNTER, labels=labels or {}
            )
        m = self._business_metrics[key]
        m.value += value
        m.last_updated = time.time()
        # 每 100 次触发一次增量清理
        self._cleanup_counter += 1
        if self._cleanup_counter >= self._cleanup_interval:
            self._cleanup_counter = 0
            self._cleanup_stale_metrics()

    def set_gauge(self, name: str, value: float, labels: Dict[str, str] = None):
        """设置仪表值"""
        key = self._make_key(name, labels)
        if key not in self._business_metrics:
            self._business_metrics[key] = Metric(
                name=name, description=f"业务仪表: {name}",
                metric_type=MetricType.GAUGE, labels=labels or {}
            )
        m = self._business_metrics[key]
        m.value = value
        m.last_updated = time.time()

    def observe_histogram(self, name: str, value: float, labels: Dict[str, str] = None):
        """观察直方图值"""
        key = self._make_key(name, labels)
        if key not in self._business_metrics:
            self._business_metrics[key] = Metric(
                name=name, description=f"业务直方图: {name}",
                metric_type=MetricType.HISTOGRAM, labels=labels or {}
            )
        m = self._business_metrics[key]
        m.value = value
        m.last_updated = time.time()

    def _make_key(self, name: str, labels: Dict[str, str] = None) -> str:
        """生成指标 key"""
        if not labels:
            return name
        label_str = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
        return f"{name}{{{label_str}}}"

    # ============== HTTP 指标 ==============

    def record_http_request(self, method: str, path: str, status: int, duration_ms: float):
        """记录 HTTP 请求"""
        labels = {"method": method, "path": path, "status": str(status)}
        self.inc_counter("http_requests_total", labels)

        if status >= 500:
            self.inc_counter("http_errors_total", {"method": method, "path": path, "status": str(status)})

        buckets = [5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000]
        for bucket in buckets:
            if duration_ms <= bucket:
                self.inc_counter("http_request_duration_ms_bucket",
                               {**labels, "le": str(bucket)})
                break
        else:
            self.inc_counter("http_request_duration_ms_bucket",
                           {**labels, "le": "+Inf"})

        self.observe_histogram("http_request_duration_ms", duration_ms, labels)

    def set_http_active_requests(self, count: int):
        """设置当前活跃请求数"""
        self.set_gauge("http_active_requests", count)

    # ============== WebSocket 指标 ==============

    def set_ws_connections(self, customer_count: int, agent_count: int):
        """设置 WebSocket 连接数"""
        self.set_gauge("ws_connections_active", customer_count, {"type": "customer"})
        self.set_gauge("ws_connections_active", agent_count, {"type": "agent"})
        self.set_gauge("ws_connections_total", customer_count + agent_count)

    def inc_ws_messages(self, direction: str, msg_type: str = "text"):
        """递增 WebSocket 消息计数"""
        self.inc_counter("ws_messages_total", {"direction": direction, "type": msg_type})

    def set_waiting_queue_size(self, size: int):
        """设置等待队列大小"""
        self.set_gauge("queue_waiting_customers", size)

    # ============== 数据库指标 ==============

    def set_db_pool_size(self, size: int, in_use: int):
        """设置数据库连接池状态"""
        self.set_gauge("db_connections_pool_size", size, {"pool": "main"})
        self.set_gauge("db_connections_in_use", in_use, {"pool": "main"})

    def record_db_query_duration(self, operation: str, duration_ms: float):
        """记录数据库查询时长"""
        self.observe_histogram("db_query_duration_ms", duration_ms, {"operation": operation})

    # ============== 业务专用指标 ==============

    def record_chat_started(self, language: str):
        """记录新对话开始"""
        self.inc_counter("chat_sessions_total", {"language": language, "type": "ai"})

    def record_transfer_to_human(self, language: str):
        """记录转人工"""
        self.inc_counter("chat_transfer_to_human_total", {"language": language})
        self.inc_counter("chat_sessions_total", {"language": language, "type": "human"})

    def record_conversation_ended(self, agent_id: str, duration_seconds: float):
        """记录对话结束"""
        self.inc_counter("conversations_ended_total", {"agent_id": agent_id})
        self.observe_histogram("conversation_duration_seconds", duration_seconds, {"agent_id": agent_id})

    def record_message_sent(self, sender: str):
        """记录消息发送"""
        self.inc_counter("messages_sent_total", {"sender": sender})

    def set_online_agents(self, count: int):
        """设置在线坐席数"""
        self.set_gauge("online_agents", count)

    # ============== Prometheus 格式输出 ==============

    def to_prometheus_text(self) -> str:
        """转换为 Prometheus 文本格式"""
        self.collect_system_metrics()
        lines = []
        timestamp = int(time.time() * 1000)

        def format_metric(m: Metric) -> str:
            label_str = ""
            if m.labels:
                label_str = "{" + ",".join(f'{k}="{v}"' for k, v in m.labels.items()) + "}"
            return f"{m.name}{label_str} {m.value}"

        # 系统指标
        lines.append("# HELP system_cpu_usage CPU 使用率")
        lines.append("# TYPE system_cpu_usage gauge")
        lines.append(format_metric(self._system_metrics.get("system_cpu_usage", Metric("", "", MetricType.GAUGE))))

        lines.append("# HELP system_memory_percent 内存使用率")
        lines.append("# TYPE system_memory_percent gauge")
        lines.append(format_metric(self._system_metrics.get("system_memory_percent", Metric("", "", MetricType.GAUGE))))

        lines.append("# HELP system_disk_percent 磁盘使用率")
        lines.append("# TYPE system_disk_percent gauge")
        lines.append(format_metric(self._system_metrics.get("system_disk_percent", Metric("", "", MetricType.GAUGE))))

        lines.append("# HELP process_uptime 进程运行时间")
        lines.append("# TYPE process_uptime gauge")
        lines.append(format_metric(self._system_metrics.get("process_uptime", Metric("", "", MetricType.GAUGE))))

        lines.append("# HELP process_memory_rss 进程内存 RSS")
        lines.append("# TYPE process_memory_rss gauge")
        lines.append(format_metric(self._system_metrics.get("process_memory_rss", Metric("", "", MetricType.GAUGE))))

        # 业务指标
        for m in self._business_metrics.values():
            help_line = f"# HELP {m.name} {m.description}"
            type_line = f"# TYPE {m.name} {m.metric_type.value}"
            value_line = format_metric(m)
            if help_line not in lines:
                lines.append(help_line)
            if type_line not in lines:
                lines.append(type_line)
            lines.append(value_line)

        return "\n".join(lines)

    def to_json(self) -> Dict[str, Any]:
        """转换为 JSON 格式"""
        self.collect_system_metrics()
        return {
            "timestamp": datetime.now().isoformat(),
            "system": {
                "cpu_percent": self._system_metrics.get("system_cpu_usage", Metric("", "", MetricType.GAUGE)).value,
                "memory_percent": self._system_metrics.get("system_memory_percent", Metric("", "", MetricType.GAUGE)).value,
                "memory_used_gb": round(self._system_metrics.get("system_memory_used", Metric("", "", MetricType.GAUGE)).value / (1024**3), 2),
                "disk_percent": self._system_metrics.get("system_disk_percent", Metric("", "", MetricType.GAUGE)).value,
                "uptime_seconds": int(self._system_metrics.get("process_uptime", Metric("", "", MetricType.GAUGE)).value),
                "platform": platform.system(),
            },
            "business": {
                name: {"value": m.value, "type": m.metric_type.value, "labels": m.labels}
                for name, m in self._business_metrics.items()
            }
        }

    def get_all_metrics_summary(self) -> Dict[str, Any]:
        """获取所有指标摘要（用于健康检查）"""
        self.collect_system_metrics()
        cpu = self._system_metrics.get("system_cpu_usage", Metric("", "", MetricType.GAUGE)).value
        mem = self._system_metrics.get("system_memory_percent", Metric("", "", MetricType.GAUGE)).value
        disk = self._system_metrics.get("system_disk_percent", Metric("", "", MetricType.GAUGE)).value

        status = "healthy"
        if cpu > 90 or mem > 90 or disk > 95:
            status = "critical"
        elif cpu > 80 or mem > 80 or disk > 85:
            status = "degraded"

        return {
            "status": status,
            "cpu_percent": round(cpu, 1),
            "memory_percent": round(mem, 1),
            "disk_percent": round(disk, 1),
            "online_agents": self._business_metrics.get("online_agents", Metric("", "", MetricType.GAUGE)).value,
            "queue_waiting": self._business_metrics.get("queue_waiting_customers", Metric("", "", MetricType.GAUGE)).value,
            "total_messages": sum(m.value for name, m in self._business_metrics.items() if name.startswith("messages_sent")),
            "total_chats": sum(m.value for name, m in self._business_metrics.items() if name.startswith("chat_sessions")),
        }


# ============== HTTP 指标中间件 ==============

class MetricsMiddleware(BaseHTTPMiddleware):
    """HTTP 指标中间件（须接收 app，供 Starlette/FastAPI add_middleware 使用）"""

    def __init__(self, app, collector: MetricsCollector):
        super().__init__(app)
        self._collector = collector
        self._active_requests = 0

    async def dispatch(self, request: Request, call_next):
        """记录请求指标"""
        import time
        start = time.time()
        self._active_requests += 1
        self._collector.set_http_active_requests(self._active_requests)
        response = None

        try:
            response = await call_next(request)
            status = response.status_code
        except Exception:
            status = 500
            response = None
        finally:
            self._active_requests -= 1

        duration_ms = (time.time() - start) * 1000
        path = request.url.path
        method = request.method
        self._collector.record_http_request(method, path, status, duration_ms)
        if response is None:
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": "Internal server error"}, status_code=500)
        return response


# 全局单例
metrics_collector = MetricsCollector()
