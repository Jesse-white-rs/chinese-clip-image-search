"""Milvus 延迟 flush 管理器。

单张上传时如果每张都 collection.flush()（重量级落盘 + 触发索引），吞吐会被严重压制。
本管理器把 flush 合并：累计到阈值张数或到达时间间隔才真正 flush 一次，
由后台守护线程执行，不阻塞上传请求。服务关闭时 flush_all() 兜底，保证数据落盘。

注意：多 worker 部署时每个进程有独立的管理器，各自按本进程的写入量 flush。
"""
import threading
import time
from config import FLUSH_THRESHOLD, FLUSH_INTERVAL, FLUSH_MODE
from logs import LOGGER


class FlushManager:
    """按集合聚合待 flush 计数，达阈值或定时批量 flush。"""

    def __init__(self, milvus_cli, threshold=None, interval=None, mode=None):
        self.cli = milvus_cli
        self.threshold = threshold or FLUSH_THRESHOLD
        self.interval = interval or FLUSH_INTERVAL
        self.mode = mode or FLUSH_MODE
        self._counts = {}          # collection -> 自上次 flush 后累计写入数
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        # 统计指标
        self.total_flushes = 0
        self.total_deferred = 0
        self.last_flush_time = 0.0
        self.last_flush_cost_ms = 0.0

    @property
    def enabled(self):
        """sync 模式下不延迟，保持每张立即 flush。"""
        return self.mode == "async"

    def start(self):
        """启动定时 flush 守护线程（仅 async 模式）。"""
        if not self.enabled or (self._thread and self._thread.is_alive()):
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="flush-manager", daemon=True)
        self._thread.start()
        LOGGER.info(f"FlushManager 已启动: 阈值={self.threshold} 间隔={self.interval}s")

    def note(self, collection):
        """记录一次向量写入。async 模式下累计，达阈值则触发一次 flush。"""
        if not self.enabled:
            return
        should_flush = False
        with self._lock:
            self._counts[collection] = self._counts.get(collection, 0) + 1
            self.total_deferred += 1
            if self._counts[collection] >= self.threshold:
                should_flush = True
        if should_flush:
            self.flush(collection)

    def flush(self, collection):
        """立即 flush 指定集合（重置计数）。线程安全，可被定时线程或请求线程调用。"""
        with self._lock:
            pending = self._counts.pop(collection, 0)
        if pending <= 0:
            return
        started = time.perf_counter()
        try:
            self.cli.flush(collection)
            cost = (time.perf_counter() - started) * 1000
            with self._lock:
                self.total_flushes += 1
                self.last_flush_time = time.time()
                self.last_flush_cost_ms = round(cost, 2)
        except Exception as e:
            LOGGER.error(f"延迟 flush 失败: {collection} - {e}")

    def flush_all(self):
        """服务关闭 / 批量结束时兜底：flush 所有待处理集合。"""
        if not self.enabled:
            return
        with self._lock:
            names = list(self._counts.keys())
        for name in names:
            self.flush(name)

    def stats(self):
        """返回监控指标。"""
        with self._lock:
            return {
                "mode": self.mode,
                "enabled": self.enabled,
                "pending": dict(self._counts),
                "totalFlushes": self.total_flushes,
                "totalDeferred": self.total_deferred,
                "lastFlushAt": self.last_flush_time,
                "lastFlushCostMs": self.last_flush_cost_ms,
            }

    def shutdown(self):
        """停止定时线程并 flush 兜底。"""
        self._stop.set()
        self.flush_all()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=self.interval + 2)

    def _loop(self):
        """守护循环：每隔一小段时间检查是否到了 flush 间隔。"""
        check_step = max(0.2, min(1.0, self.interval / 2))
        last = time.time()
        while not self._stop.wait(check_step):
            now = time.time()
            if now - last < self.interval:
                continue
            last = now
            with self._lock:
                names = [n for n, c in self._counts.items() if c > 0]
            for name in names:
                self.flush(name)
