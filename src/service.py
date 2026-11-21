import os
import time
import uuid
import shutil
import tempfile
import concurrent.futures
from diskcache import Cache
from config import DB_BATCH_SIZE, READ_BATCH_SIZE, UPLOAD_PATH
from logs import LOGGER
import audit

# 支持的图片扩展名
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".webp")

# 后台任务进度缓存（按 task_id 区分）
_TASK_CACHE = Cache("./tmp/tasks")

# 批量任务 id 映射清单的分片大小：每片存 RESULT_CHUNK_SIZE 条，避免单个大列表常驻内存
RESULT_CHUNK_SIZE = 1000

# 流式批量上传的临时图片目录（仅中转，任务结束即删）
_STREAM_TMP = os.path.join(UPLOAD_PATH, "_batch_stream")
# 下载线程池：仅在后台任务里按块使用，并发数固定，避免整批并发下载
_DOWNLOAD_POOL = concurrent.futures.ThreadPoolExecutor(max_workers=16)
# 单张入库流水线池：并行执行 MinIO 上传（网络 I/O）与模型推理（CPU）
_PIPE_POOL = concurrent.futures.ThreadPoolExecutor(max_workers=16,
                                                   thread_name_prefix="upload-pipe")


def _fetch_one(url):
    """下载单张远程图片，返回字节；失败返回 None（在线程池中同步执行）。"""
    import requests
    try:
        resp = requests.get(url, timeout=30)
        return resp.content if resp.status_code == 200 else None
    except Exception as e:
        LOGGER.error(f"批量下载图片失败: {url} - {e}")
        return None


def _collect_block_sources(block, save_default, base_index=0):
    """把一批轻量来源描述现读成 image_bytes，读完立即返回，调用方用完即弃。

    source 支持三种：
      - bytes：调用方已持有字节（兼容旧路径，仅小批量）
      - url：远程链接，按块并发下载
      - file：服务器本地路径，按块读取
    返回 items 列表（每项含 image_bytes）与每个来源的失败索引。
    """
    # 先并发下载本块的 URL，只有本块（最多 READ_BATCH_SIZE 张）在内存
    url_positions = [i for i, s in enumerate(block) if s.get("source") == "url"]
    downloaded = {}
    if url_positions:
        futures = {i: _DOWNLOAD_POOL.submit(_fetch_one, block[i]["image_url"]) for i in url_positions}
        for i, fut in futures.items():
            downloaded[i] = fut.result()

    items = []
    failed_idx = []
    for i, s in enumerate(block):
        data = None
        source = s.get("source")
        if source == "bytes":
            data = s.get("image_bytes")
        elif source == "url":
            data = downloaded.get(i)
        elif source == "file":
            try:
                with open(s["local_path"], "rb") as fh:
                    data = fh.read()
            except Exception as e:
                LOGGER.error(f"读取本地图片失败: {s.get('local_path')} - {e}")
        if not data:
            failed_idx.append(i)
            continue
        items.append({
            "image_bytes": data,
            "commodity_id": s.get("commodity_id", ""),
            "customs_param": s.get("customs_param"),
            "raw_url": s.get("raw_url", ""),
            "save_to_minio": s.get("save_to_minio", save_default),
            "milvus_id": s.get("milvus_id"),
            "_index": base_index + i,  # 全局序号，用于回传映射对齐
        })
    return items, failed_idx


def get_task_progress(task_id):
    """查询后台任务进度。"""
    return {
        "taskId": task_id,
        "current": _TASK_CACHE.get(f"{task_id}:current", 0),
        "total": _TASK_CACHE.get(f"{task_id}:total", 0),
        "success": _TASK_CACHE.get(f"{task_id}:success", 0),
        "failed": _TASK_CACHE.get(f"{task_id}:failed", 0),
        "status": _TASK_CACHE.get(f"{task_id}:status", "pending"),
        "message": _TASK_CACHE.get(f"{task_id}:message", ""),
    }


def _append_result_pairs(task_id, pairs):
    """把一批 (序号,imgId) 映射追加进任务的分片缓存。

    每 RESULT_CHUNK_SIZE 条存一个分片（key: task_id:result:N），
    满一片就落盘并清空内存，避免几百万条映射常驻内存。
    同时维护分片数 :result:chunks 与总条数 :result:count。
    """
    if not pairs:
        return
    chunk_idx = _TASK_CACHE.get(f"{task_id}:result:chunks", 0)
    buf = _TASK_CACHE.get(f"{task_id}:result:buf", [])
    count = _TASK_CACHE.get(f"{task_id}:result:count", 0)
    for pair in pairs:
        buf.append(pair)
        if len(buf) >= RESULT_CHUNK_SIZE:
            _TASK_CACHE.set(f"{task_id}:result:{chunk_idx}", buf)
            chunk_idx += 1
            buf = []
    _TASK_CACHE.set(f"{task_id}:result:buf", buf)
    _TASK_CACHE.set(f"{task_id}:result:chunks", chunk_idx)
    _TASK_CACHE.set(f"{task_id}:result:count", count + len(pairs))


def _flush_result_buffer(task_id):
    """任务结束时把不足一片的剩余映射落盘。"""
    buf = _TASK_CACHE.get(f"{task_id}:result:buf", [])
    if buf:
        chunk_idx = _TASK_CACHE.get(f"{task_id}:result:chunks", 0)
        _TASK_CACHE.set(f"{task_id}:result:{chunk_idx}", buf)
        _TASK_CACHE.set(f"{task_id}:result:chunks", chunk_idx + 1)
        _TASK_CACHE.set(f"{task_id}:result:buf", [])


def get_task_result(task_id, page=1, size=100):
    """按页读取批量任务的 (序号,imgId) 映射清单。

    从 diskcache 分片按需加载，只把当前页涉及的片读进内存，
    总条数可达数百万而不占用常驻内存。
    """
    total = _TASK_CACHE.get(f"{task_id}:result:count", 0)
    chunk_count = _TASK_CACHE.get(f"{task_id}:result:chunks", 0)
    start = (page - 1) * size
    end = start + size
    items = []
    # 分片固定大小，按全局序号区间 [start, end) 定位需要读取的分片
    first_chunk = start // RESULT_CHUNK_SIZE
    for ci in range(first_chunk, chunk_count):
        chunk = _TASK_CACHE.get(f"{task_id}:result:{ci}", [])
        chunk_start = ci * RESULT_CHUNK_SIZE
        for offset, pair in enumerate(chunk):
            global_idx = chunk_start + offset
            if global_idx >= start:
                items.append(pair)
                if len(items) >= size:
                    break
        if len(items) >= size:
            break
    return {
        "taskId": task_id,
        "total": total,
        "page": page,
        "size": size,
        "items": items,
    }


def run_batch_task(task_id, table_name, sources, model, milvus_cli, mysql_cli, minio_cli,
                   auto_id=True, save_default=True, cleanup_dir=None):
    """后台流式批量入库。

    sources 是轻量来源描述（url / file / bytes），不携带大图片字节。
    按 READ_BATCH_SIZE 分块：每块现读图片 -> 提特征 -> 入库 -> 释放，
    内存峰值恒定在一块图片的量级，与总图片数无关。
    cleanup_dir 非空时，任务结束（含异常）会删除该临时目录。
    """
    total = len(sources)
    _TASK_CACHE.set(f"{task_id}:total", total)
    _TASK_CACHE.set(f"{task_id}:current", 0)
    _TASK_CACHE.set(f"{task_id}:success", 0)
    _TASK_CACHE.set(f"{task_id}:failed", 0)
    _TASK_CACHE.set(f"{task_id}:status", "running")
    # 初始化结果映射的分片缓存，防止重跑同名 task_id 时残留旧数据
    _TASK_CACHE.set(f"{task_id}:result:buf", [])
    _TASK_CACHE.set(f"{task_id}:result:chunks", 0)
    _TASK_CACHE.set(f"{task_id}:result:count", 0)
    started = time.perf_counter()
    success = 0
    failed = 0
    save_minio = any(s.get("save_to_minio", save_default) for s in sources)
    try:
        ensure_table(table_name, model, milvus_cli, mysql_cli, auto_id=auto_id)
        for block_start in range(0, total, READ_BATCH_SIZE):
            block = sources[block_start:block_start + READ_BATCH_SIZE]
            try:
                items, failed_idx = _collect_block_sources(block, save_default, block_start)
                failed += len(failed_idx)
                if items:
                    id_pairs = []
                    s, f, _ = _batch_block(table_name, items, model, milvus_cli,
                                           mysql_cli, minio_cli, auto_id,
                                           id_collector=id_pairs)
                    success += s
                    failed += f
                    _append_result_pairs(task_id, id_pairs)  # 映射落盘，内存即时释放
                del items  # 立即释放本块图片字节
            except Exception as e:
                LOGGER.error(f"后台批量任务第 {block_start // READ_BATCH_SIZE + 1} 块失败: {e}")
                failed += len(block)
            _TASK_CACHE.set(f"{task_id}:current", min(block_start + len(block), total))
            _TASK_CACHE.set(f"{task_id}:success", success)
            _TASK_CACHE.set(f"{task_id}:failed", failed)
        _flush_result_buffer(task_id)  # 落盘不足一片的剩余映射
        _TASK_CACHE.set(f"{task_id}:status", "done")
        _TASK_CACHE.set(f"{task_id}:message", "批量导入完成")
    except Exception as e:
        _flush_result_buffer(task_id)  # 失败也保留已成功部分的映射
        LOGGER.error(f"后台批量任务 {task_id} 失败: {e}")
        _TASK_CACHE.set(f"{task_id}:status", "failed")
        _TASK_CACHE.set(f"{task_id}:message", str(e))
    finally:
        # 无论成功失败都清理流式临时图片，避免磁盘堆积
        if cleanup_dir:
            try:
                shutil.rmtree(cleanup_dir, ignore_errors=True)
            except Exception as e:
                LOGGER.error(f"清理临时目录失败: {cleanup_dir} - {e}")
    audit.log_batch(table_name, total, success, failed, save_minio,
                    task_id, int((time.perf_counter() - started) * 1000))


def _batch_block(table_name, block, model, milvus_cli, mysql_cli, minio_cli, auto_id,
                 id_collector=None):
    """处理一批入库，返回 (成功数, 失败数, 错误明细)。供同步与异步共用。

    id_collector 非空时，把每条成功记录的 (序号, imgId, 业务标识) 追加进去，
    供批量任务按 taskId 回传 milvus_id 映射。
    """
    import uuid as _uuid
    success = 0
    errors = []
    try:
        vectors = model.encode_images([it["image_bytes"] for it in block])
        object_names = [None] * len(block)
        if any(it.get("save_to_minio", True) for it in block):
            for idx, it in enumerate(block):
                if it.get("save_to_minio", True):
                    obj, _ = minio_cli.upload_image(
                        it["image_bytes"], table_name, _suffix(it.get("raw_url"))
                    )
                    object_names[idx] = obj
        ids = None if auto_id else [int(it["milvus_id"]) for it in block]
        primary_keys = milvus_cli.insert(table_name, vectors, ids=ids)
        if not primary_keys:
            raise RuntimeError("向量批量写入失败")
        rows = []
        pairs = []
        for mid, it, obj in zip(primary_keys, block, object_names):
            raw_url = it.get("raw_url") or f"batch_{_uuid.uuid4().hex}.jpg"
            rows.append((str(mid), obj, it.get("customs_param"), raw_url, it.get("commodity_id", "")))
            if id_collector is not None:
                pairs.append({
                    "index": it.get("_index"),
                    "imgId": str(mid),
                    "commodityId": it.get("commodity_id", ""),
                    "customsParam": it.get("customs_param"),
                    "rawUrl": raw_url,
                })
        if not mysql_cli.insert(table_name, rows):
            milvus_cli.delete_by_ids(table_name, primary_keys)
            raise RuntimeError(f"映射记录批量写入失败: {getattr(mysql_cli, 'last_error', '')}")
        if id_collector is not None:
            id_collector.extend(pairs)
        success = len(block)
    except Exception as e:
        LOGGER.error(f"批量入库块失败: {e}")
        errors.extend({"index": i, "error": str(e)} for i in range(len(block)))
    return success, len(errors), errors


def _suffix(name, default=".jpg"):
    """从文件名/URL 中解析出合法的图片扩展名，非法则回退为 .jpg。"""
    ext = os.path.splitext(name or "")[1].lower()
    return ext if ext in IMAGE_EXTS else default


# 已完成初始化的图库集合：同一张表只做一次建表检查，避免单张上传循环里
# 每次都执行 test_connection / CREATE TABLE IF NOT EXISTS（前者曾导致 gRPC 连接泄漏）。
_INITIALIZED_TABLES = set()


def ensure_table(table_name, model, milvus_cli, mysql_cli, auto_id=True):
    """确保图库的 Milvus 集合与 MySQL 映射表存在（幂等，重复调用零开销）。"""
    if table_name in _INITIALIZED_TABLES:
        return True
    milvus_cli.test_connection()
    created = milvus_cli.create_collection(table_name, auto_id=auto_id)
    mysql_cli.create_table(table_name)
    _INITIALIZED_TABLES.add(table_name)
    return created


def _write_one(table_name, image_bytes, model, milvus_cli, mysql_cli, minio_cli,
               commodity_id, customs_param, raw_url, save_to_minio, milvus_id=None):
    """单张入库：提特征 -> 写向量 -> 可选写 MinIO -> 写 MySQL。

    返回 (img_id, msg)；任一步失败会回滚已写入的向量，避免脏数据。
    """
    started = time.perf_counter()
    source = "url" if raw_url and (raw_url.startswith("http://") or raw_url.startswith("https://")) else "file"
    try:
        # MinIO 上传（网络 I/O）与模型推理（CPU）无依赖，并行执行以缩短单张耗时。
        # 不落 MinIO 时直接推理，省掉线程池开销。
        object_name = None
        if save_to_minio:
            fut_upload = _PIPE_POOL.submit(
                minio_cli.upload_image, image_bytes, table_name, _suffix(raw_url)
            )
        fut_vector = _PIPE_POOL.submit(model.encode_image, image_bytes)
        vector = fut_vector.result()                       # 等推理完成
        if save_to_minio:
            object_name, _ = fut_upload.result()           # 等上传完成

        ids = None if milvus_id is None else [int(milvus_id)]
        # 单张走延迟 flush：由 FlushManager 按阈值/间隔批量落盘，避免每张都 flush
        primary_keys = milvus_cli.insert(
            table_name, [vector], ids=ids, defer_flush=True
        )
        if not primary_keys:
            audit.log_upload(table_name, source, raw_url, commodity_id, customs_param,
                             save_to_minio, None, object_name, False,
                             int((time.perf_counter() - started) * 1000), "向量写入失败")
            return None, "向量写入失败"

        img_id = primary_keys[0]
        ok = mysql_cli.insert(table_name, [(
            str(img_id), object_name, customs_param, raw_url, commodity_id
        )])
        if not ok:
            milvus_cli.delete_by_ids(table_name, [img_id])
            db_err = getattr(mysql_cli, "last_error", "") or "映射记录写入失败"
            msg = f"映射记录写入失败: {db_err}"
            audit.log_upload(table_name, source, raw_url, commodity_id, customs_param,
                             save_to_minio, None, object_name, False,
                             int((time.perf_counter() - started) * 1000), msg)
            return None, msg
        audit.log_upload(table_name, source, raw_url, commodity_id, customs_param,
                         save_to_minio, str(img_id), object_name, True,
                         int((time.perf_counter() - started) * 1000))
        return str(img_id), "success"
    except Exception as e:
        LOGGER.error(f"图片入库失败: {e}")
        audit.log_upload(table_name, source, raw_url, commodity_id, customs_param,
                         save_to_minio, None, None, False,
                         int((time.perf_counter() - started) * 1000), str(e))
        return None, str(e)


def add_image(table_name, image_bytes, model, milvus_cli, mysql_cli, minio_cli,
              commodity_id="", customs_param=None, raw_url=None, save_to_minio=True):
    """通用单张上传（自增 ID）。"""
    return _write_one(table_name, image_bytes, model, milvus_cli, mysql_cli, minio_cli,
                      commodity_id, customs_param, raw_url, save_to_minio)


def add_image_with_id(table_name, milvus_id, image_bytes, model, milvus_cli, mysql_cli, minio_cli,
                      commodity_id="", customs_param=None, raw_url=None, save_to_minio=True):
    """手动指定 milvus_id 的单张上传。"""
    return _write_one(table_name, image_bytes, model, milvus_cli, mysql_cli, minio_cli,
                      commodity_id, customs_param, raw_url, save_to_minio, milvus_id=milvus_id)


def add_images_batch(table_name, items, model, milvus_cli, mysql_cli, minio_cli, auto_id=True):
    """批量入库（性能优化核心）。

    相比逐张处理，这里按 DB_BATCH_SIZE 分块，每块内：
      1) 一次批量提特征（GPU 并行）；
      2) 一次批量写 MinIO；
      3) 一次批量写 Milvus；
      4) 一次批量写 MySQL。
    大幅减少模型调用、网络往返与事务提交次数。
    items: [{image_bytes, commodity_id, customs_param, raw_url, save_to_minio, milvus_id?}]
    返回 (成功数, 失败数, 错误明细)。
    """
    ensure_table(table_name, model, milvus_cli, mysql_cli, auto_id=auto_id)
    success = 0
    errors = []
    for block_start in range(0, len(items), DB_BATCH_SIZE):
        block = items[block_start:block_start + DB_BATCH_SIZE]
        s, f, errs = _batch_block(table_name, block, model, milvus_cli, mysql_cli, minio_cli, auto_id)
        success += s
        errors.extend({"index": block_start + e["index"], "error": e["error"]} for e in errs)
        _ = f  # 失败数由 errors 长度推导
    return success, len(errors), errors


def _similarity(distance):
    """IP 度量的 distance 即余弦相似度，转成百分比字符串。"""
    return f"{max(0.0, min(100.0, distance * 100)):.2f}%"


def _search(table_name, vector, top_k, milvus_cli, mysql_cli):
    """检索通用逻辑：向量检索 -> 批量补业务字段 -> 组装结果。"""
    if not milvus_cli.has_collection(table_name):
        return []
    hits = milvus_cli.search(table_name, [vector], top_k)
    if not hits:
        return []
    ids = [hit.id for hit in hits[0]]
    # 只查一次 MySQL，避免 N+1
    extras = mysql_cli.get_rows_by_ids(table_name, ids)
    return [_format_result(hit.id, hit.distance, extras.get(str(hit.id), {})) for hit in hits[0]]


def _search_lite(table_name, vector, top_k, milvus_cli):
    """轻量检索：只做向量检索，返回 imgId + similarity，完全不访问 MySQL。"""
    if not milvus_cli.has_collection(table_name):
        return []
    hits = milvus_cli.search(table_name, [vector], top_k)
    if not hits:
        return []
    return [
        {"imgId": str(hit.id), "similarity": _similarity(hit.distance)}
        for hit in hits[0]
    ]


def search_by_image(table_name, image_bytes, top_k, model, milvus_cli, mysql_cli):
    """以图搜图：编码图片向量后检索。"""
    return _search(table_name, model.encode_image(image_bytes), top_k, milvus_cli, mysql_cli)


def search_by_text(table_name, query_text, top_k, model, milvus_cli, mysql_cli):
    """中文文本搜图：原生编码中文，无需外部翻译。"""
    return _search(table_name, model.encode_text(query_text), top_k, milvus_cli, mysql_cli)


def search_by_image_lite(table_name, image_bytes, top_k, model, milvus_cli):
    """轻量以图搜图：不经 MySQL。"""
    return _search_lite(table_name, model.encode_image(image_bytes), top_k, milvus_cli)


def search_by_text_lite(table_name, query_text, top_k, model, milvus_cli):
    """轻量文本搜图：不经 MySQL。"""
    return _search_lite(table_name, model.encode_text(query_text), top_k, milvus_cli)


def _format_result(milvus_id, similarity, extra):
    """组装完整结果：含业务字段。"""
    return {
        "imgId": str(milvus_id),
        "similarity": _similarity(similarity),
        "customsParams": extra.get("customsParams", ""),
        "commodityId": extra.get("commodityId", ""),
    }


def delete_image(table_name, milvus_id, milvus_cli, mysql_cli, minio_cli):
    """删除单张：先取对象名，再同步删向量、映射记录与 MinIO 原图。"""
    image_path = mysql_cli.get_image_path(table_name, milvus_id)
    milvus_cli.delete_by_ids(table_name, [int(milvus_id)])
    mysql_cli.delete_by_id(table_name, milvus_id)
    if image_path:
        minio_cli.delete_image(image_path)
    return True


def clear_table_images(table_name, milvus_cli, mysql_cli, minio_cli, cascade=True):
    """一键清空图库图片：清空向量 + 映射记录，可选删除 MinIO 原图。保留图库结构。"""
    if not milvus_cli.has_collection(table_name):
        return {"milvus": 0, "mysql": 0, "minio": False}
    milvus_ok = milvus_cli.clear_collection(table_name)
    mysql_ok = mysql_cli.clear_table(table_name)
    minio_ok = minio_cli.delete_by_prefix(table_name) if cascade else False
    if not (milvus_ok and mysql_ok):
        raise RuntimeError("清空失败：向量或映射记录清理出错")
    return {"milvus": milvus_ok, "mysql": mysql_ok, "minio": minio_ok}


def drop_table(table_name, milvus_cli, mysql_cli, minio_cli, cascade=False):
    """删除图库；cascade=true 时连 MinIO 原图一起删。"""
    milvus_cli.delete_collection(table_name)
    mysql_cli.delete_table(table_name)
    _INITIALIZED_TABLES.discard(table_name)  # 表已删，清除初始化标记
    if cascade:
        minio_cli.delete_by_prefix(table_name)
    return True


def get_image_content(table_name, milvus_id, mysql_cli, minio_cli):
    """按 milvus_id 获取 MinIO 原图字节；未落 MinIO 则返回 None。"""
    image_path = mysql_cli.get_image_path(table_name, milvus_id)
    if not image_path:
        return None
    return minio_cli.download_image(image_path)


def import_directory(table_name, image_dir, save_to_minio, model, milvus_cli,
                     mysql_cli, minio_cli, cache_path="./tmp"):
    """后台目录导入：按批提特征入库，并把进度写入 diskcache 供前端轮询。

    复用 add_images_batch 的批量逻辑，避免重复代码。
    """
    cache = Cache(cache_path)
    paths = [
        os.path.join(image_dir, f) for f in os.listdir(image_dir)
        if f.lower().endswith(IMAGE_EXTS)
    ]
    total = len(paths)
    cache["total"] = total
    cache["current"] = 0
    cache["status"] = "running"
    ensure_table(table_name, model, milvus_cli, mysql_cli)

    for start in range(0, total, READ_BATCH_SIZE):
        batch_paths = paths[start:start + READ_BATCH_SIZE]
        images = []
        try:
            # 只读取本块的图片字节（默认 128 张），处理完立即释放
            images = [open(p, "rb").read() for p in batch_paths]
            items = [{
                "image_bytes": img,
                "commodity_id": "default_commodity_id",
                "raw_url": f"import_{uuid.uuid4().hex}.jpg",
                "save_to_minio": save_to_minio,
            } for img in images]
            # 本块大小 <= DB_BATCH_SIZE，批量逻辑只执行一次
            add_images_batch(table_name, items, model, milvus_cli, mysql_cli, minio_cli)
        except Exception as e:
            LOGGER.error(f"目录导入第 {start // READ_BATCH_SIZE + 1} 块失败: {e}")
        finally:
            cache["current"] = min(start + READ_BATCH_SIZE, total)
            images.clear()

    cache["status"] = "done"
    cache["current"] = total
    return total
