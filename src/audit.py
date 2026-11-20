"""业务审计日志模块。

单独写入 logs/audit-YYYY-MM-DD.log，记录每次上传/检索的详细参数与结果，
与系统运行日志（milvus-*.log）分开，便于前端日志页筛选和排障。

格式：时间 | AUDIT | 操作 | key=value key=value ...
"""
import os
import datetime
import logging
from logging.handlers import TimedRotatingFileHandler


class _AuditLogger(logging.FileHandler):
    """按天切换的审计日志处理器（不依赖 backupCount，清理由 logs.py 统一按天删除）。"""

    def __init__(self, log_dir="./logs"):
        os.makedirs(log_dir, exist_ok=True)
        self.log_dir = log_dir
        self.current_date = datetime.date.today()
        path = self._path(self.current_date)
        logging.FileHandler.__init__(self, path, "a+", encoding="utf-8")

    def _path(self, date):
        return os.path.join(self.log_dir, f"audit-{date.strftime('%Y-%m-%d')}.log")

    def should_rollover(self):
        return datetime.date.today() != self.current_date

    def do_rollover(self):
        if self.stream:
            self.stream.close()
        self.current_date = datetime.date.today()
        self.baseFilename = os.path.abspath(self._path(self.current_date))
        self.stream = self._open()

    def emit(self, record):
        try:
            if self.should_rollover():
                self.do_rollover()
            logging.FileHandler.emit(self, record)
        except Exception:
            self.handleError(record)


_audit = logging.getLogger("audit")
_audit.setLevel(logging.INFO)
_audit.propagate = False          # 不冒泡到根 logger，避免写进业务日志
if not _audit.handlers:
    _handler = _AuditLogger()
    # 与系统日志保持一致的带时间格式，前端靠 "｜ AUDIT ｜" 识别审计行着色
    _handler.setFormatter(logging.Formatter(
        '%(asctime)s ｜ AUDIT ｜ %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    ))
    _audit.addHandler(_handler)


def _fmt(kv: dict) -> str:
    """把字典拼成 key=value，值统一转字符串并对空格做转义。"""
    return " ".join(f"{k}={str(v).replace(' ', '_')}" for k, v in kv.items())


def log_upload(table, source, raw_url, commodity_id, customs_param,
               save_to_minio, img_id, object_name, success, cost_ms, error=""):
    """记录一次图片入库（单张/手动 ID 上传）。"""
    _audit.info("UPLOAD " + _fmt({
        "table": table, "source": source, "url": raw_url or "-",
        "commodityId": commodity_id or "-", "customsParam": customs_param or "-",
        "saveMinio": save_to_minio, "imgId": img_id or "-",
        "objectName": object_name or "-", "success": success,
        "costMs": cost_ms, "error": error or "-",
    }))


def log_batch(table, total, success, failed, save_to_minio, task_id, cost_ms):
    """记录一次批量/目录入库任务。"""
    _audit.info("BATCH " + _fmt({
        "table": table, "taskId": task_id, "total": total,
        "success": success, "failed": failed,
        "saveMinio": save_to_minio, "costMs": cost_ms,
    }))


def log_search(table, mode, query, topk, result_count, max_similarity, cost_ms, success=True, error=""):
    """记录一次检索（以图搜图 / 文本搜图 / 轻量版）。"""
    _audit.info("SEARCH " + _fmt({
        "table": table, "mode": mode, "query": query or "-",
        "topk": topk, "results": result_count, "maxSim": max_similarity or "-",
        "success": success, "costMs": cost_ms, "error": error or "-",
    }))


def log_delete(table, img_id, success=True, error=""):
    """记录一次删除。"""
    _audit.info("DELETE " + _fmt({
        "table": table, "imgId": img_id, "success": success, "error": error or "-",
    }))
