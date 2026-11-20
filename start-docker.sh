#!/bin/bash
# ============================================================
# 图搜接口服务 Docker 一键启动脚本
# 用法：把本脚本放到服务器项目根目录，执行  bash start-docker.sh
# 项目目录：/img_search_RWG/tusou-3.0
# ============================================================
set -e

# ---------------------- 可配置项 ----------------------
PROJECT_DIR="/img_search_RWG/tusou-3.0"
CONTAINER_NAME="tusou-api"
IMAGE="python:3.10"               # 完整版自带 gcc，避免 slim 版 apt 安装卡顿；且兼容 cn_clip
PORT="5005"
WORKERS="4"                        # uvicorn worker 数：每个进程各加载 1 份模型，按 CPU 核数/内存调整

# 依赖服务地址与凭据：优先读环境变量，未设置时用占位符，请按实际情况修改
MILVUS_HOST="${MILVUS_HOST:-192.168.255.141}"
MYSQL_HOST="${MYSQL_HOST:-192.168.255.141}"
MINIO_HOST="${MINIO_HOST:-192.168.255.141}"
MYSQL_PWD="${MYSQL_PWD:-194044}"

# 国内 pip 镜像
PIP_INDEX="https://pypi.tuna.tsinghua.edu.cn/simple"

echo "========== 图搜接口服务启动 =========="
echo "项目目录: $PROJECT_DIR"
echo "容器名称: $CONTAINER_NAME"
echo "监听端口: $PORT"
echo "Worker 数: $WORKERS"

# ---------------------- 前置检查 ----------------------
if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: 未找到 docker 命令，请先安装 Docker"
  exit 1
fi
for d in src ai-model backups; do
  if [ ! -d "$PROJECT_DIR/$d" ]; then
    echo "ERROR: 目录不存在 $PROJECT_DIR/$d"
    exit 1
  fi
done

# ---------------------- 清理旧容器 ----------------------
if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
  echo "停止并删除旧容器 $CONTAINER_NAME ..."
  docker stop "$CONTAINER_NAME" >/dev/null 2>&1 || true
  docker rm "$CONTAINER_NAME" >/dev/null 2>&1 || true
fi

# ---------------------- 准备镜像 ----------------------
# 优先用本地已有镜像；没有再尝试拉取（国内服务器常无法直连 Docker Hub）
if docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "本地已存在镜像 $IMAGE，跳过拉取"
else
  echo "本地无镜像 $IMAGE，尝试拉取..."
  if ! docker pull "$IMAGE"; then
    echo ""
    echo "ERROR: 无法从 Docker Hub 拉取镜像（网络不可达）。请用以下任一方案："
    echo ""
    echo "  方案 A - 配置国内镜像加速（推荐，需 root）："
    echo "    mkdir -p /etc/docker"
    echo '    cat > /etc/docker/daemon.json <<EOF'
    echo '    {"registry-mirrors": ["https://docker.m.daocloud.io","https://docker.1ms.run","https://docker.xuanyuan.me"]}'
    echo '    EOF'
    echo "    systemctl daemon-reload && systemctl restart docker"
    echo "    然后重新执行本脚本"
    echo ""
    echo "  方案 B - 用本地已有的其它 python 镜像："
    echo "    docker images | grep python"
    echo "    把脚本顶部的 IMAGE 改成实际存在的镜像名（如 python:3.10.13）"
    echo ""
    echo "  方案 C - 从能联网的机器导出镜像再导入："
    echo "    docker pull python:3.10"
    echo "    docker save python:3.10 -o python310.tar"
    echo "    scp python310.tar root@服务器:/tmp/"
    echo "    docker load -i /tmp/python310.tar"
    echo ""
    exit 1
  fi
fi

# ---------------------- 启动容器 ----------------------
# --network host：容器直接用宿主机网络，可访问上面配置的依赖服务地址，
#                 且无需 -p 映射（5000 端口直接暴露在宿主机）。
# 挂载：src=代码, ai-model=模型权重, backups=备份, src/logs 随 src 一起持久化。
echo "启动容器 ..."
docker run -d \
  --name "$CONTAINER_NAME" \
  --network host \
  --restart unless-stopped \
  -e TZ=Asia/Shanghai \
  -e PYTHONUNBUFFERED=1 \
  -e PIP_INDEX_URL="$PIP_INDEX" \
  -e MILVUS_HOST="$MILVUS_HOST" \
  -e MYSQL_HOST="$MYSQL_HOST" \
  -e MYSQL_PWD="$MYSQL_PWD" \
  -e MINIO_HOST="$MINIO_HOST" \
  -e MODEL_DIR="/app/ai-model" \
  -e BACKUP_DIR="/app/backups" \
  -e LOG_RETENTION_DAYS=10 \
  -e OMP_NUM_THREADS=1 \
  -e MKL_NUM_THREADS=1 \
  -e INFER_CONCURRENCY="${INFER_CONCURRENCY:-6}" \
  -e MALLOC_ARENA_MAX=4 \
  -e PYTHONMALLOC=malloc \
  -e JWT_SECRET="${JWT_SECRET:-请修改为随机长字符串}" \
  -e ADMIN_USER="${ADMIN_USER:-admin}" \
  -e ADMIN_PASSWORD="${ADMIN_PASSWORD:-请修改为强密码}" \
  -v "$PROJECT_DIR/src:/app/src" \
  -v "$PROJECT_DIR/ai-model:/app/ai-model" \
  -v "$PROJECT_DIR/backups:/app/backups" \
  -v "$PROJECT_DIR/dist:/app/dist" \
  -w /app/src \
  "$IMAGE" \
  bash -c "
    set -e
    echo '[init] 检查编译工具（lmdb 用纯 Python 模式，通常无需 gcc）...'
    if ! command -v gcc >/dev/null 2>&1; then
      echo '[init] 安装 gcc（国内网络可能较慢，请等待）...'
      apt-get update -qq && apt-get install -y -qq --no-install-recommends gcc libffi-dev
    fi
    echo '[init] 安装 pip 构建依赖...'
    python -m pip install --no-cache-dir -i $PIP_INDEX --upgrade pip setuptools wheel patch-ng
    echo '[init] 安装项目依赖（首次较慢，torch 较大，请耐心等待）...'
    LMDB_PURE=1 python -m pip install --no-cache-dir --upgrade -i $PIP_INDEX -r /app/src/requirements.txt
    echo '[init] 启动 uvicorn...'
    exec python -m uvicorn main:app --host 0.0.0.0 --port $PORT --workers $WORKERS
  "

# ---------------------- 等待健康检查 ----------------------
echo "等待服务就绪（首次安装依赖可能需几分钟）..."
for i in $(seq 1 60); do
  if curl -sf "http://127.0.0.1:${PORT}/api/v1/health" >/dev/null 2>&1; then
    echo ""
    echo "========== 服务启动成功 =========="
    echo "健康检查: http://127.0.0.1:${PORT}/api/v1/health"
    echo "接口文档: http://127.0.0.1:${PORT}/docs"
    echo "查看日志: docker logs -f $CONTAINER_NAME"
    echo ""
    exit 0
  fi
  echo "  等待中... ($i/60)"
  sleep 5
done

echo "ERROR: 服务在 5 分钟内未就绪，请查看日志："
echo "  docker logs $CONTAINER_NAME"
exit 1
