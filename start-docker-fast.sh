#!/bin/bash
# ============================================================
# 图搜接口服务快速启动（使用预装依赖的自定义镜像 tusou-api:4.0）
# 首次需先构建镜像：docker build -t tusou-api:4.0 .
# 之后每次启动秒级，无需重复 pip install
# ============================================================
set -e

PROJECT_DIR="/img_search_RWG/tusou-3.0"
CONTAINER_NAME="tusou-api"
IMAGE="tusou-api:4.0"
PORT="5000"
WORKERS="4"                        # uvicorn worker 数：每个进程各加载 1 份模型，按 CPU 核数/内存调整

# 依赖服务地址与凭据：优先读环境变量，未设置时用占位符，请按实际情况修改
MILVUS_HOST="${MILVUS_HOST:-192.168.1.10}"
MYSQL_HOST="${MYSQL_HOST:-192.168.1.10}"
MINIO_HOST="${MINIO_HOST:-192.168.1.10}"
MYSQL_PWD="${MYSQL_PWD:-请修改为MySQL密码}"

echo "========== 图搜接口服务快速启动 =========="

if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "镜像 $IMAGE 不存在，先构建（首次约需几分钟）..."
  # 构建依赖 python:3.10 基础镜像，先确认本地有，否则给出指引
  if ! docker image inspect python:3.10 >/dev/null 2>&1; then
    echo "本地缺少基础镜像 python:3.10，尝试拉取..."
    if ! docker pull python:3.10; then
      echo "ERROR: 无法拉取 python:3.10，请先配置国内镜像加速或手动导入镜像。"
      echo "  mkdir -p /etc/docker && cat > /etc/docker/daemon.json <<'EOF'"
      echo '  {"registry-mirrors": ["https://docker.m.daocloud.io","https://docker.1ms.run"]}'
      echo "  EOF"
      echo "  systemctl daemon-reload && systemctl restart docker"
      exit 1
    fi
  fi
  cd "$PROJECT_DIR"
  docker build -t "$IMAGE" .
fi

if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
  docker stop "$CONTAINER_NAME" >/dev/null 2>&1 || true
  docker rm "$CONTAINER_NAME" >/dev/null 2>&1 || true
fi

docker run -d \
  --name "$CONTAINER_NAME" \
  --network host \
  --restart unless-stopped \
  -e MILVUS_HOST="$MILVUS_HOST" \
  -e MYSQL_HOST="$MYSQL_HOST" \
  -e MYSQL_PWD="$MYSQL_PWD" \
  -e MINIO_HOST="$MINIO_HOST" \
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
  python -m uvicorn main:app --host 0.0.0.0 --port "$PORT" --workers "$WORKERS"

echo "等待服务就绪..."
for i in $(seq 1 30); do
  if curl -sf "http://127.0.0.1:${PORT}/api/v1/health" >/dev/null 2>&1; then
    echo "========== 启动成功 =========="
    echo "健康检查: http://127.0.0.1:${PORT}/api/v1/health"
    echo "接口文档: http://127.0.0.1:${PORT}/docs"
    echo "查看日志: docker logs -f $CONTAINER_NAME"
    exit 0
  fi
  sleep 2
done
echo "ERROR: 启动超时，查看日志：docker logs $CONTAINER_NAME"
exit 1
