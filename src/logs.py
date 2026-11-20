import os
import re
import datetime
import logging
import sys
from config import LOG_RETENTION_DAYS

try:
    import codecs
except ImportError:
    codecs = None


class MultiprocessHandler(logging.FileHandler):
    """按天切割的日志文件处理器，并自动清理超过保留期的旧日志。"""

    def __init__(self, filename, when='D', encoding=None, delay=False):
        self.prefix = filename
        self.when = when.upper()
        self.extMath = r"^\d{4}-\d{2}-\d{2}"

        self.when_dict = {
            'S': "%Y-%m-%d-%H-%M-%S",
            'M': "%Y-%m-%d-%H-%M",
            'H': "%Y-%m-%d-%H",
            'D': "%Y-%m-%d"
        }
        self.suffix = self.when_dict.get(when)
        if not self.suffix:
            print('The specified date interval unit is invalid: ', self.when)
            sys.exit(1)

        # 日志目录：相对工作目录的 ./logs，与 log_reader 的查找路径一致
        self.log_dir = os.path.join('.', "logs")
        self.filefmt = os.path.join(self.log_dir, f"{self.prefix}-{self.suffix}.log")
        self.filePath = datetime.datetime.now().strftime(self.filefmt)

        try:
            if not os.path.exists(self.log_dir):
                os.makedirs(self.log_dir)
        except Exception as e:
            print('Failed to create log file: ', e)
            print("log_path：" + self.filePath)
            sys.exit(1)

        if codecs is None:
            encoding = None

        # 明确使用 UTF-8，避免 Windows 默认 GBK 导致日志中文在前端乱码
        logging.FileHandler.__init__(self, self.filePath, 'a+', encoding or 'utf-8', delay)
        # 启动时先清理一次过期日志
        self._cleanup_old_logs()

    def shouldChangeFileToWrite(self):
        _filePath = datetime.datetime.now().strftime(self.filefmt)
        if _filePath != self.filePath:
            self.filePath = _filePath
            return True
        return False

    def doChangeFile(self):
        self.baseFilename = os.path.abspath(self.filePath)
        if self.stream:
            self.stream.close()
            self.stream = None
        if not self.delay:
            self.stream = self._open()
        # 每次切到新日志文件时清理过期日志
        self._cleanup_old_logs()

    def _cleanup_old_logs(self):
        """删除文件名日期早于保留期的日志（默认保留 10 天）。"""
        if LOG_RETENTION_DAYS <= 0 or not os.path.isdir(self.log_dir):
            return
        cutoff = datetime.date.today() - datetime.timedelta(days=LOG_RETENTION_DAYS)
        pattern = re.compile(self.extMath)
        # 同时清理系统日志(milvus-*)与审计日志(audit-*)
        for name in os.listdir(self.log_dir):
            if not name.endswith('.log'):
                continue
            matched = False
            for prefix in (self.prefix + '-', 'audit-'):
                if name.startswith(prefix):
                    date_str = name[len(prefix):-4]
                    if pattern.match(date_str):
                        matched = True
                        break
            if not matched:
                continue
            try:
                file_date = datetime.datetime.strptime(date_str[:10], "%Y-%m-%d").date()
            except ValueError:
                continue
            if file_date < cutoff:
                try:
                    os.remove(os.path.join(self.log_dir, name))
                except OSError:
                    pass

    def emit(self, record):
        try:
            if self.shouldChangeFileToWrite():
                self.doChangeFile()
            logging.FileHandler.emit(self, record)
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            self.handleError(record)


def write_log():
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    fmt = logging.Formatter(
        '%(asctime)s ｜ %(levelname)s ｜ %(filename)s ｜ %(funcName)s ｜ %(lineno)s ｜ %(message)s')

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(fmt)

    file_handler = MultiprocessHandler("milvus", when='D')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(fmt)
    file_handler.doChangeFile()

    # 避免重复添加 handler（模块重载时）
    if not any(isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
               for h in logger.handlers):
        logger.addHandler(stream_handler)
    if not any(isinstance(h, MultiprocessHandler) for h in logger.handlers):
        logger.addHandler(file_handler)

    return logger


LOGGER = write_log()
