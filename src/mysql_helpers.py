"""MySQL 映射表操作类（连接池版）。

用 DBUtils PooledDB 管理连接池：每个操作借独立连接，用完归还，
避免单连接 + 全局锁在高并发写入时排队、超时（30 万压测会打爆单连接）。

表中 image_path 为空表示图片未落 MinIO，仅入库向量与业务字段。
失败的具体异常保存在 last_error，供上层写进审计日志。
"""
import threading
from contextlib import contextmanager
import pymysql
from dbutils.pooled_db import PooledDB
from config import (
    MYSQL_HOST, MYSQL_PORT, MYSQL_USER, MYSQL_PWD, MYSQL_DB,
    MYSQL_POOL_MIN, MYSQL_POOL_MAX,
)
from logs import LOGGER


class MySQLHelper:
    """MySQL 映射表操作：连接池 + 每操作独立 cursor。"""

    def __init__(self):
        self.connected = False
        self.last_error = ""
        self._local = threading.local()
        self._lock = threading.RLock()  # 仅用于保护 last_error，不锁 DB 操作
        try:
            self._pool = PooledDB(
                creator=pymysql,
                mincached=MYSQL_POOL_MIN,
                maxcached=MYSQL_POOL_MAX,
                maxconnections=MYSQL_POOL_MAX,
                blocking=True,          # 池满时等待而非立即报错
                host=MYSQL_HOST, user=MYSQL_USER, port=MYSQL_PORT,
                password=MYSQL_PWD, database=MYSQL_DB,
                autocommit=True, connect_timeout=30, read_timeout=30,
                charset="utf8mb4",
            )
            # 启动时借一个连接验证可用性，随后归还
            conn = self._pool.connection()
            conn.cursor().execute("SELECT 1")
            conn.close()
            self.connected = True
        except Exception as e:
            self._pool = None
            self.connected = False
            self._set_error(e)
            LOGGER.error(f"MySQL 连接池初始化失败: {e}")

    def _set_error(self, e):
        self.last_error = str(e)[:300]
        with self._lock:
            pass

    @contextmanager
    def _cursor(self):
        """从连接池借连接与 cursor，用完自动归还；异常时关闭连接。"""
        conn = self._pool.connection()
        cursor = conn.cursor()
        try:
            yield cursor
        finally:
            cursor.close()
            conn.close()   # PooledDB 的连接 close() 是归还到池

    def test_connection(self):
        """探活：借一个连接执行 SELECT 1。连接池模式下开销极低。"""
        try:
            with self._cursor() as cur:
                cur.execute("SELECT 1")
            self.connected = True
            return True
        except Exception as e:
            self.connected = False
            self._set_error(e)
            LOGGER.error(f"MySQL 连接失败: {e}")
            return False

    def health(self):
        return self.connected

    def create_table(self, table_name):
        """建表（幂等）：表名用反引号包裹，避免关键字冲突。"""
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
            with self._cursor() as cur:
                cur.execute(sql)
            return True
        except Exception as e:
            self._set_error(e)
            LOGGER.error(f"创建 MySQL 表失败: {e} SQL: {sql}")
            return False

    def insert(self, table_name, rows):
        """批量写入。rows: [(milvus_id, image_path, customs_param, raw_url, commodity_id), ...]"""
        if not rows:
            return True
        sql = (
            f"INSERT INTO `{table_name}` "
            "(milvus_id, image_path, customs_param, raw_url, commodity_id) "
            "VALUES (%s,%s,%s,%s,%s);"
        )
        try:
            with self._cursor() as cur:
                cur.executemany(sql, rows)
            return True
        except Exception as e:
            self._set_error(e)
            LOGGER.error(f"MySQL 批量写入失败: {e}")
            return False

    def exists_by_url(self, table_name, raw_url, commodity_id):
        """按 (raw_url, commodity_id) 查重，返回已存在的 milvus_id。"""
        sql = f"SELECT milvus_id FROM `{table_name}` WHERE raw_url=%s AND commodity_id=%s LIMIT 1;"
        try:
            with self._cursor() as cur:
                cur.execute(sql, (raw_url, commodity_id))
                result = cur.fetchone()
            return str(result[0]) if result else None
        except Exception as e:
            self._set_error(e)
            LOGGER.error(f"查询重复图片失败: {e}")
            return None

    def get_image_path(self, table_name, milvus_id):
        """按 milvus_id 查询 MinIO 对象名。"""
        sql = f"SELECT image_path FROM `{table_name}` WHERE milvus_id=%s LIMIT 1;"
        try:
            with self._cursor() as cur:
                cur.execute(sql, (int(milvus_id),))
                result = cur.fetchone()
            return result[0] if result else None
        except Exception as e:
            self._set_error(e)
            LOGGER.error(f"查询图片路径失败: {e}")
            return None

    def get_rows_by_ids(self, table_name, ids):
        """按 milvus_id 批量取业务字段，返回 {id: row_dict}，供检索结果组装。"""
        if not ids:
            return {}
        placeholders = ",".join(str(int(i)) for i in ids)
        sql = (
            f"SELECT milvus_id, image_path, customs_param, raw_url, commodity_id "
            f"FROM `{table_name}` WHERE milvus_id IN ({placeholders});"
        )
        try:
            with self._cursor() as cur:
                cur.execute(sql)
                rows = cur.fetchall()
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
            self._set_error(e)
            LOGGER.error(f"批量查询业务字段失败: {e}")
            return {}

    def delete_by_id(self, table_name, milvus_id):
        """按 milvus_id 删除映射记录。"""
        sql = f"DELETE FROM `{table_name}` WHERE milvus_id=%s;"
        try:
            with self._cursor() as cur:
                cur.execute(sql, (int(milvus_id),))
            return True
        except Exception as e:
            self._set_error(e)
            LOGGER.error(f"删除记录失败: {e}")
            return False

    def clear_table(self, table_name):
        """清空映射表全部记录，保留表结构（用于一键清空图库图片）。"""
        try:
            with self._cursor() as cur:
                cur.execute(f"TRUNCATE TABLE `{table_name}`;")
            return True
        except Exception as e:
            self._set_error(e)
            LOGGER.error(f"清空 MySQL 表失败: {e}")
            return False

    def delete_table(self, table_name):
        """删除整张映射表。"""
        try:
            with self._cursor() as cur:
                cur.execute(f"DROP TABLE IF EXISTS `{table_name}`;")
            return True
        except Exception as e:
            self._set_error(e)
            LOGGER.error(f"删除 MySQL 表失败: {e}")
            return False

    def count(self, table_name):
        """统计映射记录数。"""
        try:
            with self._cursor() as cur:
                cur.execute(f"SELECT COUNT(*) FROM `{table_name}`;")
                return cur.fetchone()[0]
        except Exception as e:
            self._set_error(e)
            LOGGER.error(f"统计记录数失败: {e}")
            return 0

    def page(self, table_name, page=1, size=10):
        """分页查询映射记录。"""
        try:
            with self._cursor() as cur:
                cur.execute(f"SELECT COUNT(*) FROM `{table_name}`;")
                total = cur.fetchone()[0]
                offset = (page - 1) * size
                cur.execute(
                    f"SELECT milvus_id, image_path, customs_param, raw_url, commodity_id "
                    f"FROM `{table_name}` ORDER BY milvus_id LIMIT {offset},{size};"
                )
                rows = cur.fetchall()
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
            self._set_error(e)
            LOGGER.error(f"分页查询失败: {e}")
            return {"total": 0, "totalPages": 0, "page": page, "size": size, "data": []}
