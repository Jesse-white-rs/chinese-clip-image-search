import warnings
# PyMilvus 3.x 的 ORM API 弃用警告：功能正常，屏蔽以免刷屏（须在所有 import 之前）
warnings.filterwarnings("ignore", category=Warning, message=".*ORM-style PyMilvus API.*")

import os
import time
import shutil
import tempfile
import asyncio
import threading
import concurrent.futures
import requests
from requests.adapters import HTTPAdapter
from contextlib import asynccontextmanager
from typing import Optional, List
from fastapi import FastAPI, File, UploadFile, Form, Query, Request, BackgroundTasks, Depends
from fastapi.responses import Response, FileResponse
from pydantic import BaseModel
from diskcache import Cache

from config import TOP_K, UPLOAD_PATH
from logs import LOGGER
from clip_model import ChineseClipModel
from milvus_helpers import MilvusHelper
from mysql_helpers import MySQLHelper
from minio_helpers import MinioHelper
from auth import (
    USER_STORE, verify_password, create_access_token,
    get_current_user, get_current_admin,
)
import service
import log_reader
import backup
import perf
import audit
from pymilvus import utility

# 过滤 pymilvus 3.x 的 ORM API 弃用警告（当前版本功能正常，无需刷屏）
warnings.filterwarnings("ignore", message=".*ORM-style PyMilvus API.*")

# 各基础设施客户端以模块级单例复用，避免重复建连
MODEL = ChineseClipModel()
MILVUS_CLI = MilvusHelper()
MYSQL_CLI = MySQLHelper()
MINIO_CLI = MinioHelper()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动/关闭钩子：调度器与延迟 flush 管理器的生命周期。"""
    backup.BACKUP_SCHEDULER.start()
    MILVUS_CLI.flush_manager.start()
    try:
        yield
    finally:
        # 关闭时兜底 flush，确保未落盘的向量不丢失
        MILVUS_CLI.flush_manager.shutdown()
        backup.BACKUP_SCHEDULER.shutdown()


# 创建 FastAPI 应用
app = FastAPI(title="Chinese-CLIP 图片搜索服务", lifespan=lifespan)

# 临时图片目录（仅中转，用后即删）
if not os.path.exists(UPLOAD_PATH):
    os.makedirs(UPLOAD_PATH, exist_ok=True)

# 用于异步下载远程图片的线程池（避免阻塞事件循环）
_DOWNLOAD_POOL = concurrent.futures.ThreadPoolExecutor(max_workers=16)

# 线程本地复用的 HTTP Session：每个下载线程持有一个带连接池的 Session，
# 避免每次 requests.get 新建 TCP 连接（三次握手 + TIME_WAIT 累积）。
_thread_local = threading.local()


def _get_http_session():
    session = getattr(_thread_local, "session", None)
    if session is None:
        session = requests.Session()
        adapter = HTTPAdapter(pool_connections=16, pool_maxsize=16, max_retries=0)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        _thread_local.session = session
    return session


# ---------------------- 请求 / 响应模型 ----------------------
class TableRequest(BaseModel):
    """创建图库请求体。auto_id=False 时支持手动指定 Milvus 主键。"""
    table_name: str
    auto_id: bool = True


class BatchUrlRequest(BaseModel):
    """按图片 URL 批量上传请求体。"""
    items: List[dict]
    save_to_minio: bool = True
    auto_id: bool = True


class DirImportRequest(BaseModel):
    """服务器目录导入请求体。"""
    dir_path: str
    save_to_minio: bool = True


class ResponseModel(BaseModel):
    """统一响应结构。"""
    status: bool
    message: str
    data: Optional[dict] = None


class LoginRequest(BaseModel):
    """登录请求体。"""
    username: str
    password: str


class UserCreateRequest(BaseModel):
    """新建用户请求体。"""
    username: str
    password: str
    role: str = "user"


class UserUpdateRequest(BaseModel):
    """更新用户请求体（角色 / 启停）。"""
    role: Optional[str] = None
    isActive: Optional[bool] = None


class PasswordResetRequest(BaseModel):
    """重置密码请求体。"""
    password: str


class BackupTaskRequest(BaseModel):
    """备份任务请求体。"""
    name: str
    table_name: str
    cron_expr: str = "0 2 * * *"
    enabled: bool = True
    include_minio: bool = False
    retention_days: int = 30


class BackupTaskUpdate(BaseModel):
    """备份任务更新请求体（字段可选）。"""
    name: Optional[str] = None
    table_name: Optional[str] = None
    cron_expr: Optional[str] = None
    enabled: Optional[bool] = None
    include_minio: Optional[bool] = None
    retention_days: Optional[int] = None


class PerfTaskRequest(BaseModel):
    """性能压测请求体。"""
    scenario: str
    table_name: str
    total: int = 1000
    concurrency: int = 8
    query_text: str = "红色物体"
    batch_size: int = 500  # batch_upload 场景每批图片数


def ok(message="success", data=None):
    """构造成功响应。"""
    return ResponseModel(status=True, message=message, data=data)


def fail(message):
    """构造失败响应。"""
    return ResponseModel(status=False, message=message)


def _fetch_url(url):
    """同步下载单张图片（在线程池中执行），复用线程本地 Session 连接池。"""
    resp = _get_http_session().get(url, timeout=30)
    return (resp.content, url) if resp.status_code == 200 else (None, url)


async def _read_image(image: Optional[UploadFile], image_url: Optional[str]):
    """统一读取图片来源：优先本地上传文件，其次远程 URL。"""
    if image is not None:
        return await image.read(), image.filename
    if image_url:
        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(_DOWNLOAD_POOL, _fetch_url, image_url)
        except Exception as e:
            LOGGER.error(f"下载图片失败: {e}")
    return None, None


async def _get_json_or_form(request: Request):
    """按 Content-Type 解析请求体为 JSON 或表单。"""
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        return await request.json(), None
    return None, await request.form()


# ---------------------- 认证与用户管理 ----------------------
@app.post("/api/v1/auth/login")
def login(item: LoginRequest):
    """登录：校验账号密码，签发 7 天有效的 JWT。"""
    user = USER_STORE.get_by_username(item.username)
    if not user or not verify_password(item.password, user["passwordHash"]):
        return fail("用户名或密码错误")
    if not user.get("isActive"):
        return fail("该账号已被禁用")
    USER_STORE.update_last_login(user["id"])
    token = create_access_token(user)
    return ok("登录成功", {
        "accessToken": token,
        "tokenType": "Bearer",
        "user": {"id": user["id"], "username": user["username"], "role": user["role"]},
    })


@app.post("/api/v1/auth/logout")
def logout(user=Depends(get_current_user)):
    """登出：JWT 无状态，由前端清除本地 token。"""
    return ok("已登出")


@app.get("/api/v1/auth/me")
def me(user=Depends(get_current_user)):
    """获取当前登录用户信息。"""
    return ok("success", {"user": user})


@app.get("/api/v1/users")
def list_users(page: int = Query(1, ge=1), size: int = Query(10, ge=1, le=100),
               admin=Depends(get_current_admin)):
    """用户列表（仅 admin）。"""
    return ok("success", USER_STORE.list_users(page, size))


@app.post("/api/v1/users")
def create_user(item: UserCreateRequest, admin=Depends(get_current_admin)):
    """新建用户（仅 admin）。"""
    if not item.username.strip() or not item.password:
        return fail("用户名和密码不能为空")
    if USER_STORE.get_by_username(item.username):
        return fail("用户名已存在")
    try:
        uid = USER_STORE.create(item.username.strip(), item.password, item.role)
        return ok("用户创建成功", {"id": uid})
    except Exception as e:
        LOGGER.error(f"创建用户失败: {e}")
        return fail("创建失败，用户名可能重复")


@app.put("/api/v1/users/{user_id}")
def update_user(user_id: int, item: UserUpdateRequest, admin=Depends(get_current_admin)):
    """修改用户角色 / 启停（仅 admin）。禁止禁用自己。"""
    if user_id == admin["id"] and item.isActive is False:
        return fail("不能禁用当前登录的账号")
    ok_flag = USER_STORE.update(user_id, item.role, item.isActive)
    return ok("更新成功") if ok_flag else fail("更新失败或用户不存在")


@app.put("/api/v1/users/{user_id}/password")
def reset_password(user_id: int, item: PasswordResetRequest, admin=Depends(get_current_admin)):
    """重置用户密码（仅 admin）。"""
    if not item.password:
        return fail("密码不能为空")
    ok_flag = USER_STORE.update_password(user_id, item.password)
    return ok("密码重置成功") if ok_flag else fail("重置失败或用户不存在")


@app.delete("/api/v1/users/{user_id}")
def delete_user(user_id: int, admin=Depends(get_current_admin)):
    """删除用户（仅 admin）。禁止删除自己。"""
    if user_id == admin["id"]:
        return fail("不能删除当前登录的账号")
    ok_flag = USER_STORE.delete(user_id)
    return ok("删除成功") if ok_flag else fail("删除失败或用户不存在")


# ---------------------- 性能压测（admin） ----------------------
@app.post("/api/v1/perf/tasks")
def create_perf_task(item: PerfTaskRequest, background_tasks: BackgroundTasks,
                     admin=Depends(get_current_admin)):
    """启动性能压测任务（后台执行）。上传场景会真实写入数据，请谨慎设置量级。"""
    import uuid
    if item.scenario not in perf.SCENARIOS:
        return fail(f"场景无效，可选: {', '.join(perf.SCENARIOS)}")
    if not item.table_name.strip():
        return fail("图库名不能为空")
    if item.total < 1 or item.total > 2_000_000:
        return fail("请求数需在 1 ~ 2,000,000 之间")
    if item.concurrency < 1 or item.concurrency > 256:
        return fail("并发数需在 1 ~ 256 之间")
    if item.batch_size < 1 or item.batch_size > 5000:
        return fail("每批图片数需在 1 ~ 5000 之间")
    task_id = uuid.uuid4().hex
    background_tasks.add_task(
        perf.run_perf, task_id, item.scenario, item.table_name.strip(),
        item.total, item.concurrency, MODEL, MILVUS_CLI, MYSQL_CLI, MINIO_CLI,
        item.query_text, item.batch_size,
    )
    return ok("压测任务已启动", {"taskId": task_id, "total": item.total})


@app.get("/api/v1/perf/tasks/{task_id}/progress")
def perf_progress(task_id: str, admin=Depends(get_current_admin)):
    """查询压测任务进度。"""
    return ok("success", perf.get_progress(task_id))


@app.get("/api/v1/perf/tasks/{task_id}/result")
def perf_result(task_id: str, admin=Depends(get_current_admin)):
    """查询压测任务结果（从 MySQL 读取，服务重启后仍可查看）。"""
    result = perf.PERF_STORE.get_result(task_id)
    if not result:
        result = perf.get_result(task_id)  # 兼容 diskcache 中的旧记录
    return ok("success", result) if result else fail("结果尚未生成或任务不存在")


@app.get("/api/v1/perf/results")
def perf_results(limit: int = Query(50, ge=1, le=200), admin=Depends(get_current_admin)):
    """历史压测结果列表。"""
    return ok("success", {"results": perf.PERF_STORE.list_results(limit)})


@app.delete("/api/v1/perf/results/{task_id}")
def perf_delete_result(task_id: str, admin=Depends(get_current_admin)):
    """删除一条压测结果。"""
    return ok("删除成功") if perf.PERF_STORE.delete_result(task_id) else fail("删除失败或记录不存在")


# ---------------------- 定时备份（admin） ----------------------
@app.get("/api/v1/backups/tasks")
def backup_list_tasks(admin=Depends(get_current_admin)):
    """列出所有备份任务（含下次运行时间）。"""
    tasks = backup.BACKUP_STORE.list_tasks()
    for t in tasks:
        t["nextRun"] = backup.BACKUP_SCHEDULER.next_run(t["id"])
    return ok("success", {"tasks": tasks})


@app.post("/api/v1/backups/tasks")
def backup_create_task(item: BackupTaskRequest, admin=Depends(get_current_admin)):
    """新建备份任务。cron_expr 为标准 5 段表达式，如 '0 2 * * *' 表示每天 2 点。"""
    if not item.name.strip() or not item.table_name.strip():
        return fail("任务名和图库名不能为空")
    try:
        from apscheduler.triggers.cron import CronTrigger
        CronTrigger.from_crontab(item.cron_expr)
    except Exception as e:
        return fail(f"cron 表达式无效: {e}")
    task_id = backup.BACKUP_STORE.create_task(
        item.name.strip(), item.table_name.strip(), item.cron_expr,
        item.enabled, item.include_minio, item.retention_days,
    )
    backup.BACKUP_SCHEDULER.reload_jobs()
    return ok("备份任务创建成功", {"id": task_id})


@app.put("/api/v1/backups/tasks/{task_id}")
def backup_update_task(task_id: int, item: BackupTaskUpdate, admin=Depends(get_current_admin)):
    """更新备份任务（改完自动重载调度）。"""
    fields = {k: v for k, v in item.model_dump().items() if v is not None}
    if "cron_expr" in fields:
        try:
            from apscheduler.triggers.cron import CronTrigger
            CronTrigger.from_crontab(fields["cron_expr"])
        except Exception as e:
            return fail(f"cron 表达式无效: {e}")
    if not backup.BACKUP_STORE.update_task(task_id, **fields):
        return fail("更新失败或任务不存在")
    backup.BACKUP_SCHEDULER.reload_jobs()
    return ok("更新成功")


@app.delete("/api/v1/backups/tasks/{task_id}")
def backup_delete_task(task_id: int, admin=Depends(get_current_admin)):
    """删除备份任务。"""
    if not backup.BACKUP_STORE.delete_task(task_id):
        return fail("删除失败或任务不存在")
    backup.BACKUP_SCHEDULER.reload_jobs()
    return ok("删除成功")


@app.post("/api/v1/backups/tasks/{task_id}/run")
def backup_run_now(task_id: int, background_tasks: BackgroundTasks, admin=Depends(get_current_admin)):
    """立即执行一次备份任务（后台执行）。"""
    task = backup.BACKUP_STORE.get_task(task_id)
    if not task:
        return fail("任务不存在")
    background_tasks.add_task(backup.run_task, backup.BACKUP_STORE, task_id)
    return ok("备份任务已启动", {"taskId": task_id})


@app.get("/api/v1/backups/history")
def backup_history(task_id: Optional[int] = Query(None), limit: int = Query(50, ge=1, le=200),
                   admin=Depends(get_current_admin)):
    """查询备份执行历史。"""
    return ok("success", {"history": backup.BACKUP_STORE.list_history(task_id, limit)})


@app.get("/api/v1/backups/files")
def backup_files(admin=Depends(get_current_admin)):
    """列出备份文件。"""
    return ok("success", {"files": backup.list_backup_files()})


@app.delete("/api/v1/backups/files/{name}")
def backup_delete_file(name: str, admin=Depends(get_current_admin)):
    """删除指定备份文件。"""
    return ok("删除成功") if backup.delete_backup_file(name) else fail("文件不存在或删除失败")


@app.get("/api/v1/backups/files/{name}/download")
def backup_download(name: str, admin=Depends(get_current_admin)):
    """下载备份文件。"""
    from config import BACKUP_DIR
    if not name or os.path.basename(name) != name or not name.endswith(".tar.gz"):
        return fail("非法文件名")
    path = os.path.join(BACKUP_DIR, name)
    if not os.path.isfile(path):
        return fail("文件不存在")
    return FileResponse(path, filename=name, media_type="application/gzip")


# ---------------------- 日志查询（admin） ----------------------
@app.get("/api/v1/logs")
def list_logs(admin=Depends(get_current_admin)):
    """列出可用日志文件。"""
    return ok("success", {"files": log_reader.list_logs()})


@app.get("/api/v1/logs/{name}")
def read_log(name: str, lines: int = Query(200, ge=1, le=2000),
             level: Optional[str] = Query(None), admin=Depends(get_current_admin)):
    """读取日志尾部内容，可按级别过滤。"""
    try:
        content = log_reader.read_log(name, lines, level)
        return ok("success", {"name": name, "lines": content})
    except (ValueError, FileNotFoundError) as e:
        return fail(str(e))
    except Exception as e:
        LOGGER.error(f"读取日志失败: {e}")
        return fail(str(e))


# ---------------------- 1. 健康检查 ----------------------
@app.get("/api/v1/health")
def health():
    """返回模型及各依赖服务的连通状态。"""
    data = {
        "model": MODEL.health(),
        "milvus": MILVUS_CLI.health(),
        "mysql": MYSQL_CLI.health(),
        "minio": MINIO_CLI.health(),
        "flush": MILVUS_CLI.flush_manager.stats(),  # 延迟 flush 监控指标
    }
    healthy = data["model"]["ready"] and all([data["milvus"], data["mysql"], data["minio"]])
    return ok("健康" if healthy else "部分服务不可用", data)


# ---------------------- 图库列表 ----------------------
@app.get("/api/v1/tables")
def list_tables(user=Depends(get_current_user)):
    """列出所有业务图库（过滤 Milvus 内部集合）。"""
    try:
        names = [n for n in utility.list_collections() if not n.startswith("_")]
        tables = []
        for name in names:
            count = MILVUS_CLI.count(name) if MILVUS_CLI.has_collection(name) else 0
            tables.append({"name": name, "count": count})
        return ok("success", {"tables": tables})
    except Exception as e:
        LOGGER.error(f"获取图库列表失败: {e}")
        return fail(str(e))


# ---------------------- 2. 创建图库 ----------------------
@app.post("/api/v1/tables")
def create_table(item: TableRequest, admin=Depends(get_current_admin)):
    name = item.table_name.strip()
    if not name:
        return fail("表名不能为空")
    try:
        created = service.ensure_table(name, MODEL, MILVUS_CLI, MYSQL_CLI, auto_id=item.auto_id)
        return ok("图库创建成功" if created else "图库已存在或创建失败",
                  {"table": name, "autoId": item.auto_id})
    except Exception as e:
        LOGGER.error(f"创建图库失败: {e}")
        return fail(str(e))


# ---------------------- 3. 删除图库 ----------------------
@app.delete("/api/v1/tables/{table_name}")
def delete_table(table_name: str, cascade: bool = Query(False), admin=Depends(get_current_admin)):
    """cascade=true 时级联删除 MinIO 中该图库的所有原图。"""
    try:
        service.drop_table(table_name, MILVUS_CLI, MYSQL_CLI, MINIO_CLI, cascade=cascade)
        return ok("图库删除成功")
    except Exception as e:
        LOGGER.error(f"删除图库失败: {e}")
        return fail(str(e))


# ---------------------- 4. 图片数量 ----------------------
@app.get("/api/v1/tables/{table_name}/stats")
def table_stats(table_name: str):
    count = MILVUS_CLI.count(table_name) if MILVUS_CLI.has_collection(table_name) else 0
    return ok("success", {"count": count})


# ---------------------- 5. 上传单张 ----------------------
@app.post("/api/v1/tables/{table_name}/images")
async def upload_image(
    table_name: str,
    image: Optional[UploadFile] = File(None),
    image_url: Optional[str] = Form(None),
    commodity_id: str = Form(""),
    customs_param: Optional[str] = Form(None),
    save_to_minio: bool = Form(True),
):
    """上传单张图片；save_to_minio=false 时只入库向量与业务字段，不保存原图。"""
    content, name = await _read_image(image, image_url)
    if content is None:
        return fail("未提供图片文件或图片链接")
    try:
        service.ensure_table(table_name, MODEL, MILVUS_CLI, MYSQL_CLI)
        existing = MYSQL_CLI.exists_by_url(table_name, image_url or name or "", commodity_id)
        if existing:
            return ok("图片已存在", {"imgId": existing})
        img_id, msg = service.add_image(
            table_name, content, MODEL, MILVUS_CLI, MYSQL_CLI, MINIO_CLI,
            commodity_id=commodity_id, customs_param=customs_param,
            raw_url=image_url or name or f"upload_{os.urandom(8).hex()}.jpg",
            save_to_minio=save_to_minio,
        )
        return ok("上传成功", {"imgId": img_id}) if img_id else fail(msg)
    except Exception as e:
        LOGGER.error(f"上传图片失败: {e}")
        return fail(str(e))


# ---------------------- 6. 手动指定 ID 上传 ----------------------
@app.post("/api/v1/tables/{table_name}/images/manual-id")
async def upload_image_manual_id(
    table_name: str,
    milvus_id: int = Form(...),
    image: Optional[UploadFile] = File(None),
    image_url: Optional[str] = Form(None),
    commodity_id: str = Form(""),
    customs_param: Optional[str] = Form(None),
    save_to_minio: bool = Form(True),
):
    """由调用方指定 Milvus 主键，用于与外部系统 ID 对齐的场景。"""
    content, name = await _read_image(image, image_url)
    if content is None:
        return fail("未提供图片文件或图片链接")
    try:
        # 手动指定主键要求集合为 auto_id=False；若集合已存在且为自增模式，给出明确提示
        existing_mode = MILVUS_CLI.is_auto_id(table_name)
        if existing_mode is None:
            service.ensure_table(table_name, MODEL, MILVUS_CLI, MYSQL_CLI, auto_id=False)
        elif existing_mode is True:
            return fail("该图库为自增ID模式，无法手动指定ID。请用 auto_id=false 重新创建图库，或改用普通上传接口")
        img_id, msg = service.add_image_with_id(
            table_name, milvus_id, content, MODEL, MILVUS_CLI, MYSQL_CLI, MINIO_CLI,
            commodity_id=commodity_id, customs_param=customs_param,
            raw_url=image_url or name or f"upload_{os.urandom(8).hex()}.jpg",
            save_to_minio=save_to_minio,
        )
        return ok("上传成功", {"imgId": img_id}) if img_id else fail(msg)
    except Exception as e:
        LOGGER.error(f"手动指定 ID 上传失败: {e}")
        return fail(str(e))


# ---------------------- 7. 批量上传（异步任务） ----------------------
@app.post("/api/v1/tables/{table_name}/images/batch")
async def upload_batch(table_name: str, request: Request, background_tasks: BackgroundTasks):
    """批量上传：接收数据后立即返回 taskId，后台流式分块入库，用 /tasks/{id}/progress 查进度。

    内存设计：请求层只生成轻量来源描述（URL / 临时文件路径），不驻留图片字节；
    真正的下载/读取由后台任务按块进行，内存峰值与图片总数无关。
    """
    import uuid
    body, form = await _get_json_or_form(request)
    sources = []
    cleanup_dir = None
    try:
        if body is not None:
            req = BatchUrlRequest(**body)
            save_default, auto_id = req.save_to_minio, req.auto_id
            # 只保留 URL 与元数据，不下载、不持有图片字节
            for raw in req.items:
                if not raw.get("image_url"):
                    continue
                sources.append({
                    "source": "url",
                    "image_url": raw["image_url"],
                    "commodity_id": raw.get("commodity_id", ""),
                    "customs_param": raw.get("customs_param"),
                    "raw_url": raw["image_url"],
                    "save_to_minio": raw.get("save_to_minio", save_default),
                    "milvus_id": raw.get("milvus_id"),
                })
        elif form is not None:
            files = form.getlist("files")
            save_default = str(form.get("save_to_minio", "true")).lower() == "true"
            commodity_ids = form.getlist("commodity_ids")
            # 上传文件逐个流式写临时目录，避免一次性把所有文件字节读进内存
            os.makedirs(service._STREAM_TMP, exist_ok=True)
            cleanup_dir = tempfile.mkdtemp(prefix="batch_", dir=service._STREAM_TMP)
            for idx, f in enumerate(files):
                raw_url = getattr(f, "filename", None) or f"batch_{idx}.jpg"
                local_path = os.path.join(cleanup_dir, f"{idx:06d}_{os.path.basename(raw_url)}")
                with open(local_path, "wb") as out:
                    while True:
                        chunk = await f.read(1024 * 1024)
                        if not chunk:
                            break
                        out.write(chunk)
                sources.append({
                    "source": "file",
                    "local_path": local_path,
                    "commodity_id": commodity_ids[idx] if idx < len(commodity_ids) else "",
                    "customs_param": None,
                    "raw_url": raw_url,
                    "save_to_minio": save_default,
                })
            auto_id = True
        else:
            return fail("不支持的请求格式")

        if not sources:
            if cleanup_dir:
                shutil.rmtree(cleanup_dir, ignore_errors=True)
            return fail("没有可用的图片数据")
        task_id = uuid.uuid4().hex
        background_tasks.add_task(
            service.run_batch_task, task_id, table_name, sources,
            MODEL, MILVUS_CLI, MYSQL_CLI, MINIO_CLI, auto_id, save_default, cleanup_dir,
        )
        return ok("批量导入任务已启动", {"taskId": task_id, "total": len(sources)})
    except Exception as e:
        if cleanup_dir:
            shutil.rmtree(cleanup_dir, ignore_errors=True)
        LOGGER.error(f"批量上传失败: {e}")
        return fail(str(e))


@app.get("/api/v1/tasks/{task_id}/progress")
def task_progress(task_id: str):
    """查询批量任务进度。"""
    return ok("success", service.get_task_progress(task_id))


@app.get("/api/v1/tasks/{task_id}/result")
def task_result(task_id: str, page: int = Query(1, ge=1), size: int = Query(100, ge=1, le=1000)):
    """按 taskId 分页获取批量上传生成的 (imgId ↔ 业务标识) 映射清单。

    任务完成后调用；清单存于磁盘分片，按需读取，支持数百万条。
    """
    return ok("success", service.get_task_result(task_id, page, size))


# ---------------------- 8. 目录导入（后台任务） ----------------------
@app.post("/api/v1/tables/{table_name}/import/directory")
def import_directory(table_name: str, item: DirImportRequest, background_tasks: BackgroundTasks):
    if not os.path.isdir(item.dir_path):
        return fail(f"目录不存在: {item.dir_path}")
    background_tasks.add_task(
        service.import_directory, table_name, item.dir_path, item.save_to_minio,
        MODEL, MILVUS_CLI, MYSQL_CLI, MINIO_CLI,
    )
    return ok("目录导入任务已启动")


# ---------------------- 9. 导入进度 ----------------------
@app.get("/api/v1/tables/{table_name}/import/progress")
def import_progress(table_name: str):
    cache = Cache("./tmp")
    return ok("success", {
        "current": cache.get("current", 0),
        "total": cache.get("total", 0),
        "status": cache.get("status", "idle"),
    })


# ---------------------- 10. 以图搜图 ----------------------
@app.post("/api/v1/tables/{table_name}/search/image")
async def search_image(
    table_name: str,
    image: Optional[UploadFile] = File(None),
    image_url: Optional[str] = Form(None),
    topk: int = Form(TOP_K),
):
    content, name = await _read_image(image, image_url)
    if content is None:
        return fail("未提供图片文件或图片链接")
    started = time.perf_counter()
    query = image_url or name or "file"
    try:
        results = service.search_by_image(table_name, content, topk, MODEL, MILVUS_CLI, MYSQL_CLI)
        max_sim = results[0]["similarity"] if results else "-"
        audit.log_search(table_name, "image", query, topk, len(results), max_sim,
                         int((time.perf_counter() - started) * 1000))
        return ok("搜索成功", {"results": results})
    except Exception as e:
        LOGGER.error(f"以图搜图失败: {e}")
        audit.log_search(table_name, "image", query, topk, 0, "-",
                         int((time.perf_counter() - started) * 1000), False, str(e))
        return fail(str(e))


# ---------------------- 11. 中文文本搜图 ----------------------
@app.post("/api/v1/tables/{table_name}/search/text")
def search_text(table_name: str, query_text: str = Form(...), topk: int = Form(TOP_K)):
    started = time.perf_counter()
    try:
        results = service.search_by_text(table_name, query_text, topk, MODEL, MILVUS_CLI, MYSQL_CLI)
        max_sim = results[0]["similarity"] if results else "-"
        audit.log_search(table_name, "text", query_text, topk, len(results), max_sim,
                         int((time.perf_counter() - started) * 1000))
        return ok("搜索成功", {"results": results})
    except Exception as e:
        LOGGER.error(f"文本搜索失败: {e}")
        audit.log_search(table_name, "text", query_text, topk, 0, "-",
                         int((time.perf_counter() - started) * 1000), False, str(e))
        return fail(str(e))


# ---------------------- 轻量检索（不查 MySQL） ----------------------
@app.post("/api/v1/tables/{table_name}/search/image/lite")
async def search_image_lite(
    table_name: str,
    image: Optional[UploadFile] = File(None),
    image_url: Optional[str] = Form(None),
    topk: int = Form(TOP_K),
):
    """以图搜图（轻量）：只返回 imgId 与 similarity，完全不访问 MySQL。"""
    content, name = await _read_image(image, image_url)
    if content is None:
        return fail("未提供图片文件或图片链接")
    started = time.perf_counter()
    query = image_url or name or "file"
    try:
        results = service.search_by_image_lite(table_name, content, topk, MODEL, MILVUS_CLI)
        max_sim = results[0]["similarity"] if results else "-"
        audit.log_search(table_name, "image-lite", query, topk, len(results), max_sim,
                         int((time.perf_counter() - started) * 1000))
        return ok("搜索成功", {"results": results})
    except Exception as e:
        LOGGER.error(f"轻量以图搜图失败: {e}")
        audit.log_search(table_name, "image-lite", query, topk, 0, "-",
                         int((time.perf_counter() - started) * 1000), False, str(e))
        return fail(str(e))


@app.post("/api/v1/tables/{table_name}/search/text/lite")
def search_text_lite(table_name: str, query_text: str = Form(...), topk: int = Form(TOP_K)):
    """文本搜图（轻量）：只返回 imgId 与 similarity，完全不访问 MySQL。"""
    started = time.perf_counter()
    try:
        results = service.search_by_text_lite(table_name, query_text, topk, MODEL, MILVUS_CLI)
        max_sim = results[0]["similarity"] if results else "-"
        audit.log_search(table_name, "text-lite", query_text, topk, len(results), max_sim,
                         int((time.perf_counter() - started) * 1000))
        return ok("搜索成功", {"results": results})
    except Exception as e:
        LOGGER.error(f"轻量文本搜索失败: {e}")
        audit.log_search(table_name, "text-lite", query_text, topk, 0, "-",
                         int((time.perf_counter() - started) * 1000), False, str(e))
        return fail(str(e))


# ---------------------- 12. 获取原图 ----------------------
@app.get("/api/v1/tables/{table_name}/images/{img_id}/content")
def get_image(table_name: str, img_id: str):
    """未落 MinIO 的图片会返回明确提示。"""
    try:
        content = service.get_image_content(table_name, img_id, MYSQL_CLI, MINIO_CLI)
        if content is None:
            return fail("该图片未存储原图或不存在")
        return Response(content=content, media_type="image/jpeg")
    except Exception as e:
        LOGGER.error(f"获取原图失败: {e}")
        return fail(str(e))


# ---------------------- 13. 分页列表 ----------------------
@app.get("/api/v1/tables/{table_name}/images")
def list_images(table_name: str, page: int = Query(1, ge=1), size: int = Query(10, ge=1, le=100)):
    try:
        return ok("success", MYSQL_CLI.page(table_name, page, size))
    except Exception as e:
        LOGGER.error(f"分页查询失败: {e}")
        return fail(str(e))


# ---------------------- 一键清空图库图片 ----------------------
@app.delete("/api/v1/tables/{table_name}/images")
def clear_images(table_name: str, cascade: bool = Query(True), admin=Depends(get_current_admin)):
    """一键清空该图库的所有图片（保留图库结构）。cascade=true 时连 MinIO 原图一起删。"""
    try:
        result = service.clear_table_images(
            table_name, MILVUS_CLI, MYSQL_CLI, MINIO_CLI, cascade=cascade
        )
        return ok("图库图片已清空", result)
    except Exception as e:
        LOGGER.error(f"清空图库图片失败: {e}")
        return fail(str(e))


# ---------------------- 14. 删除单张 ----------------------
@app.delete("/api/v1/tables/{table_name}/images/{img_id}")
def delete_image(table_name: str, img_id: str):
    try:
        service.delete_image(table_name, img_id, MILVUS_CLI, MYSQL_CLI, MINIO_CLI)
        audit.log_delete(table_name, img_id)
        return ok("删除成功")
    except Exception as e:
        LOGGER.error(f"删除图片失败: {e}")
        audit.log_delete(table_name, img_id, False, str(e))
        return fail(str(e))


if __name__ == "__main__":
    # 允许直接 python main.py 启动；开发环境用 uvicorn 命令可获得热重载
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000)
