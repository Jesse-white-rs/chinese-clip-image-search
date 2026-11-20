import time
import threading
import pymysql
import traceback
from config import (
    MYSQL_HOST, MYSQL_PORT, MYSQL_USER, MYSQL_PWD, MYSQL_DB, MYSQL_PING_INTERVAL
)
from logs import LOGGER


class MySQLHelper:
    """MySQL 映射表操作类。

    表中 image_path 为空表示图片未落 MinIO，仅入库向量与业务字段。
    性能优化：连接探活按间隔执行（默认 30 秒一次），避免每次 SQL 都 ping 带来的往返开销。
    """

    def __init__(self):
        self.conn = None
        self.cursor = None
        self.connected = False
        self._last_ping = 0.0
        self._lock = threading.RLock()
        self.test_connection()

    def test_connection(self):
        """建立连接，或在达到探活间隔后 ping 一次确认连接可用。"""
        try:
            now = time.time()
            if self.conn is None:
                self.conn = pymysql.connect(
                    host=MYSQL_HOST, user=MYSQL_USER, port=MYSQL_PORT,
                    password=MYSQL_PWD, database=MYSQL_DB,
                    autocommit=True, connect_timeout=30, read_timeout=30,
                    charset="utf8mb4",
                )
                self.cursor = self.conn.cursor()
            elif now - self._last_ping > MYSQL_PING_INTERVAL:
                self.conn.ping(reconnect=True)
            self._last_ping = now
            self.connected = True
            return True
        except Exception as e:
            self.connected = False
            LOGGER.error(f"MySQL 连接失败: {e}")
            return False

    def health(self):
        return self.connected

    def create_table(self, table_name):
        """建表（幂等）：表名用反引号包裹，避免关键字冲突。"""
        self.test_connection()
        sql = (
            f"CREATE TABLE IF NOT EXISTS `{table_name}` ("
            "milvus_id BIGINT NOT NULL, "
            "image_path VARCHAR(512) DEFAULT NULL, "
            "customs_param TEXT, "
            "raw_url VARCHAR(1024) DEFAULT NULL, "
            "commodity_id VARCHAR(255) DEFAULT NULL, "
            "PRIMARY KEY (milvus_id), "
            "UNIQUE KEY uk_url_commodity (raw_url(255), commodity_id)"
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;"
        )
        try:
            with self._lock:
                self.cursor.execute(sql)
            return True
        except Exception as e:
            LOGGER.error(f"创建 MySQL 表失败: {traceback.format_exc()} SQL: {sql}")
            return False

    def insert(self, table_name, rows):
        """批量写入。rows: [(milvus_id, image_path, customs_param, raw_url, commodity_id), ...]"""
        if not rows:
            return True
        self.test_connection()
        sql = (
            f"INSERT INTO `{table_name}` "
            "(milvus_id, image_path, customs_param, raw_url, commodity_id) "
            "VALUES (%s,%s,%s,%s,%s);"
        )
        try:
            with self._lock:
                self.cursor.executemany(sql, rows)
            return True
        except Exception as e:
            LOGGER.error(f"MySQL 批量写入失败: {e}")
            return False

    def exists_by_url(self, table_name, raw_url, commodity_id):
        """按 (raw_url, commodity_id) 查重，返回已存在的 milvus_id。"""
        self.test_connection()
        sql = f"SELECT milvus_id FROM `{table_name}` WHERE raw_url=%s AND commodity_id=%s LIMIT 1;"
        try:
            with self._lock:
                self.cursor.execute(sql, (raw_url, commodity_id))
                result = self.cursor.fetchone()
            return str(result[0]) if result else None
        except Exception as e:
            LOGGER.error(f"查询重复图片失败: {e}")
            return None

    def get_image_path(self, table_name, milvus_id):
        """按 milvus_id 查询 MinIO 对象名。"""
        self.test_connection()
        sql = f"SELECT image_path FROM `{table_name}` WHERE milvus_id=%s LIMIT 1;"
        try:
            with self._lock:
                self.cursor.execute(sql, (int(milvus_id),))
                result = self.cursor.fetchone()
            return result[0] if result else None
        except Exception as e:
            LOGGER.error(f"查询图片路径失败: {e}")
            return None

    def get_rows_by_ids(self, table_name, ids):
        """按 milvus_id 批量取业务字段，返回 {id: row_dict}，供检索结果组装。"""
        if not ids:
            return {}
        self.test_connection()
        placeholders = ",".join(str(int(i)) for i in ids)
        sql = (
            f"SELECT milvus_id, image_path, customs_param, raw_url, commodity_id "
            f"FROM `{table_name}` WHERE milvus_id IN ({placeholders});"
        )
        try:
            with self._lock:
                self.cursor.execute(sql)
                rows = self.cursor.fetchall()
            return {
                str(row[0]): {
                    "imgId": str(row[0]),
                    "customsParams": row[2],
                    "rawUrl": row[3],
                    "commodityId": row[4],
                    "hasMinioImage": bool(row[1]),
                }
                for row in rows
            }
        except Exception as e:
            LOGGER.error(f"批量查询业务字段失败: {e}")
            return {}

    def delete_by_id(self, table_name, milvus_id):
        """按 milvus_id 删除映射记录。"""
        self.test_connection()
        sql = f"DELETE FROM `{table_name}` WHERE milvus_id=%s;"
        try:
            with self._lock:
                self.cursor.execute(sql, (int(milvus_id),))
            return True
        except Exception as e:
            LOGGER.error(f"删除记录失败: {e}")
            return False

    def clear_table(self, table_name):
        """清空映射表全部记录，保留表结构（用于一键清空图库图片）。"""
        self.test_connection()
        try:
            with self._lock:
                self.cursor.execute(f"TRUNCATE TABLE `{table_name}`;")
            return True
        except Exception as e:
            LOGGER.error(f"清空 MySQL 表失败: {e}")
            return False

    def delete_table(self, table_name):
        """删除整张映射表。"""
        self.test_connection()
        try:
            with self._lock:
                self.cursor.execute(f"DROP TABLE IF EXISTS `{table_name}`;")
            return True
        except Exception as e:
            LOGGER.error(f"删除 MySQL 表失败: {e}")
            return False

    def count(self, table_name):
        """统计映射记录数。"""
        self.test_connection()
        try:
            with self._lock:
                self.cursor.execute(f"SELECT COUNT(*) FROM `{table_name}`;")
                return self.cursor.fetchone()[0]
        except Exception as e:
            LOGGER.error(f"统计记录数失败: {e}")
            return 0

    def page(self, table_name, page=1, size=10):
        """分页查询映射记录。"""
        self.test_connection()
        try:
            with self._lock:
                self.cursor.execute(f"SELECT COUNT(*) FROM `{table_name}`;")
                total = self.cursor.fetchone()[0]
                offset = (page - 1) * size
                self.cursor.execute(
                    f"SELECT milvus_id, image_path, customs_param, raw_url, commodity_id "
                    f"FROM `{table_name}` ORDER BY milvus_id LIMIT {offset},{size};"
                )
                rows = self.cursor.fetchall()
            data = [
                {
                    "imgId": str(row[0]),
                    "hasMinioImage": bool(row[1]),
                    "customsParams": row[2],
                    "rawUrl": row[3],
                    "commodityId": row[4],
                }
                for row in rows
            ]
            return {"total": total, "totalPages": (total + size - 1) // size,
                    "page": page, "size": size, "data": data}
        except Exception as e:
            LOGGER.error(f"分页查询失败: {e}")
            return {"total": 0, "totalPages": 0, "page": page, "size": size, "data": []}
