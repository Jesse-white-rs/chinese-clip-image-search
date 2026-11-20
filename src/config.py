import os

# 项目根目录（src 的上一级），用于定位默认的模型权重目录
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

############### Milvus 向量库配置 ###############
# Milvus 服务地址与端口
MILVUS_HOST = os.getenv("MILVUS_HOST", "192.168.1.10")
MILVUS_PORT = int(os.getenv("MILVUS_PORT", "19530"))
# chinese-clip-rn50 的图文特征统一为 1024 维
VECTOR_DIMENSION = int(os.getenv("VECTOR_DIMENSION", "1024"))
# IP（内积）：向量已归一化，等价于余弦相似度
METRIC_TYPE = os.getenv("METRIC_TYPE", "IP")
DEFAULT_TABLE = os.getenv("DEFAULT_TABLE", "milvus_img_search")
TOP_K = int(os.getenv("TOP_K", "10"))
# IVF_FLAT 索引聚类数与检索时的探测簇数
NLIST = int(os.getenv("NLIST", "1024"))
NPROBE = int(os.getenv("NPROBE", "16"))

############### MySQL 配置 ###############
MYSQL_HOST = os.getenv("MYSQL_HOST", "192.168.1.10")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PWD = os.getenv("MYSQL_PWD", "请通过环境变量设置")
MYSQL_DB = os.getenv("MYSQL_DB", "image_search")
# 连接探活间隔（秒）：避免每次 SQL 都 ping，降低批量入库开销
MYSQL_PING_INTERVAL = int(os.getenv("MYSQL_PING_INTERVAL", "30"))

############### 数据路径 ###############
UPLOAD_PATH = os.getenv("UPLOAD_PATH", "/data/default-pic-directory")

############### MinIO 对象存储配置 ###############
MINIO_HOST = os.getenv("MINIO_HOST", "192.168.1.10")
MINIO_PORT = int(os.getenv("MINIO_PORT", "9000"))
MINIO_ROOT_USER = os.getenv("MINIO_ROOT_USER", "minioadmin")
MINIO_ROOT_PASSWORD = os.getenv("MINIO_ROOT_PASSWORD", "minioadmin")
MINIO_BUCKET_NAME = os.getenv("MINIO_BUCKET_NAME", "images")
MINIO_SECURE = os.getenv("MINIO_SECURE", "false").lower() == "true"
# 上传图片时是否生成预签名 URL（默认关闭，减少一次签名计算）
MINIO_PRESIGNED_ON_UPLOAD = os.getenv("MINIO_PRESIGNED_ON_UPLOAD", "false").lower() == "true"

############### Chinese-CLIP 模型配置 ###############
MODEL_NAME = os.getenv("MODEL_NAME", "RN50")
# 模型权重目录：优先读取该目录下的离线权重，没有则联网下载到此处
MODEL_DIR = os.getenv("MODEL_DIR", os.path.join(BASE_DIR, "ai-model"))
# 推理设备：留空则自动选择 cuda / cpu
DEVICE = os.getenv("DEVICE", "")
# 批量特征编码与批量入库的块大小
ENCODE_BATCH_SIZE = int(os.getenv("ENCODE_BATCH_SIZE", "64"))
DB_BATCH_SIZE = int(os.getenv("DB_BATCH_SIZE", "500"))
# 批量上传时"读取/下载图片字节"的块大小：流式分块用，决定内存峰值。
# 每块最多同时驻留 READ_BATCH_SIZE 张图片字节，默认 128（约 25~50MB）。
# 调小更省内存但下载批次增多；调大更快但峰值更高。
READ_BATCH_SIZE = int(os.getenv("READ_BATCH_SIZE", "128"))
# 单进程内允许的并发推理数（信号量）。配合 OMP_NUM_THREADS=1，
# 让多核并行推理而不互相争抢。默认取 CPU 核数，可通过环境变量调整。
INFER_CONCURRENCY = int(os.getenv("INFER_CONCURRENCY", str(os.cpu_count() or 4)))

############### 认证与用户配置 ###############
# JWT 签名密钥：生产环境务必通过环境变量设置为随机长字符串
JWT_SECRET = os.getenv("JWT_SECRET", "change-this-secret-in-production")
JWT_ALGORITHM = "HS256"
# token 有效期（天），用户要求 7 天
TOKEN_EXPIRE_DAYS = int(os.getenv("TOKEN_EXPIRE_DAYS", "7"))
# 首次启动自动创建的管理员账号（避免默认弱口令，务必用环境变量覆盖）
ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "请通过环境变量设置")

############### 日志配置 ###############
# 日志文件按天切割，默认仅保留最近 10 天
LOG_RETENTION_DAYS = int(os.getenv("LOG_RETENTION_DAYS", "10"))
# 兼容旧变量：日志备份数量（0 表示不按数量限制）
LOGS_NUM = int(os.getenv("logs_num", "0"))

############### 备份配置 ###############
# 定时备份文件存放目录
BACKUP_DIR = os.getenv("BACKUP_DIR", os.path.join(BASE_DIR, "backups"))
# 备份文件默认保留天数
BACKUP_RETENTION_DAYS = int(os.getenv("BACKUP_RETENTION_DAYS", "30"))
