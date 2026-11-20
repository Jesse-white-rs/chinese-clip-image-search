"""定时备份模块。

功能：
- 备份任务存储在 MySQL 表 backup_tasks；
- 使用 APScheduler 按 cron 表达式调度；
- 每个备份导出：MySQL 映射表(CSV) + Milvus 向量(npy) + manifest(JSON)，打包为 tar.gz；
- MinIO 原图默认不打包（数据量大），仅在 manifest 中记录对象名清单；
- 多 worker 部署时用文件锁保证只有一个进程启动调度器；
- 备份文件按保留天数自动清理。

备份目录结构：
    backups/{table}/{timestamp}/
        ├── mysql.csv
        ├── milvus_ids.npy
        ├── milvus_vectors.npy
        ├── minio_objects.txt
        └── manifest.json
    打包后：backups/{table}_{timestamp}.tar.gz，临时目录删除。
"""
import os
import csv
import json
import time
import threading
import tarfile
import shutil
import datetime
from typing import Optional

import pymysql
import numpy as np
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from pymilvus import Collection, utility

from config import (
    MYSQL_HOST, MYSQL_PORT, MYSQL_USER, MYSQL_PWD, MYSQL_DB,
    BACKUP_DIR, BACKUP_RETENTION_DAYS, VECTOR_DIMENSION, METRIC_TYPE,
)
from logs import LOGGER


class BackupStore:
    """备份任务与执行历史的 MySQL 存储。"""

    def __init__(self):
        self.conn = None
        self.cursor = None
        self._last_ping = 0.0
        self._lock = threading.RLock()
        self._init_tables()

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

    def _init_tables(self):
        try:
            self._ensure_conn()
            self.cursor.execute(
                "CREATE TABLE IF NOT EXISTS backup_tasks ("
                "id BIGINT AUTO_INCREMENT PRIMARY KEY, "
                "name VARCHAR(128) NOT NULL, "
                "table_name VARCHAR(128) NOT NULL, "
                "cron_expr VARCHAR(64) NOT NULL DEFAULT '0 2 * * *', "
                "enabled TINYINT(1) NOT NULL DEFAULT 1, "
                "include_minio TINYINT(1) NOT NULL DEFAULT 0, "
                "retention_days INT NOT NULL DEFAULT 30, "
                "last_run DATETIME DEFAULT NULL, "
                "last_status VARCHAR(16) DEFAULT NULL, "
                "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"
                ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;"
            )
            self.cursor.execute(
                "CREATE TABLE IF NOT EXISTS backup_history ("
                "id BIGINT AUTO_INCREMENT PRIMARY KEY, "
                "task_id BIGINT, "
                "table_name VARCHAR(128), "
                "status VARCHAR(16), "
                "message TEXT, "
                "file_path VARCHAR(512), "
                "size_bytes BIGINT DEFAULT 0, "
                "started_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
                "finished_at DATETIME DEFAULT NULL"
                ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;"
            )
        except Exception as e:
            LOGGER.error(f"初始化备份表失败: {e}")
            raise

    @staticmethod
    def _task_dict(row):
        if not row:
            return None
        return {
            "id": row[0], "name": row[1], "tableName": row[2],
            "cronExpr": row[3], "enabled": bool(row[4]),
            "includeMinio": bool(row[5]), "retentionDays": row[6],
            "lastRun": str(row[7]) if row[7] else None,
            "lastStatus": row[8], "createdAt": str(row[9]) if row[9] else None,
        }

    def list_tasks(self):
        self._ensure_conn()
        with self._lock:
            self.cursor.execute(
                "SELECT id,name,table_name,cron_expr,enabled,include_minio,"
                "retention_days,last_run,last_status,created_at FROM backup_tasks ORDER BY id"
            )
            return [self._task_dict(r) for r in self.cursor.fetchall()]

    def get_task(self, task_id):
        self._ensure_conn()
        with self._lock:
            self.cursor.execute(
                "SELECT id,name,table_name,cron_expr,enabled,include_minio,"
                "retention_days,last_run,last_status,created_at FROM backup_tasks WHERE id=%s",
                (int(task_id),)
            )
            return self._task_dict(self.cursor.fetchone())

    def create_task(self, name, table_name, cron_expr, enabled=True,
                    include_minio=False, retention_days=30):
        self._ensure_conn()
        with self._lock:
            self.cursor.execute(
                "INSERT INTO backup_tasks (name,table_name,cron_expr,enabled,include_minio,retention_days) "
                "VALUES (%s,%s,%s,%s,%s,%s)",
                (name, table_name, cron_expr, 1 if enabled else 0,
                 1 if include_minio else 0, int(retention_days)),
            )
            return self.cursor.lastrowid

    def update_task(self, task_id, **fields):
        mapping = {
            "name": "name", "tableName": "table_name", "cronExpr": "cron_expr",
            "enabled": "enabled", "includeMinio": "include_minio",
            "retentionDays": "retention_days",
        }
        sets, params = [], []
        for key, col in mapping.items():
            if key in fields:
                val = fields[key]
                if key in ("enabled", "includeMinio"):
                    val = 1 if val else 0
                sets.append(f"{col}=%s")
                params.append(val)
        if not sets:
            return False
        params.append(int(task_id))
        self._ensure_conn()
        with self._lock:
            self.cursor.execute(f"UPDATE backup_tasks SET {','.join(sets)} WHERE id=%s", params)
            return self.cursor.rowcount > 0

    def delete_task(self, task_id):
        self._ensure_conn()
        with self._lock:
            self.cursor.execute("DELETE FROM backup_tasks WHERE id=%s", (int(task_id),))
            return self.cursor.rowcount > 0

    def mark_run(self, task_id, status):
        self._ensure_conn()
        with self._lock:
            self.cursor.execute(
                "UPDATE backup_tasks SET last_run=NOW(), last_status=%s WHERE id=%s",
                (status, int(task_id)),
            )

    def add_history(self, task_id, table_name, status, message, file_path="", size=0):
        self._ensure_conn()
        with self._lock:
            self.cursor.execute(
                "INSERT INTO backup_history (task_id,table_name,status,message,file_path,size_bytes,finished_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,NOW())",
                (task_id, table_name, status, message[:500], file_path, int(size)),
            )
            return self.cursor.lastrowid

    def list_history(self, task_id=None, limit=50):
        self._ensure_conn()
        with self._lock:
            if task_id:
                self.cursor.execute(
                    "SELECT id,task_id,table_name,status,message,file_path,size_bytes,started_at,finished_at "
                    "FROM backup_history WHERE task_id=%s ORDER BY id DESC LIMIT %s",
                    (int(task_id), int(limit)),
                )
            else:
                self.cursor.execute(
                    "SELECT id,task_id,table_name,status,message,file_path,size_bytes,started_at,finished_at "
                    "FROM backup_history ORDER BY id DESC LIMIT %s", (int(limit),)
                )
            rows = self.cursor.fetchall()
        return [{
            "id": r[0], "taskId": r[1], "tableName": r[2], "status": r[3],
            "message": r[4], "filePath": r[5], "sizeBytes": r[6],
            "startedAt": str(r[7]) if r[7] else None,
            "finishedAt": str(r[8]) if r[8] else None,
        } for r in rows]


# ---------------------- 备份执行 ----------------------
def _export_mysql_csv(table_name, out_path):
    """导出 MySQL 映射表为 CSV。"""
    conn = pymysql.connect(
        host=MYSQL_HOST, user=MYSQL_USER, port=MYSQL_PORT,
        password=MYSQL_PWD, database=MYSQL_DB,
        connect_timeout=30, charset="utf8mb4",
    )
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT milvus_id,image_path,customs_param,raw_url,commodity_id "
                f"FROM `{table_name}` ORDER BY milvus_id"
            )
            rows = cur.fetchall()
        with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["milvus_id", "image_path", "customs_param", "raw_url", "commodity_id"])
            writer.writerows(rows)
        return len(rows)
    finally:
        conn.close()


def _export_milvus_vectors(table_name, ids_path, vecs_path):
    """分页导出 Milvus 集合的 id 与向量，保存为 npy。"""
    if not utility.has_collection(table_name):
        raise RuntimeError(f"Milvus 集合 {table_name} 不存在")
    collection = Collection(name=table_name)
    collection.flush()
    total = collection.num_entities
    ids_list, vec_list = [], []
    page_size = 2000
    offset = 0
    while offset < total:
        results = collection.query(
            expr="id >= 0", output_fields=["id", "embedding"],
            limit=page_size, offset=offset,
        )
        if not results:
            break
        ids_list.extend(int(r["id"]) for r in results)
        vec_list.extend(r["embedding"] for r in results)
        offset += len(results)
    np.save(ids_path, np.array(ids_list, dtype=np.int64))
    np.save(vecs_path, np.array(vec_list, dtype=np.float32).reshape(-1, VECTOR_DIMENSION))
    return len(ids_list)


def _export_minio_list(table_name, out_path):
    """记录该图库下 MinIO 对象名清单（不打包原图，仅用于回溯）。"""
    try:
        from minio_helpers import MinioHelper
        cli = MinioHelper()
        objects = cli.list_images(table_name)
        with open(out_path, "w", encoding="utf-8") as f:
            for obj in objects:
                f.write(obj["object_name"] + "\n")
        return len(objects)
    except Exception as e:
        LOGGER.warning(f"导出 MinIO 清单失败（不影响备份）: {e}")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write("")
        return 0


def execute_backup(store, task_id, minio_cli=None):
    """执行一次备份，返回 (status, message, file_path, size)。"""
    task = store.get_task(task_id)
    if not task:
        return "failed", "任务不存在", "", 0
    table_name = task["tableName"]
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    tmp_dir = os.path.join(BACKUP_DIR, ".tmp", f"{table_name}_{timestamp}")
    os.makedirs(tmp_dir, exist_ok=True)
    archive_path = os.path.join(BACKUP_DIR, f"{table_name}_{timestamp}.tar.gz")

    try:
        mysql_path = os.path.join(tmp_dir, "mysql.csv")
        ids_path = os.path.join(tmp_dir, "milvus_ids.npy")
        vecs_path = os.path.join(tmp_dir, "milvus_vectors.npy")
        minio_list_path = os.path.join(tmp_dir, "minio_objects.txt")

        mysql_count = _export_mysql_csv(table_name, mysql_path)
        vector_count = _export_milvus_vectors(table_name, ids_path, vecs_path)
        minio_count = _export_minio_list(table_name, minio_list_path)

        manifest = {
            "table": table_name,
            "createdAt": datetime.datetime.now().isoformat(),
            "vectorDim": VECTOR_DIMENSION,
            "metricType": METRIC_TYPE,
            "mysqlRows": mysql_count,
            "vectorRows": vector_count,
            "minioObjects": minio_count,
            "minioImagesIncluded": False,
            "note": "MinIO 原图未打包；minio_objects.txt 列出对象名，可从 MinIO 单独导出。",
        }
        with open(os.path.join(tmp_dir, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)

        # 打包为 tar.gz
        os.makedirs(BACKUP_DIR, exist_ok=True)
        with tarfile.open(archive_path, "w:gz") as tar:
            for name in os.listdir(tmp_dir):
                tar.add(os.path.join(tmp_dir, name), arcname=name)

        size = os.path.getsize(archive_path)
        msg = f"备份完成：MySQL {mysql_count} 行，向量 {vector_count} 条，MinIO 对象 {minio_count} 个"
        LOGGER.info(msg)
        return "success", msg, archive_path, size
    except Exception as e:
        LOGGER.error(f"备份 {table_name} 失败: {e}")
        if os.path.exists(archive_path):
            os.remove(archive_path)
        return "failed", str(e), "", 0
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def run_task(store, task_id):
    """调度器/手动触发统一入口：执行备份并写历史。"""
    task = store.get_task(task_id)
    if not task:
        return
    LOGGER.info(f"开始执行备份任务: {task['name']} ({task['tableName']})")
    status, message, path, size = execute_backup(store, task_id)
    store.mark_run(task_id, status)
    store.add_history(task_id, task["tableName"], status, message, path, size)
    cleanup_old_backups()


def cleanup_old_backups():
    """删除超过保留天数的备份压缩包。"""
    if not os.path.isdir(BACKUP_DIR) or BACKUP_RETENTION_DAYS <= 0:
        return
    cutoff = datetime.datetime.now() - datetime.timedelta(days=BACKUP_RETENTION_DAYS)
    for name in os.listdir(BACKUP_DIR):
        if not name.endswith(".tar.gz"):
            continue
        path = os.path.join(BACKUP_DIR, name)
        try:
            mtime = datetime.datetime.fromtimestamp(os.path.getmtime(path))
            if mtime < cutoff:
                os.remove(path)
                LOGGER.info(f"清理过期备份: {name}")
        except OSError as e:
            LOGGER.warning(f"清理备份失败 {name}: {e}")


def list_backup_files():
    """列出备份文件。"""
    result = []
    if not os.path.isdir(BACKUP_DIR):
        return result
    for name in os.listdir(BACKUP_DIR):
        if not name.endswith(".tar.gz"):
            continue
        path = os.path.join(BACKUP_DIR, name)
        try:
            stat = os.stat(path)
            result.append({"name": name, "sizeBytes": stat.st_size,
                           "createdAt": datetime.datetime.fromtimestamp(stat.st_mtime).isoformat()})
        except OSError:
            continue
    result.sort(key=lambda x: x["createdAt"], reverse=True)
    return result


def delete_backup_file(name):
    """删除指定备份文件，防止路径穿越。"""
    if not name or os.path.basename(name) != name or not name.endswith(".tar.gz"):
        return False
    path = os.path.join(BACKUP_DIR, name)
    if not os.path.isfile(path):
        return False
    try:
        os.remove(path)
        return True
    except OSError:
        return False


# ---------------------- 调度器 ----------------------
class _FileLock:
    """跨平台文件锁：Linux 用 fcntl，Windows 用 msvcrt，保证多 worker 只有一个跑调度器。"""

    def __init__(self, path):
        self.path = path
        self.fd = None

    def acquire(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.fd = open(self.path, "a+")
        try:
            import fcntl
            fcntl.flock(self.fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except ImportError:
            pass
        except OSError:
            return False
        try:
            import msvcrt
            self.fd.seek(0)
            msvcrt.locking(self.fd.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except Exception:
            return False

    def release(self):
        if not self.fd:
            return
        try:
            import msvcrt
            self.fd.seek(0)
            msvcrt.locking(self.fd.fileno(), msvcrt.LK_UNLCK, 1)
        except Exception:
            pass
        try:
            import fcntl
            fcntl.flock(self.fd.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        self.fd.close()
        self.fd = None


class BackupScheduler:
    """备份调度器：从数据库加载启用的任务，按 cron 表达式注册定时任务。"""

    def __init__(self, store):
        self.store = store
        self.scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
        self.lock = _FileLock(os.path.join(BACKUP_DIR, ".scheduler.lock"))
        self._locked = False
        self._job_tasks = {}   # job_id -> task_id

    def start(self):
        if not self.lock.acquire():
            LOGGER.info("另一个进程已持有备份调度器锁，跳过启动调度器")
            return False
        self._locked = True
        self.reload_jobs()
        # 启动时清理一次过期备份
        cleanup_old_backups()
        self.scheduler.start()
        LOGGER.info("备份调度器已启动")
        return True

    def shutdown(self):
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
        if self._locked:
            self.lock.release()
            self._locked = False

    def _job_id(self, task_id):
        return f"backup_task_{task_id}"

    def reload_jobs(self):
        """按数据库当前任务状态重建所有定时任务。"""
        if not self._locked:
            return
        self.scheduler.remove_all_jobs()
        self._job_tasks.clear()
        for task in self.store.list_tasks():
            if not task["enabled"]:
                continue
            job_id = self._job_id(task["id"])
            try:
                trigger = CronTrigger.from_crontab(task["cronExpr"], timezone="Asia/Shanghai")
                self.scheduler.add_job(
                    self._run_job, trigger, id=job_id,
                    args=[task["id"]], replace_existing=True,
                )
                self._job_tasks[job_id] = task["id"]
                LOGGER.info(f"注册备份任务: {task['name']} ({task['cronExpr']})")
            except Exception as e:
                LOGGER.error(f"注册备份任务 {task['name']} 失败: {e}")

    def _run_job(self, task_id):
        try:
            run_task(self.store, task_id)
        except Exception as e:
            LOGGER.error(f"定时任务执行异常 task_id={task_id}: {e}")

    def next_run(self, task_id):
        """返回任务下次运行时间字符串。"""
        if not self._locked:
            return None
        job = self.scheduler.get_job(self._job_id(task_id))
        if job and job.next_run_time:
            return str(job.next_run_time)
        return None


# 模块级单例：导入时建表，调度器由 main.py 在启动时显式 start
BACKUP_STORE = BackupStore()
BACKUP_SCHEDULER = BackupScheduler(BACKUP_STORE)

