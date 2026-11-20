# 图搜接口服务镜像（预装依赖，启动秒级）
# 构建：docker build -t tusou-api:4.0 .
# 运行：bash start-docker-fast.sh
FROM python:3.10

ENV TZ=Asia/Shanghai \
    PYTHONUNBUFFERED=1 \
    PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    MODEL_DIR=/app/ai-model \
    BACKUP_DIR=/app/backups \
    OMP_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    INFER_CONCURRENCY=6

WORKDIR /app

# python:3.10 完整镜像自带 gcc/curl/tzdata，无需 apt 安装
RUN python -m pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple \
    --upgrade pip setuptools wheel patch-ng

# 复制依赖清单并安装（LMDB_PURE 规避 py-lmdb 源码编译问题）
COPY src/requirements.txt /app/src/requirements.txt
RUN LMDB_PURE=1 python -m pip install --no-cache-dir --upgrade -r /app/src/requirements.txt

# 代码由运行时挂载，镜像内不 COPY，方便更新代码不用重建镜像
EXPOSE 5000

# 默认 4 worker；可用 docker run 命令覆盖，例如 --workers 2
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "5000", "--workers", "4"]
