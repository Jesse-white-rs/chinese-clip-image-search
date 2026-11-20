"""性能压测引擎。

在后端后台线程并发调用 service 层，测量上传/以图搜图/文本搜图的真实耗时。
统计数据：QPS、平均延迟、P50/P90/P95/P99、成功率、错误数。
进度写入 diskcache 供前端轮询；结果保存到 MySQL 便于回溯。

注意：百万级上传压测会真实写入百万条向量与 MinIO 对象，请谨慎使用。
"""
import os
import time
import uuid
import threading
import concurrent.futures
from typing import Optional

import numpy as np
from diskcache import Cache
import pymysql

from config import (
    MYSQL_HOST, MYSQL_PORT, MYSQL_USER, MYSQL_PWD, MYSQL_DB,
)
from logs import LOGGER
import service

_TASK_CACHE = Cache("./tmp/perf")

SCENARIOS = ("upload", "batch_upload", "search_image", "search_text")


class PerfStore:
    """压测任务与结果的 MySQL 存储。"""

    def __init__(self):
        self.conn = None
        self.cursor = None
        self._last_ping = 0.0
        self._lock = threading.RLock()
        self._init_table()

    def _connect(self):
        self.conn = pymysql.connect(
            host=MYSQL_HOST, user=MYSQL_USER, port=MYSQL_PORT,
            password=MYSQL_PWD, database=MYSQL_DB,
            autocommit=True, connect_timeout=30, charset="utf8mb4",
        )
        self.cursor = self.conn.cursor()

    def _ensure_conn(self):
        now = time.time()
        if self.conn is None:
            self._connect()
            self._last_ping = now
        elif now - self._last_ping > 30:
            self.conn.ping(reconnect=True)
            self._last_ping = now

    def _init_table(self):
        try:
            self._ensure_conn()
            self.cursor.execute(
                "CREATE TABLE IF NOT EXISTS perf_results ("
                "id VARCHAR(32) PRIMARY KEY, "
                "scenario VARCHAR(32), table_name VARCHAR(128), query_text VARCHAR(255), "
                "total INT, concurrency INT, duration DOUBLE, qps DOUBLE, "
                "avg_ms DOUBLE, p50_ms DOUBLE, p90_ms DOUBLE, p95_ms DOUBLE, p99_ms DOUBLE, "
                "success INT, failed INT, status VARCHAR(16), errors TEXT, "
                "batch_size INT DEFAULT 0, images INT DEFAULT 0, "
                "images_per_sec DOUBLE DEFAULT 0, avg_ms_per_image DOUBLE DEFAULT 0, "
                "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
                "finished_at DATETIME DEFAULT NULL"
                ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;"
            )
            # 兼容旧表：缺列则补上
            for col, ddl in (
                ("query_text", "ALTER TABLE perf_results ADD COLUMN query_text VARCHAR(255) AFTER table_name"),
                ("errors", "ALTER TABLE perf_results ADD COLUMN errors TEXT AFTER status"),
                ("finished_at", "ALTER TABLE perf_results ADD COLUMN finished_at DATETIME AFTER created_at"),
                ("batch_size", "ALTER TABLE perf_results ADD COLUMN batch_size INT DEFAULT 0 AFTER failed"),
                ("images", "ALTER TABLE perf_results ADD COLUMN images INT DEFAULT 0 AFTER batch_size"),
                ("images_per_sec", "ALTER TABLE perf_results ADD COLUMN images_per_sec DOUBLE DEFAULT 0 AFTER images"),
                ("avg_ms_per_image", "ALTER TABLE perf_results ADD COLUMN avg_ms_per_image DOUBLE DEFAULT 0 AFTER images_per_sec"),
            ):
                self.cursor.execute(f"SHOW COLUMNS FROM perf_results LIKE '{col}'")
                if not self.cursor.fetchone():
                    try:
                        self.cursor.execute(ddl)
                    except Exception:
                        pass
        except Exception as e:
            LOGGER.error(f"初始化压测结果表失败: {e}")
            raise

    def start_record(self, task_id, scenario, table_name, total, concurrency, query_text="", batch_size=0):
        """压测开始时即写入一条 running 记录，保证中断也能追溯。"""
        self._ensure_conn()
        with self._lock:
            self.cursor.execute(
                "INSERT IGNORE INTO perf_results "
                "(id,scenario,table_name,query_text,total,concurrency,batch_size,status) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,'running')",
                (task_id, scenario, table_name, query_text or "", total, concurrency, batch_size),
            )

    def finish_record(self, data):
        """压测完成后更新完整结果。"""
        import json
        self._ensure_conn()
        errors = json.dumps(data.get("errors", []), ensure_ascii=False)[:4000]
        with self._lock:
            self.cursor.execute(
                "UPDATE perf_results SET "
                "duration=%s,qps=%s,avg_ms=%s,p50_ms=%s,p90_ms=%s,p95_ms=%s,p99_ms=%s,"
                "success=%s,failed=%s,batch_size=%s,images=%s,images_per_sec=%s,avg_ms_per_image=%s,"
                "status=%s,errors=%s,finished_at=NOW() "
                "WHERE id=%s",
                (data["duration"], data["qps"], data["avgMs"], data["p50Ms"],
                 data["p90Ms"], data["p95Ms"], data["p99Ms"], data["success"],
                 data["failed"], data.get("batchSize", 0), data.get("images", 0),
                 data.get("imagesPerSec", 0), data.get("avgMsPerImage", 0),
                 data["status"], errors, data["taskId"]),
            )

    def get_result(self, task_id):
        """从 MySQL 读取单条压测结果（持久化，重启后仍可查看）。"""
        import json
        self._ensure_conn()
        with self._lock:
            self.cursor.execute(
                "SELECT id,scenario,table_name,query_text,total,concurrency,duration,qps,"
                "avg_ms,p50_ms,p90_ms,p95_ms,p99_ms,success,failed,status,errors,"
                "created_at,finished_at,batch_size,images,images_per_sec,avg_ms_per_image "
                "FROM perf_results WHERE id=%s", (task_id,)
            )
            row = self.cursor.fetchone()
        if not row:
            return None
        try:
            errors = json.loads(row[16]) if row[16] else []
        except Exception:
            errors = [row[16]]
        return {
            "taskId": row[0], "scenario": row[1], "tableName": row[2],
            "queryText": row[3] or "", "total": row[4], "concurrency": row[5],
            "duration": round(row[6] or 0, 2), "qps": round(row[7] or 0, 1),
            "avgMs": round(row[8] or 0, 2), "p50Ms": round(row[9] or 0, 2),
            "p90Ms": round(row[10] or 0, 2), "p95Ms": round(row[11] or 0, 2),
            "p99Ms": round(row[12] or 0, 2), "success": row[13], "failed": row[14],
            "status": row[15], "errors": errors,
            "createdAt": str(row[17]) if row[17] else None,
            "finishedAt": str(row[18]) if row[18] else None,
            "batchSize": row[19] or 0, "images": row[20] or 0,
            "imagesPerSec": round(row[21] or 0, 1), "avgMsPerImage": round(row[22] or 0, 2),
        }

    def list_results(self, limit=50):
        self._ensure_conn()
        with self._lock:
            self.cursor.execute(
                "SELECT id,scenario,table_name,query_text,total,concurrency,duration,qps,"
                "avg_ms,p50_ms,p90_ms,p95_ms,p99_ms,success,failed,status,created_at,finished_at,"
                "batch_size,images,images_per_sec,avg_ms_per_image "
                "FROM perf_results ORDER BY created_at DESC LIMIT %s", (int(limit),)
            )
            rows = self.cursor.fetchall()
        return [{
            "taskId": r[0], "scenario": r[1], "tableName": r[2],
            "queryText": r[3] or "", "total": r[4], "concurrency": r[5],
            "duration": round(r[6] or 0, 2), "qps": round(r[7] or 0, 1),
            "avgMs": round(r[8] or 0, 2), "p50Ms": round(r[9] or 0, 2),
            "p90Ms": round(r[10] or 0, 2), "p95Ms": round(r[11] or 0, 2),
            "p99Ms": round(r[12] or 0, 2), "success": r[13], "failed": r[14],
            "status": r[15], "createdAt": str(r[16]) if r[16] else None,
            "finishedAt": str(r[17]) if r[17] else None,
            "batchSize": r[18] or 0, "images": r[19] or 0,
            "imagesPerSec": round(r[20] or 0, 1), "avgMsPerImage": round(r[21] or 0, 2),
        } for r in rows]

    def delete_result(self, task_id):
        self._ensure_conn()
        with self._lock:
            self.cursor.execute("DELETE FROM perf_results WHERE id=%s", (task_id,))
            return self.cursor.rowcount > 0


PERF_STORE = PerfStore()


def get_progress(task_id):
    return {
        "taskId": task_id,
        "scenario": _TASK_CACHE.get(f"{task_id}:scenario", ""),
        "current": _TASK_CACHE.get(f"{task_id}:current", 0),
        "total": _TASK_CACHE.get(f"{task_id}:total", 0),
        "success": _TASK_CACHE.get(f"{task_id}:success", 0),
        "failed": _TASK_CACHE.get(f"{task_id}:failed", 0),
        "status": _TASK_CACHE.get(f"{task_id}:status", "pending"),
        "message": _TASK_CACHE.get(f"{task_id}:message", ""),
    }


def get_result(task_id):
    return _TASK_CACHE.get(f"{task_id}:result")


def _percentile(arr, p):
    if len(arr) == 0:
        return 0.0
    return float(np.percentile(arr, p))


def _make_test_image():
    """生成一张内存中的测试图片字节（避免依赖外部文件）。"""
    import io
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (224, 224), (30, 60, 150))
    d = ImageDraw.Draw(img)
    d.rectangle([50, 50, 174, 174], fill=(240, 80, 60))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def run_perf(task_id, scenario, table_name, total, concurrency, model,
             milvus_cli, mysql_cli, minio_cli, query_text="红色物体", batch_size=500):
    """执行一次压测。total 为总请求数，concurrency 为并发数。

    batch_upload 场景：每次请求提交 batch_size 张图，total 表示请求批数；
    统计 QPS（批/秒）与图片吞吐（张/秒）。
    """
    _TASK_CACHE.set(f"{task_id}:scenario", scenario)
    _TASK_CACHE.set(f"{task_id}:total", total)
    _TASK_CACHE.set(f"{task_id}:current", 0)
    _TASK_CACHE.set(f"{task_id}:success", 0)
    _TASK_CACHE.set(f"{task_id}:failed", 0)
    _TASK_CACHE.set(f"{task_id}:status", "running")
    # 开始即写库，保证中断也能追溯
    try:
        PERF_STORE.start_record(task_id, scenario, table_name, total, concurrency,
                                query_text, batch_size if scenario == "batch_upload" else 0)
    except Exception as e:
        LOGGER.error(f"写压测开始记录失败: {e}")

    latencies = []          # 毫秒
    counter_lock = threading.Lock()
    done = [0]
    success = [0]
    failed = [0]
    images_done = [0]       # batch_upload 场景累计成功写入的图片数
    errors = []

    # 预生成测试图片，避免每次循环都编码图片
    test_image = _make_test_image()

    def one_op():
        start = time.perf_counter()
        batch_ok = 0
        try:
            if scenario == "upload":
                service.add_image(
                    table_name, test_image, model, milvus_cli, mysql_cli, minio_cli,
                    commodity_id=f"perf_{uuid.uuid4().hex[:8]}",
                    raw_url=f"perf_{uuid.uuid4().hex}.jpg", save_to_minio=False,
                )
                batch_ok = 1
            elif scenario == "batch_upload":
                # 一批 batch_size 张，走真实批量入库（流式分块 + 批量提特征/写库）
                items = [{
                    "image_bytes": test_image,
                    "commodity_id": f"perf_{uuid.uuid4().hex[:8]}",
                    "customs_param": None,
                    "raw_url": f"perf_batch_{uuid.uuid4().hex}.jpg",
                    "save_to_minio": False,
                } for _ in range(batch_size)]
                s, f, _ = service.add_images_batch(
                    table_name, items, model, milvus_cli, mysql_cli, minio_cli
                )
                batch_ok = s
            elif scenario == "search_image":
                service.search_by_image_lite(table_name, test_image, 10, model, milvus_cli)
            elif scenario == "search_text":
                service.search_by_text_lite(table_name, query_text, 10, model, milvus_cli)
            ok = True
        except Exception as e:
            ok = False
            with counter_lock:
                if len(errors) < 20:
                    errors.append(str(e)[:200])
        elapsed = (time.perf_counter() - start) * 1000
        with counter_lock:
            latencies.append(elapsed)
            done[0] += 1
            if ok:
                success[0] += 1
            else:
                failed[0] += 1
            if scenario == "batch_upload":
                images_done[0] += batch_ok
            # 每 100 次更新一次进度，减少 diskcache 写入开销
            if done[0] % max(100, total // 100) == 0 or done[0] == total:
                _TASK_CACHE.set(f"{task_id}:current", done[0])
                _TASK_CACHE.set(f"{task_id}:success", success[0])
                _TASK_CACHE.set(f"{task_id}:failed", failed[0])

    start_all = time.perf_counter()
    try:
        # 压测场景需要确保图库存在
        service.ensure_table(table_name, model, milvus_cli, mysql_cli)

        # 预热：先跑一次相同操作，触发 Milvus collection.load 冷启动与模型缓存，
        # 使统计反映稳态性能而非首次加载开销（否则 P99 会被冷启动拉高到数秒）
        try:
            if scenario == "upload":
                service.add_image(table_name, test_image, model, milvus_cli, mysql_cli,
                                  minio_cli, commodity_id="perf_warmup",
                                  raw_url=f"warmup_{uuid.uuid4().hex}.jpg", save_to_minio=False)
            elif scenario == "batch_upload":
                warm_items = [{
                    "image_bytes": test_image,
                    "commodity_id": "perf_warmup",
                    "customs_param": None,
                    "raw_url": f"warmup_{uuid.uuid4().hex}.jpg",
                    "save_to_minio": False,
                } for _ in range(min(batch_size, 10))]
                service.add_images_batch(table_name, warm_items, model, milvus_cli,
                                         mysql_cli, minio_cli)
            elif scenario == "search_image":
                service.search_by_image_lite(table_name, test_image, 10, model, milvus_cli)
            elif scenario == "search_text":
                service.search_by_text_lite(table_name, query_text, 10, model, milvus_cli)
        except Exception as e:
            LOGGER.warning(f"压测预热失败（不影响任务）: {e}")

        # 固定 worker 循环：每个线程处理一部分请求，避免一次性提交 total 个 future
        # （百万级压测时 future 对象本身会吃掉大量内存）
        def worker_loop(count):
            for _ in range(count):
                one_op()

        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
            base, remainder = divmod(total, concurrency)
            futures = []
            for i in range(concurrency):
                n = base + (1 if i < remainder else 0)
                if n > 0:
                    futures.append(pool.submit(worker_loop, n))
            for f in futures:
                try:
                    f.result()
                except Exception:
                    pass
    except Exception as e:
        LOGGER.error(f"压测任务 {task_id} 异常: {e}")
        _TASK_CACHE.set(f"{task_id}:message", str(e)[:200])

    duration = time.perf_counter() - start_all
    arr = np.array(latencies, dtype=np.float64)
    result = {
        "taskId": task_id,
        "scenario": scenario,
        "tableName": table_name,
        "total": total,
        "concurrency": concurrency,
        "duration": round(duration, 2),
        "qps": round(total / duration, 1) if duration > 0 else 0,
        "avgMs": round(float(np.mean(arr)), 2) if len(arr) else 0,
        "p50Ms": round(_percentile(arr, 50), 2),
        "p90Ms": round(_percentile(arr, 90), 2),
        "p95Ms": round(_percentile(arr, 95), 2),
        "p99Ms": round(_percentile(arr, 99), 2),
        "success": success[0],
        "failed": failed[0],
        "batchSize": batch_size if scenario == "batch_upload" else 0,
        "images": images_done[0],
        "imagesPerSec": round(images_done[0] / duration, 1) if duration > 0 else 0,
        "avgMsPerImage": round((sum(latencies) / images_done[0]), 2)
                         if images_done[0] > 0 else 0,
        "errors": errors,
        "status": "done",
    }
    _TASK_CACHE.set(f"{task_id}:current", done[0])
    _TASK_CACHE.set(f"{task_id}:success", success[0])
    _TASK_CACHE.set(f"{task_id}:failed", failed[0])
    _TASK_CACHE.set(f"{task_id}:status", "done")
    _TASK_CACHE.set(f"{task_id}:result", result)
    try:
        PERF_STORE.finish_record(result)
    except Exception as e:
        LOGGER.error(f"保存压测结果失败: {e}")
    LOGGER.info(f"压测完成 {task_id}: QPS={result['qps']} P95={result['p95Ms']}ms")
    return result
