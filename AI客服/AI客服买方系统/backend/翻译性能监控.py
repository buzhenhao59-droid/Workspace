# -*- coding: utf-8 -*-
"""
翻译性能监控模块 (Translation Performance Monitor)

功能：
- 监控翻译API响应时间
- 追踪语言切换延迟
- 支持3秒内频繁切换测试
- 记录翻译准确率统计

配置项（.env）：
- TRANSLATION_MONITOR_ENABLED=1
- TRANSLATION_PERF_LOG=translation_perf.log

使用方法：
- from translation_monitor import TranslationMonitor, monitor
- monitor.record_translation(source_lang, target_lang, duration_ms, success)
"""

import os
import time
import json
import logging
import threading
import statistics
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from collections import defaultdict

logger = logging.getLogger(__name__)

# ============== 配置 ==============
TRANSLATION_MONITOR_ENABLED = os.getenv("TRANSLATION_MONITOR_ENABLED", "1") == "1"
TRANSLATION_PERF_LOG = os.path.join(
    os.path.dirname(__file__), "..", "..", "logs", "translation_perf.log"
)


# ============== 数据结构 ==============
@dataclass
class TranslationRecord:
    """翻译记录"""
    timestamp: str
    source_lang: str
    target_lang: str
    duration_ms: float
    success: bool
    char_count: int
    error: str = ""


@dataclass
class LanguagePairStats:
    """语言对统计"""
    source_lang: str
    target_lang: str
    total_requests: int = 0
    success_count: int = 0
    total_duration_ms: float = 0.0
    min_duration_ms: float = float('inf')
    max_duration_ms: float = 0.0
    error_count: int = 0
    last_request: str = ""

    @property
    def avg_duration_ms(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return self.total_duration_ms / self.total_requests

    @property
    def success_rate(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return self.success_count / self.total_requests * 100

    @property
    def median_duration_ms(self) -> float:
        return self.avg_duration_ms  # 简化版，实际可用滑动窗口计算


@dataclass
class SwitchTestResult:
    """语言切换测试结果"""
    test_id: str
    start_time: str
    duration_ms: float
    switch_count: int
    success_count: int
    avg_latency_ms: float
    max_latency_ms: float
    all_passed: bool
    details: List[Dict] = field(default_factory=list)


# ============== 翻译性能监控器 ==============
class TranslationMonitor:
    """
    翻译性能监控器
    
    功能：
    - 记录每次翻译的响应时间
    - 统计各语言对的性能指标
    - 执行语言切换压力测试
    - 生成性能报告
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, '_initialized'):
            return
        self._initialized = True
        
        self._records: List[TranslationRecord] = []
        self._stats: Dict[str, LanguagePairStats] = {}
        self._switch_tests: List[SwitchTestResult] = []
        self._data_lock = threading.Lock()
        self._max_records = 10000  # 最多保留10000条记录
        
        # 确保日志目录存在
        os.makedirs(os.path.dirname(TRANSLATION_PERF_LOG), exist_ok=True)

    def _make_key(self, source: str, target: str) -> str:
        """生成语言对key"""
        return f"{source}->{target}"

    def record_translation(
        self,
        source_lang: str,
        target_lang: str,
        duration_ms: float,
        success: bool,
        char_count: int = 0,
        error: str = ""
    ):
        """记录一次翻译"""
        if not TRANSLATION_MONITOR_ENABLED:
            return
        
        record = TranslationRecord(
            timestamp=datetime.now().isoformat(),
            source_lang=source_lang,
            target_lang=target_lang,
            duration_ms=duration_ms,
            success=success,
            char_count=char_count,
            error=error
        )
        
        with self._data_lock:
            self._records.append(record)
            
            # 更新统计
            key = self._make_key(source_lang, target_lang)
            if key not in self._stats:
                self._stats[key] = LanguagePairStats(
                    source_lang=source_lang,
                    target_lang=target_lang
                )
            
            stats = self._stats[key]
            stats.total_requests += 1
            stats.total_duration_ms += duration_ms
            stats.min_duration_ms = min(stats.min_duration_ms, duration_ms)
            stats.max_duration_ms = max(stats.max_duration_ms, duration_ms)
            stats.last_request = record.timestamp
            
            if success:
                stats.success_count += 1
            else:
                stats.error_count += 1
            
            # 清理过期记录
            if len(self._records) > self._max_records:
                self._records = self._records[-self._max_records // 2:]
        
        # 写入日志
        self._write_log(record)

    def _write_log(self, record: TranslationRecord):
        """写入性能日志"""
        try:
            with open(TRANSLATION_PERF_LOG, 'a', encoding='utf-8') as f:
                f.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning(f"写入翻译性能日志失败: {e}")

    def get_stats(self, source_lang: str = None, target_lang: str = None) -> Dict[str, Any]:
        """获取统计数据"""
        with self._data_lock:
            stats_list = []
            
            for key, stats in self._stats.items():
                if source_lang and stats.source_lang != source_lang:
                    continue
                if target_lang and stats.target_lang != target_lang:
                    continue
                
                stats_list.append({
                    "language_pair": key,
                    "source_lang": stats.source_lang,
                    "target_lang": stats.target_lang,
                    "total_requests": stats.total_requests,
                    "success_count": stats.success_count,
                    "error_count": stats.error_count,
                    "success_rate": f"{stats.success_rate:.2f}%",
                    "avg_duration_ms": f"{stats.avg_duration_ms:.2f}",
                    "min_duration_ms": f"{stats.min_duration_ms:.2f}",
                    "max_duration_ms": f"{stats.max_duration_ms:.2f}",
                    "last_request": stats.last_request,
                })
            
            return {
                "summary": {
                    "total_records": len(self._records),
                    "total_pairs": len(stats_list),
                },
                "pairs": stats_list
            }

    def test_language_switch(
        self,
        test_languages: List[str] = None,
        iterations: int = 10,
        test_text: str = None
    ) -> SwitchTestResult:
        """
        执行语言切换压力测试
        
        测试在多种语言间频繁切换的性能
        
        Args:
            test_languages: 要测试的语言列表，默认 ["zh", "en", "ja", "fr", "es"]
            iterations: 每种语言切换的迭代次数
            test_text: 测试文本
            
        Returns:
            SwitchTestResult: 测试结果
        """
        if test_languages is None:
            test_languages = ["zh", "en", "ja", "fr", "es"]
        
        if test_text is None:
            test_text = "你好，这是一条测试消息，用于验证翻译系统在语言切换时的响应时间。"
        
        test_id = f"switch_test_{int(time.time() * 1000)}"
        start_time = datetime.now()
        details = []
        latencies = []
        success_count = 0
        
        # 模拟翻译函数（实际使用时可替换为真实翻译API）
        def mock_translate(text: str, target: str) -> str:
            return f"[{target}] {text[:20]}..."
        
        try:
            # 测试相同语言对多次切换
            for i in range(iterations):
                for j, target_lang in enumerate(test_languages):
                    test_start = time.perf_counter()
                    
                    try:
                        # 执行翻译
                        result = mock_translate(test_text, target_lang)
                        
                        # 记录延迟
                        latency = (time.perf_counter() - test_start) * 1000
                        latencies.append(latency)
                        
                        # 检查是否在3秒内
                        passed = latency < 3000
                        if passed:
                            success_count += 1
                        
                        details.append({
                            "iteration": i + 1,
                            "target_lang": target_lang,
                            "latency_ms": f"{latency:.2f}",
                            "passed": passed,
                            "result_preview": result[:30]
                        })
                        
                    except Exception as e:
                        latencies.append(9999)
                        details.append({
                            "iteration": i + 1,
                            "target_lang": target_lang,
                            "latency_ms": "ERROR",
                            "passed": False,
                            "error": str(e)
                        })
            
            duration = (datetime.now() - start_time).total_seconds() * 1000
            
            result = SwitchTestResult(
                test_id=test_id,
                start_time=start_time.isoformat(),
                duration_ms=duration,
                switch_count=len(test_languages) * iterations,
                success_count=success_count,
                avg_latency_ms=statistics.mean(latencies) if latencies else 0,
                max_latency_ms=max(latencies) if latencies else 0,
                all_passed=all(d.get("passed", False) for d in details),
                details=details
            )
            
            with self._data_lock:
                self._switch_tests.append(result)
            
            return result
            
        except Exception as e:
            logger.error(f"语言切换测试失败: {e}")
            return SwitchTestResult(
                test_id=test_id,
                start_time=start_time.isoformat(),
                duration_ms=(datetime.now() - start_time).total_seconds() * 1000,
                switch_count=0,
                success_count=0,
                avg_latency_ms=0,
                max_latency_ms=0,
                all_passed=False,
                details=[{"error": str(e)}]
            )

    def get_switch_test_results(self, limit: int = 10) -> List[Dict]:
        """获取语言切换测试结果"""
        with self._data_lock:
            tests = self._switch_tests[-limit:]
            return [
                {
                    "test_id": t.test_id,
                    "start_time": t.start_time,
                    "duration_ms": f"{t.duration_ms:.2f}",
                    "switch_count": t.switch_count,
                    "success_count": t.success_count,
                    "avg_latency_ms": f"{t.avg_latency_ms:.2f}",
                    "max_latency_ms": f"{t.max_latency_ms:.2f}",
                    "all_passed": t.all_passed,
                }
                for t in tests
            ]

    def check_performance_sla(self, sla_ms: float = 3000) -> Dict[str, Any]:
        """
        检查性能SLA
        
        Args:
            sla_ms: SLA阈值（毫秒），默认3秒
            
        Returns:
            SLA检查结果
        """
        with self._data_lock:
            recent_records = self._records[-100:]  # 最近100条
            
            if not recent_records:
                return {
                    "sla_threshold_ms": sla_ms,
                    "status": "no_data",
                    "total_checked": 0,
                    "passed": 0,
                    "failed": 0,
                    "pass_rate": "0%"
                }
            
            passed = sum(1 for r in recent_records if r.duration_ms <= sla_ms)
            failed = len(recent_records) - passed
            pass_rate = passed / len(recent_records) * 100
            
            return {
                "sla_threshold_ms": sla_ms,
                "status": "pass" if pass_rate >= 95 else "fail",
                "total_checked": len(recent_records),
                "passed": passed,
                "failed": failed,
                "pass_rate": f"{pass_rate:.2f}%",
                "avg_duration_ms": f"{statistics.mean(r.duration_ms for r in recent_records):.2f}",
                "max_duration_ms": f"{max(r.duration_ms for r in recent_records):.2f}",
            }

    def reset_stats(self):
        """重置统计数据"""
        with self._data_lock:
            self._records.clear()
            self._stats.clear()
            self._switch_tests.clear()
        logger.info("[TranslationMonitor] 统计数据已重置")


# ============== 全局实例 ==============
_translation_monitor: Optional[TranslationMonitor] = None


def get_translation_monitor() -> TranslationMonitor:
    """获取翻译监控器实例"""
    global _translation_monitor
    if _translation_monitor is None:
        _translation_monitor = TranslationMonitor()
    return _translation_monitor


# 快捷访问
monitor = get_translation_monitor()


# ============== 性能追踪装饰器 ==============
def track_translation(source_lang: str, target_lang: str):
    """翻译性能追踪装饰器"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            start = time.perf_counter()
            success = True
            error = ""
            result = None
            
            try:
                result = func(*args, **kwargs)
                return result
            except Exception as e:
                success = False
                error = str(e)
                raise
            finally:
                duration_ms = (time.perf_counter() - start) * 1000
                char_count = len(result) if result else 0
                monitor.record_translation(
                    source_lang=source_lang,
                    target_lang=target_lang,
                    duration_ms=duration_ms,
                    success=success,
                    char_count=char_count,
                    error=error
                )
        
        # 复制函数属性
        wrapper.__name__ = func.__name__
        wrapper.__doc__ = func.__doc__
        return wrapper
    return decorator


# ============== 上下文管理器 ==============
class TranslationTimer:
    """翻译性能计时上下文管理器"""
    
    def __init__(self, source_lang: str, target_lang: str):
        self.source_lang = source_lang
        self.target_lang = target_lang
        self.start_time = None
        self.success = True
        self.error = ""
        self.result = None
    
    def __enter__(self):
        self.start_time = time.perf_counter()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        duration_ms = (time.perf_counter() - self.start_time) * 1000
        if exc_type is not None:
            self.success = False
            self.error = str(exc_val)
        
        char_count = len(self.result) if self.result else 0
        monitor.record_translation(
            source_lang=self.source_lang,
            target_lang=self.target_lang,
            duration_ms=duration_ms,
            success=self.success,
            char_count=char_count,
            error=self.error
        )
        return False
    
    def set_result(self, result: str):
        self.result = result


# ============== 导出 ==============
__all__ = [
    'TranslationMonitor',
    'TranslationRecord',
    'LanguagePairStats',
    'SwitchTestResult',
    'get_translation_monitor',
    'monitor',
    'track_translation',
    'TranslationTimer',
]
