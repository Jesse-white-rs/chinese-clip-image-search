"""日志读取模块：供后端日志查询接口使用。

日志由 logs.py 以 MultiprocessHandler 写入 ./logs/milvus-YYYY-MM-DD.log，
本模块提供日志文件列表与尾部内容读取（支持按级别过滤）。
"""
import os
import re
from config import BASE_DIR


def _decode_line(raw: bytes) -> str:
    """解码单行日志：优先 UTF-8，失败回退 GBK，最后兜底 replace。

    逐行解码可以正确处理同一个文件里前半段 GBK、后半段 UTF-8 的混合编码情况。
    """
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        pass
    try:
        return raw.decode("gbk")
    except UnicodeDecodeError:
        return raw.decode("utf-8", errors="replace")


# 日志目录：优先 src/logs（服务实际工作目录），不存在时回退到项目根 logs
LOG_DIR_CANDIDATES = [
    os.path.join(BASE_DIR, "src", "logs"),
    os.path.join(BASE_DIR, "logs"),
]


def _log_dir():
    for d in LOG_DIR_CANDIDATES:
        if os.path.isdir(d):
            return d
    return LOG_DIR_CANDIDATES[0]


def list_logs():
    """列出所有日志文件，按修改时间倒序。"""
    d = _log_dir()
    result = []
    if not os.path.isdir(d):
        return result
    for name in os.listdir(d):
        # 支持系统日志(milvus-*)与业务审计日志(audit-*)
        if not name.endswith(".log") or not (name.startswith("milvus-") or name.startswith("audit-")):
            continue
        path = os.path.join(d, name)
        try:
            stat = os.stat(path)
            result.append({
                "name": name,
                "size": stat.st_size,
                "modified": int(stat.st_mtime),
            })
        except OSError:
            continue
    result.sort(key=lambda x: x["modified"], reverse=True)
    return result


def read_log(name, lines=200, level=None):
    """读取指定日志文件的尾部若干行。

    name 只允许简单文件名，防止路径穿越。
    level 为日志级别（如 ERROR/WARN/INFO/DEBUG），传入时按级别过滤。
    """
    if not name or os.path.basename(name) != name or not name.endswith(".log"):
        raise ValueError("非法的日志文件名")
    path = os.path.join(_log_dir(), name)
    if not os.path.isfile(path):
        raise FileNotFoundError("日志文件不存在")

    # 按字节读取后逐行智能解码：兼容同一文件内 UTF-8/GBK 混合编码的情况
    # （历史日志由 Windows 默认 GBK 写入，新版改为 UTF-8，可能共存于一个文件）
    with open(path, "rb") as f:
        raw_lines = f.readlines()
    content = [_decode_line(line) for line in raw_lines]

    if level:
        pattern = re.compile(rf"｜\s*{re.escape(level.upper())}\s*｜")
        content = [line for line in content if pattern.search(line)]

    # 返回最后 lines 行
    return [line.rstrip("\n") for line in content[-lines:]]
