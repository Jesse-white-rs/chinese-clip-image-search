import warnings
# 屏蔽 PyMilvus 3.x ORM API 弃用警告（当前功能正常，避免日志刷屏）
warnings.filterwarnings("ignore", message=".*ORM-style PyMilvus API.*")

import threading
from pymilvus import connections, FieldSchema, CollectionSchema, DataType, Collection, utility
from config import MILVUS_HOST, MILVUS_PORT, VECTOR_DIMENSION, METRIC_TYPE, NLIST, NPROBE
from logs import LOGGER
from flush_manager import FlushManager


class MilvusHelper:
    """向量库操作类：单表 1024 维，支持自增 ID 与手动指定 ID。

    性能优化：
    - 集合对象按表名缓存，避免每次操作都重新实例化 Collection；
    - 已 load 的集合做标记，避免每次检索重复 load（load 是重量级操作）；
    - 集合是否存在的结果做本地缓存，减少 has_collection 的网络往返。
    """

    def __init__(self):
        self.connected = False
        self._collections = {}       # 表名 -> Collection 对象缓存
        self._loaded = set()         # 已加载到内存的集合名
        self._existing = set()       # 已确认存在的集合名
        self._lock = threading.RLock()
        # 延迟 flush 管理器：把单张上传的逐张 flush 合并为批量 flush
        self.flush_manager = FlushManager(self)
        self.test_connection()

    def test_connection(self):
        """确保与 Milvus 的连接可用。

        关键：pymilvus 的 connections.connect() 每次都会新建 gRPC channel 并覆盖旧引用，
        但不会主动 close 旧 channel。单张上传每次都调本方法，若不加节流，
        循环几万次会泄漏几万个 gRPC 连接，导致内存持续上涨。
        因此已连接时直接返回，仅在首次或连接失效时重建。
        """
        if self.connected:
            return True
        try:
            connections.connect(host=MILVUS_HOST, port=MILVUS_PORT)
            self.connected = True
            LOGGER.debug(f"Milvus 连接成功: {MILVUS_HOST}:{MILVUS_PORT}")
            return True
        except Exception as e:
            self.connected = False
            LOGGER.error(f"Milvus 连接失败: {e}")
            return False

    def reconnect(self):
        """连接失效时主动断开旧连接再重建，避免遗留 gRPC channel。"""
        try:
            connections.disconnect("default")
        except Exception:
            pass
        self.connected = False
        return self.test_connection()

    def health(self):
        return self.connected

    def _get_collection(self, name):
        """获取集合对象：优先从缓存取，缓存未命中才实例化。"""
        with self._lock:
            col = self._collections.get(name)
            if col is None:
                col = Collection(name=name)
                self._collections[name] = col
            return col

    def has_collection(self, name):
        """判断集合是否存在（带本地缓存）。"""
        if name in self._existing:
            return True
        try:
            exists = utility.has_collection(name)
            if exists:
                self._existing.add(name)
            return exists
        except Exception as e:
            LOGGER.error(f"检查集合失败: {e}")
            return False

    def create_collection(self, name, auto_id=True):
        """创建集合并建立 IVF_FLAT 索引；auto_id=False 时支持手动指定 ID。"""
        try:
            if self.has_collection(name):
                LOGGER.debug(f"集合 {name} 已存在")
                return True
            field_id = FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=auto_id)
            field_vec = FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=VECTOR_DIMENSION)
            schema = CollectionSchema(fields=[field_id, field_vec], description="chinese-clip image search")
            col = Collection(name=name, schema=schema)
            index_params = {"metric_type": METRIC_TYPE, "index_type": "IVF_FLAT", "params": {"nlist": NLIST}}
            col.create_index(field_name="embedding", index_params=index_params)
            with self._lock:
                self._collections[name] = col
                self._existing.add(name)
            LOGGER.debug(f"集合 {name} 创建成功，维度 {VECTOR_DIMENSION}")
            return True
        except Exception as e:
            LOGGER.error(f"创建集合失败: {e}")
            return False

    def is_auto_id(self, name):
        """返回集合主键是否为自增模式；集合不存在时返回 None。"""
        try:
            if not self.has_collection(name):
                return None
            collection = self._get_collection(name)
            for field in collection.schema.fields:
                if field.is_primary:
                    return bool(field.auto_id)
            return None
        except Exception as e:
            LOGGER.error(f"读取集合主键模式失败: {e}")
            return None

    def insert(self, name, vectors, ids=None, batch_size=1000, flush=True, defer_flush=False):
        """向量入库。ids 不为空时按指定 ID 写入，返回主键列表。

        - flush=False：完全不 flush，由调用方负责（批量导入场景）。
        - defer_flush=True：交给 FlushManager 延迟批量 flush（单张上传高吞吐场景）。
        - 两者都为 False 之外的默认：立即 flush（上传即可搜）。
        """
        try:
            collection = self._get_collection(name)
            primary_keys = []
            for start in range(0, len(vectors), batch_size):
                batch_vecs = vectors[start:start + batch_size]
                if ids is None:
                    result = collection.insert([batch_vecs])
                else:
                    batch_ids = [int(i) for i in ids[start:start + batch_size]]
                    result = collection.insert([batch_ids, batch_vecs])
                primary_keys.extend(result.primary_keys)
            if primary_keys:
                if defer_flush:
                    # 累计计数，达阈值/定时由 FlushManager 统一 flush
                    self.flush_manager.note(name)
                elif flush:
                    collection.flush()
            return primary_keys
        except Exception as e:
            LOGGER.error(f"向量入库失败: {e}")
            return None

    def flush(self, name):
        """单独触发 flush（批量导入完成后调用一次即可）。"""
        try:
            self._get_collection(name).flush()
            return True
        except Exception as e:
            LOGGER.error(f"flush 失败: {e}")
            return False

    def search(self, name, vectors, top_k):
        """向量检索：集合首次使用时 load 到内存，之后复用。"""
        try:
            collection = self._get_collection(name)
            if name not in self._loaded:
                collection.load()
                self._loaded.add(name)
            params = {"metric_type": METRIC_TYPE, "params": {"nprobe": NPROBE}}
            return collection.search(vectors, anns_field="embedding", param=params, limit=top_k)
        except Exception as e:
            LOGGER.error(f"向量检索失败: {e}")
            return []

    def count(self, name):
        """统计集合向量数量，flush 保证计数准确。"""
        try:
            collection = self._get_collection(name)
            collection.flush()
            return collection.num_entities
        except Exception as e:
            LOGGER.error(f"统计向量数量失败: {e}")
            return 0

    def delete_by_ids(self, name, ids):
        """按主键批量删除向量。"""
        try:
            collection = self._get_collection(name)
            id_str = ",".join(str(int(i)) for i in ids)
            collection.delete(f"id in [{id_str}]")
            collection.flush()
            return True
        except Exception as e:
            LOGGER.error(f"删除向量失败: {e}")
            return False

    def clear_collection(self, name):
        """清空集合内全部向量，保留集合结构与索引（用于一键清空图库图片）。"""
        try:
            if not self.has_collection(name):
                return True
            collection = self._get_collection(name)
            collection.delete("id >= 0")
            collection.flush()
            return True
        except Exception as e:
            LOGGER.error(f"清空集合失败: {e}")
            return False

    def delete_collection(self, name):
        """删除集合，并同步清理本地缓存。"""
        try:
            if utility.has_collection(name):
                Collection(name=name).drop()
            with self._lock:
                self._collections.pop(name, None)
                self._loaded.discard(name)
                self._existing.discard(name)
            return True
        except Exception as e:
            LOGGER.error(f"删除集合失败: {e}")
            return False
